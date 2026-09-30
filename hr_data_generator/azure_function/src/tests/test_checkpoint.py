"""Checkpoint: what an incremental run carries besides the SQL tables."""
import datetime as dt
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.application import pipeline
from src.core.iso_week import has_iso_week_53
from src.infrastructure.state.checkpoint import (
    PERSISTED_KEYS,
    STATE_KEY_REGISTER,
    Checkpoint,
    CheckpointError,
    checkpoint_state,
    config_fingerprint,
    from_jsonable,
    restore_state,
    to_jsonable,
    validate_checkpoint,
)

SCHEMA = {
    "dim_employee": {"df": "dim_employee", "types": {"Employee_Key": "INT"}},
    "fact_employment": {"df": "fact_employment", "types": {"Employment_Key": "INT"}},
}


def _config(**data):
    return type("Config", (), {"_data": data})()


def _sample_persisted_state():
    """Realistic values for every persisted key, with the awkward types."""
    return {
        "_location_open": {"Fabriek Noord": True, "Fabriek Zuid": False},
        "_location_opened_on": {
            "Fabriek Noord": dt.datetime(2020, 1, 6),
            "Fabriek Zuid": pd.Timestamp("2022-03-14"),
        },
        "_location_capacity_streak": {"Fabriek Zuid": 5},
        "_location_capacity_bonus": {"Fabriek Noord": 5},
        "_home_location": {"Logistiek": "DC", "Finance": "Hoofdkantoor"},
        "_recruitment_pipeline_profiles": {
            17: {
                "Education_Key": np.int64(12),
                "Relevante_Ervaring_Jaren": 3.5,
                "Leidinggevende_Ervaring_Jaren": 0.0,
                "Qualifications": [{"Opleiding_Naam": "MBO Techniek", "Opleidingsniveau": "MBO"}],
            },
            18: {"Education_Key": None, "Relevante_Ervaring_Jaren": 0.0, "Qualifications": []},
        },
        "_vacancy_requests": [
            {"Role_Key": np.int64(3), "Department_Key": np.int64(1), "Vacature_Reden": "Interne doorstroom"},
            {"Role_Key": 4, "Department_Key": None, "Vacature_Reden": "Vervanging"},
        ],
    }


def test_every_persisted_key_has_a_sample_and_the_sample_covers_the_register():
    assert set(_sample_persisted_state()) == set(PERSISTED_KEYS)


@pytest.mark.parametrize("key", PERSISTED_KEYS)
def test_a_persisted_key_survives_the_json_round_trip_with_its_types(key):
    value = _sample_persisted_state()[key]

    restored = from_jsonable(to_jsonable(value))

    assert restored == _normalise(value)
    _assert_same_types(restored, _normalise(value))


