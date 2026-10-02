"""Write modes per table, the atomic SQL write (with a stub connection), stores,
deleted rows, the open-month snapshot window and the deterministic benchmark key."""
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from src.application import pipeline
from src.application.run_options import resolve_run_options
from src.infrastructure.database import write_to_sql
from src.infrastructure.database.simulation_lock import SimulationLockLostError
from src.infrastructure.state.checkpoint import Checkpoint
from src.infrastructure.state.store import InMemoryStore, SqlStore
from src.infrastructure.state.table_changes import (
    AppendTableChangedError,
    RowsLostError,
    WRITE_MODES,
    build_baseline,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "schemas" / "hr_maakindustrie_schema.json"

APPEND_TABLES = {
    "fact_performance_review", "fact_safety_incident",
    "fact_employee_qualification", "fact_salary_benchmark",
}


def _real_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_every_schema_table_declares_a_valid_write_mode_and_an_int_primary_key():
    schema = _real_schema()

    for table, definition in schema.items():
        assert definition.get("write_mode") in WRITE_MODES, table
        assert definition["types"][definition["primary_key"]] == "INT", table


def test_the_write_modes_follow_the_design():
    schema = _real_schema()

    for table, definition in schema.items():
        expected = "append" if table in APPEND_TABLES else "upsert"
        assert definition["write_mode"] == expected, table
    # every dimension is an upsert, so configuration changes reach SQL
    assert all(d["write_mode"] == "upsert" for t, d in schema.items() if t.startswith("dim_"))


def test_the_only_foreign_keys_between_facts_are_the_accepted_lineage_exceptions():
    """AR-26: facts relate through shared dimensions. These references are the
    documented exceptions (README data model, CLAUDE.md); a new one needs a decision."""
    schema = _real_schema()
    found = {
        (table, column, target)
        for table, definition in schema.items() if table.startswith("fact_")
        for column, target, _ in definition.get("foreign_keys", [])
        if target.startswith("fact_")
    }

    assert found == {
        ("fact_workforce_snapshot", "Employment_Key", "fact_employment"),
        ("fact_recruitment", "Vacancy_Key", "fact_vacancy"),
        ("fact_employment", "Previous_Employment_Key", "fact_employment"),    # self-reference
    }


def test_only_the_snapshot_table_may_lose_rows():
    deleting = {t for t, d in _real_schema().items() if d.get("delete_missing")}

    assert deleting == {"fact_workforce_snapshot"}


# ---------------------------------------------------------------------------
# in-memory store honours the write modes
# ---------------------------------------------------------------------------

def _schema(**table_extra):
    def table(name, mode, **extra):
        return {
            "df": name, "primary_key": "Key", "write_mode": mode,
            "types": {"Key": "INT", "Waarde": "NVARCHAR(20)", "Score": "DECIMAL(3,2)"}, **extra,
        }
    return {
        "dim_a": table("dim_a", "upsert"),
        "fact_b": table("fact_b", "append"),
        "fact_c": table("fact_c", "upsert", **table_extra),
    }


def _state(a, b, c):
    return {
        "dim_a": pd.DataFrame(a, columns=["Key", "Waarde", "Score"]),
        "fact_b": pd.DataFrame(b, columns=["Key", "Waarde", "Score"]),
        "fact_c": pd.DataFrame(c, columns=["Key", "Waarde", "Score"]),
    }


def _checkpoint(week=1):
    return Checkpoint(seed=1, next_year=2024, next_week=week, config_fingerprint="x")


def _loaded_store(schema, **kwargs):
    store = InMemoryStore(schema, **kwargs)
    store.write(_state([[1, "a", 1.0], [2, "b", 2.0]], [[1, "x", 1.0]], [[1, "p", 1.0], [2, "q", 2.0]]),
                _checkpoint(), reset=True)
    state, _ = store.load(schema)
    return store, state


def test_a_full_write_replaces_everything():
    schema = _schema()
    store, _ = _loaded_store(schema)

    store.write(_state([[9, "z", 9.0]], [], []), _checkpoint(), reset=True)

    assert store.tables["dim_a"]["Key"].tolist() == [9]
    assert store.tables["fact_b"].empty


def test_an_incremental_write_inserts_new_keys_and_updates_changed_upsert_rows_only():
    schema = _schema()
    store, state = _loaded_store(schema)
    state["dim_a"].loc[state["dim_a"]["Key"] == 2, "Waarde"] = "B!"
    state["dim_a"] = pd.concat([state["dim_a"], pd.DataFrame({"Key": [3], "Waarde": ["c"], "Score": [3.0]})])
    state["fact_b"] = pd.concat([state["fact_b"], pd.DataFrame({"Key": [2], "Waarde": ["y"], "Score": [2.0]})])

    summary = store.write(state, _checkpoint(2), reset=False)

    assert store.tables["dim_a"].set_index("Key")["Waarde"].to_dict() == {1: "a", 2: "B!", 3: "c"}
    assert store.tables["fact_b"]["Key"].tolist() == [1, 2]
    assert summary["dim_a"] == {"added": 1, "updated": 1, "unchanged": 1, "deleted": 0, "total": 3}
    assert summary["fact_b"]["added"] == 1 and summary["fact_b"]["updated"] == 0
    assert store.tables["dim_a"]["Key"].tolist() == [1, 2, 3]           # stored in key order


def test_an_append_table_never_changes_existing_rows_and_a_strict_store_objects():
    schema = _schema()
    store, state = _loaded_store(schema)
    state["fact_b"].loc[0, "Waarde"] = "CHANGED"

    with pytest.raises(AppendTableChangedError, match="fact_b"):
        store.write(state, _checkpoint(2), reset=False)

    lenient, state = _loaded_store(schema, strict=False)
    state["fact_b"].loc[0, "Waarde"] = "CHANGED"
    lenient.write(state, _checkpoint(2), reset=False)
    assert lenient.tables["fact_b"].loc[0, "Waarde"] == "x"             # the stored row was not touched


def test_a_loaded_row_that_disappears_raises_unless_the_table_declares_delete_missing():
    schema = _schema()
    store, state = _loaded_store(schema)
    state["fact_c"] = state["fact_c"].iloc[:1]

    with pytest.raises(RowsLostError, match="fact_c"):
        store.write(state, _checkpoint(2), reset=False)

    schema = _schema(delete_missing=True)
    store, state = _loaded_store(schema)
    state["fact_c"] = state["fact_c"].iloc[:1]
    summary = store.write(state, _checkpoint(2), reset=False)
    assert store.tables["fact_c"]["Key"].tolist() == [1]
    assert summary["fact_c"]["deleted"] == 1


def test_an_unchanged_state_writes_nothing_even_when_values_were_rescored_within_rounding():
    schema = _schema()
    store, state = _loaded_store(schema)
    state["dim_a"]["Score"] = state["dim_a"]["Score"] + 0.0004          # below DECIMAL(3,2) resolution

    summary = store.write(state, _checkpoint(2), reset=False)

    assert all(c["added"] == 0 and c["updated"] == 0 and c["deleted"] == 0 for c in summary.values())


def test_an_incremental_write_needs_a_preceding_load():
    schema = _schema()
    store, state = _loaded_store(schema)
    store.write(state, _checkpoint(2), reset=False)        # consumes the baseline

    with pytest.raises(RuntimeError, match="preceding load"):
        store.write(state, _checkpoint(3), reset=False)


# ---------------------------------------------------------------------------
# the atomic SQL write, with a stub engine
# ---------------------------------------------------------------------------

class _Transaction:
    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


class _Connection:
    def __init__(self, events):
        self.events = events

    def begin(self):
        self.events.append("begin")
        return _Transaction(self.events)

    def close(self):
        self.events.append("close")


class _Engine:
    def __init__(self, events):
        self.events = events

    def connect(self):
        self.events.append("connect")
        return _Connection(self.events)


@pytest.fixture
def recorded(monkeypatch):
    """A write_dataset environment that records every step instead of touching SQL."""
    events = []
    monkeypatch.setattr(write_to_sql, "ensure_schema", lambda engine, schema: events.append("ensure_schema"))
    monkeypatch.setattr(write_to_sql, "reset_tables", lambda conn, order: events.append("reset"))
    monkeypatch.setattr(write_to_sql, "insert_rows",
                        lambda conn, table, cfg, frame: events.append(f"insert:{table}:{len(frame)}") if len(frame) else None)
    monkeypatch.setattr(write_to_sql, "update_rows",
                        lambda conn, table, cfg, frame: events.append(f"update:{table}:{len(frame)}") if len(frame) else None)
    monkeypatch.setattr(write_to_sql, "delete_rows",
                        lambda conn, table, cfg, keys: events.append(f"delete:{table}:{len(keys)}") if keys else None)
    return events


def _checkpoint_writer(events):
    return lambda conn, checkpoint: events.append("checkpoint")


def test_a_successful_incremental_write_runs_schema_first_and_the_checkpoint_last(recorded):
    events = recorded
    schema = _schema()
    store, state = _loaded_store(schema)
    state["dim_a"].loc[0, "Waarde"] = "new"
    state["fact_b"] = pd.concat([state["fact_b"], pd.DataFrame({"Key": [2], "Waarde": ["y"], "Score": [2.0]})])

    write_to_sql.write_dataset(
        _Engine(events), state, schema, reset=False, baseline=build_baseline(_loaded_store(schema)[1], schema),
        checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events),
    )

    assert events[0] == "ensure_schema"                    # DDL before the data transaction
    assert events.index("ensure_schema") < events.index("connect") < events.index("begin")
    assert events[-3:] == ["checkpoint", "commit", "close"]  # checkpoint is the last statement
    assert "update:dim_a:1" in events and "insert:fact_b:1" in events
    assert "rollback" not in events


