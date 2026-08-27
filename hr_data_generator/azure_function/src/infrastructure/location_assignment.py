"""Location lifecycle: which sites exist yet, and where roles/departments sit.

A location can open in one of three ways, all driven by `config.dim_location`:
- `is_initial`: open from the very start (the single starting site).
- `opens_after_location_at_capacity`: a second production site that opens
  once a named location has been at/above its configured capacity for
  `capacity_streak_weeks` consecutive weeks - the literal "new factory
  opens" moment, not a fixed headcount.
- `active_from_headcount` (+ `active_from_scope`): a support location (a
  distribution centre, a head office) that opens once a department's, or a
  named group of departments', combined headcount crosses a threshold - the
  same shape as role activation, just scoped to one or several departments
  instead of one role.

A `multi_site` role (see `structure.<dept>.<role>.multi_site` in the sector
config) can be filled at any currently open production site. Every other
role belongs to a single fixed "home" location: a `centralized` role within
an otherwise multi-site department gets its own home (decided the first
time it's filled), and every role in an ordinary single-site department
shares that department's home. A home location only ever changes through an
explicit, one-time relocation when `department_relocation` moves that whole
department to a newly opened location (e.g. Logistiek -> DC).
"""
import pandas as pd

from src.application.allocation import (
    role_capacity,
    team_lead_requirement,
    team_lead_role_name,
)
from src.infrastructure.record_builder import build_record


def open_locations(state, config, schema, today, event_type_map):
    """Advance location activation/relocation for this week.

    Must run before vacancy/hiring selection so growth uses this week's
    up-to-date set of open locations, not last week's.
    """
    dim_location = config.dim_location
    open_flags = state.setdefault("_location_open", {})
    streaks = state.setdefault("_location_capacity_streak", {})
    opened_on = state.setdefault("_location_opened_on", {})
    capacity_bonus = state.setdefault("_location_capacity_bonus", {})

    for name, cfg in dim_location.items():
        if name not in open_flags:
            open_flags[name] = bool(cfg.get("is_initial", False))
            if open_flags[name]:
                opened_on[name] = today

    for name, cfg in dim_location.items():
        base_name = cfg.get("opens_after_location_at_capacity")
        if base_name is None or open_flags.get(name):
            continue
        base_cfg = dim_location[base_name]
        headcount = _location_headcount(state, base_name)
        capacity = float(base_cfg.get("capacity", float("inf"))) + capacity_bonus.get(
            base_name, 0
        )
        if headcount >= capacity:
            streaks[base_name] = streaks.get(base_name, 0) + 1
        else:
            streaks[base_name] = 0
        if streaks[base_name] >= int(base_cfg.get("capacity_streak_weeks", 0)):
            open_flags[name] = True
            opened_on[name] = today

    for name, cfg in dim_location.items():
        if open_flags.get(name) or "active_from_headcount" not in cfg:
            continue
        scope = cfg.get("active_from_scope", "company")
        if scope == "department":
            headcount = _department_headcount(state, cfg["active_from_department"])
        elif scope == "department_group":
            headcount = sum(
                _department_headcount(state, department)
                for department in cfg["active_from_departments"]
            )
        else:
            headcount = _company_headcount(state)
        if headcount >= float(cfg["active_from_headcount"]):
            open_flags[name] = True
            opened_on[name] = today
            bonus = float(cfg.get("capacity_bonus_amount", 0) or 0)
            if bonus:
                relocated_department = _department_relocating_to(config, name)
                if relocated_department:
                    # The relocating department's home is usually already
                    # set by now (its first hire sets it), but fall back to
                    # the initial site rather than silently dropping the
                    # bonus if it somehow isn't.
                    host = (
                        _current_home(state, relocated_department)
                        or _initial_location_name(config)
                    )
                    capacity_bonus[host] = capacity_bonus.get(host, 0) + bonus
            state = relocate_department_group(
                state, config, schema, name, today, event_type_map
            )

    return state


