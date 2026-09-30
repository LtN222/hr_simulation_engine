"""Expected incident rates implied by the safety configuration.

`safety.annual_incident_rate_by_department` is a *base* rate; the realized
rate is that base times the shift factor (department mix of flagged
ploegendienst roles and shifts) times the new-hire factor. The realized rate
per employee-year is what is calibrated against
`safety.target_incident_rate_by_department`, so a change to the shift mix or a
multiplier that would silently move the realized rate is caught by a test and
can be re-derived with `calibrated_base_rate`.

Everything is derived from configuration: the flagged-role share comes from
the real workforce allocation (`allocate_headcount`), the shift mix from
`ploegendienst_assignment` and the multipliers from `safety`.
"""

from src.application.allocation import allocate_headcount
from src.infrastructure.shift_assignment import shift_mix


def reference_headcount(config):
    """Headcount the flagged-role share is measured at (default: the growth ceiling)."""
    calibration = _safety(config).get("calibration", {})
    return int(
        calibration.get("reference_headcount")
        or getattr(config, "growth", {}).get("max_capacity")
        or getattr(config, "baseline_headcount")
    )


def flagged_role_share(config, department, headcount=None):
    """Share of a department's allocated employees in ploegendienst roles."""
    allocations = _allocation(config, headcount or reference_headcount(config))
    total = flagged = 0
    for allocation in allocations:
        if allocation["Afdeling_Naam"] != department:
            continue
        total += allocation["count"]
        role = config.structure[department][allocation["Functie_Naam"]]
        if role.get("ploegendienst", False):
            flagged += allocation["count"]
    return flagged / total if total else 0.0


def expected_shift_factor(config, department, headcount=None):
    """E[shift factor]: unflagged roles are 1.0, flagged roles follow the mix."""
    multipliers = _safety(config).get("ploegendienst_multipliers", {})
    values, weights = shift_mix(config, department)
    total_weight = sum(weights)
    flagged_factor = sum(
        weight / total_weight * float(multipliers.get(value, 1.0))
        for value, weight in zip(values, weights)
    )
    share = flagged_role_share(config, department, headcount)
    return (1 - share) + share * flagged_factor


def expected_new_hire_factor(config, new_hire_share):
    """E[new-hire factor] for a share of employees within the new-hire window."""
    rule = _safety(config).get("new_hire_multiplier", {})
    multiplier = float(rule.get("multiplier", 1.0)) if int(rule.get("within_days", 0) or 0) > 0 else 1.0
    return 1 + float(new_hire_share) * (multiplier - 1)


def configured_new_hire_share(config, department):
    shares = _safety(config).get("calibration", {}).get("new_hire_share_by_department", {})
    return float(shares.get(department, 0.0))


def expected_annual_incident_rate(
    config, department, new_hire_share=None, headcount=None, base_rate=None
):
    """Realized incidents per employee-year: base * E[shift] * E[new-hire]."""
    if base_rate is None:
        base_rate = float(
            _safety(config).get("annual_incident_rate_by_department", {}).get(department, 0.0)
        )
    if new_hire_share is None:
        new_hire_share = configured_new_hire_share(config, department)
    return (
        float(base_rate)
        * expected_shift_factor(config, department, headcount)
        * expected_new_hire_factor(config, new_hire_share)
    )


def calibrated_base_rate(config, department, target=None, new_hire_share=None, headcount=None):
    """Base rate that realizes `target` incidents per employee-year (unrounded)."""
    if target is None:
        target = float(_safety(config)["target_incident_rate_by_department"][department])
    per_unit_base = expected_annual_incident_rate(
        config, department, new_hire_share, headcount, base_rate=1.0
    )
    return float(target) / per_unit_base


def expected_lost_time_incidents_per_100_fte(config, default_new_hire_share=None, headcount=None):
    """Company-wide expected lost-time incidents per 100 FTE per year.

    Department incident rates use the configured base rates; a department
    without a configured new-hire share uses `default_new_hire_share`
    (default: the headcount-weighted mean of the configured shares).
    Employees are converted to FTE with the contract-hours distribution.
    """
    headcount = headcount or reference_headcount(config)
    allocations = _allocation(config, headcount)
    shares = _safety(config).get("calibration", {}).get("new_hire_share_by_department", {})
    if default_new_hire_share is None:
        default_new_hire_share = (
            sum(shares.values()) / len(shares) if shares else 0.0
        )
    weights = _safety(config).get("type_weights", {})
    lost_time_share = float(weights.get("Verzuimongeval", 0.0)) / (sum(weights.values()) or 1.0)

    incidents = fte = 0.0
    for allocation in allocations:
        department = allocation["Afdeling_Naam"]
        share = shares.get(department, default_new_hire_share)
        rate = expected_annual_incident_rate(config, department, share, headcount)
        incidents += allocation["count"] * rate * lost_time_share
        fte += allocation["count"] * _mean_fte(config, allocation["Functie_Naam"])
    return 100 * incidents / fte if fte else 0.0


def _mean_fte(config, role_name):
    distribution = getattr(config, "contract_hours_distribution", {})
    role = distribution.get(role_name, distribution.get("default", {"40": 1.0}))
    full_time = float(getattr(config, "workforce", {}).get("full_time_weekly_hours", 40))
    total = sum(role.values())
    return sum(int(hours) / full_time * weight for hours, weight in role.items()) / total


def _allocation(config, headcount):
    return allocate_headcount(
        config.structure, int(headcount), config.staffing, config.workforce_planning
    )


def _safety(config):
    return getattr(config, "safety", {})
