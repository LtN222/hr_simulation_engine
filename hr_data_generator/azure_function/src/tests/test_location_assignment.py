import random

import pandas as pd

from src.infrastructure.location_assignment import (
    effective_role_capacity,
    open_locations,
    relocate_department_group,
    resolve_location,
)
from src.simulation.simulation_location_transfer import simulate_location_transfers


def _config(**overrides):
    base = {
        "dim_location": {
            "Fabriek Noord": {
                "weight": 1.0,
                "is_initial": True,
                "is_production_site": True,
                "capacity": 10,
                "capacity_streak_weeks": 3,
            },
            "Fabriek Zuid": {
                "weight": 1.0,
                "is_production_site": True,
                "opens_after_location_at_capacity": "Fabriek Noord",
            },
            "DC": {
                "weight": 0.3,
                "active_from_scope": "department",
                "active_from_department": "Logistiek",
                "active_from_headcount": 4,
                "capacity_bonus_amount": 5,
            },
            "Hoofdkantoor": {
                "weight": 0.3,
                "active_from_scope": "department_group",
                "active_from_departments": ["Finance", "HR"],
                "active_from_headcount": 4,
            },
        },
        "structure": {
            "Productie": {
                "Operator": {"multi_site": True},
                "Plant Manager": {"centralized": True},
            },
            "Logistiek": {"Magazijnmedewerker": {}},
            "Finance": {"Financieel Medewerker": {}},
            "HR": {"HR Medewerker": {}},
        },
        "department_relocation": {"Logistiek": "DC"},
        "career_events": {
            # location_transfer_rate is an annual rate (divided by 52 like
            # promotion/transfer rates elsewhere); 52 here means "guaranteed
            # every week", used to make the transfer test deterministic.
            "location_transfer_rate": 52.0,
            "new_site_pull_rate": 0.0,
            "new_site_pull_weeks": 12,
        },
    }
    base.update(overrides)
    return type("Config", (), base)()


def _dim_role():
    return pd.DataFrame({
        "Role_Key": [1, 2, 3, 4, 5],
        "Functie_Naam": [
            "Operator", "Plant Manager", "Magazijnmedewerker",
            "Financieel Medewerker", "HR Medewerker",
        ],
        "Afdeling_Naam": [
            "Productie", "Productie", "Logistiek", "Finance", "HR",
        ],
        "Department_Key": [1, 1, 2, 3, 4],
    })


def _dim_location():
    return pd.DataFrame({
        "Location_Key": [1, 2, 3, 4],
        "Vestiging_Naam": ["Fabriek Noord", "Fabriek Zuid", "DC", "Hoofdkantoor"],
    })


def _active_row(employee_key, role_key, location_key):
    return {
        "Employment_Key": employee_key,
        "Employee_Key": employee_key,
        "Role_Key": role_key,
        "Location_Key": location_key,
        "Dienstverband_status": "Actief",
        "Startdatum": pd.Timestamp("2020-01-01"),
        "Einddatum": None,
    }


def test_resolve_location_without_dim_location_preserves_prior_behaviour():
    config = _config()
    state = {"fact_employment": pd.DataFrame()}

    result = resolve_location(
        state, config, random.Random(1), "Productie", "Operator",
        preferred_location_key=7,
    )

    assert result == 7


def test_resolve_location_multi_site_keeps_current_open_site():
    config = _config()
    state = {
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame([_active_row(1, 1, 2)]),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": True},
    }

    result = resolve_location(
        state, config, random.Random(1), "Productie", "Operator",
        preferred_location_key=2,
    )

    assert result == 2  # stayed at Fabriek Zuid


def test_resolve_location_multi_site_falls_back_when_current_site_not_open():
    config = _config()
    state = {
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": False},
    }

    result = resolve_location(
        state, config, random.Random(1), "Productie", "Operator",
        preferred_location_key=2,
    )

    assert result == 1  # only Fabriek Noord is open


def test_resolve_location_centralized_role_gets_one_fixed_home():
    config = _config()
    state = {"dim_location": _dim_location(), "fact_employment": pd.DataFrame()}

    first = resolve_location(state, config, random.Random(1), "Productie", "Plant Manager")
    second = resolve_location(state, config, random.Random(2), "Productie", "Plant Manager")

    assert first == second == 1  # pinned to the initial site, both times


def test_open_locations_opens_fabriek_zuid_only_after_sustained_capacity():
    config = _config()
    state = {
        "dim_role": _dim_role(),
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(
            [_active_row(i, 1, 1) for i in range(10)]  # exactly at capacity (10)
        ),
    }
    event_type_map = {"Locatietransfer": 99}

    for week in range(2):
        state = open_locations(state, config, None, pd.Timestamp("2024-01-01"), event_type_map)
        assert state["_location_open"]["Fabriek Zuid"] is False

    state = open_locations(state, config, None, pd.Timestamp("2024-01-01"), event_type_map)
    assert state["_location_open"]["Fabriek Zuid"] is True


def test_open_locations_opens_dc_once_logistiek_headcount_is_reached_and_relocates_it():
    config = _config()
    state = {
        "dim_role": _dim_role(),
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(
            [_active_row(i, 3, 1) for i in range(4)]  # 4 Logistiek staff at Fabriek Noord
        ),
    }
    event_type_map = {"Locatietransfer": 99}

    state = open_locations(state, config, None, pd.Timestamp("2024-01-01"), event_type_map)

    assert state["_location_open"]["DC"] is True
    assert state["_home_location"]["Logistiek"] == "DC"
    assert state["_location_capacity_bonus"]["Fabriek Noord"] == 5

    active = state["fact_employment"]
    active = active[active["Dienstverband_status"] == "Actief"]
    logistiek_locations = active.loc[active["Role_Key"] == 3, "Location_Key"].unique()
    assert list(logistiek_locations) == [3]  # everyone moved to DC (key 3)


