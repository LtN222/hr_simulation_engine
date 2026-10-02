import logging

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from src.infrastructure.database.simulation_lock import (
    LOCK_RESOURCE,
    SimulationAlreadyRunningError,
    SimulationLockLostError,
    acquire_simulation_lock,
    state_fingerprint,
)

ROW = {"next_year": 2026, "next_week": 40, "last_run": "2026-09-28 02:00:00"}
ALL_COLUMNS = ("next_year", "next_week", "last_run")


def _dropped():
    return DBAPIError("SELECT", {}, Exception("connection forcibly closed"))


class _Result:
    def __init__(self, value=None, rows=None, mapping=None):
        self._value, self._rows, self._mapping = value, rows or [], mapping

    def scalar_one(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def mappings(self):
        return self

    def first(self):
        return self._mapping


class _Conn:
    """A scripted SQL connection: lock calls and the simulation_state reads."""

    def __init__(self, name="conn", mode="Exclusive", getapplock=0, row=None,
                 columns=ALL_COLUMNS):
        self.name = name
        self.mode = mode
        self.getapplock = getapplock
        self.row = row
        self.columns = columns
        self.dead = False
        self.closed = False
        self.statements = []
        self.released = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if self.dead:
            raise _dropped()
        if "sp_getapplock" in sql:
            return _Result(self.getapplock)
        if "sp_releaseapplock" in sql:
            self.released = True
            return _Result()
        if "APPLOCK_MODE" in sql:
            assert params == {"resource": LOCK_RESOURCE}
            return _Result(self.mode)
        if "sys.columns" in sql:
            return _Result(rows=self.columns if self.columns else [])
        if "FROM simulation_state" in sql:
            wanted = [c.strip() for c in sql.split("SELECT")[1].split("FROM")[0].split(",")]
            mapping = None if self.row is None else {c: self.row[c] for c in wanted}
            return _Result(mapping=mapping)
        raise AssertionError(sql)

    def commit(self):
        pass

    def close(self):
        self.closed = True

    def asked_for_the_lock(self):
        return any("sp_getapplock" in s for s in self.statements)


class _Engine:
    """Hands out the given connections in order; an Exception entry is raised instead."""

    def __init__(self, *connections):
        self._queue = list(connections)
        self.connects = 0

    def connect(self):
        self.connects += 1
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _acquire(engine):
    return acquire_simulation_lock(engine, connect_attempts=1, connect_retry_delay_seconds=0)


# --- acquiring and the connect retry -------------------------------------------------------

def test_a_transient_connection_failure_is_retried_until_it_succeeds():
    failure = OperationalError("connect", {}, Exception("Login timeout expired"))
    engine = _Engine(failure, failure, _Conn())

    with acquire_simulation_lock(engine, connect_attempts=3, connect_retry_delay_seconds=0):
        pass

    assert engine.connects == 3


def test_connection_failures_beyond_the_retry_budget_still_raise():
    failure = OperationalError("connect", {}, Exception("Login timeout expired"))
    engine = _Engine(failure, failure, failure)

    with pytest.raises(OperationalError):
        with acquire_simulation_lock(engine, connect_attempts=3, connect_retry_delay_seconds=0):
            pass

    assert engine.connects == 3


def test_another_run_holding_the_lock_is_reported_and_the_connection_closed():
    connection = _Conn(getapplock=-1)

    with pytest.raises(SimulationAlreadyRunningError):
        with _acquire(_Engine(connection)):
            pass

    assert connection.closed and not connection.released


def test_a_dropped_connection_during_release_does_not_fail_a_completed_run():
    """SQL Server already released the session-scoped lock when the connection dropped."""
    connection = _Conn()
    ran_body = False

    with _acquire(_Engine(connection)):
        ran_body = True
        connection.dead = True

    assert ran_body
    assert connection.closed


def test_a_failing_close_never_masks_the_outcome():
    class _BadClose(_Conn):
        def close(self):
            raise RuntimeError("socket already gone")

    connection = _BadClose()

    with _acquire(_Engine(connection)) as lock:
        lock.verify()                                  # still held: nothing raised, nothing re-acquired
    # leaving the block without an exception is the assertion


# --- verify: the lock is still held --------------------------------------------------------

def test_verify_does_not_reacquire_while_the_lock_is_still_held(caplog):
    connection = _Conn()
    engine = _Engine(connection)

    with caplog.at_level(logging.WARNING):
        with _acquire(engine) as lock:
            lock.verify()
            lock.verify()

    assert engine.connects == 1
    assert "re-acquired" not in caplog.text
    assert connection.released                          # the original connection releases at the end


# --- verify: lost, re-acquired, nothing changed ----------------------------------------------

@pytest.mark.parametrize("how", ["dead connection", "mode NoLock"])
@pytest.mark.parametrize("row", [None, ROW], ids=["no state row", "state row"])
def test_a_lost_lock_is_reacquired_when_no_other_run_wrote(how, row, caplog):
    first, second = _Conn("first", row=row), _Conn("second", row=row)
    engine = _Engine(first, second)

    with caplog.at_level(logging.WARNING):
        with _acquire(engine) as lock:
            if how == "dead connection":
                first.dead = True
            else:
                first.mode = "NoLock"
            lock.verify()                               # recovers instead of raising

    assert "simulation lock was lost while idle and re-acquired; no other run wrote in between" in caplog.text
    assert engine.connects == 2 and second.asked_for_the_lock()
    assert second.released and not first.released       # the lock that is actually held is released
    assert first.closed and second.closed


def test_verify_called_twice_after_a_recovery_does_not_reacquire_again(caplog):
    first, second = _Conn("first", row=ROW), _Conn("second", row=ROW)
    engine = _Engine(first, second)

    with caplog.at_level(logging.WARNING):
        with _acquire(engine) as lock:
            first.dead = True
            lock.verify()
            lock.verify()

    assert engine.connects == 2
    assert caplog.text.count("re-acquired") == 1
    assert sum("APPLOCK_MODE" in s for s in second.statements) == 1


def test_a_second_loss_after_a_recovery_is_recovered_again_from_the_same_fingerprint():
    first, second, third = (_Conn(n, row=ROW) for n in ("first", "second", "third"))
    engine = _Engine(first, second, third)

    with _acquire(engine) as lock:
        first.dead = True
        lock.verify()
        second.dead = True
        lock.verify()

    assert engine.connects == 3 and third.released


# --- verify: lost and not recoverable ---------------------------------------------------------

def test_a_lost_lock_that_another_run_now_holds_fails_without_writing():
    first, second = _Conn("first", row=ROW), _Conn("second", row=ROW, getapplock=-1)

    with _acquire(_Engine(first, second)) as lock:
        first.dead = True
        with pytest.raises(SimulationLockLostError, match="another run holds it"):
            lock.verify()
        with pytest.raises(SimulationLockLostError):    # recovery is tried once, then it stays failed
            lock.verify()

    assert second.closed and first.closed
    assert not first.released and not second.released   # nothing is held, so nothing is released


def test_a_lost_lock_that_cannot_reconnect_fails_without_writing():
    first = _Conn("first", row=ROW)
    engine = _Engine(first, OperationalError("connect", {}, Exception("Login timeout expired")))

    with _acquire(engine) as lock:
        first.dead = True
        with pytest.raises(SimulationLockLostError, match="could not be re-acquired"):
            lock.verify()

    assert first.closed


def test_a_lost_lock_with_a_changed_state_fingerprint_fails_without_writing():
    first = _Conn("first", row=ROW)
    second = _Conn("second", row={**ROW, "next_week": 41})      # another run wrote in between

    with _acquire(_Engine(first, second)) as lock:
        first.mode = "NoLock"
        with pytest.raises(SimulationLockLostError, match="another run wrote in between"):
            lock.verify()

    assert second.closed and first.closed
    assert not second.released                                   # the new lock was dropped, not kept


def test_a_state_row_that_appeared_since_the_start_counts_as_changed():
    first, second = _Conn("first", row=None), _Conn("second", row=ROW)

    with _acquire(_Engine(first, second)) as lock:
        first.dead = True
        with pytest.raises(SimulationLockLostError, match="another run wrote in between"):
            lock.verify()


def test_a_newer_last_run_timestamp_counts_as_changed():
    first = _Conn("first", row=ROW)
    second = _Conn("second", row={**ROW, "last_run": "2026-09-29 02:00:00"})

    with _acquire(_Engine(first, second)) as lock:
        first.dead = True
        with pytest.raises(SimulationLockLostError):
            lock.verify()


# --- the fingerprint ---------------------------------------------------------------------------

def test_the_fingerprint_reads_none_for_a_missing_table_or_missing_columns():
    assert state_fingerprint(_Conn(columns=())) == (False, None, None, None)
    # an old table that has a row but not the checkpoint columns yet
    old = _Conn(columns=("last_run",), row=ROW)
    assert state_fingerprint(old) == (True, None, None, ROW["last_run"])
    # ... and the same row after our own schema evolution added the columns
    evolved = _Conn(columns=ALL_COLUMNS, row={**ROW, "next_year": None, "next_week": None})
    assert state_fingerprint(evolved) == (True, None, None, ROW["last_run"])


def test_the_fingerprint_of_a_full_row_and_of_no_row():
    assert state_fingerprint(_Conn(row=ROW)) == (True, 2026, 40, ROW["last_run"])
    assert state_fingerprint(_Conn(row=None)) == (False, None, None, None)
