import math
from datetime import date, datetime


def economic_event_for_date(growth_config, today):
    """Return the configured macro event active on ``today``, if any."""
    if isinstance(today, datetime):
        today = today.date()
    elif not isinstance(today, date):
        today = today.date()

    for event in growth_config.get("economic_events", []):
        start = date.fromisoformat(event["start_date"])
        end = date.fromisoformat(event["end_date"])
        if start <= today <= end:
            return event
    return None


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
    current_date = datetime.fromisocalendar(year, week, 1)
    start_date = datetime(start_year, 1, 1)
    years_since_start = max(
        0.0,
        (current_date - start_date).days / 365.2425
    )

    growth_cfg = sector_config.get("growth", {})
    shock_probability = growth_cfg.get(
        "shock_probability",
        growth_cfg.get("shock_probablity", 0.0)
    )
    shock_min = growth_cfg.get("shock_min", -20)
    shock_max = growth_cfg.get("shock_max", 30)
    max_weekly_hires = growth_cfg.get("max_weekly_hires")
    max_weekly_growth_rate = growth_cfg.get("max_weekly_growth_rate")

    if not max_capacity:
        max_capacity = baseline_headcount * 1.5

    # A compound annual path is easier to calibrate than a logistic curve and
    # does not imply that capacity must be reached within the visible horizon.
    # ``weeks_before_peak_growth`` remains accepted for runtime compatibility.
    _ = weeks_before_peak_growth
    trend_target = round(min(
        max_capacity,
        baseline_headcount * math.pow(1 + annual_growth_rate, years_since_start)
    ))

    economic_event = economic_event_for_date(growth_cfg, current_date)
    if economic_event:
        trend_target = round(
            trend_target * float(economic_event.get("target_multiplier", 1.0))
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
        seasonal_offset = round(trend_target * corrected_season)

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