def relocate_department_group(state, config, schema, location_name, today, event_type_map):
    """Move every existing employee of the relocating department(s) at once.

    A newly opened location only pulls in the department(s) configured in
    `department_relocation` to move there - most departments never relocate.
    This is a one-time bulk move on the location's opening week, not a
    gradual drift: simpler than staggering it, and good enough for a demo.
    """
    departments = [
        department
        for department, target in config.department_relocation.items()
        if target == location_name
    ]
    if not departments:
        return state

    dim_role = state["dim_role"]
    fact_employment = state["fact_employment"]
    home = state.setdefault("_home_location", {})
    location_key = _location_key(state, location_name)

    moving_roles = dim_role[dim_role["Afdeling_Naam"].isin(departments)]["Role_Key"]
    active = fact_employment[
        (fact_employment["Dienstverband_status"] == "Actief")
        & (fact_employment["Role_Key"].isin(moving_roles))
        & (fact_employment["Location_Key"] != location_key)
    ]

    if not active.empty:
        next_key = int(fact_employment["Employment_Key"].max()) + 1
        new_records = []
        for idx, row in active.iterrows():
            fact_employment.loc[idx, "Einddatum"] = today
            fact_employment.loc[idx, "Dienstverband_status"] = "Inactief"
            new_records.append(build_record(
                schema,
                "fact_employment",
                {
                    **row.to_dict(),
                    "Employment_Key": next_key,
                    "Previous_Employment_Key": row["Employment_Key"],
                    "Location_Key": location_key,
                    "Startdatum": today,
                    "Einddatum": None,
                    "Dienstverband_status": "Actief",
                    "EventType_Key": event_type_map.get("Locatietransfer"),
                    "DepartureReason_Key": None,
                    "Tevredenheid_Score_Bij_Uitdienst": None,
                    "SatisfactionBand_Key_Bij_Uitdienst": None,
                    "Betrokkenheid_Score_Bij_Uitdienst": None,
                    "EngagementBand_Key_Bij_Uitdienst": None,
                }
            ))
            next_key += 1
        state["fact_employment"] = pd.concat(
            [fact_employment, pd.DataFrame(new_records)], ignore_index=True
        )

    for department in departments:
        home[department] = location_name
    return state


def resolve_location(state, config, rng, department_name, role_name, preferred_location_key=None):
    """Return the Location_Key a person filling this role should have.

    `preferred_location_key` is the employee's current location for an
    internal move (promotion/transfer); omit it for a fresh external hire.
    A multi-site role keeps the employee's current site if it's still a
    valid, open production site; otherwise (including every fresh hire) a
    site is chosen weighted toward whichever open site has more headroom.
    """
    if state.get("dim_location") is None or state["dim_location"].empty:
        # No location dimension to resolve against (some tests, and any
        # fixture that doesn't model locations) - preserve prior behaviour
        # rather than guessing.
        return preferred_location_key

    role_config = config.structure.get(department_name, {}).get(role_name, {})
    open_flags = state.get("_location_open", {})

    if role_config.get("multi_site"):
        open_sites = [
            name
            for name, cfg in config.dim_location.items()
            if cfg.get("is_production_site") and open_flags.get(name)
        ]
        if not open_sites:
            open_sites = [_initial_location_name(config)]
        preferred_name = _location_name(state, preferred_location_key)
        if preferred_name in open_sites:
            return _location_key(state, preferred_name)
        weights = [_remaining_headroom(state, config, name) for name in open_sites]
        chosen = rng.choices(open_sites, weights=weights)[0]
        return _location_key(state, chosen)

    home_key = role_name if role_config.get("centralized") else department_name
    home = state.setdefault("_home_location", {})
    if home_key not in home:
        home[home_key] = _location_name(state, preferred_location_key) or _initial_location_name(config)
    return _location_key(state, home[home_key])


