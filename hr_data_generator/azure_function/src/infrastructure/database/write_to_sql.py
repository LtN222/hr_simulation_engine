import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text, Integer, String, Date, Boolean, Numeric
import urllib
import logging

from src.infrastructure.state.table_changes import (
    APPEND,
    UPSERT,
    WRITE_MODES,
    normalize_column,
    plan_incremental,
    summarize,
)


# =====================================================
# DATABASE WRITE PIPELINE
# =====================================================
#
# Every schema table declares its write mode (`write_mode`: "upsert" or
# "append", see table_changes.py). A run writes in two phases:
#
#   1. schema evolution (create missing tables, add columns, drop retired
#      tables/columns, constraints) - DDL, outside the data transaction;
#   2. ONE transaction on one connection: a full run resets the managed tables
#      and bulk-inserts everything, an incremental run writes only new and
#      changed rows (plus explicit deletes), and the checkpoint in
#      `simulation_state` is written LAST. A failure rolls everything back, so
#      the database keeps its previous data and its previous checkpoint.

# SQL Server accepts at most 2,100 bound parameters in a single statement. Keep
# a small margin so pandas' ``method='multi'`` remains reliable for wide facts.
SQL_SERVER_INSERT_PARAMETER_BUDGET = 2_000
DEFAULT_INSERT_CHUNKSIZE = 100


def get_engine(database_name):

    template = os.environ["SQL_CONNECTION_TEMPLATE"]
    conn_str = template.format(database=database_name)

    params = urllib.parse.quote_plus(conn_str)

    engine = create_engine(
        f"mssql+pyodbc:///?odbc_connect={params}",
        # A large share of write_dataframes' time is repeated multi-row
        # INSERTs (to_sql with method="multi"). fast_executemany batches
        # pyodbc's parameter arrays into far fewer network round-trips and
        # is usually a large (often 5-20x) win for exactly that pattern.
        fast_executemany=True,
        # A full run holds a connection checked out for the whole run
        # (see acquire_simulation_lock); pre-ping catches a connection Azure
        # SQL's gateway dropped for being idle and transparently reconnects
        # instead of surfacing a stale-connection error mid-run.
        pool_pre_ping=True,
    )

    return engine

def map_sql_types(type_config):

    mapping = {}

    for col, sql_type in type_config.items():

        if sql_type.startswith("INT"):
            mapping[col] = Integer()

        elif sql_type.startswith("NVARCHAR"):
            size = int(sql_type.split("(")[1].replace(")", ""))
            mapping[col] = String(size)

        elif sql_type.startswith("DATE"):
            mapping[col] = Date()

        elif sql_type.startswith("BIT"):
            mapping[col] = Boolean()

        elif sql_type.startswith("DECIMAL"):
            precision = int(sql_type.split("(")[1].split(",")[0])
            scale = int(sql_type.split(",")[1].replace(")", ""))
            mapping[col] = Numeric(precision, scale)

    return mapping