def _normalise(value):
    """numpy scalars come back as plain Python numbers."""
    if isinstance(value, dict):
        return {_normalise(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _assert_same_types(a, b):
    assert type(a) is type(b)
    if isinstance(a, dict):
        assert {type(k) for k in a} == {type(k) for k in b}
        for key in a:
            _assert_same_types(a[key], b[key])
    elif isinstance(a, list):
        for x, y in zip(a, b):
            _assert_same_types(x, y)


def test_a_full_checkpoint_round_trips_through_json_text():
    checkpoint = Checkpoint(
        seed=42, next_year=2021, next_week=1, config_fingerprint="abc",
        persisted_state=_sample_persisted_state(),
    )

    restored = Checkpoint.from_json(checkpoint.to_json())

    assert (restored.seed, restored.next_year, restored.next_week) == (42, 2021, 1)
    assert restored.config_fingerprint == "abc"
    assert restored.persisted_state["_recruitment_pipeline_profiles"][17]["Qualifications"][0][
        "Opleiding_Naam"] == "MBO Techniek"
    assert isinstance(restored.persisted_state["_location_opened_on"]["Fabriek Zuid"], pd.Timestamp)
    assert isinstance(restored.persisted_state["_location_opened_on"]["Fabriek Noord"], dt.datetime)


def test_checkpoint_state_captures_persisted_keys_and_defaults_missing_ones():
    state = {"dim_employee": pd.DataFrame(), "_location_open": {"A": True}, "_satisfaction_cache": {}}
    checkpoint = Checkpoint(seed=1, next_year=2024, next_week=3, config_fingerprint="x")

    checkpoint_state(state, SCHEMA, checkpoint)

    assert checkpoint.persisted_state["_location_open"] == {"A": True}
    assert checkpoint.persisted_state["_vacancy_requests"] == []
    assert set(checkpoint.persisted_state) == set(PERSISTED_KEYS)
    assert "_satisfaction_cache" not in checkpoint.persisted_state  # transient


def test_restore_state_puts_persisted_keys_back_and_defaults_the_rest():
    checkpoint = Checkpoint(1, 2024, 3, "x", persisted_state={"_home_location": {"Logistiek": "DC"}})
    state = restore_state({}, checkpoint)

    assert state["_home_location"] == {"Logistiek": "DC"}
    assert state["_recruitment_pipeline_profiles"] == {}
    assert state["_vacancy_requests"] == []


def test_an_unclassified_state_key_raises_instead_of_vanishing():
    state = {"dim_employee": pd.DataFrame(), "_brand_new_cache": {"x": 1}}
    checkpoint = Checkpoint(1, 2024, 3, "x")

    with pytest.raises(CheckpointError, match="_brand_new_cache"):
        checkpoint_state(state, SCHEMA, checkpoint)


def test_accepted_applications_left_over_at_week_end_raise():
    checkpoint = Checkpoint(1, 2024, 3, "x")

    checkpoint_state({"_accepted_applications": []}, SCHEMA, checkpoint)  # empty is fine
    with pytest.raises(CheckpointError, match="_accepted_applications"):
        checkpoint_state({"_accepted_applications": [{"Vacancy_Key": 1}]}, SCHEMA, checkpoint)


def test_a_missing_checkpoint_asks_for_a_full_run():
    with pytest.raises(CheckpointError, match="full run"):
        validate_checkpoint(None, seed=42, config=_config())


def test_a_different_seed_raises():
    config = _config(a=1)
    checkpoint = Checkpoint(42, 2024, 3, config_fingerprint(config))

    with pytest.raises(CheckpointError, match="seed"):
        validate_checkpoint(checkpoint, seed=43, config=config)
    assert validate_checkpoint(checkpoint, seed=42, config=config) is checkpoint
    assert validate_checkpoint(checkpoint, seed="42", config=config) is checkpoint


def test_a_changed_config_only_warns(caplog):
    checkpoint = Checkpoint(42, 2024, 3, config_fingerprint(_config(a=1)))

    with caplog.at_level(logging.WARNING):
        result = validate_checkpoint(checkpoint, seed=42, config=_config(a=2))

    assert result is checkpoint
    assert "configuration changed" in caplog.text


def test_the_config_fingerprint_is_stable_and_ignores_runtime_only_settings():
    a = _config(x=1, y={"b": 2, "a": 1}, simulation_mode="full", simulation_weeks=104)
    b = _config(y={"a": 1, "b": 2}, x=1, simulation_mode="incremental", simulation_weeks=10)

    assert config_fingerprint(a) == config_fingerprint(b)
    assert config_fingerprint(a) != config_fingerprint(_config(x=2, y={"a": 1, "b": 2}))


def test_the_checkpoint_points_at_the_next_week_across_iso_week_53():
    assert has_iso_week_53(2020) and not has_iso_week_53(2021)

    last_of_2020 = Checkpoint(1, 2020, 53, "x")
    first_of_2021 = Checkpoint(1, 2021, 1, "x")
    first_of_2020 = Checkpoint(1, 2020, 1, "x")

    assert last_of_2020.last_simulated_week == (2020, 52)
    assert first_of_2021.last_simulated_week == (2020, 53)  # 2021 starts after a week 53
    assert first_of_2020.last_simulated_week == (2019, 52)


def test_run_weeks_walks_through_week_53_and_leaves_the_pointer_on_the_next_week(monkeypatch):
    simulated = []
    monkeypatch.setattr(
        pipeline, "simulate_week",
        lambda state, config, schema, year, week, *args, **kwargs: simulated.append((year, week)) or state,
    )
    config = type("Config", (), {"start_year_simulation": 2020})()
    params = pipeline.SimulationParameters(
        baseline_headcount=1, initial_headcount=1, max_capacity=1, annual_growth_rate=0.1,
        weeks_before_peak_growth=1, promotion_rate=0, transfer_rate=0, burn_in_years=0,
        burn_in_start_date=dt.datetime(2020, 1, 1), visible_start_date=dt.datetime(2020, 1, 1),
    )
    checkpoint = Checkpoint(1, 2020, 52, "x")

    pipeline.run_weeks({}, checkpoint, config, {}, params, seed=1,
                       today=dt.datetime.fromisocalendar(2021, 2, 1))

    assert simulated == [(2020, 52), (2020, 53), (2021, 1), (2021, 2)]
    assert (checkpoint.next_year, checkpoint.next_week) == (2021, 3)


def test_run_weeks_simulates_nothing_when_the_next_week_is_still_in_the_future(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "simulate_week", lambda *a, **k: calls.append(1))
    config = type("Config", (), {"start_year_simulation": 2024})()
    params = pipeline.SimulationParameters(
        1, 1, 1, 0.1, 1, 0, 0, 0, dt.datetime(2024, 1, 1), dt.datetime(2024, 1, 1),
    )
    checkpoint = Checkpoint(1, 2024, 10, "x")

    pipeline.run_weeks({}, checkpoint, config, {}, params, 1, dt.datetime.fromisocalendar(2024, 9, 1))

    assert calls == []
    assert (checkpoint.next_year, checkpoint.next_week) == (2024, 10)


def test_every_non_table_state_key_used_in_the_source_is_classified():
    """A new `state["_something"]` in the code must be added to the register."""
    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'state(?:\.get|\.setdefault|\.pop)?[\(\[]\s*"(_[a-z_]+)"')
    used = set()
    for folder in ("simulation", "infrastructure", "application", "generator"):
        for path in (root / folder).rglob("*.py"):
            if "obsolete" in path.parts:
                continue
            used.update(pattern.findall(path.read_text(encoding="utf-8")))
    used.discard("_data")

    assert used <= set(STATE_KEY_REGISTER), sorted(used - set(STATE_KEY_REGISTER))
