import os
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
    "dim_hire_source",
    "dim_education_level",
    "dim_absence_type",
    "dim_event_type",
    "dim_reden_vertrek"
}


# =====================================================
# 1️⃣ Database engine ophalen
# =====================================================

def get_engine(database_name):

    template = os.environ["SQL_CONNECTION_TEMPLATE"]
    conn_str = template.format(database=database_name)

    params = urllib.parse.quote_plus(conn_str)

    engine = create_engine(
        f"mssql+pyodbc:///?odbc_connect={params}"
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

    dim_tables = []
    fact_tables = []

    for table in schema_config.keys():

        if table == "simulation_state":
            continue

        elif table.startswith("dim_"):
            dim_tables.append(table)

        elif table.startswith("fact_"):
            fact_tables.append(table)

    return dim_tables + fact_tables


# =====================================================
# Helper: tabellen resetten
# =====================================================

def reset_tables(engine, table_order):

    with engine.begin() as conn:

        for table in reversed(table_order):

            conn.execute(text(f"""
                IF OBJECT_ID('{table}', 'U') IS NOT NULL
                DELETE FROM {table}
            """))


# =====================================================
# 3️⃣ DataFrames naar SQL schrijven
# =====================================================

def write_dataframes(engine, dataframes, schema_config, reset):
    summary = {}
    table_order = get_table_write_order(schema_config)
    logging.info(f"Table write order: {table_order}")

    for table in table_order:

        if not reset and table in STATIC_DIMENSIONS:
            logging.info(f"{table}: skipped (static dimension)")
            continue

        cfg = schema_config[table]
        df_name = cfg["df"]

        if df_name not in dataframes:
            logging.warning(f"DataFrame {df_name} not found — skipping")
            continue

        df = dataframes[df_name]

        try:
            with engine.begin() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                existing_rows = result.scalar()
        except Exception:
            existing_rows = 0

        dtype_map = map_sql_types(cfg["types"]) if "types" in cfg else None

        df_to_insert = df.iloc[existing_rows:] if not reset else df

        if len(df_to_insert) > 0:

            df_to_insert.to_sql(
                table,
                engine,
                if_exists="append",
                index=False,
                chunksize=100,
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

        DELETE fa
        FROM fact_employment_attribute fa
        JOIN fact_employment fe
            ON fa.Employment_Key = fe.Employment_Key
        JOIN Chains c
            ON fe.Employment_Key = c.Employment_Key
        JOIN OldChains oc
            ON c.Root_Key = oc.Root_Key
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
            DELETE FROM fact_employment_attribute
            WHERE Employment_Key NOT IN (
                SELECT Employment_Key FROM fact_employment
            )
        """))


# =====================================================
# 6️⃣ Dataset write orchestrator
# =====================================================

def write_dataset(engine, state, schema_config, reset=False):

    logging.info("Writing dataset to SQL")

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