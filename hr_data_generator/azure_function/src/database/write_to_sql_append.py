import os
import pandas as pd
from sqlalchemy import create_engine, text
import urllib
from Beheer_Repo.Demo_dashboards.hr_data_generator.azure_function.src.generator.obsolete.schema_config import SCHEMA_CONFIG


def get_engine():

    conn_str = os.environ["SQL_CONNECTION_STRING"]

    params = urllib.parse.quote_plus(conn_str)

    engine = create_engine(
        f"mssql+pyodbc:///?odbc_connect={params}"
    )

    return engine


def write_dataset(
    engine, dataframes
):

    engine = get_engine()

    for table, cfg in SCHEMA_CONFIG.items():
        df_name = cfg["df"]
        df = dataframes[df_name]

        df.to_sql(
            table,
            engine,
            if_exists="append",
            index=False,
            method="multi"
        )

def apply_constraints(
        engine
):
    with engine.begin() as conn:
        for table, cfg in SCHEMA_CONFIG.items():

            if "primary_key" in cfg:

                pk = cfg["primary_key"]

                conn.execute(text(f"""
                    ALTER TABLE {table}
                    ADD CONSTRAINT PK_{table}
                    PRIMARY KEY ({pk})
                """))

            if "foreign_keys" in cfg:

                for col, ref_table, ref_col in cfg["foreign_keys"]:

                    conn.execute(text(f"""
                        ALTER TABLE {table}
                        ADD CONSTRAINT FK_{table}_{col}
                        FOREIGN KEY ({col})
                        REFERENCES {ref_table}({ref_col})
                    """))

            if "indexes" in cfg:

                for col in cfg["indexes"]:

                    conn.execute(text(f"""
                        CREATE INDEX IX_{table}_{col}
                        ON {table}({col})
                    """))

#opschonen data na 5 jaar:                    
def apply_retention(engine):

    with engine.begin() as conn:

        conn.execute(text("""
            DELETE FROM fact_employment
            WHERE Startdatum < DATEADD(year, -5, GETDATE())
        """))

        conn.execute(text("""
            DELETE FROM fact_employment_attribute
            WHERE Employment_Key NOT IN (
                SELECT Employment_Key FROM fact_employment
            )
        """))
   