"""Tenure and relevant experience must follow continuous service, not the
current fact_employment row, which every salary review, renewal or move resets."""
import random

import pandas as pd
import pytest

from src.infrastructure.departure_records import build_departure_row
from src.infrastructure.location_assignment import relocate_department_group
from src.infrastructure.relevant_experience import experience_as_of
from src.infrastructure.tenure import service_days, service_start, service_years
from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_contracts import ContractLifecycleSimulator
from src.simulation.simulation_location_transfer import simulate_location_transfers
from src.simulation.simulation_performance import PerformanceSimulator
from src.simulation.simulation_safety import SafetyIncidentSimulator
from src.tests.test_location_assignment import (
    _active_row,
    _config as _location_config,
    _dim_location,
    _dim_role,
)
from src.tests.test_simulation_contracts import (
    DEPARTURE_REASON_MAP,
    EVENT_TYPE_MAP,
    ForcedChoice,
    _base_state,
    _config as _contract_config,
)

TODAY = pd.Timestamp("2024-06-10")
LONG_SERVICE = pd.Timestamp("2015-03-01")
RECENT_REVIEW = TODAY - pd.Timedelta(days=20)  # the current row was just reset


def _employee():
    return pd.Series({"Aaneengesloten_Indienst_Datum": LONG_SERVICE})


def _reset_row():
    return pd.Series({"Startdatum": RECENT_REVIEW})


def test_service_start_prefers_continuous_service_and_falls_back_to_the_row():
    assert service_start(_employee(), _reset_row()) == LONG_SERVICE
    assert service_start(
        pd.Series({"Aaneengesloten_Indienst_Datum": None}), _reset_row()
    ) == RECENT_REVIEW
    assert service_start(None, _reset_row()) == RECENT_REVIEW
    assert pd.isna(service_start(None, None))


def test_service_days_and_years_measure_from_continuous_service():
    days = (TODAY - LONG_SERVICE).days

    assert service_days(_employee(), _reset_row(), TODAY) == days
    assert service_years(_employee(), _reset_row(), TODAY) == pytest.approx(days / 365.2425)
    assert service_days(None, None, TODAY) is None
    assert service_years(None, None, TODAY) == 0.0
    future = pd.Series({"Aaneengesloten_Indienst_Datum": TODAY + pd.Timedelta(days=5)})
    assert service_years(future, None, TODAY) == 0.0


def test_performance_tenure_days_is_unchanged_by_the_refactor():
    simulator = PerformanceSimulator(config=None, schema=None, rng=random.Random(1))
    emp = pd.Series({"Aaneengesloten_Indienst_Datum": pd.Timestamp("2013-09-29")})

    assert simulator._tenure_days(emp, pd.Timestamp("2019-01-15")) == (
        pd.Timestamp("2019-01-15") - pd.Timestamp("2013-09-29")
    ).days
    # A missing service date still yields NaN, so `< 180` is False as before.
    missing = simulator._tenure_days(pd.Series({"Aaneengesloten_Indienst_Datum": None}), TODAY)
    assert missing != missing and not (missing < 180)


def test_safety_new_hire_factor_uses_continuous_service_not_the_reset_row():
    config = type("Config", (), {
        "safety": {"new_hire_multiplier": {"within_days": 180, "multiplier": 1.8}},
        "workforce": {},
    })()
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    new_joiner = pd.Series({"Aaneengesloten_Indienst_Datum": TODAY - pd.Timedelta(days=30)})

    assert simulator._new_hire_factor(_employee(), _reset_row(), TODAY) == 1.0
    assert simulator._new_hire_factor(new_joiner, _reset_row(), TODAY) == 1.8


def _absence_simulator():
    config = type("Config", (), {
        "absence": {"minimum_tenure_days": 10},
        "satisfaction": {},
        "engagement": {},
    })()
    return AbsenceSimulator(config, schema=None, rng=random.Random(1))


def test_absence_eligibility_uses_continuous_service_not_the_reset_row():
    simulator = _absence_simulator()
    new_joiner = pd.Series({"Aaneengesloten_Indienst_Datum": TODAY - pd.Timedelta(days=3)})
    # A row reset 5 days ago must not block a long-serving employee.
    fresh_row = pd.Series({
        "Startdatum": TODAY - pd.Timedelta(days=5),
        "Einddatum": pd.NaT,
        "Contract_einddatum": pd.NaT,
    })

    assert simulator._eligible_for_absence(_employee(), fresh_row, TODAY) is True
    assert simulator._eligible_for_absence(new_joiner, fresh_row, TODAY) is False


def test_leave_min_tenure_rule_uses_continuous_service_not_the_reset_row():
    simulator = _absence_simulator()
    rule = {"min_tenure_days": 180}
    absence_type = pd.Series({"AbsenceType_Key": 1})
    employee = pd.Series({
        "Employee_Key": 1,
        "Geboortedatum": TODAY - pd.Timedelta(days=40 * 365),
        "Aaneengesloten_Indienst_Datum": LONG_SERVICE,
        "Geslacht": "M",
    })
    new_joiner = employee.copy()
    new_joiner["Aaneengesloten_Indienst_Datum"] = TODAY - pd.Timedelta(days=60)

    def eligible(who):
        return simulator._eligible_for_leave_type(
            who, _reset_row(), {}, absence_type, rule, pd.DataFrame(), [], TODAY, {},
        )

    assert eligible(employee) is True
    assert eligible(new_joiner) is False


