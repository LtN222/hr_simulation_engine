"""AR-11: historical snapshot rows must not show today's values."""
import pandas as pd

from src.core.config_loader import ConfigLoader
from src.infrastructure import absence_context
from src.infrastructure.dimensions import build_dim_department, build_dim_role
from src.infrastructure.performance_baseline import starting_performance
from src.infrastructure.workforce_snapshot import build_workforce_snapshots

D = pd.Timestamp


def test_starting_performance_prefers_the_initial_score_over_the_current_one():
    both = {"Aanvangs_Prestatie_Score": 3.1, "Prestatie_Score": 4.5}

    assert starting_performance(both) == 3.1
    assert starting_performance({"Prestatie_Score": 4.5}) == 4.5
    assert starting_performance({"Aanvangs_Prestatie_Score": None, "Prestatie_Score": 4.5}) == 4.5
    assert starting_performance({}) == 3.4
    assert starting_performance(pd.Series({"Aanvangs_Prestatie_Score": 2.5})) == 2.5


def _snapshot_state(config, employment_scale=None, with_initial=True):
    departments = build_dim_department(config.structure)
    scales = pd.DataFrame(config.dim_salary_scale)
    roles = build_dim_role(
        config.structure, departments, scales,
        config.salary_benchmark["market_median_by_role"], config.role_career_paths,
    )
    role = roles[roles["Functie_Naam"] == "Operator A"].iloc[0]
    if employment_scale is None:
        employment_scale = int(scales.loc[
            scales["SalaryScale_Key"] != role["SalaryScale_Key"], "SalaryScale_Key"
        ].iloc[0])
    employee = {
        "Employee_Key": 1, "Prestatie_Score": 4.4, "HireSource_Key": 1, "Education_Key": 1,
        "Aaneengesloten_Indienst_Datum": D("2024-01-01"),
    }
    if with_initial:
        employee["Aanvangs_Prestatie_Score"] = 3.0
    return {
        "dim_employee": pd.DataFrame([employee]),
        "dim_role": roles, "dim_department": departments, "dim_salary_scale": scales,
        "fact_employment": pd.DataFrame([{
            "Employment_Key": 1, "Employee_Key": 1, "Role_Key": int(role["Role_Key"]),
            "Location_Key": 1, "Shift_Key": 0, "SalaryScale_Key": employment_scale,
            "Streef_Compa_Ratio": 1.0, "Startdatum": D("2024-01-01"), "Einddatum": None,
            "Contracttype": "Vast", "Contracturen": 40, "Salaris": 42000,
            "Dienstverband_status": "Actief",
        }]),
        "fact_performance_review": pd.DataFrame({
            "Employee_Key": [1], "Review_Datum": [D("2024-03-10")], "Prestatie_Score": [4.4],
        }),
    }, employment_scale


def _snapshots(state, config):
    return build_workforce_snapshots(
        state, schema=None, config=config,
        start_date=D("2024-01-31"), end_date=D("2024-04-30"),
    )["fact_workforce_snapshot"].set_index("Snapshot_Date")


def test_snapshot_before_the_first_review_uses_the_initial_score_not_todays():
    config = ConfigLoader().load()
    state, _ = _snapshot_state(config)

    snapshots = _snapshots(state, config)

    assert snapshots.loc[D("2024-01-31"), "Prestatie_Score"] == 3.0
    assert snapshots.loc[D("2024-02-29"), "Prestatie_Score"] == 3.0
    assert snapshots.loc[D("2024-03-31"), "Prestatie_Score"] == 4.4  # the review has happened


def test_snapshot_falls_back_to_the_current_score_when_no_initial_score_exists():
    config = ConfigLoader().load()
    state, _ = _snapshot_state(config, with_initial=False)

    snapshots = _snapshots(state, config)

    assert snapshots.loc[D("2024-01-31"), "Prestatie_Score"] == 4.4


def test_snapshot_keeps_the_effective_rows_salary_scale_not_the_roles_current_one():
    config = ConfigLoader().load()
    state, employment_scale = _snapshot_state(config)
    role_scale = int(state["dim_role"].loc[
        state["dim_role"]["Functie_Naam"] == "Operator A", "SalaryScale_Key"
    ].iloc[0])

    snapshots = _snapshots(state, config)

    assert employment_scale != role_scale
    assert (snapshots["SalaryScale_Key"] == employment_scale).all()
    # the benchmark amounts still come from the benchmark builder
    assert snapshots["Benchmark_Salaris"].notna().all()


def test_absence_satisfaction_scoring_uses_the_initial_score_before_a_first_review(monkeypatch):
    config = type("Config", (), {"satisfaction": {}, "engagement": {}})()
    seen = []

    def spy(model, state, employee, employment, date, performance_score=None, manager_key=None):
        seen.append(performance_score)
        return 7.0

    monkeypatch.setattr(absence_context, "score_employee_satisfaction", spy)
    state = {
        "fact_absence": pd.DataFrame({
            "Absence_Key": [1], "Employee_Key": [1], "Startdatum": [D("2024-02-05")],
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1], "Employee_Key": [1], "Startdatum": [D("2024-01-01")],
            "Einddatum": [pd.NaT],
        }),
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1], "Prestatie_Score": [4.4], "Aanvangs_Prestatie_Score": [3.0],
        }),
        "dim_satisfaction_band": pd.DataFrame({
            "SatisfactionBand_Key": [1], "Minimum_Score": [1.0], "Maximum_Score": [10.0],
        }),
        "fact_performance_review": pd.DataFrame({
            "Employee_Key": [1], "Review_Datum": [D("2024-03-10")], "Prestatie_Score": [4.4],
        }),
    }

    absence_context.sync_absence_satisfaction(state, config)

    assert seen == [3.0]
