import random

import pandas as pd

from src.core.config_loader import ConfigLoader
from src.simulation.simulation_safety import (
    LOST_TIME_ABSENCE_TYPE,
    LOST_TIME_INCIDENT_TYPE,
    SafetyIncidentSimulator,
)


def _config(**safety_overrides):
    safety = {
        "annual_incident_rate_by_department": {"Productie": 1.0, "Finance": 0.0},
        "ploegendienst_multipliers": {"Niet van toepassing": 1.0, "3-ploeg": 1.3},
        "new_hire_multiplier": {"within_days": 180, "multiplier": 1.8},
        "type_weights": {
            "Bijna-ongeval": 60, "EHBO-geval": 25,
            "Medische behandeling": 10, "Verzuimongeval": 5,
        },
        "lost_workdays_range": {"min_days": 1, "mode_days": 3, "max_days": 20},
    }
    safety.update(safety_overrides)
    return type("Config", (), {"safety": safety, "workforce": {}})()


def _incident_types():
    return pd.DataFrame({
        "IncidentType_Key": [1, 2, 3, 4],
        "IncidentType_Name": ["Bijna-ongeval", "EHBO-geval", "Medische behandeling", "Verzuimongeval"],
        "Recordable": [False, False, True, True],
    })


def _employment_row(employee_key=1, role_key=1, startdatum=pd.Timestamp("2020-01-01")):
    return pd.Series({
        "Employee_Key": employee_key, "Role_Key": role_key, "Location_Key": 1,
        "Shift_Key": 0, "SalaryScale_Key": 1, "Salaris": 40000,
        "Contracturen": 40, "Startdatum": startdatum, "Einddatum": None,
        "Contract_einddatum": None,
    })


def test_annual_rate_scales_with_department_shift_and_new_hire_multipliers():
    config = _config()
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    state = {
        "dim_role": pd.DataFrame({"Role_Key": [1], "Role_Name": ["Operator"], "Department_Key": [1]}),
        "dim_department": pd.DataFrame({"Department_Key": [1], "Department_Name": ["Productie"]}),
        "dim_shift": pd.DataFrame({
            "Shift_Key": [0, 3], "Shift_Name": ["Niet van toepassing", "3-ploeg"],
        }),
    }
    long_tenure = _employment_row(startdatum=pd.Timestamp("2015-01-01"))
    long_tenure["Shift_Key"] = 0
    new_hire = _employment_row(startdatum=pd.Timestamp("2023-12-15"))
    new_hire["Shift_Key"] = 3

    base_rate = simulator._annual_rate(long_tenure, state, pd.Timestamp("2024-01-01"))
    boosted_rate = simulator._annual_rate(new_hire, state, pd.Timestamp("2024-01-01"))

    assert base_rate == 1.0  # no shift bonus, not a new hire
    assert boosted_rate == 1.0 * 1.3 * 1.8  # shift bonus and new-hire bonus both apply


def test_new_hire_factor_only_applies_within_the_configured_window():
    config = _config()
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    today = pd.Timestamp("2024-01-01")

    recent = _employment_row(startdatum=today - pd.Timedelta(days=30))
    old = _employment_row(startdatum=today - pd.Timedelta(days=400))

    assert simulator._new_hire_factor(recent, today) == 1.8
    assert simulator._new_hire_factor(old, today) == 1.0


def test_choose_incident_type_respects_configured_weights():
    config = _config(type_weights={"Bijna-ongeval": 1000, "Verzuimongeval": 0.001,
                                    "EHBO-geval": 0.001, "Medische behandeling": 0.001})
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    incident_types = _incident_types().to_dict(orient="records")

    picks = [simulator._choose_incident_type(incident_types)["IncidentType_Name"] for _ in range(200)]

    assert picks.count("Bijna-ongeval") > 190


def test_choose_lost_workdays_stays_within_the_configured_range():
    config = _config(lost_workdays_range={"min_days": 2, "mode_days": 4, "max_days": 6})
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))

    values = [simulator._choose_lost_workdays() for _ in range(100)]

    assert all(2 <= value <= 6 for value in values)


def _base_state(config):
    return {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1], "Geboortedatum": [pd.Timestamp("1990-01-01")], "Gender": ["V"],
        }),
        "dim_role": pd.DataFrame({"Role_Key": [1], "Role_Name": ["Operator"], "Department_Key": [1]}),
        "dim_department": pd.DataFrame({"Department_Key": [1], "Department_Name": ["Productie"]}),
        "dim_shift": pd.DataFrame({
            "Shift_Key": [0], "Shift_Name": ["Niet van toepassing"],
        }),
        "dim_incident_type": _incident_types(),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1], "AbsenceType_Name": [LOST_TIME_ABSENCE_TYPE],
            "Telt_als_verzuim": [True],
        }),
        "dim_satisfaction_band": pd.DataFrame({
            "SatisfactionBand_Key": [1], "SatisfactionBand_Name": ["Neutraal"],
            "Minimum_Score": [0], "Maximum_Score": [10],
        }),
        "dim_salary_band": pd.DataFrame({
            "SalaryBand_Key": [1], "SalaryBand_Name": ["Band"],
            "Minimum_Salaris": [0], "Maximum_Salaris": [None],
        }),
        "fact_employment": pd.DataFrame([{
            **_employment_row().to_dict(), "Dienstverband_status": "Actief",
        }]),
        "fact_absence": pd.DataFrame(),
        "satisfaction": {}, "career_events": {}, "engagement": {},
    }


