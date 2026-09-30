"""AR-14: a leaver's open absence episodes end on the departure date."""
import random

import pandas as pd
import pytest

from src.infrastructure.departure_records import close_open_absence
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_contracts import ContractLifecycleSimulator
from src.tests.test_simulation_contracts import (
    DEPARTURE_REASON_MAP,
    EVENT_TYPE_MAP,
    ForcedChoice,
    _base_state,
    _config as _contract_config,
)

D = pd.Timestamp
DEPARTURE = D("2024-01-10")  # a Wednesday


def _episode(key, employee, start, end, hours_per_day=8.0, sickness=True, type_key=1):
    workdays = len(pd.bdate_range(start, end))
    hours = workdays * hours_per_day
    return {
        "Absence_Key": key, "Employee_Key": employee, "AbsenceType_Key": type_key,
        "Startdatum": D(start), "Einddatum": D(end),
        "Duur_dagen": (D(end) - D(start)).days + 1,
        "Afwezigheid_Werkdagen": workdays, "Afwezigheid_Uren": hours,
        "Verzuim_Werkdagen": workdays if sickness else 0,
        "Verzuim_Uren": hours if sickness else 0.0,
    }


def _state(*episodes):
    return {"fact_absence": pd.DataFrame(list(episodes))}


def test_an_open_episode_is_cut_on_the_departure_date_and_recomputed():
    state = _state(_episode(1, 1, "2024-01-01", "2024-03-31", hours_per_day=6.4))

    changed = close_open_absence(state, 1, DEPARTURE)

    row = state["fact_absence"].iloc[0]
    assert changed == 1
    assert row["Einddatum"] == DEPARTURE
    assert row["Duur_dagen"] == 10                      # inclusive: 1 to 10 January
    assert row["Afwezigheid_Werkdagen"] == 8            # weekdays 1-5 and 8-10 January
    assert row["Afwezigheid_Uren"] == pytest.approx(8 * 6.4)
    assert row["Verzuim_Werkdagen"] == 8
    assert row["Verzuim_Uren"] == pytest.approx(8 * 6.4)


def test_leave_episodes_keep_zero_verzuim_after_the_cut():
    state = _state(_episode(1, 1, "2024-01-01", "2024-02-29", sickness=False))

    close_open_absence(state, 1, DEPARTURE)

    row = state["fact_absence"].iloc[0]
    assert row["Afwezigheid_Werkdagen"] == 8
    assert row["Verzuim_Werkdagen"] == 0 and row["Verzuim_Uren"] == 0.0


def test_episodes_that_ended_before_departure_or_belong_to_others_are_untouched():
    ended = _episode(1, 1, "2023-12-01", "2023-12-15")
    on_departure_day = _episode(2, 1, "2024-01-08", "2024-01-10")
    other_employee = _episode(3, 2, "2024-01-01", "2024-03-31")
    state = _state(ended, on_departure_day, other_employee)
    before = state["fact_absence"].copy()

    changed = close_open_absence(state, 1, DEPARTURE)

    assert changed == 0
    pd.testing.assert_frame_equal(state["fact_absence"], before)


def test_a_missing_or_empty_absence_table_is_fine():
    assert close_open_absence({}, 1, DEPARTURE) == 0
    assert close_open_absence({"fact_absence": pd.DataFrame()}, 1, DEPARTURE) == 0


def test_a_lost_time_bedrijfsongeval_is_cut_like_any_other_episode():
    state = _state(_episode(1, 1, "2024-01-08", "2024-01-19", type_key=11))

    close_open_absence(state, 1, DEPARTURE)

    assert state["fact_absence"].iloc[0]["Einddatum"] == DEPARTURE
    assert state["fact_absence"].iloc[0]["Afwezigheid_Werkdagen"] == 3


def test_attrition_cuts_an_open_long_term_sickness_episode():
    config = _contract_config(
        attrition={"Productie": 500.0},  # weekly probability far above 1: always leaves
        retirement={"minimum_age": 50, "forced_retirement_age": 67, "age_bands": []},
        dim_departure_reason={"vrijwillig": ["Eigen initiatief"], "werkgever": ["Ontslag"]},
    )
    state = _base_state(
        contract_einddatum=None, contract_ronde=None, contracttype="Vast",
        hire_date=D("2015-03-01"), row_startdatum=D("2023-06-01"),
    )
    state["dim_employee"]["Geboortedatum"] = D("1985-01-01")
    state["fact_absence"] = pd.DataFrame([
        _episode(1, 1, "2024-01-02", "2024-06-30"),
        _episode(2, 1, "2023-11-01", "2023-11-20"),
    ])
    simulator = AttritionSimulator(
        config, None, random.Random(1), EVENT_TYPE_MAP,
        {"Eigen initiatief": 1, "Ontslag": 2, **DEPARTURE_REASON_MAP},
    )

    state = simulator.run(state, DEPARTURE)

    open_one, ended = state["fact_absence"].sort_values("Absence_Key").iloc
    assert not state["dim_employee"].iloc[0]["In_Dienst"]
    assert open_one["Einddatum"] == DEPARTURE
    assert open_one["Afwezigheid_Werkdagen"] == 7        # 2-5 and 8-10 January
    assert ended["Einddatum"] == D("2023-11-20")


def test_a_contract_non_renewal_cuts_an_open_episode():
    state = _base_state(contract_einddatum=D("2024-01-10"), contract_ronde=1)
    state["fact_absence"] = pd.DataFrame([_episode(1, 1, "2024-01-03", "2024-04-30")])
    simulator = ContractLifecycleSimulator(
        _contract_config(), schema=None, rng=ForcedChoice("depart"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, DEPARTURE)

    episode = state["fact_absence"].iloc[0]
    assert episode["Einddatum"] == DEPARTURE
    assert episode["Duur_dagen"] == 8
    assert episode["Afwezigheid_Werkdagen"] == 6
    assert episode["Verzuim_Uren"] == pytest.approx(6 * 8.0)


def test_a_contract_renewal_leaves_open_absence_alone():
    state = _base_state(contract_einddatum=D("2024-01-10"), contract_ronde=1)
    state["fact_absence"] = pd.DataFrame([_episode(1, 1, "2024-01-03", "2024-04-30")])
    simulator = ContractLifecycleSimulator(
        _contract_config(), schema=None, rng=ForcedChoice("renew"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, DEPARTURE)

    assert state["fact_absence"].iloc[0]["Einddatum"] == D("2024-04-30")
