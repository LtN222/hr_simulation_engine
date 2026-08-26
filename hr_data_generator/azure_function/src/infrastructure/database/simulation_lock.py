"""Database-wide lock for mutually exclusive HR simulation runs."""

import logging
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


LOCK_RESOURCE = "hr_data_generator_simulation"


class SimulationAlreadyRunningError(RuntimeError):
    """Raised when another full or incremental pipeline still holds the lock."""


@contextmanager
def acquire_simulation_lock(engine, timeout_ms=0):
    """Hold a SQL Server application lock for the complete pipeline run.

    A full run clears and rebuilds related tables. Without a shared lock, a
    timer-triggered incremental run can read that partial state in between and
    encounter orphaned foreign keys. The session remains checked out while the
    lock is held, so the lock also works across Function App instances.
    """
    connection = engine.connect()
    acquired = False

    try:
        lock_result = connection.execute(
            text("""
                DECLARE @result INT;
                EXEC @result = sp_getapplock
                    @Resource = :resource,
                    @LockMode = 'Exclusive',
                    @LockOwner = 'Session',
                    @LockTimeout = :timeout_ms;
                SELECT @result;
            """),
            {"resource": LOCK_RESOURCE, "timeout_ms": timeout_ms}
        ).scalar_one()

        if lock_result < 0:
            raise SimulationAlreadyRunningError(
                "Another HR data generation run is already in progress."
            )

        acquired = True
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text("""
                        EXEC sp_releaseapplock
                            @Resource = :resource,
                            @LockOwner = 'Session';
                    """),
                    {"resource": LOCK_RESOURCE}
                )
                connection.commit()
            except DBAPIError:
                # A session-scoped applock is released automatically by SQL
                # Server the moment its connection ends. A full run can
                # hold this connection idle for the entire simulation
                # (there is no SQL activity on it until this point), and
                # Azure SQL's gateway - or any network path - can drop an
                # idle connection before this explicit release runs. The
                # lock is already gone server-side by then, so this must
                # not fail a run whose simulation and SQL write already
                # completed successfully.
                logging.warning(
                    "Could not explicitly release the simulation lock; "
                    "the connection was likely dropped for being idle "
                    "during the run. SQL Server releases a session-scoped "
                    "applock automatically when its session ends, so the "
                    "lock is not left held."
                )
        try:
            connection.close()
        except DBAPIError:
            pass
