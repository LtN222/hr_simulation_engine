"""LF-01: Ploegentoeslag, derived in one place from Salaris and Shift_Key."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.config_loader import ConfigLoader
from src.infrastructure.config_validation import validate_role_configuration
from src.infrastructure.shift_allowance import derive_ploegentoeslag, shift_allowance
from src.infrastructure.state.table_changes import compute_changes, row_digests
from src.infrastructure.workforce_snapshot import build_workforce_snapshots
from src.tests.test_snapshot_history import _snapshot_state

D = pd.Timestamp
SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "config" / "schemas"
                     / "hr_maakindustrie_schema.json").read_text(encoding="utf-8"))

DIM_SHIFT = pd.DataFrame({
    "Shift_Key": [0, 1, 2, 3],
    "Ploegendienst_Naam": ["Niet van toepassing", "Dag", "2-ploeg", "3-ploeg"],
})


def _config(percentages=None, **extra):
    percentages = {"Niet van toepassing": 0.0, "Dag": 0.0, "2-ploeg": 0.12, "3-ploeg": 0.20} \
        if percentages is None else percentages
    return type("Config", (), {"shift_allowance": {"percentages": percentages}, **extra})()


def _state(rows=None):
    state = {"dim_shift": DIM_SHIFT.copy()}
    if rows is not None:
        state["fact_employment"] = pd.DataFrame(rows)
    return state


# ---------------------------------------------------------------------------
# the helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shift_key,expected", [(0, 0), (1, 0), (2, 4800), (3, 8000)])
def test_the_allowance_is_a_percentage_of_the_base_salary_per_shift_type(shift_key, expected):
    assert shift_allowance(40000, shift_key, _state(), _config()) == expected


def test_the_allowance_is_rounded_to_whole_euros():
    assert shift_allowance(33674, 2, _state(), _config()) == 4041        # 4040.88
    assert shift_allowance(33674, 3, _state(), _config()) == 6735        # 6734.8


@pytest.mark.parametrize("salary,shift_key", [
    (None, 3), (float("nan"), 3), ("onbekend", 3),     # missing salary
    (40000, None), (40000, float("nan")), (40000, 99), # missing or unknown shift
])
def test_a_missing_shift_or_salary_gives_zero(salary, shift_key):
    assert shift_allowance(salary, shift_key, _state(), _config()) == 0


def test_a_shift_without_a_configured_percentage_or_without_config_gives_zero():
    assert shift_allowance(40000, 3, _state(), _config(percentages={"2-ploeg": 0.12})) == 0
    assert shift_allowance(40000, 3, _state(), type("Config", (), {})()) == 0


# ---------------------------------------------------------------------------
# derived for every employment row
# ---------------------------------------------------------------------------

def _employment_rows():
    return [
        {"Employment_Key": 1, "Employee_Key": 1, "Salaris": 40000, "Shift_Key": 3, "Dienstverband_status": "Actief"},
        {"Employment_Key": 2, "Employee_Key": 2, "Salaris": 33674, "Shift_Key": 2, "Dienstverband_status": "Actief"},
        {"Employment_Key": 3, "Employee_Key": 3, "Salaris": 50000, "Shift_Key": 0, "Dienstverband_status": "Actief"},
        {"Employment_Key": 4, "Employee_Key": 4, "Salaris": 45000, "Shift_Key": 1, "Dienstverband_status": "Inactief"},
        {"Employment_Key": 5, "Employee_Key": 1, "Salaris": 40000, "Shift_Key": 3, "Dienstverband_status": "Uit dienst"},
        {"Employment_Key": 6, "Employee_Key": 5, "Salaris": None, "Shift_Key": 3, "Dienstverband_status": "Actief"},
        {"Employment_Key": 7, "Employee_Key": 6, "Salaris": 40000, "Shift_Key": None, "Dienstverband_status": "Actief"},
    ]


def test_every_employment_row_gets_the_value_the_helper_gives_and_salaris_is_untouched():
    state = _state(_employment_rows())
    salaries_before = state["fact_employment"]["Salaris"].copy()

    derive_ploegentoeslag(state, _config())

    employment = state["fact_employment"]
    assert employment["Ploegentoeslag"].tolist() == [8000, 4041, 0, 0, 8000, 0, 0]
    for _, row in employment.iterrows():
        assert row["Ploegentoeslag"] == shift_allowance(row["Salaris"], row["Shift_Key"], state, _config())
    assert employment["Ploegentoeslag"].dtype.kind == "i"
    pd.testing.assert_series_equal(employment["Salaris"], salaries_before)


def test_deriving_is_idempotent_and_ignores_a_stale_column():
    state = _state(_employment_rows())
    state["fact_employment"]["Ploegentoeslag"] = 123456                    # e.g. an older percentage

    derive_ploegentoeslag(state, _config())
    first = state["fact_employment"]["Ploegentoeslag"].tolist()
    derive_ploegentoeslag(state, _config())

    assert state["fact_employment"]["Ploegentoeslag"].tolist() == first == [8000, 4041, 0, 0, 8000, 0, 0]


def test_an_empty_or_missing_employment_table_is_fine():
    assert derive_ploegentoeslag(_state(), _config()) is not None
    state = _state()
    state["fact_employment"] = pd.DataFrame(columns=["Salaris", "Shift_Key"])
    derive_ploegentoeslag(state, _config())
    assert state["fact_employment"].empty


# ---------------------------------------------------------------------------
# the snapshot copies it; base pay and benchmarks do not change
# ---------------------------------------------------------------------------

def _snapshots_for(config, shift_key=3):
    state, _ = _snapshot_state(config)
    state["dim_shift"] = DIM_SHIFT.copy()
    state["fact_employment"]["Shift_Key"] = shift_key
    config.shift_allowance = config.shift_allowance if hasattr(config, "shift_allowance") else {}
    derive_ploegentoeslag(state, config)
    snapshots = build_workforce_snapshots(
        state, schema=None, config=config, start_date=D("2024-01-31"), end_date=D("2024-03-31"),
    )["fact_workforce_snapshot"]
    return state["fact_employment"], snapshots


def test_the_snapshot_equals_its_employment_rows_value():
    employment, snapshots = _snapshots_for(ConfigLoader().load())

    assert set(snapshots["Ploegentoeslag"]) == {int(employment["Ploegentoeslag"].iloc[0])} == {8400}  # 42,000 * 20%
    assert (snapshots["Salaris"] == employment["Salaris"].iloc[0]).all()


def test_salaris_the_benchmark_and_the_compa_ratio_do_not_depend_on_the_allowance():
    with_allowance = ConfigLoader().load()
    without = copy.deepcopy(ConfigLoader().load())
    without.shift_allowance = {}

    _, on = _snapshots_for(with_allowance)
    _, off = _snapshots_for(without)

    assert (off["Ploegentoeslag"] == 0).all() and (on["Ploegentoeslag"] > 0).all()
    pd.testing.assert_frame_equal(
        on.drop(columns=["Ploegentoeslag"]).reset_index(drop=True),
        off.drop(columns=["Ploegentoeslag"]).reset_index(drop=True),
    )
    for column in ("Salaris", "Benchmark_Salaris", "Benchmark_Verschil", "Benchmark_Status", "SalaryBand_Key"):
        assert column in on.columns


def test_the_floor_and_the_salary_review_never_see_the_allowance():
    import inspect

    from src.infrastructure import salary_policy

    assert "Ploegentoeslag" not in inspect.getsource(salary_policy)
    assert "shift_allowance" not in inspect.getsource(salary_policy)


# ---------------------------------------------------------------------------
# a recomputed value is not a change
# ---------------------------------------------------------------------------

def test_a_load_post_process_compare_round_trip_reports_no_changed_rows():
    definition = SCHEMA["fact_employment"]
    state = _state(_employment_rows())
    derive_ploegentoeslag(state, _config())
    written = state["fact_employment"]

    # what an INT column with NULLs looks like after a SQL read, then recomputed
    loaded = written.copy()
    loaded["Ploegentoeslag"] = loaded["Ploegentoeslag"].astype(float)
    loaded["Salaris"] = pd.to_numeric(loaded["Salaris"], errors="coerce")
    baseline = row_digests(loaded, definition["types"], definition["primary_key"])

    reloaded = _state(loaded.drop(columns=["Ploegentoeslag"]).to_dict("records"))
    derive_ploegentoeslag(reloaded, _config())
    changes = compute_changes("fact_employment", definition, reloaded["fact_employment"], baseline)

    assert (len(changes.added), len(changes.updated)) == (0, 0)
    assert changes.unchanged == len(written)


def test_a_changed_percentage_does_show_up_as_changed_rows():
    definition = SCHEMA["fact_employment"]
    state = _state(_employment_rows())
    derive_ploegentoeslag(state, _config())
    baseline = row_digests(state["fact_employment"], definition["types"], definition["primary_key"])

    changed = _state(_employment_rows())
    derive_ploegentoeslag(changed, _config({"Niet van toepassing": 0.0, "Dag": 0.0, "2-ploeg": 0.15, "3-ploeg": 0.20}))
    changes = compute_changes("fact_employment", definition, changed["fact_employment"], baseline)

    assert changes.updated["Employment_Key"].tolist() == [2]


def test_the_schema_has_the_column_on_both_tables_as_an_upsert():
    for table in ("fact_employment", "fact_workforce_snapshot"):
        assert SCHEMA[table]["types"]["Ploegentoeslag"] == "INT"
        assert SCHEMA[table]["write_mode"] == "upsert"


# ---------------------------------------------------------------------------
# config validation
# ---------------------------------------------------------------------------

def _validation_config(percentages):
    return type("Config", (), {
        "structure": {},
        "dim_shift": [{"Ploegendienst_Naam": name} for name in ("Niet van toepassing", "Dag", "2-ploeg", "3-ploeg")],
        "shift_allowance": {"percentages": percentages},
    })()


GOOD = {"Niet van toepassing": 0.0, "Dag": 0.0, "2-ploeg": 0.12, "3-ploeg": 0.20}


def test_the_real_config_passes_the_shift_allowance_rule():
    config = ConfigLoader().load()

    assert config.shift_allowance["percentages"] == GOOD
    assert validate_role_configuration(config) == []


def test_the_validation_accepts_a_complete_in_range_setup():
    assert validate_role_configuration(_validation_config(GOOD)) == []


def test_the_validation_flags_a_missing_shift_an_unknown_key_and_out_of_range_values():
    problems = validate_role_configuration(_validation_config({
        "Niet van toepassing": 0.0, "Dag": 0.0, "3-ploeg": 0.7, "4-ploeg": 0.1, "2-ploeg": -0.01,
    }))

    assert any("['3-ploeg'] = 0.7 is outside" in p for p in problems)
    assert any("['2-ploeg'] = -0.01 is outside" in p for p in problems)
    assert any("'4-ploeg' is not a dim_shift" in p for p in problems)

    missing = validate_role_configuration(_validation_config({"Niet van toepassing": 0.0}))
    assert any("no percentage for shift 'Dag'" in p for p in missing)
    assert any("no percentage for shift '3-ploeg'" in p for p in missing)
