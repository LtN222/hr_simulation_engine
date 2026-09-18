import random
from datetime import datetime

import pandas as pd

from src.simulation.simulation_performance import PerformanceSimulator


def _config():
    return type("Config", (), {
        "satisfaction": {},
        "engagement": {},
        "career_events": {},
    })()


def _base_state(startdatum, hire_date):
    return {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Education_Key": [1],
            "Aaneengesloten_Indienst_Datum": [hire_date],
            "Prestatie_Score": [3.99],
            "Manager_Key": [None],
        }),
        "fact_employment": pd.DataFrame({
            "Employee_Key": [1],
            "Role_Key": [1],
            "Startdatum": [startdatum],
            "Dienstverband_status": ["Actief"],
            "Streef_Compa_Ratio": [1.0],
            "Relevante_Ervaring_Jaren_Bij_Start": [0.0],
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Leidinggevend": [False],
            "Department_Key": [1],
            "Functie_Naam": ["Operator A"],
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1],
            "Afdeling_Naam": ["Productie"],
        }),
        "dim_education": pd.DataFrame({
            "Education_Key": [1],
            "Opleidingsniveau": ["MBO"],
        }),
    }


def test_tenure_days_uses_continuous_tenure_not_the_current_employment_rows_startdatum():
    simulator = PerformanceSimulator(config=None, schema=None, rng=random.Random(1))
    emp = pd.Series({"Aaneengesloten_Indienst_Datum": pd.Timestamp("2013-09-29")})
    today = pd.Timestamp("2019-01-15")

    tenure_days = simulator._tenure_days(emp, today)

    assert tenure_days > 1900


def test_run_weekly_reviews_a_long_tenured_employee_even_right_after_a_salary_review():
    """Regression test: a routine salary review closes the old fact_employment
    row and opens a new one whose Startdatum is the review date itself. That
    must not make a long-tenured employee look newly hired and skip their
    annual performance review - real data showed ~36% of tenured employees
    permanently stuck this way before the fix (see BACKLOG.md/CLAUDE.md)."""
    config = _config()
    simulator = PerformanceSimulator(config, schema=None, rng=random.Random(1))

    review_week = simulator._review_week(1)
    today = pd.Timestamp(datetime.fromisocalendar(2024, review_week, 1))
    recent_salary_review_startdatum = today - pd.Timedelta(days=60)
    true_hire_date = pd.Timestamp("2013-09-29")

    state = _base_state(recent_salary_review_startdatum, true_hire_date)

    state = simulator.run_weekly(state, today)

    reviews = state["fact_performance_review"]
    assert len(reviews) == 1
    assert reviews.iloc[0]["Employee_Key"] == 1


def test_run_weekly_still_skips_a_genuinely_new_hire():
    config = _config()
    simulator = PerformanceSimulator(config, schema=None, rng=random.Random(1))

    review_week = simulator._review_week(1)
    today = pd.Timestamp(datetime.fromisocalendar(2024, review_week, 1))
    recent_hire_date = today - pd.Timedelta(days=60)

    state = _base_state(recent_hire_date, recent_hire_date)

    state = simulator.run_weekly(state, today)

    reviews = state.get("fact_performance_review", pd.DataFrame())
    assert reviews.empty