def test_a_full_write_resets_and_inserts_everything_in_one_transaction(recorded):
    events = recorded
    schema = _schema()
    _, state = _loaded_store(schema)

    summary = write_to_sql.write_dataset(
        _Engine(events), state, schema, reset=True,
        checkpoint=_checkpoint(), write_checkpoint=_checkpoint_writer(events),
    )

    inside = events[events.index("begin"):]
    assert inside[1] == "reset"
    assert [e for e in inside if e.startswith("insert:")]
    assert inside[-3:] == ["checkpoint", "commit", "close"]
    assert summary["dim_a"]["added"] == 2


def test_a_failure_midway_rolls_back_and_never_writes_the_checkpoint(recorded, monkeypatch, caplog):
    events = recorded
    schema = _schema()
    _, state = _loaded_store(schema)

    def failing_insert(conn, table, cfg, frame):
        events.append(f"insert:{table}")
        if table == "fact_b":
            raise RuntimeError("the transaction log is full")

    monkeypatch.setattr(write_to_sql, "insert_rows", failing_insert)

    with pytest.raises(RuntimeError, match="transaction log is full"):
        write_to_sql.write_dataset(
            _Engine(events), state, schema, reset=True,
            checkpoint=_checkpoint(), write_checkpoint=_checkpoint_writer(events),
        )

    assert "checkpoint" not in events
    assert "commit" not in events
    assert events[-2:] == ["rollback", "close"]
    assert "rolled back" in caplog.text and "previous data and the previous checkpoint" in caplog.text


