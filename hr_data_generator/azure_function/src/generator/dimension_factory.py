import pandas as pd
from src.generator.record_builder import build_record

def generate_dimensions(config, schema):

    dimensions = {}

    for table_name, table_schema in schema.items():

        if not table_name.startswith("dim_"):
            continue

        if table_name not in config:
            continue

        values = config[table_name]

        rows = []

        pk = table_schema["primary_key"]
        value_columns = [
            c for c in table_schema["types"].keys()
            if c != pk
        ]

        for i, value in enumerate(values, start=1):

            row = {pk: i}

            if isinstance(values, dict):

                key = value
                row[value_columns[0]] = key

                if len(value_columns) > 1:
                    row[value_columns[1]] = values[key]

            else:

                row[value_columns[0]] = value

            rows.append(
                build_record(schema, table_name, row)
            )

        dimensions[table_name] = pd.DataFrame(rows)

    return dimensions