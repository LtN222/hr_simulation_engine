"""Checkpoint of everything an incremental run needs besides the SQL tables.

An incremental run is a full run resumed from a checkpoint, so the checkpoint
must carry exactly what a continuing in-memory run would still know: which week
to simulate next, and the simulation-state keys that are not tables (location
openings, the recruitment pipeline's candidate profiles, pending vacancy
requests). Every non-table key in the simulation state is classified in
`STATE_KEY_REGISTER`; a key that is neither a schema table nor registered makes
`checkpoint_state` raise, so a new key needs an explicit persisted/transient
decision instead of silently vanishing between runs (AR-04, AR-22).
"""

import datetime as _dt
import hashlib
import json
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.iso_week import next_iso_week

logger = logging.getLogger(__name__)

PERSISTED = "persisted"
TRANSIENT = "transient"


class CheckpointError(RuntimeError):
    """The stored checkpoint is missing or does not belong to this run."""


# ---------------------------------------------------------------------------
# JSON codec: dates as ISO strings, dict keys restored to their original types
# ---------------------------------------------------------------------------

_TAG = "__t"


def to_jsonable(value):
    """Convert a persisted-state value to plain JSON types, tagging what JSON
    cannot represent (dates, non-string dict keys, tuples, sets)."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return {_TAG: "nan"} if value != value else value
    if value is pd.NaT:
        return {_TAG: "nat"}
    if isinstance(value, pd.Timestamp):
        return {_TAG: "ts", "v": value.isoformat()}
    if isinstance(value, _dt.datetime):
        return {_TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, _dt.date):
        return {_TAG: "date", "v": value.isoformat()}
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value) and _TAG not in value:
            return {key: to_jsonable(item) for key, item in value.items()}
        return {
            _TAG: "dict",
            "items": [[to_jsonable(key), to_jsonable(item)] for key, item in value.items()],
        }
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return {_TAG: "tuple", "v": [to_jsonable(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {_TAG: "set", "v": [to_jsonable(item) for item in value]}
    raise TypeError(f"Cannot checkpoint a value of type {type(value).__name__}: {value!r}")


def from_jsonable(value):
    """Inverse of `to_jsonable`."""
    if isinstance(value, list):
        return [from_jsonable(item) for item in value]
    if not isinstance(value, dict):
        return value
    tag = value.get(_TAG)
    if tag is None:
        return {key: from_jsonable(item) for key, item in value.items()}
    if tag == "ts":
        return pd.Timestamp(value["v"])
    if tag == "datetime":
        return _dt.datetime.fromisoformat(value["v"])
    if tag == "date":
        return _dt.date.fromisoformat(value["v"])
    if tag == "nat":
        return pd.NaT
    if tag == "nan":
        return float("nan")
    if tag == "dict":
        return {from_jsonable(key): from_jsonable(item) for key, item in value["items"]}
    if tag == "tuple":
        return tuple(from_jsonable(item) for item in value["v"])
    if tag == "set":
        return {from_jsonable(item) for item in value["v"]}
    raise ValueError(f"Unknown checkpoint tag {tag!r}")


def _empty_dict():
    return {}


def _empty_list():
    return []


@dataclass(frozen=True)
class StateKey:
    """How one non-table simulation-state key is treated at a checkpoint."""

    kind: str
    default: callable = None
    reason: str = ""


def _persisted(default, reason):
    return StateKey(PERSISTED, default, reason)


def _transient(reason):
    return StateKey(TRANSIENT, None, reason)


# Every non-table key the simulation puts in `state`. Persisted keys survive an
# incremental run through the checkpoint; transient keys are rebuilt or are only
# meaningful within one week.
STATE_KEY_REGISTER = {
    "_location_open": _persisted(
        _empty_dict, "which sites are open; openings need a capacity streak or headcount"),
    "_location_opened_on": _persisted(
        _empty_dict, "opening date per site (drives the new-site pull)"),
    "_location_capacity_streak": _persisted(
        _empty_dict, "consecutive weeks at capacity, needed to open the next site"),
    "_location_capacity_bonus": _persisted(
        _empty_dict, "extra capacity granted when another site opens"),
    "_home_location": _persisted(
        _empty_dict, "location a department was relocated to"),
    "_recruitment_pipeline_profiles": _persisted(
        _empty_dict, "screened education/experience of candidates still in the pipeline"),
    "_vacancy_requests": _persisted(
        _empty_list, "backfill requests raised after this week's vacancy step"),
    "_satisfaction_cache": _transient("per-week cache, cleared every week"),
    "_satisfaction_momentum_cache": _transient("per-week cache, cleared every week"),
    "_engagement_cache": _transient("per-week cache, cleared every week"),
    "_engagement_momentum_cache": _transient("per-week cache, cleared every week"),
    "_constructive_contributions_cache": _transient("per-week cache, cleared every week"),
    "_dimension_lookup_cache": _transient("lookup cache rebuilt from the dimensions"),
    "_employment_by_employee": _transient("index over fact_employment, rebuilt on demand"),
    "_employment_by_employee_source": _transient("identity marker of the employment index"),
    "role_allocations": _transient("initial-population scaffolding, removed after generation"),
    "_accepted_applications": _transient(
        "handed from recruitment to hiring within one week; must be empty at week end"),
}

PERSISTED_KEYS = tuple(key for key, spec in STATE_KEY_REGISTER.items() if spec.kind == PERSISTED)


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    """Where a run stopped: the NEXT week to simulate plus the persisted state."""

    seed: object
    next_year: int
    next_week: int
    config_fingerprint: str
    persisted_state: dict = field(default_factory=dict)

    def advance_to(self, year, week):
        self.next_year, self.next_week = int(year), int(week)

    @property
    def last_simulated_week(self):
        """The (year, week) simulated last, for readability in simulation_state."""
        year, week = self.next_year, self.next_week
        if week > 1:
            return year, week - 1
        previous_year = year - 1
        return previous_year, (53 if _has_week_53(previous_year) else 52)

    def to_json(self):
        return json.dumps({
            "seed": self.seed,
            "next_year": self.next_year,
            "next_week": self.next_week,
            "config_fingerprint": self.config_fingerprint,
            "persisted_state": to_jsonable(self.persisted_state),
        })

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        return cls(
            seed=data["seed"],
            next_year=int(data["next_year"]),
            next_week=int(data["next_week"]),
            config_fingerprint=data["config_fingerprint"],
            persisted_state=from_jsonable(data["persisted_state"]),
        )


def _has_week_53(year):
    from src.core.iso_week import has_iso_week_53
    return has_iso_week_53(year)


def config_fingerprint(config):
    """A stable hash of the merged sector configuration.

    Runtime-only values (mode, timer settings) are left out: only what shapes
    the simulation counts, so a changed sector config is detected while a mode
    switch is not.
    """
    data = dict(getattr(config, "_data", {}) or {})
    for runtime_key in (
        "simulation_mode", "simulation_weeks", "simulation_dry_run", "simulation_as_of",
    ):
        data.pop(runtime_key, None)
    canonical = json.dumps(data, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_table_names(schema):
    """State keys that are tables: the `df` name of every schema table."""
    return {table["df"] for table in schema.values()}


def check_state_keys(state, schema):
    """Raise when `state` holds a key that is neither a table nor registered."""
    tables = schema_table_names(schema)
    unknown = sorted(
        key for key in state
        if key not in tables and key not in STATE_KEY_REGISTER
    )
    if unknown:
        raise CheckpointError(
            "Simulation state has keys that are neither schema tables nor classified "
            f"in STATE_KEY_REGISTER: {unknown}. Decide for each whether it is persisted "
            "in the checkpoint or transient."
        )


def checkpoint_state(state, schema, checkpoint):
    """Capture the persisted keys of `state` into `checkpoint` (validating first)."""
    check_state_keys(state, schema)

    leftover = state.get("_accepted_applications")
    if leftover:
        raise CheckpointError(
            "_accepted_applications must be empty at the end of a week "
            f"(found {len(leftover)}): hiring did not consume them."
        )

    persisted = {}
    for key in PERSISTED_KEYS:
        value = state.get(key)
        persisted[key] = STATE_KEY_REGISTER[key].default() if value is None else value
    checkpoint.persisted_state = from_jsonable(to_jsonable(persisted))  # deep, JSON-safe copy
    return checkpoint


def restore_state(state, checkpoint):
    """Put the checkpoint's persisted keys back into a freshly loaded state."""
    for key in PERSISTED_KEYS:
        value = checkpoint.persisted_state.get(key)
        state[key] = STATE_KEY_REGISTER[key].default() if value is None else value
    return state


