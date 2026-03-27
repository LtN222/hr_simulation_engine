import pandas as pd


def build_table(schema, table_name, rows):
    """
    Bouwt een dataframe volgens schema-definitie.
    Werkt voor zowel dim_* als fact_* tabellen.
    """

    if len(rows) == 0:
        return pd.DataFrame()

    columns = list(schema[table_name]["types"].keys())

    df = pd.DataFrame(rows)

    # kolommen ordenen volgens schema
    ordered = [c for c in columns if c in df.columns]

    return df[ordered]