import pandas as pd
from sqlalchemy import text


def _ensure_simulation_state_table(conn):
    conn.execute(text("""
        IF OBJECT_ID('simulation_state', 'U') IS NULL
        CREATE TABLE simulation_state (
            id INT NOT NULL PRIMARY KEY,
            current_year INT NOT NULL,
            current_week INT NOT NULL,
            last_run DATETIME NULL
        )
    """))


def get_simulation_state(engine, default_year=2020, default_week=1):
    with engine.begin() as conn:
        _ensure_simulation_state_table(conn)

    df = pd.read_sql(
        "SELECT current_year, current_week FROM simulation_state WHERE id = 1",
        engine
    )

    if df.empty:
        return int(default_year), int(default_week)

    return df.iloc[0]["current_year"], df.iloc[0]["current_week"]


def update_simulation_state(engine, year, week):

    year = int(year)
    week = int(week)

    with engine.begin() as conn:
        _ensure_simulation_state_table(conn)

        conn.execute(text("""
        IF EXISTS (SELECT 1 FROM simulation_state WHERE id = 1)
        BEGIN
            UPDATE simulation_state
            SET current_year = :year,
                current_week = :week,
                last_run = GETDATE()
            WHERE id = 1
        END
        ELSE
        BEGIN
            INSERT INTO simulation_state (id, current_year, current_week, last_run)
            VALUES (1, :year, :week, GETDATE())
        END
        """), {"year": year, "week": week})
