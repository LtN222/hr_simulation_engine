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
    rng
):
    start_year = sector_config["start_year_simulation"]
    weeks_since_start = (year - start_year) * 52 + week

    growth_cfg = sector_config.get("growth", {})
    shock_probability = growth_cfg.get(
        "shock_probability",
        growth_cfg.get("shock_probablity", 0.05)
    )
    shock_min = growth_cfg.get("shock_min", -20)
    shock_max = growth_cfg.get("shock_max", 30)
    max_weekly_hires = growth_cfg.get("max_weekly_hires")
    max_weekly_growth_rate = growth_cfg.get("max_weekly_growth_rate")

    if not max_capacity:
        max_capacity = baseline_headcount * 1.5

    # annual_growth_rate is a yearly curve speed. The model advances in weeks,
    # so the logistic steepness is converted to a weekly value.
    growth_speed = (annual_growth_rate / 52) * (
        1 + 0.1 * (rng.random() - 0.5)
    )

    growth_factor = 1 / (
        1 + math.exp(
            -growth_speed * (weeks_since_start - weeks_before_peak_growth)
        )
    )

    trend_target = round(
        baseline_headcount
        + (max_capacity - baseline_headcount) * growth_factor
    )

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
        seasonal_offset = round(baseline_headcount * corrected_season)

    shock = 0

    if rng.random() < shock_probability:
        shock = rng.randint(shock_min, shock_max)

    active_count = len(
        fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ]
    )

    expected_size = trend_target + seasonal_offset + shock
    hires_needed = max(0, expected_size - active_count)

    # Even with a rising target curve, onboarding has an operational ceiling.
    # This prevents sudden jumps when the logistic curve enters its steepest
    # phase or when an accumulated vacancy backlog exists.
    weekly_caps = []

    if max_weekly_hires is not None:
        weekly_caps.append(int(max_weekly_hires))

    if max_weekly_growth_rate is not None:
        weekly_caps.append(max(1, round(active_count * max_weekly_growth_rate)))

    if weekly_caps:
        hires_needed = min(hires_needed, min(weekly_caps))

    return hires_needed