def test_a_dry_run_executes_everything_including_the_checkpoint_and_rolls_back(recorded):
    events = recorded
    schema = _schema()
    store, state = _loaded_store(schema)
    state["dim_a"].loc[0, "Waarde"] = "new"

    summary = write_to_sql.write_dataset(
        _Engine(events), state, schema, reset=False,
        baseline=build_baseline(_loaded_store(schema)[1], schema),
        checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events), dry_run=True,
    )

    assert events[-3:] == ["checkpoint", "rollback", "close"]
    assert "commit" not in events
    assert summary["dim_a"]["updated"] == 1


def test_a_dry_run_is_rejected_for_a_full_write_and_an_incremental_write_needs_a_baseline(recorded):
    schema = _schema()
    _, state = _loaded_store(schema)

    with pytest.raises(ValueError, match="dry run"):
        write_to_sql.write_dataset(_Engine(recorded), state, schema, reset=True, dry_run=True)
    with pytest.raises(ValueError, match="baseline"):
        write_to_sql.write_dataset(_Engine(recorded), state, schema, reset=False)


def test_rows_lost_are_detected_before_anything_is_written(recorded):
    events = recorded
    schema = _schema()
    _, state = _loaded_store(schema)
    baseline = build_baseline(state, schema)
    state["fact_c"] = state["fact_c"].iloc[:1]

    with pytest.raises(RowsLostError):
        write_to_sql.write_dataset(_Engine(events), state, schema, reset=False, baseline=baseline)

    assert "begin" not in events                             # no transaction was even started