def validate_checkpoint(checkpoint, seed, config):
    """Reject a checkpoint that cannot be resumed with this seed/config."""
    if checkpoint is None:
        raise CheckpointError(
            "No checkpoint found in the store: run a full run first "
            "(an incremental run resumes from the checkpoint a full run writes)."
        )
    if str(checkpoint.seed) != str(seed):
        raise CheckpointError(
            f"The checkpoint was written with simulation seed {checkpoint.seed!r}, "
            f"but this run uses {seed!r}. Use the same seed or run a full run."
        )
    fingerprint = config_fingerprint(config)
    if checkpoint.config_fingerprint != fingerprint:
        logger.warning(
            "The sector configuration changed since the checkpoint was written "
            "(fingerprint %s -> %s); continuing, but history was generated with the "
            "old configuration.", checkpoint.config_fingerprint[:12], fingerprint[:12],
        )
    return checkpoint


def initial_checkpoint(seed, start_year, start_week, config):
    return Checkpoint(
        seed=seed,
        next_year=int(start_year),
        next_week=int(start_week),
        config_fingerprint=config_fingerprint(config),
    )


__all__ = [
    "Checkpoint", "CheckpointError", "STATE_KEY_REGISTER", "PERSISTED_KEYS",
    "checkpoint_state", "restore_state", "validate_checkpoint", "check_state_keys",
    "config_fingerprint", "initial_checkpoint", "to_jsonable", "from_jsonable",
    "next_iso_week",
]
