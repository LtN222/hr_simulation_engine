import random
from datetime import datetime

import pandas as pd

from src.core.config_loader import ConfigLoader
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


def _chained_scores(simulator, employee_key, reviews, is_manager=False, experience=6.0):
    scores = []
    previous = None
    for _ in range(reviews):
        previous = simulator._calculate_score(
            is_manager,
            previous_score=previous,
            relevant_experience=experience,
            employee_key=employee_key,
        )
        scores.append(previous)
    return scores


def test_performance_scores_match_the_calibrated_target_distribution():
    """The configured model must land on a realistic Dutch review spread:
    most employees around 'goed', few at 4.0+, a perfect 5.0 almost never."""
    simulator = PerformanceSimulator(
        ConfigLoader().load(), schema=None, rng=random.Random(7)
    )
    rng = random.Random(3)
    latest = []
    for employee_key in range(1, 3001):
        latest.append(_chained_scores(
            simulator,
            employee_key,
            reviews=8,
            is_manager=rng.random() < 0.07,
            experience=rng.uniform(0, 15),
        )[-1])
    scores = pd.Series(latest)

    assert 3.25 <= scores.mean() <= 3.45
    assert 0.03 <= (scores >= 4.0).mean() <= 0.13
    assert (scores >= 4.5).mean() < 0.02
    assert (scores >= 5.0).mean() < 0.005
    assert (scores < 2.5).mean() < 0.06


def test_performance_bonuses_do_not_compound_across_reviews():
    """Regression test: carrying over the whole previous score re-added every
    bonus each year and pinned long-tenured employees at the 5.0 cap. Only the
    deviation may persist, so a long review history averages out at the
    employee's own expected level."""
    simulator = PerformanceSimulator(
        ConfigLoader().load(), schema=None, rng=random.Random(11)
    )
    employee_key = 42
    expected = simulator._expected_score(True, 20.0, employee_key)

    scores = _chained_scores(
        simulator, employee_key, reviews=400, is_manager=True, experience=20.0
    )

    assert abs(pd.Series(scores[20:]).mean() - expected) < 0.1
    assert sum(score >= 5.0 for score in scores) / len(scores) < 0.05


def test_initial_backfill_reviews_cover_the_most_recent_anniversaries():
    simulator = PerformanceSimulator(
        ConfigLoader().load(), schema=None, rng=random.Random(5)
    )
    start = pd.Timestamp("2000-03-01")
    today = pd.Timestamp("2020-06-01")
    employment = pd.Series({
        "Startdatum": start,
        "Relevante_Ervaring_Jaren_Bij_Start": 2.0,
    })
    role = pd.Series({"Leidinggevend": False})

    reviews = simulator._generate_reviews(
        1, start, role, today, 1, employment, {}
    )["records"]

    review_years = sorted(
        pd.Timestamp(record["Review_Datum"]).year for record in reviews
    )
    assert review_years
    assert min(review_years) >= 2015
    assert max(review_years) == 2020
