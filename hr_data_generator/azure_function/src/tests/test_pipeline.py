"""The shared pipeline: modes, growth parameters, per-week random streams, stores."""
import datetime as dt
import random

import pandas as pd
import pytest
from faker import Faker

from src.application import pipeline
from src.core.config_loader import ConfigLoader
from src.infrastructure.state.checkpoint import Checkpoint
from src.infrastructure.state.incremental_load import load_incremental_state
from src.infrastructure.state.store import InMemoryStore

SCHEMA = {
    "dim_shift": {
        "df": "dim_shift", "primary_key": "Shift_Key",
        "types": {"Shift_Key": "INT", "Ploegendienst_Naam": "NVARCHAR(50)", "Aangemaakt": "DATE"},
    },
}


def test_only_full_and_incremental_are_valid_modes():
    assert pipeline.validate_mode("full") == "full"
    assert pipeline.validate_mode("incremental") == "incremental"
    for bad in ("Full", "", "weekly", None):
        with pytest.raises(ValueError, match="Unknown simulation mode"):
            pipeline.validate_mode(bad)


def test_run_pipeline_rejects_an_unknown_mode_before_touching_the_store():
    with pytest.raises(ValueError):
        pipeline.run_pipeline("resume", None, {}, 42, store=None, today=dt.datetime(2024, 1, 1))


def test_the_growth_rate_is_the_same_in_every_run_and_depends_only_on_seed_and_config():
    config = ConfigLoader().load()

    first = pipeline.simulation_parameters(config, 42)
    again = pipeline.simulation_parameters(config, 42)
    other_seed = pipeline.simulation_parameters(config, 43)

    low = config.growth["annual_growth_rate"]["min"]
    high = config.growth["annual_growth_rate"]["max"]
    assert first.annual_growth_rate == again.annual_growth_rate
    assert low <= first.annual_growth_rate <= high
    assert other_seed.annual_growth_rate != first.annual_growth_rate
    assert first.burn_in_start_date.year == config.start_year_simulation - first.burn_in_years


def test_the_growth_rate_does_not_consume_a_run_stream():
    config = ConfigLoader().load()
    stream = random.Random("42:2024:10")
    before = stream.random()

    pipeline.simulation_parameters(config, 42)

    assert random.Random("42:2024:10").random() == before


def _params():
    return pipeline.SimulationParameters(
        1, 1, 1, 0.1, 1, 0, 0, 0, dt.datetime(2020, 1, 1), dt.datetime(2020, 1, 1),
    )


def _record_weeks(monkeypatch):
    draws = {}

    def fake_simulate_week(state, config, schema, year, week, *args, **kwargs):
        rng = args[4]  # after baseline, capacity, growth rate and peak weeks
        draws[(year, week)] = (rng.random(), rng.random(), Faker("nl_NL").name())
        return state

    monkeypatch.setattr(pipeline, "simulate_week", fake_simulate_week)
    return draws


def test_a_weeks_draws_do_not_depend_on_how_many_weeks_ran_before_it(monkeypatch):
    config = type("Config", (), {"start_year_simulation": 2020})()
    end = dt.datetime.fromisocalendar(2024, 12, 1)

    draws = _record_weeks(monkeypatch)
    pipeline.run_weeks({}, Checkpoint(42, 2024, 10, "x"), config, {}, _params(), 42, end)
    late_start = dict(draws)

    draws.clear()
    pipeline.run_weeks({}, Checkpoint(42, 2024, 2, "x"), config, {}, _params(), 42, end)
    early_start = dict(draws)

    for week in ((2024, 10), (2024, 11), (2024, 12)):
        assert late_start[week] == early_start[week]
    assert len({v for v in early_start.values()}) == len(early_start)  # weeks differ from each other


def test_a_different_seed_changes_the_weeks_draws(monkeypatch):
    config = type("Config", (), {"start_year_simulation": 2020})()
    end = dt.datetime.fromisocalendar(2024, 10, 1)
    draws = _record_weeks(monkeypatch)

    pipeline.run_weeks({}, Checkpoint(42, 2024, 10, "x"), config, {}, _params(), 42, end)
    first = dict(draws)
    draws.clear()
    pipeline.run_weeks({}, Checkpoint(43, 2024, 10, "x"), config, {}, _params(), 43, end)

    assert draws[(2024, 10)] != first[(2024, 10)]


def test_the_in_memory_store_keeps_only_schema_tables_and_columns():
    store = InMemoryStore(SCHEMA)
    state = {
        "dim_shift": pd.DataFrame({
            "Shift_Key": [1, 2], "Ploegendienst_Naam": ["Dag", "2-ploeg"], "Extra": ["x", "y"],
        }),
        "_location_open": {"A": True},
        "not_a_table": pd.DataFrame({"a": [1]}),
    }
    checkpoint = Checkpoint(42, 2024, 3, "fp", persisted_state={"_location_open": {"A": True}})

    store.write(state, checkpoint, reset=True)
    loaded, loaded_checkpoint = store.load(SCHEMA)

    assert list(loaded) == ["dim_shift"]
    assert list(loaded["dim_shift"].columns) == ["Shift_Key", "Ploegendienst_Naam", "Aangemaakt"]
    assert loaded["dim_shift"]["Aangemaakt"].isna().all()   # a missing schema column comes back NULL
    assert loaded_checkpoint.next_week == 3
    assert loaded_checkpoint.persisted_state == {"_location_open": {"A": True}}
    assert loaded is not store.tables                       # a copy, not the store's own frames


def test_a_load_from_an_empty_store_has_empty_tables_and_no_checkpoint():
    state, checkpoint = InMemoryStore(SCHEMA).load(SCHEMA)

    assert state["dim_shift"].empty and list(state["dim_shift"].columns)[0] == "Shift_Key"
    assert checkpoint is None


def test_an_incremental_load_without_a_checkpoint_asks_for_a_full_run():
    from src.infrastructure.state.checkpoint import CheckpointError

    with pytest.raises(CheckpointError, match="full run"):
        load_incremental_state(InMemoryStore(SCHEMA), None, SCHEMA, 42)


# ---------------------------------------------------------------------------
# AR-22: the weekly state contract
# ---------------------------------------------------------------------------

def test_hiring_no_longer_writes_the_dead_state_keys_or_assigns_managers():
    import inspect

    from src.simulation import simulation_hiring, simulation_vacancy

    hiring = simulation_hiring.HiringSimulator(
        type("Config", (), {"avatar": {}})(), None, random.Random(1), {}
    )
    state = hiring.run({"_accepted_applications": []}, pd.Timestamp("2024-01-01"))

    assert "vacancies" not in state and "_latest_hires" not in state
    for module in (simulation_hiring, simulation_vacancy):
        source = inspect.getsource(module)
        assert 'state["vacancies"]' not in source and "_latest_hires" not in source
    assert "assign_managers" not in inspect.getsource(simulation_hiring)


def test_post_process_starts_with_empty_week_caches(monkeypatch):
    from src.application import simulation_runner

    class Stop(Exception):
        pass

    seen = {}

    def first_step(state):
        seen.update(state)
        raise Stop

    monkeypatch.setattr(pipeline, "sync_employee_employment_status", first_step)
    state = {key: {"stale": 1} for key in simulation_runner.WEEK_CACHE_KEYS}

    with pytest.raises(Stop):
        pipeline.post_process(state, None, {}, None, dt.datetime(2024, 1, 1))

    assert all(seen[key] == {} for key in simulation_runner.WEEK_CACHE_KEYS)
