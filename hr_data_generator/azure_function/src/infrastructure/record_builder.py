def build_record(schema, table, data):

    # 🔥 debug mode → geen schema
    if schema is None:
        return data

    columns = schema[table]["types"].keys()

    return {
        col: data.get(col)
        for col in columns
    }