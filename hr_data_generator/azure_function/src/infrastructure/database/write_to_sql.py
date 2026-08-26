import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text, Integer, String, Date, Boolean, Numeric
import urllib
import logging


# =====================================================
# DATABASE WRITE PIPELINE
# =====================================================

STATIC_DIMENSIONS = {
    "dim_department",
    "dim_role",
    "dim_location",
    "dim_education",
    "dim_absence_type",
    "dim_satisfaction_band",
    "dim_satisfaction_driver",
    "dim_engagement_band",
    "dim_performance_driver",
    "dim_engagement_driver",
    "dim_candidate_quality_driver",
    "dim_salary_band",
    "dim_salary_scale",
    "dim_shift",
    "dim_event_type",
    "dim_departure_reason",
    "dim_decline_reason",
    "dim_rejection_reason",
    "dim_recruitment_stage",
    "dim_incident_type"
}

# These dimensions represent either current employee state or configuration
# owned labels. Both need Type 1 updates on incremental runs.
MUTABLE_DIMENSIONS = {
    "dim_employee",
    "dim_manager",
    "dim_hire_source",
    "dim_recruitment_status"
}

# Most facts are immutable events. An employment event is the exception: an
# active event is completed in place when a contract ends, changes internally,
# or receives its final departure context.
MUTABLE_FACTS = {"fact_absence", "fact_employment", "fact_recruitment"}

# SQL Server accepts at most 2,100 bound parameters in a single statement. Keep
# a small margin so pandas' ``method='multi'`` remains reliable for wide facts.
SQL_SERVER_INSERT_PARAMETER_BUDGET = 2_000
DEFAULT_INSERT_CHUNKSIZE = 100


# =====================================================
# 1️⃣ Database engine ophalen
# =====================================================

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
    )

    return engine


# =====================================================
# 2️⃣ SQL datatype mapping
# =====================================================

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


# =====================================================
# Helper: state filter
# =====================================================

def filter_state_tables(state):

    return {
        key: value
        for key, value in state.items()
        if isinstance(value, pd.DataFrame)
    }


# =====================================================
# Helper: tabel volgorde bepalen
# =====================================================

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


# =====================================================
# Helper: bestaande primary key waarden ophalen
# =====================================================

def _get_existing_primary_keys(engine, table, pk_column):
    try:
        with engine.begin() as conn:
            result = conn.execute(text(
                f"SELECT CAST({pk_column} AS NVARCHAR(255)) FROM {table}"
            ))
            return {
                str(row[0])
                for row in result.fetchall()
                if row[0] is not None
            }
    except Exception as exc:
        logging.warning(f"Could not read existing keys for {table}: {exc}")
        return set()


def _filter_existing_primary_key_rows(engine, df, table, cfg):
    if df.empty:
        return df

    pk_column = cfg.get("primary_key")
    if not pk_column or pk_column not in df.columns:
        return df

    existing_keys = _get_existing_primary_keys(engine, table, pk_column)
    if not existing_keys:
        return df

    df = df.drop_duplicates(subset=[pk_column], keep="first")

    def _normalize_value(value):
        if pd.isna(value):
            return None
        return str(value)

    normalized_values = df[pk_column].apply(_normalize_value)
    mask = normalized_values.isin(existing_keys)
    filtered_df = df.loc[~mask]

    skipped = len(df) - len(filtered_df)
    if skipped > 0:
        logging.info(f"{table}: skipped {skipped} rows already present in SQL")

    return filtered_df


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
            return float(value)

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


