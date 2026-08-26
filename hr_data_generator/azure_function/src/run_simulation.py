import logging
import random
from datetime import datetime

from src.application.population import WorkforceGenerator
from src.application.simulation_runner import simulate_week
from src.core.config_loader import ConfigLoader
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.absence_context import sync_absence_satisfaction
from src.infrastructure.avatar import ensure_employee_avatars
from src.infrastructure.departure_context import (
    sync_departure_satisfaction,
    sync_employment_hire_sources,
)
from src.infrastructure.employee_status import sync_employee_employment_status
from src.infrastructure.recruitment_context import sync_recruitment_status_keys
from src.infrastructure.manager_builder import build_dim_manager
from src.infrastructure.manager_assignment import sync_manager_assignments
from src.infrastructure.workforce_snapshot import build_workforce_snapshots
from src.infrastructure.state.simulation_state import update_simulation_state


def run_simulation(engine, sector, seed):
    logging.info("Starting full HR simulation")

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

    initial_population_cfg = config.initial_population
    burn_in_years = max(
        0,
        int(initial_population_cfg.get("burn_in_years", 0))
    )
    visible_start_date = datetime(config.start_year_simulation, 1, 1)
    burn_in_start_date = datetime(
        config.start_year_simulation - burn_in_years,
        1,
        1
    )
    initial_headcount = int(initial_population_cfg.get(
        "headcount",
        baseline_headcount
    ))

    career_cfg = config.career_events
    promotion_rate = career_cfg.get("promotion_rate", 0)
    transfer_rate = career_cfg.get("internal_transfer_rate", 0)

    state = WorkforceGenerator(
        sector=sector,
        seed=seed,
        initial_date=burn_in_start_date,
        initial_headcount=initial_headcount
    ).run()
    state = ensure_employee_avatars(state, config)
    state["vacancies"] = 0

    # The workforce is warmed up before the visible simulation period. This
    # lets attrition, hiring, vacancies and management assignments settle
    # instead of making January of the first visible year an artificial reset.
    year_current = config.start_year_simulation - burn_in_years
    week_current = 1
    simulation_end_date = datetime.today()

    while datetime.fromisocalendar(year_current, week_current, 1) <= simulation_end_date:
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
            transfer_rate,
            simulation_start_date=burn_in_start_date
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
    state = sync_recruitment_status_keys(state)
    state = sync_manager_assignments(state, schema, simulation_end_date)
    state = build_dim_manager(state)
    state = sync_absence_satisfaction(state, config)
    state = build_workforce_snapshots(
        state,
        schema,
        config=config,
        start_date=visible_start_date,
        end_date=simulation_end_date
    )
    state = sync_departure_satisfaction(state)

    logging.info("Full HR simulation finished successfully")
    return state
