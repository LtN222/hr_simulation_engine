"""The incremental load step: SQL/store tables -> a state a run can resume from.

A stored table can lag the configuration (a new static dimension, a new schema
column) and comes back with plain date columns, so loading is more than
`SELECT *`: the configuration-owned dimensions are repaired, schema-declared date
columns are coerced, and the checkpoint's persisted state is put back.
"""

import pandas as pd

from src.infrastructure.dimension_factory import generate_dimensions
from src.infrastructure.dimensions import (
    build_dim_department,
    build_dim_departure_reason,
    build_dim_role,
)
from src.infrastructure.state.checkpoint import restore_state, validate_checkpoint


def load_incremental_state(store, config, schema, seed):
    """Load the store, validate its checkpoint and return (state, checkpoint)."""
    state, checkpoint = store.load(schema)
    validate_checkpoint(checkpoint, seed, config)
    ensure_missing_static_dimensions(state, config, schema)
    normalize_date_columns(state, schema)
    restore_state(state, checkpoint)
    return state, checkpoint


def normalize_date_columns(state, schema):
    """Coerce genuinely date/datetime-typed columns to pandas datetime dtype.

    Which columns count as dates is decided from the schema's own declared
    SQL types (matching the "DATE"-prefix convention `map_sql_types` already
    uses), not from a name heuristic - a column name merely *containing*
    "date" is not reliable: `dim_candidate_quality_driver.CandidateQualityDriver_Key`
    (an INT primary key) contains "date" inside "Candi-date", which the
    previous `"date" in col.lower()` check matched. `pd.to_datetime` then
    reinterpreted its small integer values (1-6) as nanoseconds since the
    Unix epoch, corrupting the column into a handful of indistinguishable
    1970-01-01 timestamps once truncated to `datetime.datetime` - which
    Azure SQL then rejected on write with an INT/datetime2 type clash,
    crashing every incremental run that needed to insert into that table.
    """
    for table_name, df in state.items():
        if not hasattr(df, "columns"):
            continue

        column_types = schema.get(table_name, {}).get("types", {})
        for col in df.columns:
            sql_type = column_types.get(col)
            if not sql_type or not sql_type.startswith("DATE"):
                continue

            df[col] = pd.to_datetime(df[col], errors="coerce")


def ensure_missing_static_dimensions(state, config, schema):
    """Seed new static dimensions and repair missing configured members."""
    expected_dimensions = generate_dimensions(config, schema)
    expected_departments = build_dim_department(config.structure)
    expected_dimensions["dim_department"] = expected_departments
    expected_dimensions["dim_role"] = build_dim_role(
        config.structure,
        expected_departments,
        expected_dimensions.get("dim_salary_scale"),
        getattr(config, "salary_benchmark", {}).get("market_median_by_role", {}),
        getattr(config, "role_career_paths", {}),
    )
    expected_dimensions["dim_departure_reason"] = build_dim_departure_reason(
        config.dim_departure_reason
    )

    for table_name, dataframe in expected_dimensions.items():
        current = state.get(table_name)
        if current is None or current.empty:
            state[table_name] = dataframe
            continue

        primary_key = schema[table_name]["primary_key"]
        if primary_key not in current.columns:
            state[table_name] = dataframe
            continue

        # Static dimensions are configuration-owned. Preserve existing keys so
        # fact rows stay valid, but refresh their descriptive attributes and
        # add any columns introduced by an evolving schema.
        current = current.copy()
        for column in dataframe.columns:
            if column not in current.columns:
                current[column] = pd.NA
        expected_by_key = dataframe.set_index(primary_key)
        for index, key in current[primary_key].items():
            if key not in expected_by_key.index:
                continue
            for column in dataframe.columns:
                if column != primary_key:
                    current.at[index, column] = expected_by_key.at[key, column]

        current_keys = {
            str(value)
            for value in current[primary_key].dropna().tolist()
        }
        missing_rows = dataframe[
            ~dataframe[primary_key].astype(str).isin(current_keys)
        ]
        if not missing_rows.empty:
            current = pd.concat(
                [current, missing_rows],
                ignore_index=True
            )
        state[table_name] = current