def test_open_locations_opens_hoofdkantoor_from_combined_department_group():
    config = _config()
    state = {
        "dim_role": _dim_role(),
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(
            [_active_row(1, 4, 1), _active_row(2, 5, 1), _active_row(3, 5, 1)]
        ),
    }
    event_type_map = {"Locatietransfer": 99}

    # 3 combined Finance+HR staff: below the threshold of 4.
    state = open_locations(state, config, None, pd.Timestamp("2024-01-01"), event_type_map)
    assert state["_location_open"]["Hoofdkantoor"] is False

    state["fact_employment"] = pd.concat(
        [state["fact_employment"], pd.DataFrame([_active_row(4, 4, 1)])],
        ignore_index=True,
    )
    state = open_locations(state, config, None, pd.Timestamp("2024-01-08"), event_type_map)
    assert state["_location_open"]["Hoofdkantoor"] is True


def test_effective_role_capacity_returns_the_flat_max_count():
    config = _config(structure={"Productie": {"Plant Manager": {"max_count": 1}}})

    assert effective_role_capacity({}, config, "Productie", "Plant Manager") == 1


def test_effective_role_capacity_is_none_for_an_uncapped_role():
    config = _config()

    assert effective_role_capacity({}, config, "Productie", "Operator") is None


def test_effective_role_capacity_stays_at_one_before_the_second_site_reaches_threshold():
    """The multi_site flag on Productiemanager means one person can cover
    several open sites, not that each site automatically gets its own - so a
    second seat must stay closed until the newly opened site's own headcount
    actually needs it."""
    config = _config(structure={
        "Productie": {
            "Productiemanager": {
                "multi_site": True,
                "secondary_site_manager_threshold": 3,
            },
        },
    })
    state = {
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(
            [_active_row(1, 1, 2)]  # only 1 person at Fabriek Zuid (key 2)
        ),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": True},
    }

    assert effective_role_capacity(state, config, "Productie", "Productiemanager") == 1


def test_effective_role_capacity_grants_a_second_productiemanager_once_the_new_site_grows_large():
    config = _config(structure={
        "Productie": {
            "Productiemanager": {
                "multi_site": True,
                "secondary_site_manager_threshold": 3,
            },
        },
    })
    state = {
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame(
            [_active_row(i, 1, 2) for i in range(3)]  # 3 people at Fabriek Zuid
        ),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": True},
    }

    assert effective_role_capacity(state, config, "Productie", "Productiemanager") == 2


def test_effective_role_capacity_scales_the_team_lead_role_with_non_manager_headcount():
    """The department's lowest-salaried leidinggevend role is its team-lead
    layer - its ceiling should track actual non-manager headcount via
    `max_team_size`, not stay flat regardless of department size."""
    config = _config(
        structure={
            "Productie": {
                "Operator": {"leidinggevend": False},
                "Teamleider": {"leidinggevend": True, "salaris_range": [45000, 60000]},
                "Plant Manager": {"leidinggevend": True, "salaris_range": [90000, 120000]},
            },
        },
        staffing={"max_team_size": 10},
    )
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2, 3],
            "Functie_Naam": ["Operator", "Teamleider", "Plant Manager"],
            "Afdeling_Naam": ["Productie", "Productie", "Productie"],
            "Department_Key": [1, 1, 1],
        }),
        "fact_employment": pd.DataFrame(
            [_active_row(i, 1, 1) for i in range(24)]  # 24 active Operators
        ),
    }

    assert effective_role_capacity(state, config, "Productie", "Teamleider") == 3  # ceil(24/10)
    # Plant Manager is a leidinggevend role but not the team-lead layer -
    # it keeps scaling freely (or via its own max_count/threshold, if any).
    assert effective_role_capacity(state, config, "Productie", "Plant Manager") is None


def test_effective_role_capacity_caps_the_team_lead_role_at_zero_with_no_staff_yet():
    config = _config(
        structure={
            "Productie": {
                "Operator": {"leidinggevend": False},
                "Teamleider": {"leidinggevend": True, "salaris_range": [45000, 60000]},
            },
        },
        staffing={"max_team_size": 10},
    )
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Functie_Naam": ["Operator", "Teamleider"],
            "Afdeling_Naam": ["Productie", "Productie"],
            "Department_Key": [1, 1],
        }),
        "fact_employment": pd.DataFrame(),
    }

    assert effective_role_capacity(state, config, "Productie", "Teamleider") == 0


def test_location_transfers_only_happen_once_a_second_site_is_open():
    config = _config()
    dim_role = _dim_role()
    dim_location = _dim_location()
    event_type_map = {"Locatietransfer": 99}

    single_site_state = {
        "dim_role": dim_role,
        "dim_location": dim_location,
        "fact_employment": pd.DataFrame([_active_row(1, 1, 1)]),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": False},
    }
    result = simulate_location_transfers(
        single_site_state, config, None, pd.Timestamp("2024-01-01"),
        random.Random(1), event_type_map,
    )
    assert len(result["fact_employment"]) == 1  # no transfer possible yet

    two_site_state = {
        "dim_role": dim_role,
        "dim_location": dim_location,
        "fact_employment": pd.DataFrame([_active_row(1, 1, 1)]),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": True},
    }
    result = simulate_location_transfers(
        two_site_state, config, None, pd.Timestamp("2024-01-01"),
        random.Random(1), event_type_map,
    )
    assert len(result["fact_employment"]) == 2  # transfer_rate=1.0 guarantees one
    moved = result["fact_employment"].iloc[-1]
    assert moved["Location_Key"] == 2
    assert moved["EventType_Key"] == 99
