import math
from typing import Optional


def allocate_headcount(
    structure: dict,
    total_employees: int,
    staffing_rules: Optional[dict] = None,
    workforce_planning: Optional[dict] = None,
):
    """Allocate a total headcount over roles using largest remainders.

    Management roles need a minimum presence even when their fte ratio rounds
    down to zero.  The minimum is applied before the remaining employees are
    distributed by the configured workforce mix.
    """
    staffing_rules = staffing_rules or {}
    workforce_planning = workforce_planning or {}
    active_structure = _active_structure_for_initial_population(
        structure, total_employees, workforce_planning
    )
    minimum_counts = _minimum_counts(
        active_structure,
        total_employees,
        staffing_rules,
        workforce_planning,
    )

    role_allocations = []

    for afdeling, functies in active_structure.items():
        for functie, details in functies.items():

            target_ratio = role_target_ratio(
                active_structure,
                afdeling,
                functie,
                workforce_planning,
            )
            exact = total_employees * target_ratio
            floor_count = int(exact)
            remainder = exact - floor_count
            minimum_count = minimum_counts[(afdeling, functie)]
            capacity = role_capacity(details)
            count = max(floor_count, minimum_count)
            if capacity is not None:
                count = min(count, capacity)

            role_allocations.append({
                "Department_Name": afdeling,
                "Role_Name": functie,
                "count": count,
                "remainder": remainder,
                "_capacity": capacity,
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
            total_employees * _role_ratio(active_structure, item, workforce_planning)
            - item["count"],
            item["remainder"]
        ),
        reverse=True
    )

    i = 0
    while remaining > 0:
        allocation = role_allocations[i]
        capacity = allocation["_capacity"]
        if capacity is None or allocation["count"] < capacity:
            allocation["count"] += 1
            remaining -= 1
        i = (i + 1) % len(role_allocations)

    for allocation in role_allocations:
        del allocation["_capacity"]

    return role_allocations


def _role_ratio(structure, allocation, workforce_planning=None):
    return role_target_ratio(
        structure,
        allocation["Department_Name"],
        allocation["Role_Name"],
        workforce_planning,
    )


def role_target_ratio(structure, department_name, role_name, workforce_planning=None):
    """Return a role's normalized workforce target within active roles.

    Department targets are deliberately separated from role weights.  This
    means an inactive specialist role does not consume start-population
    capacity, while active roles keep their intended relative mix.
    """
    workforce_planning = workforce_planning or {}
    department_weights = workforce_planning.get("department_target_weights", {})
    if not department_weights:
        # Keep the historic allocation contract for callers without a
        # workforce plan: fte_ratio is an absolute share, not a normalized
        # role weight.
        has_target_weights = any(
            "target_weight" in role_config
            for roles in structure.values() for role_config in roles.values()
        )
        if not has_target_weights:
            return _configured_role_weight(structure[department_name][role_name])
        total_weight = sum(_configured_role_weight(role_config) for roles in structure.values() for role_config in roles.values())
        return _configured_role_weight(structure[department_name][role_name]) / total_weight

    raw_weights = []

    for department, roles in structure.items():
        department_weight = float(department_weights.get(department, 1.0))
        role_weight_total = sum(
            _configured_role_weight(role_config)
            for role_config in roles.values()
        )
        if role_weight_total <= 0:
            continue
        for role_config in roles.values():
            raw_weights.append(
                department_weight
                * _configured_role_weight(role_config)
                / role_weight_total
            )

    role_weight_total = sum(raw_weights)
    if role_weight_total <= 0:
        return 0.0

    roles = structure[department_name]
    department_weight = float(department_weights.get(department_name, 1.0))
    within_department_total = sum(
        _configured_role_weight(role_config)
        for role_config in roles.values()
    )
    if within_department_total <= 0:
        return 0.0
    return (
        department_weight
        * _configured_role_weight(roles[role_name])
        / within_department_total
        / role_weight_total
    )


def role_is_active(role_config, company_headcount, department_headcount=0):
    """Whether a role may receive vacancies at the given headcount.

    ``active_from_headcount`` gates a role on a headcount rather than a
    calendar date, so it scales with how the simulation actually grows
    instead of unlocking a fixed set of roles on one shared date regardless
    of company size. ``active_from_scope`` selects which headcount the
    threshold applies to: "company" (the default) reflects roles that become
    relevant once the company overall reaches a certain complexity/size;
    "department" and "department_group" reflect roles - typically team
    leads and managers - whose need depends on one or several departments'
    own size, not the company's. For either of those, the caller resolves
    the right number via `scope_headcount` and passes it as
    `department_headcount` - this function itself just compares whichever
    number is relevant to the threshold.
    """
    threshold = role_config.get("active_from_headcount")
    if threshold is None:
        return True
    scope = role_config.get("active_from_scope", "company")
    headcount = company_headcount if scope == "company" else department_headcount
    return headcount >= int(threshold)


