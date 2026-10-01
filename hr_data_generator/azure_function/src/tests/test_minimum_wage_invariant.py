"""HP-03 invariant: no salary is ever below the legal minimum of its date.

A small pipeline run crosses several 1 January and 1 July indexations. Salaries
only change at hire, moves, reviews and the minimum-wage adjustment, so any gap
between the step-wise floor and a salary must be closed by that adjustment.
"""
from datetime import datetime

import pandas as pd
import pytest

from src.application.pipeline import run_pipeline
from src.core.config_loader import ConfigLoader
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.salary_policy import SalaryPolicy
from src.infrastructure.state.store import InMemoryStore
from src.infrastructure.workforce_snapshot import _active_employment

pytestmark = pytest.mark.slow

START_YEAR = 2023
UNTIL = datetime(2025, 1, 20)          # 2 years and 3 weeks: indexations 1 Jan 2024, 1 Jul 2023/2024, 1 Jan 2025


HIGH_FLOOR_UNTIL = datetime(2024, 2, 5)    # 1 Jul 2023 and 1 Jan 2024 are crossed


def _small_config(high_floor=False):
    config = ConfigLoader().load()
    if high_floor:
        # a floor above many starting salaries, so the indexation steps catch people
        config.salary_benchmark["legal_minimum_salary"]["annual_full_time_salary"] = 37000
    config.avatar["auto_discover_from_blob"] = False   # no network in tests
    config.start_year_simulation = START_YEAR
    config.baseline_headcount = 60
    config.initial_population = {**config.initial_population, "burn_in_years": 0, "headcount": 60}
    config.growth = {**config.growth, "max_capacity": 120}
    return config


@pytest.fixture(scope="module")
def run():
    config = _small_config()
    schema = load_schema(config.schema)
    store = InMemoryStore(schema)
    run_pipeline("full", config, schema, 42, store, UNTIL)
    return config, store.tables


@pytest.fixture(scope="module")
def policy(run):
    config, _ = run
    return SalaryPolicy(config)


def test_no_snapshot_row_is_below_the_floor_of_its_snapshot_date(run, policy):
    _, tables = run
    snapshots = tables["fact_workforce_snapshot"]
    snapshots["floor"] = [policy.legal_minimum(date) for date in snapshots["Snapshot_Date"]]

    below = snapshots[snapshots["Salaris"] < snapshots["floor"]]

    assert len(snapshots) > 500
    assert below.empty, below[["Snapshot_Date", "Employee_Key", "Salaris", "floor"]].head(10).to_string()


def test_every_active_employment_row_on_every_snapshot_date_is_at_or_above_the_floor(run, policy):
    _, tables = run
    employment = tables["fact_employment"].copy()
    employment["Startdatum"] = pd.to_datetime(employment["Startdatum"])
    employment["Einddatum"] = pd.to_datetime(employment["Einddatum"])
    dates = sorted(pd.to_datetime(tables["fact_workforce_snapshot"]["Snapshot_Date"]).unique())
    assert len(dates) >= 24

    for date in dates:
        active = _active_employment(employment, pd.Timestamp(date))
        floor = policy.legal_minimum(date)
        assert (active["Salaris"] >= floor).all(), (date, active[active["Salaris"] < floor]["Salaris"].tolist())


def test_the_adjustment_rows_exist_stay_a_small_share_and_are_never_below_the_floor(run, policy):
    _, tables = run
    event_key = int(tables["dim_event_type"].set_index("Gebeurtenis").loc["Minimumloonaanpassing", "EventType_Key"])
    employment = tables["fact_employment"].copy()
    employment["Startdatum"] = pd.to_datetime(employment["Startdatum"])
    adjustments = employment[employment["EventType_Key"] == event_key]
    headcount = tables["dim_employee"]["Employee_Key"].nunique()

    per_year = adjustments.groupby(adjustments["Startdatum"].dt.year).size()

    assert not adjustments.empty
    assert (per_year <= headcount * 0.25).all(), per_year.to_dict()
    for _, row in adjustments.iterrows():
        assert row["Salaris"] == policy.legal_minimum(row["Startdatum"])
    # an adjustment never lands in the middle of a week other than the indexation week
    assert set(adjustments["Startdatum"].dt.month) <= {1, 2, 7, 8}


def test_the_new_event_is_not_used_as_a_promotion_or_transfer(run):
    _, tables = run
    event_key = int(tables["dim_event_type"].set_index("Gebeurtenis").loc["Minimumloonaanpassing", "EventType_Key"])
    employment = tables["fact_employment"]
    adjusted = employment[employment["EventType_Key"] == event_key]
    previous = employment.set_index("Employment_Key").loc[adjusted["Previous_Employment_Key"]]

    assert (adjusted["Role_Key"].to_numpy() == previous["Role_Key"].to_numpy()).all()
    assert (adjusted["Location_Key"].to_numpy() == previous["Location_Key"].to_numpy()).all()


# ---------------------------------------------------------------------------
# higher-floor variant: the assertion must really bite
# ---------------------------------------------------------------------------

def _rows_below_the_floor(config, tables):
    policy = SalaryPolicy(config)
    snapshots = tables["fact_workforce_snapshot"]
    floors = pd.Series([policy.legal_minimum(date) for date in snapshots["Snapshot_Date"]], index=snapshots.index)
    return snapshots[snapshots["Salaris"] < floors], len(snapshots)


def _high_floor_run(adjustment_on, monkeypatch=None):
    from src.application import simulation_runner

    config = _small_config(high_floor=True)
    schema = load_schema(config.schema)
    store = InMemoryStore(schema)
    original = simulation_runner.simulate_minimum_wage_adjustments
    if not adjustment_on:
        simulation_runner.simulate_minimum_wage_adjustments = lambda state, *args, **kwargs: state
    try:
        run_pipeline("full", config, schema, 42, store, HIGH_FLOOR_UNTIL)
    finally:
        simulation_runner.simulate_minimum_wage_adjustments = original
    return config, store.tables


def test_with_a_higher_floor_the_invariant_bites_without_the_step_and_holds_with_it():
    """With a floor above many salaries, switching the minimum-wage adjustment off
    leaves rows below the floor; switching it on leaves none (and does adjust people)."""
    config_off, tables_off = _high_floor_run(adjustment_on=False)
    below_off, total = _rows_below_the_floor(config_off, tables_off)

    config_on, tables_on = _high_floor_run(adjustment_on=True)
    below_on, total_on = _rows_below_the_floor(config_on, tables_on)

    event_key = int(tables_on["dim_event_type"].set_index("Gebeurtenis").loc["Minimumloonaanpassing", "EventType_Key"])
    adjustments = (tables_on["fact_employment"]["EventType_Key"] == event_key).sum()

    assert total > 200 and total_on > 200
    assert len(below_off) > 0, "the higher-floor variant does not exercise the adjustment"
    assert below_on.empty, below_on[["Snapshot_Date", "Employee_Key", "Salaris"]].head().to_string()
    assert adjustments > 0
