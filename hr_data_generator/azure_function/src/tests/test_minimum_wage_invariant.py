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


def _small_config():
    config = ConfigLoader().load()
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
