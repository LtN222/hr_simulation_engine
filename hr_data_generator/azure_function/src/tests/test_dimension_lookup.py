import pandas as pd

from src.infrastructure.dimension_lookup import (
    department_name_for_role,
    event_gebeurtenis_lookup,
    shift_name_for_key,
)


def _state():
    return {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2, 3],
            "Department_Key": [10, 20, 99],  # 99 has no matching department
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [10, 20],
            "Afdeling_Naam": ["Productie", "Logistiek"],
        }),
        "dim_shift": pd.DataFrame({
            "Shift_Key": [1, 2],
            "Ploegendienst_Naam": ["Dagdienst", "Nachtdienst"],
        }),
        "dim_event_type": pd.DataFrame({
            "EventType_Key": [1, 2],
            "Gebeurtenis": ["Indiensttreding", "Promotie"],
        }),
    }


def test_department_name_for_role_matches_role_to_department():
    state = _state()
    assert department_name_for_role(state, 1) == "Productie"
    assert department_name_for_role(state, 2) == "Logistiek"


def test_department_name_for_role_returns_none_for_unknown_or_missing_role():
    state = _state()
    assert department_name_for_role(state, 999) is None
    assert department_name_for_role(state, None) is None
    assert department_name_for_role(state, float("nan")) is None


def test_department_name_for_role_returns_none_when_department_row_is_missing():
    """Role_Key 3 points at Department_Key 99, which has no dim_department
    row - must return None like the original two-step `.loc` filter did, not
    a pandas NaN (which would hash/format differently downstream, e.g. in the
    satisfaction model's stable-value string key)."""
    state = _state()
    assert department_name_for_role(state, 3) is None


def test_shift_name_for_key_matches_and_falls_back_to_none():
    state = _state()
    assert shift_name_for_key(state, 1) == "Dagdienst"
    assert shift_name_for_key(state, 2) == "Nachtdienst"
    assert shift_name_for_key(state, 999) is None
    assert shift_name_for_key(state, None) is None


def test_event_gebeurtenis_lookup_returns_a_full_dict_for_map():
    state = _state()
    lookup = event_gebeurtenis_lookup(state)
    assert lookup == {1: "Indiensttreding", 2: "Promotie"}


def test_lookups_are_cached_per_state_and_rebuilt_when_the_source_dataframe_changes():
    state = _state()
    first = department_name_for_role(state, 1)
    assert first == "Productie"

    # Mutating dim_role's *values* in place, without replacing the object,
    # must not be picked up - the cache is only invalidated by a new object
    # (the actual invalidation trigger every simulator already uses when it
    # replaces a table via pd.concat/reassignment).
    state["dim_role"].loc[state["dim_role"]["Role_Key"] == 1, "Department_Key"] = 20
    assert department_name_for_role(state, 1) == "Productie"

    # Replacing the DataFrame object itself busts the cache.
    state["dim_role"] = state["dim_role"].copy()
    assert department_name_for_role(state, 1) == "Logistiek"


def test_empty_or_missing_dimensions_return_none_without_raising():
    state = {"dim_role": pd.DataFrame(), "dim_department": pd.DataFrame()}
    assert department_name_for_role(state, 1) is None
    assert shift_name_for_key({}, 1) is None
    assert event_gebeurtenis_lookup({}) == {}
