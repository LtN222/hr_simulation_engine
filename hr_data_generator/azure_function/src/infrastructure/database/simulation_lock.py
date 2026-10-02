"""Database-wide lock for mutually exclusive HR simulation runs."""

import logging
import time
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError


LOCK_RESOURCE = "hr_data_generator_simulation"
CONNECT_ATTEMPTS = 3
CONNECT_RETRY_DELAY_SECONDS = 10
FINGERPRINT_COLUMNS = ("next_year", "next_week", "last_run")


class SimulationAlreadyRunningError(RuntimeError):
    """Raised when another full or incremental pipeline still holds the lock."""


class SimulationLockLostError(RuntimeError):
    """Raised when the run no longer holds the simulation lock and it could not
    be recovered (another run holds it or wrote in between), so writing could
    overlap with another run."""


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


def _close_quietly(connection):
    """Close a connection; a cleanup error must never mask the real outcome."""
    if connection is None:
        return
    try:
        connection.close()
    except Exception:
        pass


def _get_applock(connection, timeout_ms):
    """Try to take the lock on `connection`; True when it was granted."""
    result = connection.execute(
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
    return result >= 0


def state_fingerprint(connection):
    """What `simulation_state` looks like now: (row exists, next_year, next_week, last_run).

    A run only changes this table in its final write, so a different fingerprint
    means another run wrote since ours started. A missing table, or missing
    checkpoint columns of an older table, read as None values; adding the columns
    (our own schema evolution) therefore does not change the fingerprint.
    """
    present = set(connection.execute(
        text("""
            SELECT name FROM sys.columns
            WHERE object_id = OBJECT_ID('simulation_state', 'U')
              AND name IN ('next_year', 'next_week', 'last_run')
        """)
    ).scalars().all())
    columns = [c for c in FINGERPRINT_COLUMNS if c in present]
    row = None
    if columns:
        # `columns` is a subset of the fixed whitelist above; nothing user-supplied.
        row = connection.execute(
            text(f"SELECT {', '.join(columns)} FROM simulation_state WHERE id = 1")
        ).mappings().first()
    return (row is not None,) + tuple(
        row[c] if row is not None and c in columns else None for c in FINGERPRINT_COLUMNS
    )


class SimulationLock:
    """The held lock. `verify()` re-checks it and recovers from an idle drop.

    The lock connection sits idle for the whole simulation, so Azure SQL or the
    network may drop it, which silently releases the lock. A lost lock only
    matters if another run ran in between, so `verify()` tries once to take the
    lock again on a fresh connection and compares `simulation_state` with the
    fingerprint taken when the lock was first acquired. Unchanged: continue (the
    new connection holds the lock from then on). Otherwise it raises
    `SimulationLockLostError`, and the caller writes nothing.
    """

    def __init__(self, engine, connection, fingerprint, timeout_ms=0,
                 connect_attempts=CONNECT_ATTEMPTS,
                 connect_retry_delay_seconds=CONNECT_RETRY_DELAY_SECONDS):
        self._engine = engine
        self._connection = connection
        self._fingerprint = fingerprint
        self._timeout_ms = timeout_ms
        self._connect_attempts = connect_attempts
        self._connect_retry_delay_seconds = connect_retry_delay_seconds
        self._failed = False

    @property
    def held_connection(self):
        """The connection that really holds the lock now (None after a failed recovery)."""
        return None if self._failed else self._connection

    def verify(self):
        """Return normally only when the lock is held and nobody wrote in between."""
        if self._failed:
            raise SimulationLockLostError(
                "The simulation lock was lost and could not be recovered; nothing was written."
            )
        try:
            mode = self._connection.execute(
                text("SELECT APPLOCK_MODE('public', :resource, 'Session');"),
                {"resource": LOCK_RESOURCE},
            ).scalar_one()
            if mode == "Exclusive":
                return
            reason = f"mode {mode}"
        except DBAPIError:
            reason = "its connection was dropped"
        self._recover(reason)

    def _recover(self, reason):
        """Try ONCE to re-acquire the lock on a fresh connection (see the class docstring)."""
        fresh = None
        try:
            fresh = _connect_with_retry(
                self._engine, self._connect_attempts, self._connect_retry_delay_seconds
            )
            if not _get_applock(fresh, self._timeout_ms):
                raise SimulationLockLostError(
                    f"The simulation lock was lost ({reason}) and another run holds it now; "
                    "nothing was written."
                )
            if state_fingerprint(fresh) != self._fingerprint:
                raise SimulationLockLostError(
                    f"The simulation lock was lost ({reason}) and simulation_state changed "
                    "since this run started, so another run wrote in between; nothing was written."
                )
        except SimulationLockLostError:
            self._give_up(fresh)
            raise
        except DBAPIError as exc:
            self._give_up(fresh)
            raise SimulationLockLostError(
                f"The simulation lock was lost ({reason}) and could not be re-acquired "
                f"({type(exc).__name__}); nothing was written."
            ) from exc

        logging.warning(
            "simulation lock was lost while idle and re-acquired; no other run wrote in between"
        )
        _close_quietly(self._connection)
        self._connection = fresh

    def _give_up(self, fresh):
        # A closed session releases its session-owned lock on the server.
        _close_quietly(fresh)
        _close_quietly(self._connection)
        self._failed = True


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

    Yields a `SimulationLock`; call its `verify()` before writing (the SQL store
    does), because the lock can be lost silently while the simulation runs.
    Right after acquiring, the state of `simulation_state` is fingerprinted so
    `verify()` can tell whether another run wrote after a lost lock.
    """
    connection = _connect_with_retry(engine, connect_attempts, connect_retry_delay_seconds)
    lock = None

    try:
        if not _get_applock(connection, timeout_ms):
            raise SimulationAlreadyRunningError(
                "Another HR data generation run is already in progress."
            )

        lock = SimulationLock(
            engine, connection, state_fingerprint(connection), timeout_ms,
            connect_attempts, connect_retry_delay_seconds,
        )
        yield lock
    finally:
        # Release the lock that is actually held: after a recovery that is the
        # new connection, not the one the run started with.
        held = lock.held_connection if lock is not None else None
        if held is not None:
            try:
                held.execute(
                    text("""
                        EXEC sp_releaseapplock
                            @Resource = :resource,
                            @LockOwner = 'Session';
                    """),
                    {"resource": LOCK_RESOURCE}
                )
                held.commit()
            except Exception:
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
        _close_quietly(held)
        if held is not connection:
            _close_quietly(connection)
