"""Acceptance tests of the pipeline merge: an incremental run is a full run
resumed from a checkpoint.

A full run to week N must give exactly the same tables as a full run to week N-1
followed by one incremental week (and as any other split into chunks). The runs
use a small population and go through `InMemoryStore`, which drops everything a
SQL round trip would drop (non-table state, non-schema columns) and reloads
through the same date normalization as the SQL load path. Values are compared,
not dtypes, and DECIMAL rounding is deliberately not mimicked.
"""
import copy
from datetime import date, datetime

import pandas as pd
import pytest

from src.application.pipeline import run_pipeline
from src.application.run_options import resolve_run_options
from src.core.config_loader import ConfigLoader
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.state.checkpoint import CheckpointError
from src.infrastructure.state.store import InMemoryStore

pytestmark = pytest.mark.slow

SEED = 42
YEAR = 2024
LAST_WEEK = 7          # the "full run to week N"


def _small_config(indexation_months=None, high_floor=False):
    config = ConfigLoader().load()
    if indexation_months:
        config.salary_benchmark["legal_minimum_salary"]["indexation_months"] = indexation_months
    if high_floor:
        # a floor above many starting salaries, so an indexation step catches people
        config.salary_benchmark["legal_minimum_salary"]["annual_full_time_salary"] = 37000
    config.avatar["auto_discover_from_blob"] = False   # no network in tests
    config.start_year_simulation = YEAR
    config.baseline_headcount = 60
    config.initial_population = {**config.initial_population, "burn_in_years": 0, "headcount": 60}
    config.growth = {**config.growth, "max_capacity": 120}
    return config


def _monday(week):
    return datetime.fromisocalendar(YEAR, week, 1)


def _canonical(value):
    if value is None or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def _table_values(frame):
    rows = [tuple(_canonical(cell) for cell in row) for row in frame.itertuples(index=False, name=None)]
    return list(frame.columns), sorted(rows, key=lambda row: tuple(str(cell) for cell in row))


def table_differences(left, right):
    """Names of tables whose values differ between two stores (empty = equal)."""
    differences = []
    for name in sorted(set(left.tables) | set(right.tables)):
        if name not in left.tables or name not in right.tables:
            differences.append(name)
            continue
        if _table_values(left.tables[name]) != _table_values(right.tables[name]):
            differences.append(name)
    return differences


def _full(schema, through_week):
    store = InMemoryStore(schema)
    run_pipeline("full", _small_config(), schema, SEED, store, _monday(through_week))
    return store


def _incremental(schema, store, through_week):
    run_pipeline("incremental", _small_config(), schema, SEED, store, _monday(through_week))
    return store


@pytest.fixture(scope="module")
def schema():
    return load_schema(_small_config().schema)


@pytest.fixture(scope="module")
def full_run(schema):
    return _full(schema, LAST_WEEK)


@pytest.fixture(scope="module")
def stopped_one_week_early(schema):
    return _full(schema, LAST_WEEK - 1)


def test_the_comparison_notices_a_difference():
    a, b = InMemoryStore({}), InMemoryStore({})
    a.tables = {"t": pd.DataFrame({"k": [1, 2], "v": [1.0, None]})}
    b.tables = {"t": pd.DataFrame({"k": [2, 1], "v": [None, 1]})}
    assert table_differences(a, b) == []          # row order, dtype and NaN/None are ignored
    b.tables["t"].loc[0, "v"] = 5
    assert table_differences(a, b) == ["t"]


def test_a_full_run_to_week_n_equals_a_full_run_to_week_n_minus_1_plus_one_incremental_week(
    schema, full_run, stopped_one_week_early
):
    resumed = _incremental(schema, copy.deepcopy(stopped_one_week_early), LAST_WEEK)

    assert (resumed.checkpoint.next_year, resumed.checkpoint.next_week) == (YEAR, LAST_WEEK + 1)
    assert table_differences(full_run, resumed) == []
    assert resumed.checkpoint.persisted_state == full_run.checkpoint.persisted_state


def test_three_chunks_equal_one_run(schema, full_run):
    store = _full(schema, LAST_WEEK - 3)
    _incremental(schema, store, LAST_WEEK - 2)
    _incremental(schema, store, LAST_WEEK)      # catches up two weeks in one incremental run

    assert table_differences(full_run, store) == []


def test_two_incremental_runs_of_the_same_week_from_the_same_checkpoint_are_identical(
    schema, stopped_one_week_early
):
    first = _incremental(schema, copy.deepcopy(stopped_one_week_early), LAST_WEEK)
    second = _incremental(schema, copy.deepcopy(stopped_one_week_early), LAST_WEEK)

    assert table_differences(first, second) == []


