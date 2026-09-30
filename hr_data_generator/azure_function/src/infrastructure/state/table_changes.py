"""Which rows of which table an incremental run must write, and how.

Every schema table declares a `write_mode`:

- ``upsert``: new primary keys are inserted and rows whose values changed are
  updated (dimensions, mutable facts, the rebuilt snapshot window);
- ``append``: only new primary keys are inserted; an existing row is never
  changed (immutable event facts).

The incremental load keeps a *baseline* of every table as it was loaded: one
digest per primary key over the normalized row. At write time the new state is
normalized the same way and compared, so only rows that are new or really
changed reach SQL - an incremental week stays far below the Function timeout.

Normalization makes both sides comparable whatever their origin (SQL read, pandas
frame): values are converted by the schema type, DECIMAL(p,s) is rounded to its
scale (a re-scored 6.8123 equals the stored 6.81), NaN/None/NaT are equal, dates
are compared as dates and ints equal floats with the same value.
"""

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

UPSERT = "upsert"
APPEND = "append"
WRITE_MODES = (UPSERT, APPEND)


class RowsLostError(RuntimeError):
    """Rows that were loaded from the store are missing from the new state."""


class AppendTableChangedError(RuntimeError):
    """An append-only table has existing rows whose values changed."""


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_DECIMAL_TYPE = "DECIMAL"


def _decimal_scale(sql_type):
    return int(sql_type.split(",")[1].replace(")", "").strip())


def _is_missing(value):
    if value is None or value is pd.NaT:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _normalize_int(column):
    numeric = pd.to_numeric(column, errors="coerce")
    ints = numeric.fillna(0).to_numpy(dtype="float64").astype("int64")  # truncates like int()
    return pd.Series(np.where(numeric.notna(), ints, None), index=column.index, dtype=object)


def quantize_decimal(value, scale):
    """`value` as a Decimal with exactly `scale` decimals (half up), or None.

    The single definition of DECIMAL(p,s) rounding: the change comparison and
    the values sent to SQL both use it. SQL Server would round a *float* sent
    for a DECIMAL column differently (6.805 -> 6.80, 2.675 -> 2.67), so writes
    send these Decimals instead, and what is stored equals what is compared.
    """
    if _is_missing(value):
        return None
    # repr(float) is the shortest round-trip form (6.805, not 6.80499...);
    # Decimal input is used exactly.
    return Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def _normalize_decimal(column, scale):
    return _object_series([quantize_decimal(value, scale) for value in column], column.index)


def _normalize_date(column):
    converted = pd.to_datetime(column, errors="coerce").dt.normalize()
    return pd.Series(
        [None if pd.isna(value) else value.date() for value in converted],
        index=column.index, dtype=object,
    )


def _object_series(values, index):
    # Built from a list so NULL stays None (pandas 3 would turn it into NaN
    # when mapping over a string column).
    return pd.Series(values, index=index, dtype=object)


def _normalize_bool(column):
    return _object_series([None if _is_missing(v) else bool(v) for v in column], column.index)


def _normalize_text(column):
    return _object_series([None if _is_missing(v) else str(v) for v in column], column.index)


def normalize_column(column, sql_type):
    """One column in its canonical, comparable form (object dtype, None for NULL)."""
    sql_type = (sql_type or "").upper()
    if sql_type.startswith("INT"):
        return _normalize_int(column)
    if sql_type.startswith(_DECIMAL_TYPE):
        return _normalize_decimal(column, _decimal_scale(sql_type))
    if sql_type.startswith("DATE"):
        return _normalize_date(column)
    if sql_type.startswith("BIT"):
        return _normalize_bool(column)
    return _normalize_text(column)


def normalize_frame(frame, types):
    """The frame restricted to the schema columns, every column normalized.

    A schema column the frame does not have comes back as all NULL, like a SQL
    column that exists but was never filled.
    """
    columns = list(types)
    normalized = {}
    for name in columns:
        if name in frame.columns:
            normalized[name] = normalize_column(frame[name], types[name])
        else:
            normalized[name] = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    return pd.DataFrame(normalized, index=frame.index, columns=columns)


def row_digests(frame, types, primary_key):
    """{primary key: digest of the normalized row} for every row of `frame`."""
    if frame is None or frame.empty:
        return {}
    normalized = normalize_frame(frame, types)
    keys = normalized[primary_key].tolist()
    digests = pd.util.hash_pandas_object(normalized.astype(str), index=False).tolist()
    return dict(zip(keys, digests))


