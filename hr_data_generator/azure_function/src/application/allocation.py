import math
from typing import Optional


def allocate_headcount(
    structure: dict,
    total_employees: int,
    staffing_rules: Optional[dict] = None
):
    """Allocate a total headcount over roles using largest remainders.

    Management roles need a minimum presence even when their fte ratio rounds
    down to zero.  The minimum is applied before the remaining employees are
    distributed by the configured workforce mix.
    """
    staffing_rules = staffing_rules or {}
    minimum_counts = _minimum_counts(
        structure,
        total_employees,
        staffing_rules
    )

    role_allocations = []

    for afdeling, functies in structure.items():
        for functie, details in functies.items():

            exact = total_employees * details["fte_ratio"]
            floor_count = int(exact)
            remainder = exact - floor_count
            minimum_count = minimum_counts[(afdeling, functie)]

            role_allocations.append({
                "Department_Name": afdeling,
                "Role_Name": functie,
                "count": max(floor_count, minimum_count),
                "remainder": remainder
            })

    current_total = sum(r["count"] for r in role_allocations)
    if current_total > total_employees:
        raise ValueError(
            "Headcount is too small for the configured minimum staffing "
            f"rules: {current_total} required, {total_employees} available."
        )

    remaining = total_employees - current_total

    # Prefer roles that are furthest below their ratio after minimums have
    # been applied. The original remainder remains the deterministic tie-break.
    role_allocations.sort(
        key=lambda item: (
            total_employees * _role_ratio(structure, item)
            - item["count"],
            item["remainder"]
        ),
        reverse=True
    )

    i = 0
    while remaining > 0:
        role_allocations[i]["count"] += 1
        remaining -= 1
        i = (i + 1) % len(role_allocations)

    return role_allocations


def _role_ratio(structure, allocation):
    return structure[allocation["Department_Name"]][
        allocation["Role_Name"]
    ]["fte_ratio"]


def minimum_count_for_role(
    department_name,
    role_name,
    role_config,
    staffing_rules
):
    overrides = staffing_rules.get("minimum_count_by_role", {})
    department_overrides = overrides.get(department_name, {})

    if role_name in department_overrides:
        return max(0, int(department_overrides[role_name]))

    if "minimum_count" in role_config:
        return max(0, int(role_config["minimum_count"]))

    if role_config.get("leidinggevend", False):
        return max(
            0,
            int(staffing_rules.get("minimum_count_for_manager_role", 1))
        )

    return 0


def _minimum_counts(structure, total_employees, staffing_rules):
    minimums = {}

    for department_name, roles in structure.items():
        manager_roles = []
        non_manager_ratio = 0.0

        for role_name, role_config in roles.items():
            minimums[(department_name, role_name)] = minimum_count_for_role(
                department_name,
                role_name,
                role_config,
                staffing_rules
            )
            if role_config.get("leidinggevend", False):
                manager_roles.append((role_name, role_config))
            else:
                non_manager_ratio += role_config.get("fte_ratio", 0)

        max_team_size = int(staffing_rules.get("max_team_size", 0))
        if not manager_roles or max_team_size <= 0:
            continue

        required_team_managers = math.ceil(
            total_employees * non_manager_ratio / max_team_size
        )
        if required_team_managers <= 0:
            continue

        # The lowest management role is the natural team-lead layer. Salary
        # bands provide a stable ordering without hard-coding role names.
        team_role_name, _ = min(
            manager_roles,
            key=lambda item: item[1].get("salaris_max", float("inf"))
        )
        minimums[(department_name, team_role_name)] = max(
            minimums[(department_name, team_role_name)],
            required_team_managers
        )

    return minimums
