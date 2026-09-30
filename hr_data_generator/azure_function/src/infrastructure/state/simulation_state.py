"""The `simulation_state` table: last simulated week plus the run checkpoint.

`current_year`/`current_week` stay "the last week that was simulated" for
readability. The checkpoint itself (the NEXT week to simulate, the seed, the
config fingerprint and the persisted non-table state) lives in the columns added
here. The checkpoint is written as the last statement of the same transaction as
the data; the columns are created beforehand (schema evolution).
"""

import pandas as pd
from sqlalchemy import text

from src.infrastructure.state.checkpoint import Checkpoint

CHECKPOINT_COLUMNS = {
    "next_year": "INT NULL",
    "next_week": "INT NULL",
    "simulation_seed": "NVARCHAR(100) NULL",
    "config_fingerprint": "NVARCHAR(64) NULL",
    "checkpoint_json": "NVARCHAR(MAX) NULL",
}


def ensure_simulation_state_table(conn):
    conn.execute(text("""
        IF OBJECT_ID('simulation_state', 'U') IS NULL
        CREATE TABLE simulation_state (
            id INT NOT NULL PRIMARY KEY,
            current_year INT NOT NULL,
            current_week INT NOT NULL,
            last_run DATETIME NULL
        )
    """))
    # Idempotent: a live table may already have simulation_seed, and tables
    # written by an older version lack the checkpoint columns.
    for column, definition in CHECKPOINT_COLUMNS.items():
        conn.execute(text(
            f"IF COL_LENGTH('simulation_state', '{column}') IS NULL "
            f"ALTER TABLE simulation_state ADD {column} {definition}"
        ))


def read_checkpoint(engine):
    """Return the stored `Checkpoint`, or None when there is no new-style one."""
    with engine.begin() as conn:
        ensure_simulation_state_table(conn)

    df = pd.read_sql(
        "SELECT next_year, next_week, checkpoint_json FROM simulation_state WHERE id = 1",
        engine,
    )
    if df.empty:
        return None
    row = df.iloc[0]
    if pd.isna(row["next_year"]) or pd.isna(row["next_week"]) or not row["checkpoint_json"]:
        return None
    checkpoint = Checkpoint.from_json(row["checkpoint_json"])
    checkpoint.advance_to(int(row["next_year"]), int(row["next_week"]))
    return checkpoint


def write_checkpoint(conn, checkpoint):
    """Store the checkpoint on `conn`; `current_year/current_week` = last simulated week.

    Runs as the LAST statement of the data transaction (see `write_dataset`), so
    the checkpoint only ever advances together with the data. The columns are
    created beforehand by `ensure_simulation_state_table` (schema evolution).
    """
    last_year, last_week = checkpoint.last_simulated_week
    params = {
        "year": int(last_year),
        "week": int(last_week),
        "next_year": int(checkpoint.next_year),
        "next_week": int(checkpoint.next_week),
        "seed": str(checkpoint.seed),
        "fingerprint": checkpoint.config_fingerprint,
        "checkpoint_json": checkpoint.to_json(),
    }
    conn.execute(text("""
    IF EXISTS (SELECT 1 FROM simulation_state WHERE id = 1)
    BEGIN
        UPDATE simulation_state
        SET current_year = :year,
            current_week = :week,
            next_year = :next_year,
            next_week = :next_week,
            simulation_seed = :seed,
            config_fingerprint = :fingerprint,
            checkpoint_json = :checkpoint_json,
            last_run = GETDATE()
        WHERE id = 1
    END
    ELSE
    BEGIN
        INSERT INTO simulation_state (
            id, current_year, current_week, next_year, next_week,
            simulation_seed, config_fingerprint, checkpoint_json, last_run
        )
        VALUES (
            1, :year, :week, :next_year, :next_week,
            :seed, :fingerprint, :checkpoint_json, GETDATE()
        )
    END
    """), params)