def test_a_lost_simulation_lock_fails_before_schema_evolution_or_any_write(recorded):
    events = recorded
    schema = _schema()
    store, state = _loaded_store(schema)

    def lock_lost():
        events.append("verify_lock")
        raise SimulationLockLostError("no longer held")

    with pytest.raises(SimulationLockLostError):
        write_to_sql.write_dataset(
            _Engine(events), state, schema, reset=False,
            baseline=build_baseline(_loaded_store(schema)[1], schema),
            checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events),
            verify_lock=lock_lost,
        )

    assert events == ["verify_lock"]         # no ensure_schema, connect, begin, insert or checkpoint


def test_the_lock_is_verified_again_right_before_the_write_transaction_starts(recorded):
    events = recorded
    schema = _schema()
    store, state = _loaded_store(schema)

    write_to_sql.write_dataset(
        _Engine(events), state, schema, reset=False,
        baseline=build_baseline(_loaded_store(schema)[1], schema),
        checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events),
        verify_lock=lambda: events.append("verify_lock"),
    )

    assert [e for e in events if e in ("verify_lock", "ensure_schema", "connect", "begin")] == [
        "verify_lock", "ensure_schema", "verify_lock", "connect", "begin"]


def test_the_sql_store_verifies_its_lock_before_writing(recorded):
    events = recorded
    schema = _schema()
    _, state = _loaded_store(schema)

    class LostLock:
        def verify(self):
            raise SimulationLockLostError("no longer held")

    store = SqlStore(_Engine(events), schema, lock=LostLock())
    store.baseline = build_baseline(state, schema)

    with pytest.raises(SimulationLockLostError):
        store.write(state, _checkpoint(2), reset=False)

    assert events == []                      # not even a connection was opened


def test_reads_fail_loudly_except_for_a_missing_table(monkeypatch):
    from src.infrastructure.state import load_state

    schema = {"dim_a": {"df": "dim_a", "primary_key": "Key", "types": {"Key": "INT"}}}
    monkeypatch.setattr(load_state, "_table_exists", lambda engine, table: False)
    assert load_state.load_current_state(object(), schema)["dim_a"].empty

    monkeypatch.setattr(load_state, "_table_exists", lambda engine, table: True)

    def broken_read(query, engine):
        raise ConnectionError("transient read error")

    monkeypatch.setattr(load_state.pd, "read_sql", broken_read)
    with pytest.raises(ConnectionError, match="transient"):
        load_state.load_current_state(object(), schema)


def test_the_load_reads_rows_in_primary_key_order(monkeypatch):
    from src.infrastructure.state import load_state

    queries = []
    monkeypatch.setattr(load_state, "_table_exists", lambda engine, table: True)
    monkeypatch.setattr(load_state.pd, "read_sql", lambda query, engine: queries.append(query) or pd.DataFrame())

    load_state.load_current_state(object(), {"dim_a": {"df": "dim_a", "primary_key": "Key", "types": {"Key": "INT"}}})

    assert queries == ["SELECT * FROM dim_a ORDER BY [Key]"]


# ---------------------------------------------------------------------------
# open-month snapshot window and deterministic keys
# ---------------------------------------------------------------------------

def test_the_snapshot_window_starts_on_the_first_of_the_month_of_the_first_simulated_week():
    # ISO 2024-W06 starts on Monday 5 February; 2020-W01 starts on Monday 30 December 2019
    assert pipeline.snapshot_window_start(Checkpoint(1, 2024, 6, "x")) == dt.datetime(2024, 2, 1)
    assert pipeline.snapshot_window_start(Checkpoint(1, 2020, 1, "x")) == dt.datetime(2019, 12, 1)


