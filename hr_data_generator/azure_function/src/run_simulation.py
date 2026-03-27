import logging
from datetime import datetime, timedelta
import random

from src.generator.population import generate_initial_workforce
from src.generator.simulation import simulate_week
from src.generator.config_loader import load_config
from src.database.schema_loader import load_schema
from src.database.simulation_state import update_simulation_state
from src.generator.manager_builder import build_dim_manager

# =====================================================
# SIMULATION ORCHESTRATOR
# =====================================================
# Volledige HR simulatie pipeline
#
# Flow:
#
# 1️⃣ Initial workforce genereren
# 2️⃣ Weekly simulation uitvoeren
# 3️⃣ Simulation state opslaan
# =====================================================


def run_simulation(engine, sector, seed):

    logging.info("Starting HR simulation")

    # -------------------------------------------------
    # 1️⃣ Config laden
    # -------------------------------------------------

    rng = random.Random(seed)

    config = load_config(sector)
    schema = load_schema(config["schema"])

    start_year = config["start_year_simulation"]
    baseline_headcount = config["baseline_headcount"]

    max_capacity = config.get("max_capacity", baseline_headcount * 1.8)

    year_current = start_year
    week_current = 1

    #start_date = datetime(start_year, 1, 1)

    simulation_end_date = datetime.today()

    # -------------------------------------------------
    # Growth rate bepalen
    # -------------------------------------------------

    growth_cfg = config.get("growth", {})

    annual_growth_cfg = growth_cfg.get("annual_growth_rate", {})
    annual_growth_rate = rng.uniform(
        annual_growth_cfg.get("min", 0.02),
        annual_growth_cfg.get("max", 0.04)
    )

    max_capacity = growth_cfg.get(
        "max_capacity",
        baseline_headcount * 1.5
    )

    weeks_before_peak_growth = growth_cfg.get(
        "weeks_before_peak_growth",
        100
    )

    # -------------------------------------------------
    # Career event parameters
    # -------------------------------------------------

    career_cfg = config.get("career_events", {})

    promotion_rate = career_cfg.get("promotion_rate", 0)
    transfer_rate = career_cfg.get("internal_transfer_rate", 0)

    # -------------------------------------------------
    # 2️⃣ Initiële workforce genereren
    # -------------------------------------------------

    state = generate_initial_workforce(
        sector=sector,
        seed=seed
    )

    state["vacancies"] = 0
    # -------------------------------------------------
    # 3️⃣ Weekly simulation
    # -------------------------------------------------

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
            weeks_before_peak_growth,   # 👈 NIEUW
            rng,
            promotion_rate,
            transfer_rate
        )

        # ---------------------------------------------
        # Week vooruit
        # ---------------------------------------------

        week_current += 1

        if week_current > 52:
            week_current = 1
            year_current += 1

    # -------------------------------------------------
    # 4️⃣ Simulation state bepalen
    # -------------------------------------------------

    last_week = week_current - 1
    last_year = year_current

    if last_week == 0:
        last_week = 52
        last_year -= 1

    # -------------------------------------------------
    # 5️⃣ Simulation state opslaan
    # -------------------------------------------------

    update_simulation_state(
        engine,
        last_year,
        last_week
        
    )

    logging.info(
        f"Simulation state updated → year {last_year}, week {last_week}"
    )

    logging.info("HR simulation finished successfully")

    # -------------------------------------------------
    # 6 dim_manager bouwen uit employments
    # -------------------------------------------------
    state = build_dim_manager(state)
    # -------------------------------------------------
    # 7 Resultaat retourneren
    # -------------------------------------------------

    return state