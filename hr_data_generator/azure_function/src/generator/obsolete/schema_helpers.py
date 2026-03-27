def get_columns(schema, table):

    return list(schema[table]["types"].keys())


def get_primary_key(schema, table):

    return schema[table]["primary_key"]