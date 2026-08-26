from sqlalchemy.exc import DBAPIError

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