def _as_of_run(mode, schema, store, as_of):
    """Run the pipeline the way function_app does for HR_SIMULATION_AS_OF."""
    _, _, today = resolve_run_options(mode, False, as_of.isoformat(), now=datetime(2030, 1, 1))
    run_pipeline(mode, _small_config(), schema, SEED, store, today)
    return store


def test_an_incremental_run_on_the_same_date_simulates_zero_weeks_and_writes_nothing(schema, full_run):
    """The checkpoint points at the next week, so a re-trigger simulates nothing
    instead of repeating the last week - and the changed-row comparison must see
    every re-derived value (snapshots, absence scores, manager assignments) as
    unchanged, or the rewrite of the open month would touch rows every run."""
    store = copy.deepcopy(full_run)

    _incremental(schema, store, LAST_WEEK)

    assert (store.checkpoint.next_year, store.checkpoint.next_week) == (YEAR, LAST_WEEK + 1)
    assert table_differences(full_run, store) == []
    assert store.last_summary
    assert all(counts["added"] == 0 and counts["updated"] == 0 and counts["deleted"] == 0
               for counts in store.last_summary.values()), {
        table: counts for table, counts in store.last_summary.items()
        if counts["added"] or counts["updated"] or counts["deleted"]}
    assert store.last_summary["fact_workforce_snapshot"]["unchanged"] > 0     # the open month was rebuilt and compared


def test_a_full_run_as_of_week_n_plus_an_incremental_run_as_of_week_n_plus_2_equals_a_full_run(schema):
    """HR_SIMULATION_AS_OF: validate the SQL path by running the full run two weeks in the past."""
    wednesday_n = date.fromisocalendar(YEAR, LAST_WEEK - 2, 3)
    friday_n_plus_2 = date.fromisocalendar(YEAR, LAST_WEEK, 5)

    resumed = _as_of_run("full", schema, InMemoryStore(schema), wednesday_n)
    _as_of_run("incremental", schema, resumed, friday_n_plus_2)
    reference = _as_of_run("full", schema, InMemoryStore(schema), friday_n_plus_2)

    assert (resumed.checkpoint.next_year, resumed.checkpoint.next_week) == (YEAR, LAST_WEEK + 1)
    assert table_differences(reference, resumed) == []
    # the two weeks were really simulated by the incremental run
    assert resumed.last_summary["fact_employment"]["added"] + resumed.last_summary["fact_employment"]["updated"] > 0


def test_the_run_contains_real_activity_so_the_comparison_means_something(full_run):
    tables = full_run.tables
    assert len(tables["dim_employee"]) > 60                       # hires happened
    assert len(tables["fact_recruitment"]) > 50
    assert len(tables["fact_workforce_snapshot"]) > 60
    assert full_run.checkpoint.persisted_state["_recruitment_pipeline_profiles"]


def test_an_incremental_run_needs_a_checkpoint_and_the_same_seed(schema, stopped_one_week_early):
    with pytest.raises(CheckpointError, match="full run"):
        _incremental(schema, InMemoryStore(schema), LAST_WEEK)

    with pytest.raises(CheckpointError, match="seed"):
        run_pipeline("incremental", _small_config(), schema, SEED + 1,
                     copy.deepcopy(stopped_one_week_early), _monday(LAST_WEEK))


def test_a_split_across_a_minimum_wage_indexation_equals_one_run(schema):
    """The adjustment keeps no state, so resuming right at an indexation week must
    give the same rows. Indexation on 1 February (a Thursday) makes the week of
    Monday 5 February the one that adjusts everyone below the new floor."""
    indexation_week = 6
    config = lambda: _small_config(indexation_months=[1, 2], high_floor=True)

    def run(mode, store, through_week):
        run_pipeline(mode, config(), schema, SEED, store, _monday(through_week))
        return store

    one_run = run("full", InMemoryStore(schema), indexation_week)
    split = run("full", InMemoryStore(schema), indexation_week - 1)
    run("incremental", split, indexation_week)
    adjustment_key = int(one_run.tables["dim_event_type"].set_index("Gebeurtenis")
                         .loc["Minimumloonaanpassing", "EventType_Key"])

    adjusted = one_run.tables["fact_employment"]["EventType_Key"] == adjustment_key
    assert adjusted.sum() > 0                          # the indexation week really adjusted someone
    assert table_differences(one_run, split) == []