def _drop_deprecated_columns(engine, schema_config):
    """Remove explicitly deprecated source columns from existing SQL tables."""
    with engine.begin() as conn:
        for table, cfg in schema_config.items():
            for column in cfg.get("deprecated_columns", []):
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
                """), {
                    "table_name": table,
                    "column_name": column
                }).fetchall()
                for foreign_key in foreign_keys:
                    conn.execute(text(
                        f"ALTER TABLE [{table}] DROP CONSTRAINT [{foreign_key[0]}]"
                    ))
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


def _table_exists(engine, table):
    with engine.begin() as conn:
        return conn.execute(text(
            "SELECT OBJECT_ID(:table_name, 'U')"
        ), {"table_name": table}).scalar() is not None


def _upsert_mutable_dimension(engine, table, dataframe, cfg):
    """Insert new dimension members and update existing current-state rows."""
    if dataframe.empty:
        return

    if not _table_exists(engine, table):
        dataframe.to_sql(
            table,
            engine,
            if_exists="append",
            index=False,
            chunksize=get_insert_chunksize(dataframe),
            method="multi",
            dtype=map_sql_types(cfg["types"])
        )
        return

    pk_column = cfg.get("primary_key")
    columns = [
        column
        for column in cfg.get("types", {})
        if column in dataframe.columns
    ]
    if not pk_column or pk_column not in columns:
        raise ValueError(f"{table} requires a primary key for an upsert.")

    update_columns = [column for column in columns if column != pk_column]
    update_sql = ", ".join(
        f"[{column}] = :{column}"
        for column in update_columns
    )
    insert_columns = ", ".join(f"[{column}]" for column in columns)
    insert_values = ", ".join(f":{column}" for column in columns)
    update_statement = text(f"""
        UPDATE {table}
        SET {update_sql}
        WHERE [{pk_column}] = :{pk_column}
    """)
    insert_statement = text(f"""
        INSERT INTO {table} ({insert_columns})
        VALUES ({insert_values})
    """)

    rows = dataframe.drop_duplicates(
        subset=[pk_column],
        keep="last"
    )[columns].to_dict(orient="records")

    with engine.begin() as conn:
        for row in rows:
            result = conn.execute(update_statement, row)
            if result.rowcount == 0:
                conn.execute(insert_statement, row)


# =====================================================
# Helper: tabellen resetten
# =====================================================

def reset_tables(engine, table_order):

    with engine.begin() as conn:
        constraint_commands = _get_foreign_key_constraint_commands(
            conn,
            table_order
        )

        # SQL Server blocks parent deletes while FK constraints on child tables
        # are active. During a full rebuild we intentionally empty all managed
        # tables first, then insert a fresh consistent dataset.
        for command in constraint_commands["disable"]:
            conn.execute(text(command))

        for table in reversed(table_order):

            conn.execute(text(f"""
                IF OBJECT_ID('{table}', 'U') IS NOT NULL
                DELETE FROM {table}
            """))

        for command in constraint_commands["enable"]:
            conn.execute(text(command))


def _get_foreign_key_constraint_commands(conn, table_order):
    escaped_table_names = [
        table.replace("'", "''")
        for table in table_order
    ]
    table_values = ", ".join(
        f"('{table}')"
        for table in escaped_table_names
    )

    if not table_values:
        return {"disable": [], "enable": []}

    rows = conn.execute(text(f"""
        WITH ManagedTables AS (
            SELECT table_name
            FROM (VALUES {table_values}) AS v(table_name)
        )
        SELECT DISTINCT
            'ALTER TABLE '
                + QUOTENAME(OBJECT_SCHEMA_NAME(fk.parent_object_id))
                + '.'
                + QUOTENAME(OBJECT_NAME(fk.parent_object_id))
                + ' NOCHECK CONSTRAINT '
                + QUOTENAME(fk.name) AS disable_sql,
            'ALTER TABLE '
                + QUOTENAME(OBJECT_SCHEMA_NAME(fk.parent_object_id))
                + '.'
                + QUOTENAME(OBJECT_NAME(fk.parent_object_id))
                + ' WITH CHECK CHECK CONSTRAINT '
                + QUOTENAME(fk.name) AS enable_sql
        FROM sys.foreign_keys fk
        JOIN ManagedTables parent_tables
            ON OBJECT_NAME(fk.parent_object_id) = parent_tables.table_name
        JOIN ManagedTables referenced_tables
            ON OBJECT_NAME(fk.referenced_object_id) = referenced_tables.table_name
    """)).fetchall()

    return {
        "disable": [row.disable_sql for row in rows],
        "enable": [row.enable_sql for row in reversed(rows)]
    }


# =====================================================
# 3️⃣ DataFrames naar SQL schrijven
# =====================================================

def write_dataframes(engine, dataframes, schema_config, reset):
    summary = {}
    table_order = get_table_write_order(schema_config)
    logging.info(f"Table write order: {table_order}")

    for table in table_order:

        cfg = schema_config[table]
        _ensure_table_columns(engine, table, cfg)

        df_name = cfg["df"]

        if df_name not in dataframes:
            logging.warning(f"DataFrame {df_name} not found — skipping")
            continue

        df = dataframes[df_name]

        if not reset and table in STATIC_DIMENSIONS and _table_exists(engine, table):
            missing_rows = _filter_existing_primary_key_rows(
                engine,
                df,
                table,
                cfg
            )
            if not missing_rows.empty:
                dtype_map = map_sql_types(cfg["types"])
                normalized = _normalize_dataframe_for_sql(
                    missing_rows,
                    cfg.get("types")
                )
                normalized.to_sql(
                    table,
                    engine,
                    if_exists="append",
                    index=False,
                    chunksize=get_insert_chunksize(normalized),
                    method="multi",
                    dtype=dtype_map
                )

            summary[table] = {
                "added": len(missing_rows),
                "total": len(df)
            }
            logging.info(
                f"{table}: +{len(missing_rows)} static rows "
                f"(total {len(df)})"
            )
            continue

        if not reset and table in MUTABLE_DIMENSIONS | MUTABLE_FACTS:
            new_rows = _filter_existing_primary_key_rows(engine, df, table, cfg)
            _ensure_table_columns(engine, table, cfg)
            normalized = _normalize_dataframe_for_sql(
                df,
                cfg.get("types")
            )
            _upsert_mutable_dimension(engine, table, normalized, cfg)

            summary[table] = {
                "added": len(new_rows),
                "total": len(df)
            }
            logging.info(
                f"{table}: +{len(new_rows)} rows, "
                f"{len(df) - len(new_rows)} rows updated"
            )
            continue

        used_primary_key_filter = False

        if not reset:
            df = _filter_existing_primary_key_rows(engine, df, table, cfg)
            used_primary_key_filter = bool(cfg.get("primary_key"))

        try:
            with engine.begin() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                existing_rows = result.scalar()
        except Exception:
            existing_rows = 0

        if reset or used_primary_key_filter:
            df_to_insert = df
        else:
            df_to_insert = df.iloc[existing_rows:]

        if len(df_to_insert) > 0:
            _ensure_table_columns(engine, table, cfg)
            dtype_map = map_sql_types(cfg["types"]) if "types" in cfg else None
            df_to_insert = _normalize_dataframe_for_sql(
                df_to_insert,
                cfg.get("types")
            )

            df_to_insert.to_sql(
                table,
                engine,
                if_exists="append",
                index=False,
                chunksize=get_insert_chunksize(df_to_insert),
                method="multi",
                dtype=dtype_map
            )

        rows_added = len(df_to_insert)

        summary[table] = {
            "added": rows_added,
            "total": len(df)
        }

        logging.info(f"{table}: +{rows_added} rows (total {len(df)})")

    return summary

# =====================================================
# 4️⃣ Constraints toepassen
# =====================================================

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


# =====================================================
# 5️⃣ Retention policy (FIXED)
# =====================================================

def apply_retention(engine):

    with engine.begin() as conn:

        # -------------------------------------------------
        # Chains bepalen
        # -------------------------------------------------

        # -------------------------------------------------
        # 1️⃣ Eerst attributes verwijderen (FK SAFE)
        # -------------------------------------------------

        # Delete fact tables that depend on fact_employment before deleting
        # old employment chains. This must stay in sync with schema FKs.
        conn.execute(text("""
        IF OBJECT_ID('fact_workforce_snapshot', 'U') IS NOT NULL
        BEGIN
            ;WITH Chains AS (
                SELECT
                    Employment_Key,
                    Previous_Employment_Key,
                    Einddatum,
                    Employment_Key AS Root_Key
                FROM fact_employment
                WHERE Previous_Employment_Key IS NULL

                UNION ALL

                SELECT
                    fe.Employment_Key,
                    fe.Previous_Employment_Key,
                    fe.Einddatum,
                    c.Root_Key
                FROM fact_employment fe
                JOIN Chains c
                    ON fe.Previous_Employment_Key = c.Employment_Key
            ),

            OldChains AS (
                SELECT Root_Key
                FROM Chains
                GROUP BY Root_Key
                HAVING MAX(Einddatum) < DATEADD(year, -5, GETDATE())
            )

            DELETE fws
            FROM fact_workforce_snapshot fws
            JOIN Chains c
                ON fws.Employment_Key = c.Employment_Key
            JOIN OldChains oc
                ON c.Root_Key = oc.Root_Key
        END
        """))

        # -------------------------------------------------
        # 2️⃣ Daarna employment verwijderen
        # -------------------------------------------------

        conn.execute(text("""
        WITH Chains AS (

            SELECT
                Employment_Key,
                Previous_Employment_Key,
                Einddatum,
                Employment_Key AS Root_Key
            FROM fact_employment
            WHERE Previous_Employment_Key IS NULL

            UNION ALL

            SELECT
                fe.Employment_Key,
                fe.Previous_Employment_Key,
                fe.Einddatum,
                c.Root_Key
            FROM fact_employment fe
            JOIN Chains c
                ON fe.Previous_Employment_Key = c.Employment_Key
        ),

        OldChains AS (

            SELECT Root_Key
            FROM Chains
            GROUP BY Root_Key
            HAVING MAX(Einddatum) < DATEADD(year, -5, GETDATE())

        )

        DELETE fe
        FROM fact_employment fe
        JOIN Chains c
            ON fe.Employment_Key = c.Employment_Key
        JOIN OldChains oc
            ON c.Root_Key = oc.Root_Key
        """))

        # -------------------------------------------------
        # 3️⃣ Orphan cleanup (extra safety)
        # -------------------------------------------------

        conn.execute(text("""
            IF OBJECT_ID('fact_workforce_snapshot', 'U') IS NOT NULL
            DELETE FROM fact_workforce_snapshot
            WHERE Employment_Key NOT IN (
                SELECT Employment_Key FROM fact_employment
            )
        """))


# =====================================================
# 6️⃣ Dataset write orchestrator
# =====================================================

def write_dataset(engine, state, schema_config, reset=False):

    logging.info("Writing dataset to SQL")

    _drop_obsolete_tables(engine)
    _drop_deprecated_columns(engine, schema_config)

    if reset:
        table_order = get_table_write_order(schema_config)
        reset_tables(engine, table_order)

    dataframes = filter_state_tables(state)

    summary = write_dataframes(
        engine,
        dataframes,
        schema_config,
        reset
    )

    logging.info(f"Tables written: {list(dataframes.keys())}")

    apply_constraints(engine, schema_config)

    apply_retention(engine)

    logging.info("Dataset write pipeline completed")
    return summary