def scope_headcount(role_config, department_name, department_headcounts):
    """Resolve the headcount `role_is_active` should compare against.

    `department_headcounts` is keyed by department name. "department" uses
    the role's own department; "department_group" sums the departments
    listed in `active_from_departments` (e.g. a Commercial Director role
    gated on Sales + Marketing combined, not on either alone).
    """
    scope = role_config.get("active_from_scope", "company")
    if scope == "department_group":
        return sum(
            department_headcounts.get(department, 0)
            for department in role_config.get("active_from_departments", [])
        )
    return department_headcounts.get(department_name, 0)


def role_capacity(role_config):
    """Return a role's hard headcount ceiling, or None if it scales freely.

    A handful of roles are a single seat (or another small fixed number)
    regardless of company size - e.g. exactly one Managing Director. The
    proportional target-share model used elsewhere in this module is only
    correct for roles that should genuinely scale with headcount; without
    an explicit ceiling, a single-seat role's "fair share" keeps growing
    right along with the company and is never capped.
    """
    max_count = role_config.get("max_count")
    return int(max_count) if max_count is not None else None


def _configured_role_weight(role_config):
    return float(role_config.get("target_weight", role_config.get("fte_ratio", 0)))


def _active_structure_for_initial_population(
    structure, total_employees, workforce_planning=None
):
    """Which roles exist when the initial population is built at this size.

    This must use the same `active_from_headcount`/`active_from_scope` rule
    that growth uses, or a large `initial_population.headcount` produces a
    company with the small-headcount role mix stretched thin over more
    people, instead of the richer structure that headcount would actually
    have grown into. A department's own headcount does not exist yet before
    the initial population is allocated, so department-scoped roles are
    checked against an estimate derived from `department_target_weights`
    instead - the same weights growth itself converges toward.
    """
    department_headcounts = _estimated_department_headcounts(
        structure, total_employees, workforce_planning
    )
    return {
        department: {
            role_name: role_config
            for role_name, role_config in roles.items()
            if role_is_active(
                role_config,
                total_employees,
                scope_headcount(role_config, department, department_headcounts),
            )
        }
        for department, roles in structure.items()
        if any(
            role_is_active(
                role_config,
                total_employees,
                scope_headcount(role_config, department, department_headcounts),
            )
            for role_config in roles.values()
        )
    }


def _estimated_department_headcounts(structure, total_employees, workforce_planning):
    """Estimate each department's headcount from its configured target share.

    Used only to evaluate department-scoped activation before the initial
    population exists. It intentionally reuses `department_target_weights`
    rather than inventing a separate estimate, since that is the same
    long-term mix growth itself targets.
    """
    workforce_planning = workforce_planning or {}
    department_weights = workforce_planning.get("department_target_weights", {})
    total_weight = sum(float(weight) for weight in department_weights.values())
    if not department_weights or total_weight <= 0:
        return {department: total_employees for department in structure}
    return {
        department: total_employees * float(weight) / total_weight
        for department, weight in department_weights.items()
    }


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


def team_lead_role_name(manager_roles):
    """Pick a department's team-lead role: its lowest-salaried leidinggevend
    role, using each role's own configured salary range.

    The sector config stores a role's pay range as `salaris_range`, not
    `salaris_max` - a lookup keyed on `salaris_max` always misses and silently
    falls back to whatever's first in the department's dict, rather than
    genuinely ordering by salary.
    """
    if not manager_roles:
        return None
    return min(
        manager_roles,
        key=lambda item: item[1].get("salaris_range", [None, float("inf")])[-1]
    )[0]


def team_lead_requirement(non_manager_headcount, max_team_size):
    """How many team leads a department's span of control calls for, given
    its current (or estimated) non-manager headcount.

    Returns ``None`` when no ``max_team_size`` is configured, meaning the
    concept doesn't apply rather than that zero leads are required.
    """
    if not max_team_size or max_team_size <= 0:
        return None
    return math.ceil(max(0, non_manager_headcount) / max_team_size)


def _minimum_counts(
    structure,
    total_employees,
    staffing_rules,
    workforce_planning=None,
):
    minimums = {}
    max_team_size = int(staffing_rules.get("max_team_size", 0))

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
                non_manager_ratio += role_target_ratio(
                    structure,
                    department_name,
                    role_name,
                    workforce_planning,
                )

        team_role_name = team_lead_role_name(manager_roles)
        if team_role_name is None:
            continue

        required_team_managers = team_lead_requirement(
            total_employees * non_manager_ratio, max_team_size
        )
        if not required_team_managers:
            continue

        minimums[(department_name, team_role_name)] = max(
            minimums[(department_name, team_role_name)],
            required_team_managers
        )

    return minimums
