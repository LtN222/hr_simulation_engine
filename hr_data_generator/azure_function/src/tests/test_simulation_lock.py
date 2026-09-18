import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from src.infrastructure.database.simulation_lock import acquire_simulation_lock


class _FakeConnection:
    """Acquire succeeds; every call after that raises like a dropped socket."""

    def __init__(self):
        self.closed = False
        self.release_attempted = False

    def execute(self, statement, params=None):
        if "sp_getapplock" in str(statement):
            return _FakeScalarResult(0)
        self.release_attempted = True
        raise DBAPIError(
            str(statement), params or {}, Exception("connection forcibly closed")
        )

    def commit(self):
        pass

    def close(self):
        self.closed = True


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _FakeEngine:
    def __init__(self, connection):
        self._connection = connection

    def connect(self):
        return self._connection


class _FlakyEngine:
    """connect() fails like a dropped login for the first N calls, then succeeds."""

    def __init__(self, failures_before_success, connection):
        self._failures_remaining = failures_before_success
        self._connection = connection
        self.connect_attempts = 0

    def connect(self):
        self.connect_attempts += 1
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise OperationalError("connect", {}, Exception("Login timeout expired"))
        return self._connection


def test_a_transient_connection_failure_is_retried_until_it_succeeds():
    engine = _FlakyEngine(failures_before_success=2, connection=_FakeConnection())

    with acquire_simulation_lock(engine, connect_attempts=3, connect_retry_delay_seconds=0):
        pass

    assert engine.connect_attempts == 3


def test_connection_failures_beyond_the_retry_budget_still_raise():
    engine = _FlakyEngine(failures_before_success=5, connection=_FakeConnection())

    with pytest.raises(OperationalError):
        with acquire_simulation_lock(engine, connect_attempts=3, connect_retry_delay_seconds=0):
            pass

    assert engine.connect_attempts == 3


def test_a_dropped_connection_during_release_does_not_fail_a_completed_run():
    """The simulated pipeline body must complete even though the lock
    connection dies before the explicit release - SQL Server already
    released the session-scoped lock when the connection dropped."""
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    ran_body = False

    with acquire_simulation_lock(engine):
        ran_body = True

    assert ran_body
    assert connection.release_attempted
    assert connection.closed
