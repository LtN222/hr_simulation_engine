import pandas as pd


def load_current_state(engine, schema_config):
    """
    Laadt alle tabellen uit de database op basis van schema_config
    en retourneert ze als dictionary met DataFrames.
    """

    dataframes = {}

    for table_name, table_config in schema_config.items():

        df_name = table_config["df"]

        query = f"SELECT * FROM {table_name}"

        try:
            dataframes[df_name] = pd.read_sql(query, engine)
        except Exception:
            columns = list(table_config.get("types", {}).keys())
            dataframes[df_name] = pd.DataFrame(columns=columns)

    return dataframes
