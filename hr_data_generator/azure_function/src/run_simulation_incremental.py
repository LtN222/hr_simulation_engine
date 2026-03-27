import logging
from datetime import datetime
import random

from src.generator.simulation import simulate_week
from src.generator.config_loader import load_config
from src.database.schema_loader import load_schema
from src.database.load_state import load_current_state
from src.database.simulation_state import (
    get_simulation_state,
    update_simulation_state
)
from src.generator.manager_builder import build_dim_manager


def run_incremental_simulation(engine, sector, seed):

    logging.info("Starting incremental HR simulation")

    rng = random.Random(seed)

    # -------------------------------------------------
    # 1️⃣ Config + schema laden (IDENTIEK aan full run)
    # -------------------------------------------------

    config = load_config(sector)
    schema = load_schema(config["schema"])

    baseline_headcount = config["baseline_headcount"]

    # 👉 zelfde growth config als full run
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
    # Career events (zelfde als full)
    # -------------------------------------------------

    career_cfg = config.get("career_events", {})

    promotion_rate = career_cfg.get("promotion_rate", 0)
    transfer_rate = career_cfg.get("internal_transfer_rate", 0)

    # -------------------------------------------------
    # 2️⃣ State laden
    # -------------------------------------------------

    state = load_current_state(engine, schema)

    # Zorg dat vacancies bestaat (consistent met full run)
    if "vacancies" not in state:
        state["vacancies"] = 0

    # -------------------------------------------------
    # Fix date/datetime inconsistency
    # -------------------------------------------------

    for table_name, df in state.items():

        if hasattr(df, "columns"):

            for col in df.columns:

                # alleen kolommen die op datum lijken
                if "date" in col.lower() or "datum" in col.lower():

                    df[col] = df[col].apply(
                        lambda x: datetime.combine(x, datetime.min.time())
                        if x is not None and not isinstance(x, datetime)
                        else x
                    )

    # -------------------------------------------------
    # 3️⃣ Laatste simulatiestatus ophalen
    # -------------------------------------------------

    year_current, week_current = get_simulation_state(engine)

    today = datetime.today()

    logging.info(
        f"Continuing simulation from year {year_current}, week {week_current}"
    )

    # -------------------------------------------------
    # 4️⃣ Weekly simulation (IDENTIEK aan full run)
    # -------------------------------------------------

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

        # ---------------------------------------------
        # Week vooruit
        # ---------------------------------------------

        week_current += 1

        if week_current > 52:
            week_current = 1
            year_current += 1

    # -------------------------------------------------
    # 5️⃣ Simulatiestatus bepalen
    # -------------------------------------------------

    last_week = week_current - 1
    last_year = year_current

    if last_week == 0:
        last_week = 52
        last_year -= 1

    # -------------------------------------------------
    # 6️⃣ Simulatiestatus opslaan
    # -------------------------------------------------

    update_simulation_state(
        engine,
        last_year,
        last_week
    )

    logging.info(
        f"Simulation state updated → year {last_year}, week {last_week}"
    )

    logging.info("Incremental HR simulation finished")

    # -------------------------------------------------
    # 7️⃣ dim_manager bouwen (consistent met full)
    # -------------------------------------------------

    state = build_dim_manager(state)

    # -------------------------------------------------
    # 8️⃣ Resultaat retourneren
    # -------------------------------------------------

    return state