def test_the_window_merge_keeps_earlier_months_and_replaces_the_rest():
    loaded = pd.DataFrame({"Snapshot_Date": pd.to_datetime(["2024-01-31", "2024-02-29"]), "v": [1, 2]})
    rebuilt = pd.DataFrame({"Snapshot_Date": pd.to_datetime(["2024-02-29", "2024-03-31"]), "v": [20, 3]})

    merged = pipeline._merge_window(loaded, rebuilt, "Snapshot_Date", dt.datetime(2024, 2, 1))

    assert merged["v"].tolist() == [1, 20, 3]
    empty = pipeline._merge_window(loaded, pd.DataFrame(), "Snapshot_Date", dt.datetime(2024, 3, 1))
    assert empty["v"].tolist() == [1, 2]                      # nothing rebuilt: earlier rows stay


def test_the_benchmark_key_is_deterministic_and_fits_an_int():
    from src.infrastructure.salary_benchmark import benchmark_key

    assert benchmark_key(pd.Timestamp("2024-03-31"), 7, 4) == 202403 * 10_000 + 704
    assert benchmark_key(pd.Timestamp("2024-03-31"), 7, 4) == benchmark_key(dt.datetime(2024, 3, 31), 7.0, 4.0)
    assert benchmark_key(pd.Timestamp("2099-12-31"), 99, 99) < 2_147_483_647
    with pytest.raises(ValueError, match="Role_Key"):
        benchmark_key(pd.Timestamp("2024-03-31"), 100, 1)
    with pytest.raises(ValueError, match="Salaris_Trede"):
        benchmark_key(pd.Timestamp("2024-03-31"), 1, 100)


def test_adding_a_role_or_step_does_not_relabel_existing_benchmark_keys():
    from src.infrastructure.salary_benchmark import benchmark_key

    before = {(role, step): benchmark_key(pd.Timestamp("2024-01-31"), role, step)
              for role in (1, 2, 3) for step in (1, 2)}
    after = {(role, step): benchmark_key(pd.Timestamp("2024-01-31"), role, step)
             for role in (1, 2, 3, 4) for step in (1, 2, 3)}

    assert all(after[key] == value for key, value in before.items())
    assert len(set(after.values())) == len(after)


def test_the_workforce_snapshot_key_is_deterministic_per_employee_and_month():
    from src.infrastructure.workforce_snapshot import _snapshot_key

    assert _snapshot_key(pd.Timestamp("2024-03-31"), 42) == 202403 * 10_000 + 42
    assert _snapshot_key(dt.datetime(2024, 3, 31), 42) == _snapshot_key(pd.Timestamp("2024-03-31"), 42)


def test_config_validation_flags_a_role_key_or_step_count_that_breaks_the_benchmark_key():
    from src.infrastructure.config_validation import validate_role_configuration

    config = type("Config", (), {
        "structure": {"A": {"Rol": {"role_key": 100, "department_key": 1}}},
        "salary_benchmark": {"market_median_by_role": {}},
        "dim_salary_scale": [{"Salarisschaal_Code": "X", "Minimum_Salaris": 1, "Maximum_Salaris": 2,
                              "Aantal_Treden": 100}],
    })()

    problems = validate_role_configuration(config)

    assert any("role_key 100 exceeds" in p for p in problems)
    assert any("Aantal_Treden 100 exceeds" in p for p in problems)


# ---------------------------------------------------------------------------
# run options: dry run and as-of date
# ---------------------------------------------------------------------------

NOW = dt.datetime(2026, 10, 15, 9, 30)


def test_without_options_today_is_the_current_moment():
    assert resolve_run_options("incremental", False, None, NOW) == ("incremental", False, NOW)


def test_an_as_of_date_replaces_today_for_both_modes():
    for mode in ("full", "incremental"):
        assert resolve_run_options(mode, False, "2026-10-01", NOW)[2] == dt.datetime(2026, 10, 1)


