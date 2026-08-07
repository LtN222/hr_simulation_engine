import pandas as pd
from src.infrastructure.record_builder import build_record


def generate_dimensions(config, schema):

    dimensions = {}

    for table_name, table_schema in schema.items():

        if not table_name.startswith("dim_"):
            continue

        values = config.get(table_name)

        if values is None:
            continue

        rows = []

        pk = table_schema["primary_key"]
        value_columns = [
            c for c in table_schema["types"].keys()
            if c != pk
        ]

        for i, value in enumerate(values, start=1):

            if isinstance(value, dict):
                row = {pk: value.get(pk, i)}
                row.update({
                    column: value.get(column)
                    for column in value_columns
                })

            elif isinstance(values, dict):

                row = {pk: i}

                key = value
                row[value_columns[0]] = key

                if len(value_columns) > 1:
                    row[value_columns[1]] = values[key]

            else:

                row = {pk: i}
                row[value_columns[0]] = value

            rows.append(
                build_record(schema, table_name, row)
            )

        dimensions[table_name] = pd.DataFrame(rows)

    return dimensions
