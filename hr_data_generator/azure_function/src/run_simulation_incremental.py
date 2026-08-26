import logging
import random
from datetime import datetime

import pandas as pd

from src.application.simulation_runner import simulate_week
from src.core.config_loader import ConfigLoader
from src.infrastructure.absence_context import sync_absence_satisfaction
from src.infrastructure.avatar import ensure_employee_avatars
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.dimension_factory import generate_dimensions
from src.infrastructure.dimensions import (
    build_dim_department,
    build_dim_departure_reason,
    build_dim_role
)
from src.infrastructure.departure_context import (
    sync_departure_satisfaction,
    sync_employment_hire_sources,
)
from src.infrastructure.employee_status import sync_employee_employment_status
from src.infrastructure.manager_builder import build_dim_manager
from src.infrastructure.manager_assignment import sync_manager_assignments
from src.infrastructure.recruitment_context import sync_recruitment_status_keys
from src.infrastructure.workforce_snapshot import build_workforce_snapshots
from src.infrastructure.state.load_state import load_current_state
from src.infrastructure.state.simulation_state import (
    get_simulation_state,
    update_simulation_state
)


def run_incremental_simulation(engine, sector, seed):
    logging.info("Starting incremental HR simulation")

    rng = random.Random(seed)
    config = ConfigLoader().load()
    schema = load_schema(config.schema)

    baseline_headcount = config.baseline_headcount
    growth_cfg = config.growth
    annual_growth_cfg = growth_cfg.get("annual_growth_rate", {})
    annual_growth_rate = rng.uniform(
        annual_growth_cfg.get("min", 0.02),
        annual_growth_cfg.get("max", 0.04)
    )
    max_capacity = growth_cfg.get("max_capacity", baseline_headcount * 1.5)
    weeks_before_peak_growth = growth_cfg.get("weeks_before_peak_growth", 100)

    career_cfg = config.career_events
    promotion_rate = career_cfg.get("promotion_rate", 0)
    transfer_rate = career_cfg.get("internal_transfer_rate", 0)

    state = load_current_state(engine, schema)
    _ensure_missing_static_dimensions(state, config, schema)
    state = sync_recruitment_status_keys(state)
    state.setdefault("vacancies", 0)
    _normalize_date_columns(state)
    state = sync_employee_employment_status(state)
    state = ensure_employee_avatars(state, config)

    year_current, week_current = get_simulation_state(
        engine,
        default_year=config.start_year_simulation,
        default_week=1
    )
    today = datetime.today()

    logging.info(
        f"Continuing simulation from year {year_current}, week {week_current}"
    )

    while datetime.fromisocalendar(year_current, week_current, 1) <= today:
        state = simulate_week(
            state,
            config,
            schema,
            year_current,
            week_current,
            baseline_headcount,
            max_capacity,
            annual_growth_rate,
            weeks_before_peak_growth,
            rng,
            promotion_rate,
            transfer_rate
        )

        week_current += 1
        if week_current > 52:
            week_current = 1
            year_current += 1

    last_week = week_current - 1
    last_year = year_current

    if last_week == 0:
        last_week = 52
        last_year -= 1

    update_simulation_state(engine, last_year, last_week)
    state = sync_employee_employment_status(state)
    state = sync_employment_hire_sources(state)
    state = sync_manager_assignments(state, schema, today)
    state = build_dim_manager(state)
    state = sync_absence_satisfaction(state, config)
    state = build_workforce_snapshots(
        state,
        schema,
        config=config,
        start_date=datetime(config.start_year_simulation, 1, 1),
        end_date=today
    )
    state = sync_departure_satisfaction(state)

    logging.info("Incremental HR simulation finished")
    return state


def _normalize_date_columns(state):
    for df in state.values():
        if not hasattr(df, "columns"):
            continue

        for col in df.columns:
            if "date" not in col.lower() and "datum" not in col.lower():
                continue

            df[col] = pd.to_datetime(df[col], errors="coerce")


def _ensure_missing_static_dimensions(state, config, schema):
    """Seed new static dimensions and repair missing configured members."""
    expected_dimensions = generate_dimensions(config, schema)
    expected_departments = build_dim_department(config.structure)
    expected_dimensions["dim_department"] = expected_departments
    expected_dimensions["dim_role"] = build_dim_role(
        config.structure,
        expected_departments,
        expected_dimensions.get("dim_salary_scale"),
            getattr(config, "salary_benchmark", {}).get("market_median_by_role", {})
            ,getattr(config, "role_career_paths", {})
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