def test_an_as_of_date_in_the_future_or_malformed_is_rejected():
    with pytest.raises(ValueError, match="future"):
        resolve_run_options("incremental", False, "2026-10-16", NOW)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        resolve_run_options("incremental", False, "15-10-2026", NOW)
    assert resolve_run_options("incremental", False, "2026-10-15", NOW)[2] == dt.datetime(2026, 10, 15)


def test_a_dry_run_is_only_allowed_for_incremental_and_the_mode_is_validated():
    assert resolve_run_options("incremental", True, None, NOW)[1] is True
    with pytest.raises(ValueError, match="DRY_RUN"):
        resolve_run_options("full", True, None, NOW)
    with pytest.raises(ValueError, match="Unknown simulation mode"):
        resolve_run_options("weekly", False, None, NOW)


def test_the_runtime_settings_are_read_from_the_environment(monkeypatch):
    from config.runtime_config import load_runtime_config

    monkeypatch.delenv("HR_SIMULATION_DRY_RUN", raising=False)
    monkeypatch.delenv("HR_SIMULATION_AS_OF", raising=False)
    defaults = load_runtime_config()
    assert defaults["simulation_dry_run"] is False and defaults["simulation_as_of"] is None

    monkeypatch.setenv("HR_SIMULATION_DRY_RUN", "True")
    monkeypatch.setenv("HR_SIMULATION_AS_OF", "2026-09-30")
    configured = load_runtime_config()
    assert configured["simulation_dry_run"] is True and configured["simulation_as_of"] == "2026-09-30"


# ---------------------------------------------------------------------------
# review fixes: DECIMAL values, reset without ALTER TABLE, dry run, timer
# ---------------------------------------------------------------------------

def test_decimal_columns_are_sent_as_decimals_quantized_like_the_comparison():
    from decimal import Decimal

    from src.infrastructure.state.table_changes import normalize_column

    frame = pd.DataFrame({"Score": [6.805, 2.675, 1.005, None, 6.8123]})

    sent = write_to_sql._normalize_dataframe_for_sql(frame, {"Score": "DECIMAL(4,2)"})["Score"].tolist()

    # SQL Server would turn these floats into 6.80 / 2.67 / 1.00; the values sent are not floats
    assert sent == [Decimal("6.81"), Decimal("2.68"), Decimal("1.01"), None, Decimal("6.81")]
    assert all(value is None or isinstance(value, Decimal) for value in sent)
    assert sent == normalize_column(frame["Score"], "DECIMAL(4,2)").tolist()


def test_inserts_and_updates_send_the_quantized_decimals(monkeypatch):
    from decimal import Decimal

    cfg = {"primary_key": "Key", "types": {"Key": "INT", "Score": "DECIMAL(4,2)"}}
    frame = pd.DataFrame({"Key": [1, 2], "Score": [6.805, 2.675]})

    captured = {}
    monkeypatch.setattr(pd.DataFrame, "to_sql", lambda self, *a, **k: captured.update(insert=self["Score"].tolist()))

    class Conn:
        def execute(self, statement, params=None):
            captured["update"] = [row["Score"] for row in params]

    write_to_sql.insert_rows(Conn(), "t", cfg, frame)
    write_to_sql.update_rows(Conn(), "t", cfg, frame)

    assert captured["insert"] == captured["update"] == [Decimal("6.81"), Decimal("2.68")]


def test_a_write_load_round_trip_that_stores_decimals_exactly_reports_no_changes():
    from src.infrastructure.state.table_changes import compute_changes, row_digests

    definition = {"df": "t", "primary_key": "Key", "write_mode": "upsert",
                  "types": {"Key": "INT", "Score": "DECIMAL(4,2)"}}
    in_memory = pd.DataFrame({"Key": [1, 2, 3, 4], "Score": [6.805, 2.675, 1.005, 6.8123]})

    stored = write_to_sql._normalize_dataframe_for_sql(in_memory, definition["types"])   # what SQL keeps
    loaded = pd.DataFrame({"Key": stored["Key"], "Score": stored["Score"]})             # exact Decimals back
    baseline = row_digests(loaded, definition["types"], "Key")

    changes = compute_changes("t", definition, in_memory, baseline)

    assert (len(changes.added), len(changes.updated), changes.unchanged) == (0, 0, 4)


