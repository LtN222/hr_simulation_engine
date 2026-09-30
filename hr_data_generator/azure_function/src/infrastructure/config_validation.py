"""Structural validation for the sector configuration's role model.

`structure`/`role_career_paths` in the sector config are large and
hand-maintained; a typo in either (a dangling promotion target, a
department_key mismatch, a lateral transfer across salary scales, an
`active_from_headcount` threshold the company can never reach, a
`relevante_opleidingen` entry with no matching `dim_education` row) would
otherwise fail silently rather than loudly - the generator would just run
with subtly wrong eligibility/reporting data.
"""

import pandas as pd

from src.infrastructure.salary_policy import SalaryPolicy
from src.simulation.simulation_safety import LOST_TIME_ABSENCE_TYPE


def validate_role_configuration(config):
    """Return a list of human-readable problems; an empty list means the
    role configuration is internally consistent."""
    structure = getattr(config, "structure", {}) or {}
    role_career_paths = getattr(config, "role_career_paths", {}) or {}
    growth = getattr(config, "growth", {}) or {}
    dim_education = getattr(config, "dim_education", []) or []

    all_role_names = {
        role_name for roles in structure.values() for role_name in roles.keys()
    }
    education_names = {entry.get("Opleiding_Naam") for entry in dim_education}

    problems = []
    problems.extend(_check_role_key_uniqueness(structure))
    problems.extend(_check_department_key_consistency(structure))
    problems.extend(_check_career_path_targets_exist(role_career_paths, all_role_names))
    problems.extend(_check_lateral_transfer_salary_scales(structure, role_career_paths))
    problems.extend(_check_unreachable_roles(structure, growth))
    problems.extend(_check_relevante_opleidingen_resolve(role_career_paths, education_names))
    problems.extend(_check_salary_scales(config, structure))
    problems.extend(_check_lost_time_absence_type(config))
    problems.extend(_check_voluntary_reasons_exist(config))
    problems.extend(_check_hire_source_weights(config))
    return problems


def _check_role_key_uniqueness(structure):
    problems = []
    seen = {}
    for department, roles in structure.items():
        for role_name, role_config in roles.items():
            role_key = role_config.get("role_key")
            location = f"{department}/{role_name}"
            if role_key is None:
                problems.append(f"{location}: missing role_key")
                continue
            if role_key in seen:
                problems.append(
                    f"role_key {role_key} is used by both {seen[role_key]} and {location}"
                )
            else:
                seen[role_key] = location
    return problems


def _check_department_key_consistency(structure):
    """Every role within a department must agree on that department's key,
    and no two departments may share one."""
    problems = []
    department_key_owner = {}
    for department, roles in structure.items():
        keys_in_department = {role_config.get("department_key") for role_config in roles.values()}
        if len(keys_in_department) > 1:
            problems.append(f"{department}: roles disagree on department_key: {sorted(keys_in_department, key=str)}")
            continue
        department_key = next(iter(keys_in_department), None)
        if department_key is None:
            problems.append(f"{department}: missing department_key")
            continue
        owner = department_key_owner.get(department_key)
        if owner is not None and owner != department:
            problems.append(f"department_key {department_key} is used by both {owner} and {department}")
        else:
            department_key_owner[department_key] = department
    return problems


def _check_career_path_targets_exist(role_career_paths, all_role_names):
    problems = []
    for source, paths in role_career_paths.items():
        for field in ("logische_doorgroei", "laterale_transfers"):
            for target in paths.get(field, []):
                if target not in all_role_names:
                    problems.append(f"{source}.{field} references unknown role '{target}'")
    return problems


def _check_lateral_transfer_salary_scales(structure, role_career_paths):
    problems = []
    role_scale = {
        role_name: role_config.get("salary_scale_code")
        for roles in structure.values()
        for role_name, role_config in roles.items()
    }
    for source, paths in role_career_paths.items():
        source_scale = role_scale.get(source)
        for target in paths.get("laterale_transfers", []):
            if target not in role_scale:
                continue  # already reported by _check_career_path_targets_exist
            target_scale = role_scale.get(target)
            if source_scale != target_scale:
                problems.append(
                    f"lateral transfer {source} ({source_scale}) -> {target} "
                    f"({target_scale}): salary scales differ"
                )
    return problems


def _check_unreachable_roles(structure, growth):
    """A role with a non-zero target weight whose own active_from_headcount
    exceeds the company's configured growth ceiling can never activate."""
    problems = []
    max_capacity = growth.get("max_capacity")
    if max_capacity is None:
        return problems
    for department, roles in structure.items():
        for role_name, role_config in roles.items():
            weight = float(role_config.get("target_weight", role_config.get("fte_ratio", 0)))
            threshold = role_config.get("active_from_headcount")
            if weight > 0 and threshold is not None and int(threshold) > int(max_capacity):
                problems.append(
                    f"{department}/{role_name}: active_from_headcount ({threshold}) "
                    f"exceeds growth.max_capacity ({max_capacity}) - unreachable"
                )
    return problems