def test_attrition_uses_continuous_service_for_every_tenure_dependent_rule():
    seen = []

    class Recorder(AttritionSimulator):
        @staticmethod
        def _tenure_multiplier(tenure_years):
            seen.append(tenure_years)
            return 1.0

        @staticmethod
        def _salary_multiplier(salary_ratio, performance, tenure_years):
            seen.append(tenure_years)
            return 1.0

        def _departure_category(self, performance, tenure_years, satisfaction, engagement):
            seen.append(tenure_years)
            return "vrijwillig"

        def _choose_reason(self, category, performance, tenure_years, salary_ratio, satisfaction):
            seen.append(tenure_years)
            return "Eigen initiatief"

    config = _contract_config(
        attrition={"Productie": 500.0},  # weekly probability far above 1: always leaves
        retirement={"minimum_age": 50, "forced_retirement_age": 67, "age_bands": []},
        dim_departure_reason={"vrijwillig": ["Eigen initiatief"], "werkgever": ["Ontslag"]},
    )
    state = _base_state(
        contract_einddatum=None, contract_ronde=None, contracttype="Vast",
        hire_date=LONG_SERVICE, row_startdatum=RECENT_REVIEW,
    )
    state["dim_employee"]["Geboortedatum"] = pd.Timestamp("1985-01-01")
    simulator = Recorder(
        config, None, random.Random(1), EVENT_TYPE_MAP,
        {"Eigen initiatief": 1, **DEPARTURE_REASON_MAP},
    )

    simulator.run(state, TODAY)

    expected = (TODAY - LONG_SERVICE).days / 365.2425
    assert len(seen) == 4  # multiplier, salary rule, departure category, reason weight
    assert all(value == pytest.approx(expected) for value in seen)


def test_renewal_keeps_relevant_experience_growing_across_the_new_row():
    state = _base_state(
        contract_einddatum=pd.Timestamp("2024-01-01"), contract_ronde=1,
        hire_date=pd.Timestamp("2023-01-01"),
    )
    renewal_date = pd.Timestamp("2024-01-01")
    before = experience_as_of(state["fact_employment"].iloc[0], renewal_date)
    simulator = ContractLifecycleSimulator(
        _contract_config(), schema=None, rng=ForcedChoice("renew"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, renewal_date)

    new_row = state["fact_employment"].iloc[-1]
    assert before == pytest.approx(1.0, abs=0.01)
    assert new_row["Relevante_Ervaring_Jaren_Bij_Start"] == pytest.approx(before)
    previous = before
    for months in range(0, 25):
        current = experience_as_of(new_row, renewal_date + pd.DateOffset(months=months))
        assert current >= previous
        previous = current


def test_location_transfer_carries_relevant_experience_forward():
    config = _location_config()
    active = _active_row(1, 1, 1)
    active["Relevante_Ervaring_Jaren_Bij_Start"] = 2.0
    state = {
        "dim_role": _dim_role(),
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame([active]),
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": True},
    }
    today = pd.Timestamp("2024-01-01")
    expected = experience_as_of(pd.Series(active), today)  # 2.0 + four years

    result = simulate_location_transfers(
        state, config, None, today, random.Random(1), {"Locatietransfer": 99},
    )

    moved = result["fact_employment"].iloc[-1]
    assert expected > 5.9
    assert moved["Relevante_Ervaring_Jaren_Bij_Start"] == pytest.approx(expected)
    previous = 0.0
    for months in range(0, 25):
        current = experience_as_of(moved, today + pd.DateOffset(months=months))
        assert current >= previous
        previous = current


def test_department_group_relocation_carries_relevant_experience_forward():
    config = _location_config()
    active = _active_row(1, 3, 1)
    active["Relevante_Ervaring_Jaren_Bij_Start"] = 1.0
    state = {
        "dim_role": _dim_role(),
        "dim_location": _dim_location(),
        "fact_employment": pd.DataFrame([active]),
    }
    today = pd.Timestamp("2024-01-01")

    result = relocate_department_group(
        state, config, None, "DC", today, {"Locatietransfer": 99},
    )

    moved = result["fact_employment"].iloc[-1]
    assert moved["Relevante_Ervaring_Jaren_Bij_Start"] == pytest.approx(
        experience_as_of(pd.Series(active), today)
    )


def test_departure_row_carries_relevant_experience_forward():
    employment = pd.Series({
        "Employment_Key": 1, "Employee_Key": 1, "Role_Key": 1,
        "Startdatum": pd.Timestamp("2022-01-01"),
        "Relevante_Ervaring_Jaren_Bij_Start": 3.0,
    })

    row = build_departure_row(None, employment, 2, TODAY, 1, 1, 7.0, 1, 7.0, 1)

    assert row["Relevante_Ervaring_Jaren_Bij_Start"] == pytest.approx(
        experience_as_of(employment, TODAY)
    )
    assert row["Relevante_Ervaring_Jaren_Bij_Start"] > 5.0
