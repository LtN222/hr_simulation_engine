from datetime import datetime

from src.generator.simulation_attrition import simulate_attrition
from src.generator.simulation_growth import calculate_growth_target
from src.generator.simulation_hiring import simulate_hiring
from src.generator.simulation_career_events import simulate_career_events

# =====================================================
# WEEKLY HR SIMULATION ORCHESTRATOR
# =====================================================
# Orkestreert alle HR events per week
#
# Volgorde:
#
# 1️⃣ Attrition
# 2️⃣ Growth target bepalen
# 3️⃣ Hiring uitvoeren
# =====================================================

def simulate_week(
    state,
    config,
    schema,
    year,
    week,
    baseline_headcount,
    max_capacity,
    annual_growth_rate,
    weeks_before_peak_growth,   # 👈 NIEUW
    rng,
    promotion_rate,
    transfer_rate
):

    today = datetime.fromisocalendar(year, week, 1)

    dim_event_type = state["dim_event_type"]
    dim_reden_vertrek = state["dim_reden_vertrek"]

    # event type mapping
    event_type_map = dict(
        zip(
            dim_event_type["EventType"],
            dim_event_type["EventType_Key"]
        )
    )

    # vertrekreden mapping
    reden_vertrek_map = dict(
        zip(
            dim_reden_vertrek["RedenVertrek"],
            dim_reden_vertrek["RedenVertrek_Key"]
        )
    )

    # =====================================================
    # 1️⃣ Attrition simuleren
    # =====================================================

    state = simulate_attrition(
        state,
        config,
        schema,
        today,
        rng,
        event_type_map,
        reden_vertrek_map
    )

    # =====================================================
    # Career events simuleren
    # =====================================================

    state = simulate_career_events(
        state,
        config,
        schema,
        today,
        rng,
        event_type_map,
        promotion_rate,
        transfer_rate
    )

    # =====================================================
    # 2️⃣ Groei berekenen
    # =====================================================

    hires_needed = calculate_growth_target(
        state["fact_employment"],
        config,
        baseline_headcount,
        max_capacity,
        year,
        week,
        annual_growth_rate,
        weeks_before_peak_growth,
        rng
    )

    state["vacancies"] += hires_needed
    # =====================================================
    # 3️⃣ Hiring simuleren
    # =====================================================

    state = simulate_hiring(
        state,
        config,
        schema,
        today,
        rng,
        event_type_map
    )

    state["vacancies"] += hires_needed



    return state