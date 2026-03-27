def get_dimension_tables(schema):

    return [
        name for name in schema
        if name.startswith("dim_")
    ]


def get_fact_tables(schema):

    return [
        name for name in schema
        if name.startswith("fact_")
    ]