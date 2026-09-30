import pandas as pd
from sqlalchemy import text


def load_current_state(engine, schema_config):
    """
    Laadt alle tabellen uit de database op basis van schema_config
    en retourneert ze als dictionary met DataFrames.

    Only a table that does not exist yet yields an empty frame (the very first
    run). Any other failure propagates: a transient read error must never
    become an empty table that a later write would then "repair" (AR-06).
    """

    dataframes = {}

    for table_name, table_config in schema_config.items():

        df_name = table_config["df"]

        if _table_exists(engine, table_name):
            # Rows come back in primary-key order (the clustered index) on
            # purpose: the simulators iterate tables in row order and draw
            # random numbers along the way, so a reload must reproduce the
            # order an in-memory run had.
            primary_key = table_config["primary_key"]
            dataframes[df_name] = pd.read_sql(
                f"SELECT * FROM {table_name} ORDER BY [{primary_key}]", engine
            )
        else:
            columns = list(table_config.get("types", {}).keys())
            dataframes[df_name] = pd.DataFrame(columns=columns)

    return dataframes


def _table_exists(engine, table_name):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT OBJECT_ID(:table_name, 'U')"), {"table_name": table_name}
        ).scalar() is not None
