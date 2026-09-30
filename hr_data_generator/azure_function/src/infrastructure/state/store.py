"""Where a run's state lives between runs: SQL in production, memory in tests.

`Store.load(schema)` returns the tables as DataFrames plus the checkpoint (or
None) and remembers a baseline of what it loaded; `Store.write(state,
checkpoint, reset)` persists the run. A full run (`reset=True`) replaces
everything. An incremental run writes only what changed since the load, per
table write mode (`upsert`/`append`, see table_changes.py), and never loses rows
silently. Both stores implement exactly these semantics, so the equivalence
tests on `InMemoryStore` prove the write modes that `SqlStore` will apply.
"""

import copy
import logging

import pandas as pd

from src.infrastructure.state.checkpoint import Checkpoint
from src.infrastructure.state.table_changes import (
    AppendTableChangedError,
    build_baseline,
    plan_incremental,
    summarize,
)

logger = logging.getLogger(__name__)


class Store:
    """Interface of a state store."""

    def load(self, schema):
        raise NotImplementedError

    def write(self, state, checkpoint, reset):
        raise NotImplementedError


def _empty_tables(schema):
    return {
        table["df"]: pd.DataFrame(columns=list(table.get("types", {}).keys()))
        for table in schema.values()
    }


def _write_order(schema):
    from src.infrastructure.database.write_to_sql import get_table_write_order

    return get_table_write_order(schema)


class InMemoryStore(Store):
    """Test store that behaves like SQL, including the write modes.

    Only schema tables and columns survive a write (a missing column comes back
    as NULL); every other state key is dropped. A full run replaces everything;
    an incremental run inserts new primary keys, updates changed rows of
    `upsert` tables, never changes existing rows of `append` tables and deletes
    only where a table declares `delete_missing`. It compares rows with the same
    normalization as the SQL store, so it reports the same added/updated/
    unchanged counts. It deliberately does not mimic DECIMAL rounding of the
    stored values: a real SQL round trip may drift by rounding where this store
    does not (the comparison itself rounds, so that drift does not count as a
    change).

    With `strict` (default) an `append` table whose existing rows changed in
    memory raises: that table's write_mode is misclassified.
    """

    def __init__(self, schema, strict=True):
        self.schema = schema
        self.strict = strict
        self.tables = None
        self.checkpoint = None
        self.baseline = None
        self.last_summary = {}

    def load(self, schema):
        state = _empty_tables(schema)
        if self.tables is not None:
            for name, frame in self.tables.items():
                state[name] = frame.copy(deep=True)
        self.baseline = build_baseline(state, schema)
        checkpoint = copy.deepcopy(self.checkpoint) if self.checkpoint else None
        if checkpoint is not None:
            # Round trip through JSON like the SQL store, so a value the
            # checkpoint cannot represent fails here as well.
            checkpoint = Checkpoint.from_json(checkpoint.to_json())
        return state, checkpoint

    def write(self, state, checkpoint, reset):
        if reset or self.tables is None:
            summary = self._write_full(state)
        else:
            summary = self._write_incremental(state)
        self.checkpoint = Checkpoint.from_json(checkpoint.to_json())
        self.baseline = None            # the next incremental run must load first
        self.last_summary = summary
        return summary

    def _schema_frame(self, frame, definition):
        columns = list(definition["types"])
        return self._in_key_order(
            frame.reindex(columns=columns).drop_duplicates(
                subset=[definition["primary_key"]], keep="last"
            ), definition,
        )

    @staticmethod
    def _in_key_order(frame, definition):
        """Stored tables come back in primary-key order, like SQL's clustered index."""
        return frame.sort_values(definition["primary_key"], kind="stable").reset_index(drop=True)

    def _write_full(self, state):
        self.tables = {}
        summary = {}
        for table_name, definition in self.schema.items():
            frame = state.get(definition["df"])
            if frame is None:
                continue
            stored = self._schema_frame(frame, definition)
            self.tables[definition["df"]] = stored
            summary[table_name] = {
                "added": len(stored), "updated": 0, "unchanged": 0, "deleted": 0,
                "total": len(stored),
            }
        return summary

    def _write_incremental(self, state):
        if self.baseline is None:
            raise RuntimeError(
                "An incremental write needs a preceding load (the baseline of the loaded tables)."
            )
        tables = {
            name: frame for name, frame in state.items() if isinstance(frame, pd.DataFrame)
        }
        changes = plan_incremental(tables, self.schema, self.baseline, _write_order(self.schema))
        summary = summarize(changes)

        if self.strict:
            for change in changes:
                if change.existing_changed:
                    raise AppendTableChangedError(
                        f"{change.table} (write_mode append): {change.existing_changed} "
                        "existing rows changed in memory - it must be an upsert table."
                    )

        for change in changes:
            definition = self.schema[change.table]
            primary_key = definition["primary_key"]
            current = self.tables.get(definition["df"])
            if current is None:
                current = pd.DataFrame(columns=list(definition["types"]))
            touched = set(change.updated[primary_key].tolist()) | set(change.deleted_keys)
            if touched:
                current = current[~current[primary_key].isin(touched)]
            frames = [
                frame.reindex(columns=list(definition["types"]))
                for frame in (change.updated, change.added) if not frame.empty
            ]
            if frames:
                current = pd.concat([current.reindex(columns=list(definition["types"]))] + frames,
                                    ignore_index=True)
            self.tables[definition["df"]] = self._in_key_order(current, definition)
        return summary


class SqlStore(Store):
    """Azure SQL store: the managed tables plus the checkpoint in `simulation_state`.

    `load` keeps a normalized baseline of every table as loaded; `write` runs
    schema evolution, then ONE transaction (data, deletes, checkpoint last).
    With `dry_run` the transaction is rolled back and the counts are returned.
    """

    def __init__(self, engine, schema, dry_run=False):
        self.engine = engine
        self.schema = schema
        self.dry_run = dry_run
        self.baseline = None

    def load(self, schema):
        from src.infrastructure.state.load_state import load_current_state
        from src.infrastructure.state.simulation_state import read_checkpoint

        tables = load_current_state(self.engine, schema)
        self.baseline = build_baseline(tables, schema)
        return tables, read_checkpoint(self.engine)

    def write(self, state, checkpoint, reset):
        from src.infrastructure.database.write_to_sql import write_dataset
        from src.infrastructure.state.simulation_state import write_checkpoint

        return write_dataset(
            self.engine,
            state,
            self.schema,
            reset=reset,
            baseline=self.baseline,
            checkpoint=checkpoint,
            write_checkpoint=write_checkpoint,
            dry_run=self.dry_run,
        )