def get_insert_chunksize(df):
    """Return a SQL Server-safe multi-row insert batch size for ``df``."""
    column_count = len(df.columns)
    if column_count == 0:
        return DEFAULT_INSERT_CHUNKSIZE
    if column_count > SQL_SERVER_INSERT_PARAMETER_BUDGET:
        raise ValueError(
            "Cannot insert a row with more columns than the SQL Server "
            f"parameter budget ({column_count} columns)."
        )

    return min(
        DEFAULT_INSERT_CHUNKSIZE,
        max(1, SQL_SERVER_INSERT_PARAMETER_BUDGET // column_count)
    )

def filter_state_tables(state):

    return {
        key: value
        for key, value in state.items()
        if isinstance(value, pd.DataFrame)
    }

def get_table_write_order(schema_config):
    """Return a stable write order in which referenced rows exist first.

    A dimensions-first order alone is insufficient when one dimension references
    another one, such as ``dim_role.SalaryScale_Key`` referencing
    ``dim_salary_scale``. Derive the order from the configured foreign keys so
    the schema remains safe when dimensions or fact-to-fact references are added.
    Self references (for example an employment event's previous event) are
    intentionally ignored because this order guarantees only that the table
    itself has already been written.
    """
    tables = [
        table
        for table in schema_config
        if table != "simulation_state"
        and (table.startswith("dim_") or table.startswith("fact_"))
    ]
    table_set = set(tables)
    dependencies = {
        table: {
            referenced_table
            for _, referenced_table, _ in definition.get("foreign_keys", [])
            if referenced_table in table_set and referenced_table != table
        }
        for table, definition in schema_config.items()
        if table in table_set
    }

    ordered_tables = []
    remaining_tables = list(tables)
    while remaining_tables:
        resolved_tables = set(ordered_tables)
        ready_tables = [
            table
            for table in remaining_tables
            if dependencies[table].issubset(resolved_tables)
        ]

        if not ready_tables:
            unresolved = {
                table: sorted(dependencies[table] - resolved_tables)
                for table in remaining_tables
            }
            raise ValueError(
                "Unable to determine a foreign-key-safe table write order: "
                f"{unresolved}"
            )

        ordered_tables.extend(ready_tables)
        ready_set = set(ready_tables)
        remaining_tables = [
            table for table in remaining_tables if table not in ready_set
        ]

    return ordered_tables

def _normalize_dataframe_for_sql(df, type_config=None):
    normalized = df.copy()

    def _normalize_scalar(value, sql_type=None):
        if value is None:
            return None

        if pd.isna(value):
            return None

        if sql_type and sql_type.startswith("INT"):
            return int(value)

        if sql_type and sql_type.startswith("DECIMAL"):
            # Placeholder: DECIMAL columns are converted as a whole column below,
            # with the exact quantization the change comparison uses.
            return value

        if sql_type and sql_type.startswith("BIT"):
            return bool(value)

        if isinstance(value, (pd.Timestamp, pd.Timedelta)):
            return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value.to_pytimedelta()

        if isinstance(value, np.datetime64):
            return pd.Timestamp(value).to_pydatetime()

        if isinstance(value, np.timedelta64):
            return pd.Timedelta(value).to_pytimedelta()

        if isinstance(value, np.generic):
            return value.item()

        if hasattr(value, "to_pydatetime") and callable(value.to_pydatetime):
            return value.to_pydatetime()

        if hasattr(value, "to_pytimedelta") and callable(value.to_pytimedelta):
            return value.to_pytimedelta()

        if hasattr(value, "item") and not isinstance(value, (str, bytes, bool, int, float, type(None))):
            return value.item()

        return value

    for col in normalized.columns:
        try:
            sql_type = type_config.get(col) if type_config else None
            if sql_type and sql_type.startswith("DECIMAL"):
                # Send Decimals quantized like the comparison does, never floats:
                # SQL Server rounds float -> DECIMAL differently (6.805 -> 6.80).
                normalized[col] = normalize_column(normalized[col], sql_type)
                continue
            normalized[col] = pd.Series(
                [
                    _normalize_scalar(value, sql_type)
                    for value in normalized[col]
                ],
                index=normalized.index,
                dtype=object
            )
        except Exception:
            continue

    return normalized

def _ensure_table_columns(engine, table, cfg):
    """Add missing nullable columns when the schema evolves.

    Pandas creates tables on first write, but existing Azure SQL tables need an
    ALTER TABLE before appending DataFrames with newly introduced columns.
    """

    type_config = cfg.get("types", {})
    if not type_config:
        return

    with engine.begin() as conn:
        for column, sql_type in type_config.items():
            conn.execute(text(f"""
                IF OBJECT_ID('{table}', 'U') IS NOT NULL
                AND COL_LENGTH('{table}', '{column}') IS NULL
                ALTER TABLE {table}
                ADD {column} {sql_type} NULL
            """))

def _column_dependency_drop_commands(conn, table, column):
    """Statements that remove every object SQL Server lets block DROP COLUMN.

    Foreign keys, indexes (including unique constraints), default constraints
    and manually created statistics on the column must go first; automatically
    created statistics (`_WA_Sys_*`) are removed by SQL Server itself. The
    first real run of AR-07 failed on `IX_fact_absence_Ploegendienst_Key`
    because only foreign keys were handled.
    """
    parameters = {"table_name": table, "column_name": column}
    commands = []

    foreign_keys = conn.execute(text("""
        SELECT fk.name
        FROM sys.foreign_keys AS fk
        JOIN sys.foreign_key_columns AS fkc
          ON fkc.constraint_object_id = fk.object_id
        JOIN sys.columns AS c
          ON c.object_id = fkc.parent_object_id
         AND c.column_id = fkc.parent_column_id
        WHERE fkc.parent_object_id = OBJECT_ID(:table_name)
          AND c.name = :column_name
    """), parameters).fetchall()
    commands += [f"ALTER TABLE [{table}] DROP CONSTRAINT [{row[0]}]" for row in foreign_keys]

    indexes = conn.execute(text("""
        SELECT DISTINCT i.name, i.is_primary_key, i.is_unique_constraint
        FROM sys.indexes AS i
        JOIN sys.index_columns AS ic
          ON ic.object_id = i.object_id
         AND ic.index_id = i.index_id
        JOIN sys.columns AS c
          ON c.object_id = ic.object_id
         AND c.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID(:table_name)
          AND c.name = :column_name
          AND i.name IS NOT NULL
    """), parameters).fetchall()
    for name, is_primary_key, is_unique_constraint in indexes:
        if is_primary_key:
            raise ValueError(
                f"{table}.{column} is deprecated but part of the primary key {name}; "
                "remove it from deprecated_columns or change the primary key first."
            )
        if is_unique_constraint:
            commands.append(f"ALTER TABLE [{table}] DROP CONSTRAINT [{name}]")
        else:
            commands.append(f"DROP INDEX [{name}] ON [{table}]")

    defaults = conn.execute(text("""
        SELECT dc.name
        FROM sys.default_constraints AS dc
        JOIN sys.columns AS c
          ON c.object_id = dc.parent_object_id
         AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(:table_name)
          AND c.name = :column_name
    """), parameters).fetchall()
    commands += [f"ALTER TABLE [{table}] DROP CONSTRAINT [{row[0]}]" for row in defaults]

    # Statistics that belong to an index disappear with the index above.
    statistics = conn.execute(text("""
        SELECT DISTINCT st.name
        FROM sys.stats AS st
        JOIN sys.stats_columns AS sc
          ON sc.object_id = st.object_id
         AND sc.stats_id = st.stats_id
        JOIN sys.columns AS c
          ON c.object_id = sc.object_id
         AND c.column_id = sc.column_id
        WHERE st.object_id = OBJECT_ID(:table_name)
          AND c.name = :column_name
          AND st.user_created = 1
          AND NOT EXISTS (
              SELECT 1 FROM sys.indexes AS i
              WHERE i.object_id = st.object_id AND i.name = st.name
          )
    """), parameters).fetchall()
    commands += [f"DROP STATISTICS [{table}].[{row[0]}]" for row in statistics]

    return commands


def _drop_deprecated_columns(engine, schema_config):
    """Remove explicitly deprecated source columns from existing SQL tables."""
    with engine.begin() as conn:
        for table, cfg in schema_config.items():
            for column in cfg.get("deprecated_columns", []):
                for command in _column_dependency_drop_commands(conn, table, column):
                    conn.execute(text(command))
                conn.execute(text(f"""
                    IF OBJECT_ID('{table}', 'U') IS NOT NULL
                    AND COL_LENGTH('{table}', '{column}') IS NOT NULL
                    ALTER TABLE [{table}] DROP COLUMN [{column}]
                """))

def _drop_obsolete_tables(engine):
    """Remove tables retired from the reporting model and their constraints."""
    for table in (
        "fact_employment_attribute",
        "fact_salary_snapshot",
        "dim_absence_duration",
        # Renamed to English structural names: dim_ploegendienst -> dim_shift,
        # dim_reden_vertrek -> dim_departure_reason.
        "dim_ploegendienst",
        "dim_reden_vertrek",
    ):
        with engine.begin() as conn:
            constraints = conn.execute(text("""
                SELECT DISTINCT
                    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS schema_name,
                    OBJECT_NAME(fk.parent_object_id) AS table_name,
                    fk.name AS constraint_name
                FROM sys.foreign_keys AS fk
                WHERE fk.parent_object_id = OBJECT_ID(:table_name)
                   OR fk.referenced_object_id = OBJECT_ID(:table_name)
            """), {"table_name": table}).fetchall()
            for constraint in constraints:
                conn.execute(text(
                    f"ALTER TABLE [{constraint.schema_name}].[{constraint.table_name}] "
                    f"DROP CONSTRAINT [{constraint.constraint_name}]"
                ))
            conn.execute(text(f"""
                IF OBJECT_ID('{table}', 'U') IS NOT NULL
                DROP TABLE [{table}]
            """))

def apply_constraints(engine, schema_config):

    with engine.begin() as conn:

        for table, cfg in schema_config.items():

            if "primary_key" in cfg:

                pk = cfg["primary_key"]

                conn.execute(text(f"""
                    ALTER TABLE {table}
                    ALTER COLUMN {pk} INT NOT NULL
                """))

                conn.execute(text(f"""
                    IF NOT EXISTS (
                        SELECT 1
                        FROM sys.key_constraints
                        WHERE name = 'PK_{table}'
                    )
                    ALTER TABLE {table}
                    ADD CONSTRAINT PK_{table}
                    PRIMARY KEY ({pk})
                """))

            if "foreign_keys" in cfg:

                for col, ref_table, ref_col in cfg["foreign_keys"]:

                    conn.execute(text(f"""
                        ALTER TABLE {table}
                        ALTER COLUMN {col} INT
                    """))

                    conn.execute(text(f"""
                        IF NOT EXISTS (
                            SELECT 1
                            FROM sys.foreign_keys
                            WHERE name = 'FK_{table}_{col}'
                        )
                        ALTER TABLE {table}
                        ADD CONSTRAINT FK_{table}_{col}
                        FOREIGN KEY ({col})
                        REFERENCES {ref_table}({ref_col})
                        ON DELETE NO ACTION
                    """))

            if "indexes" in cfg:

                for col in cfg["indexes"]:

                    conn.execute(text(f"""
                        IF NOT EXISTS (
                            SELECT 1
                            FROM sys.indexes
                            WHERE name = 'IX_{table}_{col}'
                        )
                        CREATE INDEX IX_{table}_{col}
                        ON {table}({col})
                    """))



def table_exists(conn, table):
    """Whether `table` exists; the only read failure callers may tolerate."""
    return conn.execute(text(
        "SELECT OBJECT_ID(:table_name, 'U')"
    ), {"table_name": table}).scalar() is not None


# =====================================================
# Phase 1: schema evolution (before the data transaction)
# =====================================================

def _column_ddl(column, sql_type, primary_key):
    nullability = "NOT NULL" if column == primary_key else "NULL"
    return f"[{column}] {sql_type} {nullability}"


def _create_missing_tables(engine, schema_config, table_order):
    with engine.begin() as conn:
        for table in table_order:
            cfg = schema_config[table]
            primary_key = cfg["primary_key"]
            columns = ", ".join(
                _column_ddl(column, sql_type, primary_key)
                for column, sql_type in cfg["types"].items()
            )
            conn.execute(text(f"""
                IF OBJECT_ID('{table}', 'U') IS NULL
                CREATE TABLE {table} (
                    {columns},
                    CONSTRAINT PK_{table} PRIMARY KEY ({primary_key})
                )
            """))


def ensure_schema(engine, schema_config):
    """Bring the SQL schema up to date. DDL: never run inside the data transaction."""
    from src.infrastructure.state.simulation_state import ensure_simulation_state_table

    table_order = get_table_write_order(schema_config)
    _drop_obsolete_tables(engine)
    _drop_deprecated_columns(engine, schema_config)
    _create_missing_tables(engine, schema_config, table_order)
    for table in table_order:
        _ensure_table_columns(engine, table, schema_config[table])
    apply_constraints(engine, schema_config)
    with engine.begin() as conn:
        ensure_simulation_state_table(conn)


# =====================================================
# Phase 2: statements inside the data transaction
# =====================================================

def reset_tables(conn, table_order):
    """Empty every managed table on `conn` (inside the caller's transaction).

    Children are deleted before their parents (reverse write order), so no
    foreign key has to be switched off: ALTER TABLE takes a schema-modification
    lock that would block readers, even under READ_COMMITTED_SNAPSHOT, until the
    commit. Deleting all rows of one self-referencing table in a single
    statement (fact_employment.Previous_Employment_Key) is allowed.
    """
    for table in reversed(table_order):
        conn.execute(text(f"""
            IF OBJECT_ID('{table}', 'U') IS NOT NULL
            DELETE FROM {table}
        """))


def insert_rows(conn, table, cfg, frame):
    """Insert `frame` into `table` on `conn`."""
    if frame.empty:
        return
    normalized = _normalize_dataframe_for_sql(frame, cfg.get("types"))
    normalized.to_sql(
        table,
        conn,
        if_exists="append",
        index=False,
        chunksize=get_insert_chunksize(normalized),
        method="multi",
        dtype=map_sql_types(cfg["types"])
    )


def update_rows(conn, table, cfg, frame):
    """UPDATE the changed rows (known to exist) by primary key, one batch."""
    if frame.empty:
        return
    primary_key = cfg["primary_key"]
    columns = [column for column in cfg["types"] if column in frame.columns]
    update_columns = [column for column in columns if column != primary_key]
    assignments = ", ".join(f"[{column}] = :{column}" for column in update_columns)
    normalized = _normalize_dataframe_for_sql(frame[columns], cfg.get("types"))
    conn.execute(
        text(f"UPDATE {table} SET {assignments} WHERE [{primary_key}] = :{primary_key}"),
        normalized.to_dict(orient="records"),
    )


def delete_rows(conn, table, cfg, keys):
    """DELETE rows by primary key (only tables declaring `delete_missing`)."""
    if not keys:
        return
    primary_key = cfg["primary_key"]
    conn.execute(
        text(f"DELETE FROM {table} WHERE [{primary_key}] = :key"),
        [{"key": key} for key in keys],
    )


def _write_full(conn, tables, schema_config, table_order):
    """Reset the managed tables and bulk-insert every table."""
    reset_tables(conn, table_order)
    summary = {}
    for table in table_order:
        cfg = schema_config[table]
        frame = tables.get(cfg["df"])
        if frame is None:
            logging.warning(f"DataFrame {cfg['df']} not found - skipping")
            continue
        frame = frame.drop_duplicates(subset=[cfg["primary_key"]], keep="last")
        insert_rows(conn, table, cfg, frame)
        summary[table] = {
            "added": len(frame), "updated": 0, "unchanged": 0, "deleted": 0, "total": len(frame),
        }
        logging.info(f"{table}: +{len(frame)} rows (full run)")
    return summary


def _write_incremental(conn, changes, schema_config):
    for change in changes:
        cfg = schema_config[change.table]
        insert_rows(conn, change.table, cfg, change.added)
        update_rows(conn, change.table, cfg, change.updated)
        delete_rows(conn, change.table, cfg, change.deleted_keys)


def write_dataset(
    engine,
    state,
    schema_config,
    reset=False,
    baseline=None,
    checkpoint=None,
    write_checkpoint=None,
    dry_run=False,
    verify_lock=None,
):
    """Write the state to SQL: schema first, then one atomic data transaction.

    `baseline` (per-table row digests from the incremental load) is required for
    an incremental write; a full run (`reset=True`) bulk-inserts everything.
    `write_checkpoint(conn, checkpoint)` runs as the last statement of the
    transaction. With `dry_run` schema evolution is skipped and the whole
    transaction runs and is rolled back; the per-table counts are returned.
    `verify_lock()` raises when the simulation lock is no longer held; it runs
    before the first write (schema evolution) and again before the transaction.
    """
    logging.info("Writing dataset to SQL")
    if dry_run and reset:
        raise ValueError("A dry run is only allowed for incremental writes.")
    if not reset and baseline is None:
        raise ValueError("An incremental write needs the baseline of the loaded tables.")

    if verify_lock is not None:
        verify_lock()

    if dry_run:
        # A dry run must not change anything, schema included. If the schema is
        # out of date the write fails inside the transaction and rolls back.
        logging.info("DRY RUN: schema evolution skipped.")
    else:
        ensure_schema(engine, schema_config)

    table_order = get_table_write_order(schema_config)
    tables = filter_state_tables(state)
    # Planning is pure: it raises (before anything is written) when a table
    # lost rows it may not lose.
    changes = None if reset else plan_incremental(tables, schema_config, baseline, table_order)

    # Schema evolution can take a while on a big table; re-check right before the data transaction.
    if verify_lock is not None:
        verify_lock()

    conn = engine.connect()
    transaction = conn.begin()
    try:
        if reset:
            summary = _write_full(conn, tables, schema_config, table_order)
        else:
            _write_incremental(conn, changes, schema_config)
            summary = summarize(changes)

        if checkpoint is not None and write_checkpoint is not None:
            write_checkpoint(conn, checkpoint)   # LAST statement of the transaction

        if dry_run:
            transaction.rollback()
            logging.info("DRY RUN: the write transaction was rolled back; nothing was changed.")
        else:
            transaction.commit()
    except BaseException:
        try:
            transaction.rollback()
        except Exception:
            logging.exception("The rollback itself failed; the server discards an open transaction when the connection closes.")
        logging.error(
            "The SQL write failed and was rolled back: the database still holds the "
            "previous data and the previous checkpoint. No partial run is stored "
            "(for a full run on a small tier the usual cause is a full transaction log)."
        )
        raise
    finally:
        conn.close()

    logging.info("Dataset write pipeline completed")
    return summary
