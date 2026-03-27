import pandas as pd


def build_dimension(schema_table, values):

    pk = schema_table["primary_key"]
    columns = list(schema_table["types"].keys())

    value_columns = [c for c in columns if c != pk]

    rows = []

    for i, value in enumerate(values, start=1):

        row = {pk: i}

        if len(value_columns) == 1:
            row[value_columns[0]] = value

        rows.append(row)

    return pd.DataFrame(rows)