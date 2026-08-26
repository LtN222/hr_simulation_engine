from types import SimpleNamespace

import pandas as pd

from src.infrastructure.satisfaction import (
    SatisfactionModel,
    explain_employee_satisfaction,
)


def _model():
    return SatisfactionModel(SimpleNamespace(satisfaction={
        "baseline_mean": 7.0,
        "individual_spread": 0.0,
        "performance_midpoint": 3.4,
        "performance_effect": 0.0,
        "manager_effect_spread": 0.0,
        "team_effect_spread": 0.0,
        "culture_effect_spread": 0.0,
        "driver_selection": {
            "minimum_absolute_impact": 0.12,
            "low_score": 6.0,
            "high_score": 7.5,
        },
    }))


def test_satisfaction_explanation_selects_pay_for_low_compa_ratio():
    explanation = _model().explain(
        employee_key=1,
        snapshot_date="2026-01-31",
        performance_score=3.4,
        compa_ratio=0.75,
    )

    assert explanation.score == 5.85
    assert explanation.driver_name == "Beloning"
    assert explanation.driver_direction == "Negatief"


def test_satisfaction_explanation_can_resolve_a_dimension_key():
    model = _model()
    explanation = model.explain(
        employee_key=1,
        snapshot_date="2026-01-31",
        performance_score=3.4,
        compa_ratio=0.75,
    )
    drivers = pd.DataFrame({
        "SatisfactionDriver_Key": [1, 13],
        "Driver_Name": ["Beloning", "Geen dominant aandachtspunt"],
        "Direction": ["Negatief", "Neutraal"],
    })

    assert model.driver_key_for(drivers, explanation) == 1


def test_satisfaction_explanation_uses_neutral_driver_without_material_factor():
    explanation = _model().explain(
        employee_key=1,
        snapshot_date="2026-01-31",
        performance_score=3.4,
        compa_ratio=1.0,
    )

    assert explanation.score == 7.0
    assert explanation.driver_name == "Geen dominant aandachtspunt"
    assert explanation.driver_direction == "Neutraal"


def _employee_and_employment():
    employee = pd.Series({
        "Employee_Key": 1,
        "Performance_Score": 3.4,
        "Manager_Key": 5,
        "Aaneengesloten_Indienst_Datum": pd.Timestamp("2020-01-01"),
    })
    employment = pd.Series({
        "Employee_Key": 1,
        "Role_Key": 1,
        "Target_Compa_Ratio": 1.0,
        "Startdatum": pd.Timestamp("2020-01-01"),
    })
    return employee, employment


def test_explain_employee_satisfaction_caches_identical_resolved_inputs():
    state = {"fact_employment": pd.DataFrame()}
    model = _model()
    employee, employment = _employee_and_employment()

    first = explain_employee_satisfaction(
        model, state, employee, employment, "2026-01-31"
    )
    second = explain_employee_satisfaction(
        model, state, employee, employment, "2026-01-31"
    )

    assert first is second  # served from cache, not recomputed
    assert len(state["_satisfaction_cache"]) == 1


def test_explain_employee_satisfaction_does_not_reuse_across_different_performance():
    state = {"fact_employment": pd.DataFrame()}
    model = _model()
    employee, employment = _employee_and_employment()

    explain_employee_satisfaction(
        model, state, employee, employment, "2026-01-31", performance_score=3.0
    )
    explain_employee_satisfaction(
        model, state, employee, employment, "2026-01-31", performance_score=4.5
    )

    # Different effective inputs must not collapse into one cache entry.
    assert len(state["_satisfaction_cache"]) == 2
