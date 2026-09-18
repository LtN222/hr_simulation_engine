"""Structural validation for the sector configuration's role model.

`structure`/`role_career_paths` in the sector config are large and
hand-maintained; a typo in either (a dangling promotion target, a
department_key mismatch, a lateral transfer across salary scales, an
`active_from_headcount` threshold the company can never reach, a
`relevante_opleidingen` entry with no matching `dim_education` row) would
otherwise fail silently rather than loudly - the generator would just run
with subtly wrong eligibility/reporting data.
"""


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