def effective_role_capacity(state, config, department_name, role_name):
    """Return this role's current hard headcount ceiling, or None if free.

    Delegates to the flat `max_count` ceiling for most capped roles.
    `Productiemanager` is a deliberate special case: its `multi_site` flag
    means one Productiemanager can be responsible for more than one open
    site, not that every open site automatically gets its own - a second
    Productiemanager only becomes warranted once a non-initial production
    site has grown large enough on its own (`secondary_site_manager_threshold`)
    that one person managing both is no longer realistic.

    A department's team-lead role (its lowest-salaried `leidinggevend` role)
    gets a dynamic ceiling instead: `staffing.max_team_size` applied to that
    department's actual current non-manager headcount. Without this, growth,
    promotions and transfers can keep adding team leads past what the
    department's real span of control calls for, with nothing to ever pull
    that back down once it drifts.
    """
    role_config = config.structure.get(department_name, {}).get(role_name, {})
    flat_cap = role_capacity(role_config)
    if flat_cap is not None:
        return flat_cap

    threshold = role_config.get("secondary_site_manager_threshold")
    if threshold is not None:
        open_flags = state.get("_location_open", {})
        secondary_sites_over_threshold = sum(
            1
            for name, cfg in getattr(config, "dim_location", {}).items()
            if cfg.get("is_production_site")
            and not cfg.get("is_initial")
            and open_flags.get(name)
            and _location_headcount(state, name) >= float(threshold)
        )
        return 1 + secondary_sites_over_threshold

    if role_config.get("leidinggevend", False):
        manager_roles = [
            (name, cfg)
            for name, cfg in config.structure.get(department_name, {}).items()
            if cfg.get("leidinggevend", False)
        ]
        if team_lead_role_name(manager_roles) == role_name:
            max_team_size = int(getattr(config, "staffing", {}).get("max_team_size", 0))
            non_manager_headcount = _non_manager_department_headcount(
                state, config, department_name
            )
            return team_lead_requirement(non_manager_headcount, max_team_size)

    return None


def _initial_location_name(config):
    for name, cfg in config.dim_location.items():
        if cfg.get("is_initial"):
            return name
    return next(iter(config.dim_location))


def _location_key(state, location_name):
    dim_location = state.get("dim_location")
    if dim_location is None or location_name is None:
        return None
    matches = dim_location.loc[dim_location["Vestiging_Naam"] == location_name, "Location_Key"]
    return matches.iloc[0] if not matches.empty else None


def _location_name(state, location_key):
    if location_key is None or pd.isna(location_key):
        return None
    dim_location = state.get("dim_location")
    if dim_location is None:
        return None
    matches = dim_location.loc[dim_location["Location_Key"] == location_key, "Vestiging_Naam"]
    return matches.iloc[0] if not matches.empty else None


def _active_employment(state):
    fact_employment = state.get("fact_employment")
    if fact_employment is None or "Dienstverband_status" not in fact_employment.columns:
        return pd.DataFrame()
    return fact_employment[fact_employment["Dienstverband_status"] == "Actief"]


def _location_headcount(state, location_name):
    active = _active_employment(state)
    if active.empty or "Location_Key" not in active.columns:
        return 0
    location_key = _location_key(state, location_name)
    return int((active["Location_Key"] == location_key).sum())


def _remaining_headroom(state, config, location_name):
    cfg = config.dim_location[location_name]
    capacity = float(cfg.get("capacity", float("inf")))
    bonus = state.get("_location_capacity_bonus", {}).get(location_name, 0)
    return max(1.0, capacity + bonus - _location_headcount(state, location_name))


def _department_headcount(state, department_name):
    active = _active_employment(state)
    dim_role = state.get("dim_role")
    if active.empty or dim_role is None or "Role_Key" not in active.columns:
        return 0
    department_roles = dim_role.loc[
        dim_role["Afdeling_Naam"] == department_name, "Role_Key"
    ]
    return int(active["Role_Key"].isin(department_roles).sum())


def _non_manager_department_headcount(state, config, department_name):
    active = _active_employment(state)
    dim_role = state.get("dim_role")
    if active.empty or dim_role is None or "Role_Key" not in active.columns:
        return 0
    department_roles = dim_role[dim_role["Afdeling_Naam"] == department_name]
    non_manager_role_keys = [
        role["Role_Key"]
        for _, role in department_roles.iterrows()
        if not config.structure.get(department_name, {})
        .get(role["Functie_Naam"], {})
        .get("leidinggevend", False)
    ]
    return int(active["Role_Key"].isin(non_manager_role_keys).sum())


def _company_headcount(state):
    return len(_active_employment(state))


def _department_relocating_to(config, location_name):
    for department, target in config.department_relocation.items():
        if target == location_name:
            return department
    return None


def _current_home(state, department_name):
    home = state.get("_home_location", {})
    return home.get(department_name)
