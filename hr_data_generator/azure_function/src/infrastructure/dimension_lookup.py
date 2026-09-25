"""Cached lookups against small, run-static dimensions.

`dim_role`, `dim_department`, `dim_shift` and `dim_event_type` are all
config-owned (or config-derived) dimensions assigned to `state` exactly once,
during initial population generation (see `application/population.py`), and
never reassigned during the weekly simulation loop afterwards. Despite that,
several call sites (satisfaction/engagement scoring, absence risk, safety
risk, career-momentum scoring) each independently re-derived "this role's
department name" or "this shift's display name" with a fresh pair of
boolean-mask `.loc[]` filters on every call - once per active employee, every
simulated week - and the career-momentum functions rebuilt the whole
EventType_Key -> Gebeurtenis dict from scratch on every call too, even though
`dim_event_type` never changes within a run.

Building each of these once and reusing the result turns a per-employee,
per-week join into a single dict lookup. The cache is invalidated by the
source DataFrame(s)' object identity, the same pattern already used by
`employment_history.employment_history_for` - since these dimensions are
never reassigned mid-run, the cache is in practice built once per run and
never rebuilt, and correctness does not depend on that: a genuine replacement
of the source DataFrame (a new object) still busts the cache.
"""
import pandas as pd


def department_name_for_role(state, role_key):
    """Return the department name for a role, or None if it cannot be resolved."""
    if pd.isna(role_key):
        return None
    return _role_department_name_lookup(state).get(role_key)


def shift_name_for_key(state, shift_key):
    """Return the display name for a shift, or None if it cannot be resolved."""
    if pd.isna(shift_key):
        return None
    return _shift_name_lookup(state).get(shift_key)


def event_gebeurtenis_lookup(state):
    """Return the cached EventType_Key -> Gebeurtenis dict, for use with `.map()`."""
    return _event_gebeurtenis_lookup(state)


def _cache_for(state):
    return state.setdefault("_dimension_lookup_cache", {})


def _role_department_name_lookup(state):
    roles = state.get("dim_role", pd.DataFrame())
    departments = state.get("dim_department", pd.DataFrame())
    cache = _cache_for(state)
    cache_key = ("role_department_name", id(roles), id(departments))
    if cache_key in cache:
        return cache[cache_key]

    result = {}
    if (
        not roles.empty
        and not departments.empty
        and "Department_Key" in roles.columns
        and "Afdeling_Naam" in departments.columns
    ):
        department_names = dict(
            zip(departments["Department_Key"], departments["Afdeling_Naam"])
        )
        for role_key, department_key in zip(
            roles["Role_Key"], roles["Department_Key"]
        ):
            result[role_key] = department_names.get(department_key)

    cache[cache_key] = result
    return result


def _shift_name_lookup(state):
    shifts = state.get("dim_shift", pd.DataFrame())
    cache = _cache_for(state)
    cache_key = ("shift_name", id(shifts))
    if cache_key in cache:
        return cache[cache_key]

    result = {}
    if (
        not shifts.empty
        and "Shift_Key" in shifts.columns
        and "Ploegendienst_Naam" in shifts.columns
    ):
        result = dict(zip(shifts["Shift_Key"], shifts["Ploegendienst_Naam"]))

    cache[cache_key] = result
    return result


def _event_gebeurtenis_lookup(state):
    event_types = state.get("dim_event_type", pd.DataFrame())
    cache = _cache_for(state)
    cache_key = ("event_gebeurtenis", id(event_types))
    if cache_key in cache:
        return cache[cache_key]

    result = {}
    if (
        not event_types.empty
        and "EventType_Key" in event_types.columns
        and "Gebeurtenis" in event_types.columns
    ):
        result = dict(zip(event_types["EventType_Key"], event_types["Gebeurtenis"]))

    cache[cache_key] = result
    return result
