import pandas as pd

from src.infrastructure.employment_history import employment_history_for


def _fact_employment():
    return pd.DataFrame({
        "Employee_Key": [1, 1, 2],
        "Employment_Key": [10, 11, 20],
        "Startdatum": pd.to_datetime(["2020-01-01", "2021-01-01", "2020-06-01"]),
    })


def test_employment_history_for_returns_only_that_employees_rows():
    state = {"fact_employment": _fact_employment()}

    history = employment_history_for(state, 1)

    assert sorted(history["Employment_Key"]) == [10, 11]


def test_employment_history_for_returns_empty_for_unknown_employee():
    state = {"fact_employment": _fact_employment()}

    history = employment_history_for(state, 999)

    assert history.empty


def test_employment_history_for_handles_missing_or_empty_fact_employment():
    assert employment_history_for({}, 1).empty
    assert employment_history_for({"fact_employment": pd.DataFrame()}, 1).empty


def test_employment_history_for_reuses_the_grouping_until_the_table_is_replaced():
    state = {"fact_employment": _fact_employment()}

    employment_history_for(state, 1)
    cached_groups = state["_employment_by_employee"]
    employment_history_for(state, 2)

    assert state["_employment_by_employee"] is cached_groups  # no rebuild

    # A new employment row always arrives via pd.concat, i.e. a new object -
    # that must trigger a rebuild so the new row is visible.
    state["fact_employment"] = pd.concat(
        [state["fact_employment"], pd.DataFrame([
            {"Employee_Key": 1, "Employment_Key": 12, "Startdatum": pd.Timestamp("2022-01-01")}
        ])],
        ignore_index=True,
    )
    history = employment_history_for(state, 1)

    assert sorted(history["Employment_Key"]) == [10, 11, 12]
    assert state["_employment_by_employee"] is not cached_groups
