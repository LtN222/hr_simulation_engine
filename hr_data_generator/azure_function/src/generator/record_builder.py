def build_record(schema, table, values):

    columns = schema[table]["types"].keys()

    row = {}

    for col in columns:

        row[col] = values.get(col)

    return row