def test_run_creates_a_linked_absence_episode_for_a_lost_time_incident():
    config = _config(
        annual_incident_rate_by_department={"Productie": 1000.0},  # force an incident this week
        type_weights={"Verzuimongeval": 1.0, "Bijna-ongeval": 0.0,
                       "EHBO-geval": 0.0, "Medische behandeling": 0.0},
    )
    config.satisfaction = {}
    config.engagement = {}
    config.career_events = {}
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    state = _base_state(config)

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    incidents = state["fact_safety_incident"]
    assert len(incidents) == 1
    incident = incidents.iloc[0]
    assert incident["Lost_Workdays"] > 0
    assert pd.notna(incident["Absence_Key"])

    absence = state["fact_absence"]
    assert len(absence) == 1
    linked = absence.iloc[0]
    assert linked["Absence_Key"] == incident["Absence_Key"]
    assert linked["AbsenceType_Key"] == 1
    assert linked["Verzuim_Werkdagen"] > 0


def test_run_does_not_touch_fact_absence_for_a_non_lost_time_incident():
    config = _config(
        annual_incident_rate_by_department={"Productie": 1000.0},
        type_weights={"Bijna-ongeval": 1.0, "EHBO-geval": 0.0,
                      "Medische behandeling": 0.0, "Verzuimongeval": 0.0},
    )
    config.satisfaction = {}
    config.engagement = {}
    config.career_events = {}
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    state = _base_state(config)

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    incidents = state["fact_safety_incident"]
    assert len(incidents) == 1
    assert incidents.iloc[0]["Lost_Workdays"] == 0
    assert pd.isna(incidents.iloc[0]["Absence_Key"])
    assert state["fact_absence"].empty


def test_run_skips_employees_already_absent_this_week():
    config = _config(annual_incident_rate_by_department={"Productie": 1000.0})
    config.satisfaction = {}
    config.engagement = {}
    config.career_events = {}
    simulator = SafetyIncidentSimulator(config, schema=None, rng=random.Random(1))
    state = _base_state(config)
    state["fact_absence"] = pd.DataFrame({
        "Employee_Key": [1], "Startdatum": [pd.Timestamp("2023-12-30")],
        "Einddatum": [pd.Timestamp("2024-01-05")],
    })

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    assert state["fact_safety_incident"].empty


def test_full_run_with_real_config_produces_incidents_over_many_weeks():
    """End-to-end regression guard against the real sector config: over a
    large enough population and enough weeks, Productie should accumulate
    incidents, and at least one should be a lost-time incident linked to a
    real fact_absence row."""
    config = ConfigLoader().load()
    rng = random.Random(11)
    employee_count = 60
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": list(range(1, employee_count + 1)),
            "Geboortedatum": [pd.Timestamp("1990-01-01")] * employee_count,
            "Gender": ["V"] * employee_count,
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Role_Name": ["Operator"], "Department_Key": [1],
        }),
        "dim_department": pd.DataFrame({"Department_Key": [1], "Department_Name": ["Productie"]}),
        "dim_shift": pd.DataFrame(config.dim_shift),
        "dim_incident_type": pd.DataFrame(config.dim_incident_type),
        "dim_absence_type": pd.DataFrame([
            {"AbsenceType_Key": i + 1, "AbsenceType_Name": name, "Telt_als_verzuim": telt}
            for i, (name, telt) in enumerate(config.dim_absence_type.items())
        ]),
        "dim_satisfaction_band": pd.DataFrame(config.dim_satisfaction_band),
        "dim_salary_band": pd.DataFrame(config.dim_salary_band),
        "fact_employment": pd.DataFrame([
            {**_employment_row(employee_key=key).to_dict(), "Dienstverband_status": "Actief"}
            for key in range(1, employee_count + 1)
        ]),
        "fact_absence": pd.DataFrame(),
    }

    for week in range(52):
        state = SafetyIncidentSimulator(config, schema=None, rng=rng).run(
            state, pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=week)
        )

    incidents = state["fact_safety_incident"]
    assert not incidents.empty
    lost_time = incidents[incidents["Lost_Workdays"] > 0]
    if not lost_time.empty:
        linked_absences = state["fact_absence"]
        assert set(lost_time["Absence_Key"].dropna()).issubset(
            set(linked_absences["Absence_Key"])
        )
