"""Database-wide lock for mutually exclusive HR simulation runs."""

import logging
import time
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError


LOCK_RESOURCE = "hr_data_generator_simulation"
CONNECT_ATTEMPTS = 3
CONNECT_RETRY_DELAY_SECONDS = 10


class SimulationAlreadyRunningError(RuntimeError):
    """Raised when another full or incremental pipeline still holds the lock."""


def _connect_with_retry(engine, attempts, delay_seconds):
    """Retry past transient Azure SQL connection failures (e.g. an HYT00
    login timeout from a brief gateway blip) instead of failing the whole
    weekly run on a single attempt.
    """
    for attempt in range(1, attempts + 1):
        try:
            return engine.connect()
        except OperationalError:
            if attempt == attempts:
                raise
            logging.warning(
                "SQL connection attempt %d/%d failed, retrying in %ds",
                attempt, attempts, delay_seconds,
            )
            time.sleep(delay_seconds)


@contextmanager
def acquire_simulation_lock(
    engine,
    timeout_ms=0,
    connect_attempts=CONNECT_ATTEMPTS,
    connect_retry_delay_seconds=CONNECT_RETRY_DELAY_SECONDS,
):
    """Hold a SQL Server application lock for the complete pipeline run.

    A full run clears and rebuilds related tables. Without a shared lock, a
    timer-triggered incremental run can read that partial state in between and
    encounter orphaned foreign keys. The session remains checked out while the
    lock is held, so the lock also works across Function App instances.
    """
    connection = _connect_with_retry(engine, connect_attempts, connect_retry_delay_seconds)
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