class _StatementRecorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))


def test_a_reset_contains_no_alter_table_and_deletes_children_before_parents():
    schema = _real_schema()
    order = write_to_sql.get_table_write_order(schema)
    conn = _StatementRecorder()

    write_to_sql.reset_tables(conn, order)

    assert not any("ALTER TABLE" in statement.upper() for statement in conn.statements)
    deleted = [statement.split("DELETE FROM")[1].strip() for statement in conn.statements]
    assert deleted == list(reversed(order))
    assert deleted.index("fact_employment") < deleted.index("dim_role")          # child before parent


def test_a_dry_run_never_evolves_the_schema_but_a_real_run_does(recorded):
    events = recorded
    schema = _schema()
    store, state = _loaded_store(schema)
    baseline = build_baseline(_loaded_store(schema)[1], schema)

    write_to_sql.write_dataset(_Engine(events), state, schema, reset=False, baseline=baseline,
                               checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events), dry_run=True)
    assert "ensure_schema" not in events

    events.clear()
    write_to_sql.write_dataset(_Engine(events), state, schema, reset=False, baseline=baseline,
                               checkpoint=_checkpoint(2), write_checkpoint=_checkpoint_writer(events))
    assert events[0] == "ensure_schema"


def _patched_function_app(monkeypatch, runtime):
    import function_app

    captured = {}
    monkeypatch.setattr(function_app, "load_runtime_config", lambda: dict(runtime))
    monkeypatch.setattr(function_app, "get_engine", lambda database: object())
    monkeypatch.setattr(function_app, "load_schema", lambda name: {})
    monkeypatch.setattr(function_app, "ConfigLoader", lambda: type("L", (), {
        "load": lambda self, sector=None: type("C", (), {"database": "db", "schema": "s"})()})())
    monkeypatch.setattr(function_app, "SqlStore", lambda engine, schema, dry_run=False, lock=None: captured.update(dry_run=dry_run))
    monkeypatch.setattr(function_app, "acquire_simulation_lock", lambda engine: __import__("contextlib").nullcontext())
    monkeypatch.setattr(function_app, "run_pipeline",
                        lambda mode, config, schema, seed, store, today: captured.update(today=today) or ({}, {}))
    return function_app, captured


RUNTIME = {"sector": "x", "simulation_seed": 1, "simulation_dry_run": True, "simulation_as_of": "2026-09-16"}


def test_the_http_path_honours_the_validation_settings_and_the_timer_path_ignores_them(monkeypatch):
    function_app, captured = _patched_function_app(monkeypatch, RUNTIME)

    function_app.run_hr_pipeline("incremental")
    assert captured["dry_run"] is True and captured["today"] == dt.datetime(2026, 9, 16)

    function_app.run_hr_pipeline("incremental", use_validation_settings=False)
    assert captured["dry_run"] is False
    assert captured["today"].date() == dt.date.today()          # the real date, not the as-of setting


def test_the_timer_warns_when_the_validation_settings_are_set_and_never_passes_them_on(monkeypatch, caplog):
    import logging

    function_app, _ = _patched_function_app(monkeypatch, RUNTIME)
    calls = []
    monkeypatch.setattr(function_app, "run_hr_pipeline",
                        lambda mode, use_validation_settings=True: calls.append((mode, use_validation_settings)) or ({}, {}))
    timer_function = function_app.weekly_hr_run._function.get_user_function()

    with caplog.at_level(logging.WARNING):
        timer_function(object())

    assert calls == [("incremental", False)]
    assert "ignored for the timer" in caplog.text and "Remove them from the app settings" in caplog.text

    caplog.clear()
    monkeypatch.setattr(function_app, "load_runtime_config",
                        lambda: {**RUNTIME, "simulation_dry_run": False, "simulation_as_of": None})
    with caplog.at_level(logging.WARNING):
        timer_function(object())
    assert "ignored for the timer" not in caplog.text
