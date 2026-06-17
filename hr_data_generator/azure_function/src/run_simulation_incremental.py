import logging
import random
from datetime import datetime

from src.application.simulation_runner import simulate_week
from src.core.config_loader import ConfigLoader
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.manager_builder import build_dim_manager
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
    state.setdefault("vacancies", 0)
    _normalize_date_columns(state)

    year_current, week_current = get_simulation_state(engine)
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
    state = build_dim_manager(state)

    logging.info("Incremental HR simulation finished")
    return state


def _normalize_date_columns(state):
    for df in state.values():
        if not hasattr(df, "columns"):
            continue

        for col in df.columns:
            if "date" not in col.lower() and "datum" not in col.lower():
                continue

            df[col] = df[col].apply(
                lambda x: datetime.combine(x, datetime.min.time())
                if x is not None and not isinstance(x, datetime)
                else x
            )
