"""Changed-row detection: normalization, baseline digests, write modes."""
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.infrastructure.state.table_changes import (
    AppendTableChangedError,
    RowsLostError,
    build_baseline,
    compute_changes,
    normalize_column,
    normalize_frame,
    plan_incremental,
    row_digests,
)

TYPES = {
    "Key": "INT",
    "Naam": "NVARCHAR(50)",
    "Score": "DECIMAL(3,2)",
    "Datum": "DATE",
    "Actief": "BIT",
    "Aantal": "INT",
}


def _definition(mode="upsert", **extra):
    return {"df": "t", "primary_key": "Key", "types": dict(TYPES), "write_mode": mode, **extra}


def _frame(**overrides):
    base = {
        "Key": [1, 2, 3],
        "Naam": ["a", "b", None],
        "Score": [6.81, 7.0, None],
        "Datum": [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29"), pd.NaT],
        "Actief": [True, False, None],
        "Aantal": [1, 2, None],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _baseline(frame, definition=None):
    definition = definition or _definition()
    return row_digests(frame, definition["types"], "Key")


def test_decimal_values_are_rounded_to_their_scale_half_up():
    column = pd.Series([6.8123, 6.805, 6.804, np.float64(2.675), Decimal("6.81"), None, np.nan])

    normalized = normalize_column(column, "DECIMAL(3,2)").tolist()

    assert normalized == [Decimal("6.81"), Decimal("6.81"), Decimal("6.80"), Decimal("2.68"),
                          Decimal("6.81"), None, None]


def test_ints_and_floats_compare_numerically_and_null_variants_are_equal():
    a = normalize_column(pd.Series([3, 4.0, np.nan, None]), "INT").tolist()

    assert a == [3, 4, None, None]
    assert normalize_column(pd.Series(["x", None, np.nan, pd.NA]), "NVARCHAR(10)").tolist() == [
        "x", None, None, None]
    assert normalize_column(pd.Series([True, 0, None]), "BIT").tolist() == [True, False, None]


def test_dates_are_compared_as_dates_whatever_their_representation():
    import datetime as dt

    column = pd.Series([pd.Timestamp("2024-01-31 13:45"), dt.date(2024, 2, 29),
                        "2024-03-31", np.datetime64("2024-04-30"), pd.NaT])

    assert normalize_column(column, "DATE").tolist() == [
        dt.date(2024, 1, 31), dt.date(2024, 2, 29), dt.date(2024, 3, 31), dt.date(2024, 4, 30), None]


def test_a_missing_schema_column_normalizes_to_null():
    frame = _frame().drop(columns=["Aantal"])

    assert normalize_frame(frame, TYPES)["Aantal"].tolist() == [None, None, None]


def test_identical_data_in_different_representations_has_identical_digests():
    sql_like = pd.DataFrame({
        "Key": [1.0, 2.0, 3.0],                       # read_sql of an INT column with NULLs
        "Naam": ["a", "b", None],
        "Score": [Decimal("6.81"), Decimal("7.00"), None],
        "Datum": [pd.Timestamp("2024-01-31").date(), pd.Timestamp("2024-02-29").date(), None],
        "Actief": [1, 0, None],
        "Aantal": [1.0, 2.0, np.nan],
    })

    assert _baseline(sql_like) == _baseline(_frame())


def test_a_rescored_value_within_rounding_is_unchanged_but_a_real_change_is_not():
    """sync_absence_satisfaction re-scores episodes in memory (6.8123); SQL holds 6.81."""
    loaded = _frame()
    rescored = _frame(Score=[6.8123, 6.9999999, None])   # 6.81 and 7.00 after rounding

    unchanged = compute_changes("t", _definition(), rescored, _baseline(loaded))
    assert (len(unchanged.added), len(unchanged.updated), unchanged.unchanged) == (0, 0, 3)

    really_changed = compute_changes("t", _definition(), _frame(Score=[6.84, 7.0, None]), _baseline(loaded))
    assert really_changed.updated["Key"].tolist() == [1]
    assert really_changed.unchanged == 2


def test_new_rows_are_added_changed_rows_updated_and_the_rest_unchanged():
    loaded = _frame()
    new = pd.concat([
        _frame(Naam=["a", "CHANGED", None]),
        pd.DataFrame({"Key": [4], "Naam": ["new"], "Score": [1.0], "Datum": [pd.Timestamp("2024-03-31")],
                      "Actief": [True], "Aantal": [9]}),
    ], ignore_index=True)

    changes = compute_changes("t", _definition(), new, _baseline(loaded))

    assert changes.added["Key"].tolist() == [4]
    assert changes.updated["Key"].tolist() == [2]
    assert changes.unchanged == 2
    assert changes.counts() == {"added": 1, "updated": 1, "unchanged": 2, "deleted": 0, "total": 4}


def test_an_append_table_only_adds_and_reports_changed_existing_rows():
    loaded = _frame()
    new = _frame(Naam=["a", "CHANGED", None])

    changes = compute_changes("t", _definition("append"), new, _baseline(loaded))

    assert len(changes.updated) == 0
    assert changes.existing_changed == 1


def test_a_loaded_row_missing_from_the_new_state_raises_unless_the_table_may_delete():
    loaded = _frame()
    shrunk = _frame().iloc[:2]

    with pytest.raises(RowsLostError, match="1 loaded rows are missing"):
        compute_changes("t", _definition(), shrunk, _baseline(loaded))

    changes = compute_changes("t", _definition(delete_missing=True), shrunk, _baseline(loaded))
    assert changes.deleted_keys == [3]


def test_the_write_mode_must_be_valid():
    with pytest.raises(ValueError, match="write_mode"):
        compute_changes("t", {**_definition(), "write_mode": "merge"}, _frame(), {})


def test_plan_follows_the_write_order_and_skips_missing_frames():
    schema = {"a": {**_definition(), "df": "a"}, "b": {**_definition("append"), "df": "b"}}
    tables = {"b": _frame()}

    plan = plan_incremental(tables, schema, build_baseline({"b": _frame()}, schema), ["a", "b"])

    assert [change.table for change in plan] == ["b"]
    assert plan[0].unchanged == 3


def test_an_append_violation_error_type_exists_for_strict_stores():
    assert issubclass(AppendTableChangedError, RuntimeError)
