import math


def calculate_growth_target(
    fact_employment,
    sector_config,
    baseline_headcount,
    max_capacity,
    year,
    week,
    annual_growth_rate,
    weeks_before_peak_growth,
    rng   # 👈 nodig voor deterministic shocks
):
    # -------------------------------------------------
    # 1️⃣ Tijd sinds start bepalen
    # -------------------------------------------------

    start_year = sector_config["start_year_simulation"]
    weeks_since_start = (year - start_year) * 52 + week

    # -------------------------------------------------
    # 2️⃣ Growth config ophalen
    # -------------------------------------------------

    growth_cfg = sector_config.get("growth", {})

    shock_probability = growth_cfg.get("shock_probablity", 0.05)
    shock_min = growth_cfg.get("shock_min", -20)
    shock_max = growth_cfg.get("shock_max", 30)

    # fallback max capacity
    if not max_capacity:
        max_capacity = baseline_headcount * 1.5

    # -------------------------------------------------
    # 3️⃣ Logistic growth (parametrized)
    # -------------------------------------------------

    # annual_growth_rate gebruiken als snelheid (steepness)
    growth_speed = annual_growth_rate * (1 + 0.1 * (rng.random() - 0.5))  # ~0.02–0.04 werkt goed

    growth_factor = 1 / (
        1 + math.exp(
            -growth_speed * (weeks_since_start - weeks_before_peak_growth)
        )
    )

    trend_target = round(
        baseline_headcount +
        (max_capacity - baseline_headcount) * growth_factor
    )

    # -------------------------------------------------
    # 4️⃣ Seasonality
    # -------------------------------------------------

    seasonal_offset = 0

    if (
        "seasonality" in sector_config
        and sector_config["seasonality"]["enabled"]
    ):

        amplitude = sector_config["seasonality"]["amplitude"]
        phase_shift = sector_config["seasonality"]["phase_shift_weeks"]

        raw_season = amplitude * math.sin(
            2 * math.pi * (week - phase_shift) / 52
        )

        raw_season_end = amplitude * math.sin(
            2 * math.pi * (52 - phase_shift) / 52
        )

        corrected_season = raw_season - raw_season_end

        seasonal_offset = round(
            baseline_headcount * corrected_season
        )

    # -------------------------------------------------
    # 5️⃣ Deterministic shocks
    # -------------------------------------------------

    shock = 0

    if rng.random() < shock_probability:
        shock = rng.randint(shock_min, shock_max)

    # -------------------------------------------------
    # 6️⃣ Huidige workforce
    # -------------------------------------------------

    active_count = len(
        fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ]
    )

    # -------------------------------------------------
    # 7️⃣ Expected size → hires
    # -------------------------------------------------

    expected_size = trend_target + seasonal_offset + shock

    hires_needed = max(0, expected_size - active_count)

    return hires_needed