# ---------------------------------------------------------------------------
# Baseline and change detection
# ---------------------------------------------------------------------------

def build_baseline(tables, schema):
    """Digest every loaded table. `tables` maps df name -> DataFrame."""
    baseline = {}
    for table_name, definition in schema.items():
        frame = tables.get(definition["df"])
        if frame is None:
            continue
        baseline[table_name] = row_digests(frame, definition["types"], definition["primary_key"])
    return baseline


@dataclass
class TableChanges:
    """The rows one table needs written, plus counts for the log/summary."""

    table: str
    write_mode: str
    added: pd.DataFrame
    updated: pd.DataFrame
    deleted_keys: list = field(default_factory=list)
    unchanged: int = 0
    total: int = 0
    existing_changed: int = 0     # append tables: existing rows that differ in memory

    def counts(self):
        return {
            "added": len(self.added),
            "updated": len(self.updated),
            "unchanged": self.unchanged,
            "deleted": len(self.deleted_keys),
            "total": self.total,
        }


def compute_changes(table, definition, frame, baseline_digests):
    """Compare the new `frame` with the loaded baseline of one table."""
    mode = definition.get("write_mode")
    if mode not in WRITE_MODES:
        raise ValueError(f"{table}: write_mode must be one of {WRITE_MODES}, got {mode!r}")
    primary_key = definition["primary_key"]
    types = definition["types"]

    frame = frame.drop_duplicates(subset=[primary_key], keep="last")
    new_digests = row_digests(frame, types, primary_key)
    keys = frame[primary_key].tolist() if not frame.empty else []
    normalized_keys = normalize_column(frame[primary_key], types[primary_key]).tolist() if keys else []

    is_new, is_changed = [], []
    unchanged = existing_changed = 0
    for key in normalized_keys:
        previous = baseline_digests.get(key)
        if previous is None:
            is_new.append(True); is_changed.append(False)
        elif previous != new_digests[key]:
            is_new.append(False); is_changed.append(True)
        else:
            is_new.append(False); is_changed.append(False)
            unchanged += 1

    mask_new = np.array(is_new, dtype=bool)
    mask_changed = np.array(is_changed, dtype=bool)
    added = frame[mask_new] if len(frame) else frame
    changed = frame[mask_changed] if len(frame) else frame

    if mode == APPEND:
        existing_changed = len(changed)
        changed = frame.iloc[0:0]

    present = set(normalized_keys)
    missing = [key for key in baseline_digests if key not in present]
    if missing and not definition.get("delete_missing", False):
        raise RowsLostError(
            f"{table}: {len(missing)} loaded rows are missing from the new state "
            f"(e.g. keys {missing[:5]}). Only tables that declare 'delete_missing' may "
            "lose rows; this is a simulation bug, nothing was written."
        )

    return TableChanges(
        table=table,
        write_mode=mode,
        added=added,
        updated=changed,
        deleted_keys=missing if definition.get("delete_missing", False) else [],
        unchanged=unchanged,
        total=len(frame),
        existing_changed=existing_changed,
    )


def plan_incremental(tables, schema, baseline, order):
    """TableChanges for every schema table present in `tables`, in write order."""
    changes = []
    for table_name in order:
        definition = schema[table_name]
        frame = tables.get(definition["df"])
        if frame is None:
            logger.warning("DataFrame %s not found - skipping", definition["df"])
            continue
        changes.append(compute_changes(table_name, definition, frame, baseline.get(table_name, {})))
    return changes


def summarize(changes):
    """{table: counts} for the log/summary (keys `added`, `updated`, `unchanged`, `deleted`)."""
    summary = {change.table: change.counts() for change in changes}
    for change in changes:
        counts = summary[change.table]
        logger.info(
            "%s (%s): +%d added, %d updated, %d unchanged, %d deleted",
            change.table, change.write_mode, counts["added"], counts["updated"],
            counts["unchanged"], counts["deleted"],
        )
        if change.existing_changed:
            logger.warning(
                "%s is append-only but %d existing rows changed in memory; those changes "
                "are NOT written. Its write_mode is probably wrong.",
                change.table, change.existing_changed,
            )
    return summary