def _check_relevante_opleidingen_resolve(role_career_paths, education_names):
    problems = []
    for role_name, paths in role_career_paths.items():
        for education in paths.get("relevante_opleidingen", []):
            if education not in education_names:
                problems.append(
                    f"{role_name}.relevante_opleidingen references unknown education '{education}'"
                )
    return problems


def _check_salary_scales(config, structure):
    """Market medians, salary scales and the legal minimum must fit together.

    (a) every role has a market median; (b) every role's market P25-P75 lies
    inside its salary scale (a scale without a maximum only bounds the
    minimum); (c) the lowest scale starts at or above the legal minimum in
    the first simulated year, the lowest indexed floor.

    Skipped when the config has no `salary_benchmark`/`dim_salary_scale`.
    """
    benchmark = getattr(config, "salary_benchmark", None)
    scales = getattr(config, "dim_salary_scale", None)
    if not benchmark or not scales:
        return []

    problems = []
    medians = benchmark.get("market_median_by_role", {})
    spread = float(benchmark.get("market_percentile_spread", 0.10))
    scale_by_code = {scale.get("Salarisschaal_Code"): scale for scale in scales}

    for department, roles in structure.items():
        for role_name, role_config in roles.items():
            location = f"{department}/{role_name}"
            median = medians.get(role_name)
            if median is None:
                problems.append(f"{location}: no market median in salary_benchmark.market_median_by_role")
                continue
            code = role_config.get("salary_scale_code")
            scale = scale_by_code.get(code)
            if scale is None:
                continue
            p25, p75 = median * (1 - spread), median * (1 + spread)
            minimum, maximum = scale.get("Minimum_Salaris"), scale.get("Maximum_Salaris")
            if minimum is not None and p25 < minimum:
                problems.append(
                    f"{location}: market P25 {p25:,.0f} is below the minimum {minimum:,.0f} of scale {code}"
                )
            if maximum is not None and p75 > maximum:
                problems.append(
                    f"{location}: market P75 {p75:,.0f} is above the maximum {maximum:,.0f} of scale {code}"
                )

    if "legal_minimum_salary" in benchmark:
        floor = SalaryPolicy(config).legal_minimum(
            pd.Timestamp(benchmark.get("base_date", "2020-01-01"))
        )
        lowest = min(scales, key=lambda scale: scale["Minimum_Salaris"])
        if lowest["Minimum_Salaris"] < floor:
            problems.append(
                f"lowest scale {lowest.get('Salarisschaal_Code')} starts at "
                f"{lowest['Minimum_Salaris']:,.0f}, below the indexed legal minimum {floor:,.0f} "
                f"on the benchmark base date"
            )
    return problems


def _check_lost_time_absence_type(config):
    """The safety simulator owns the lost-time absence type: it must exist in
    `dim_absence_type` and be kept out of the absence simulator's random draw,
    otherwise it is created twice (AR-33)."""
    absence_types = getattr(config, "dim_absence_type", None)
    absence = getattr(config, "absence", None)
    if absence_types is None or absence is None:
        return []
    problems = []
    if LOST_TIME_ABSENCE_TYPE not in absence_types:
        problems.append(
            f"dim_absence_type has no '{LOST_TIME_ABSENCE_TYPE}' (used by the safety simulator)"
        )
    if LOST_TIME_ABSENCE_TYPE not in absence.get("excluded_from_random_draw", []):
        problems.append(
            f"absence.excluded_from_random_draw must list '{LOST_TIME_ABSENCE_TYPE}'"
        )
    return problems


def _check_voluntary_reasons_exist(config):
    """A garbled or misspelled reason key silently never matches (AR-40)."""
    attrition = getattr(config, "attrition", None)
    reasons = getattr(config, "dim_departure_reason", None)
    if not attrition or not reasons:
        return []
    known = {reason for group in reasons.values() for reason in group}
    return [
        f"attrition.voluntary_reason_satisfaction_multipliers: '{reason}' is not in dim_departure_reason"
        for reason in attrition.get("voluntary_reason_satisfaction_multipliers", {})
        if reason not in known
    ]


def _check_hire_source_weights(config):
    """Every weighted initial hire source must exist and be external."""
    weights = (getattr(config, "initial_population", None) or {}).get("hire_source_weights")
    sources = getattr(config, "dim_hire_source", None)
    if not weights or not sources:
        return []
    by_name = {source.get("Bron_Naam"): source for source in sources}
    problems = []
    for name in weights:
        source = by_name.get(name)
        if source is None:
            problems.append(f"initial_population.hire_source_weights: '{name}' is not in dim_hire_source")
        elif source.get("Is_Internal", False):
            problems.append(
                f"initial_population.hire_source_weights: '{name}' is an internal source"
            )
    return problems

