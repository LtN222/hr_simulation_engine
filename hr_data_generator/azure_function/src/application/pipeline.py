"""One HR simulation pipeline for full and incremental runs.

An incremental run is a full run resumed from a checkpoint::

    prepare_state  -> full: population at the burn-in start
                      incremental: store.load + checkpoint
    run_weeks      -> simulate from checkpoint.next_week while the week's
                      Monday <= today, one random stream per week
    post_process   -> the same derived-table sync sequence for both modes
    store.write    -> tables + checkpoint (reset only for a full run)

Acceptance property: a full run to week N gives exactly the same tables as a
full run to week N-1 followed by one incremental week.
"""

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.application.population import WorkforceGenerator
from src.application.simulation_runner import clear_week_caches, simulate_week
from src.core.iso_week import next_iso_week
from src.generator.person_factory import seed_person_names
from src.infrastructure.absence_context import sync_absence_satisfaction
from src.infrastructure.avatar import ensure_employee_avatars
from src.infrastructure.departure_context import (
    sync_departure_satisfaction,
    sync_employment_hire_sources,
)
from src.infrastructure.employee_status import sync_employee_employment_status
from src.infrastructure.manager_assignment import sync_manager_assignments
from src.infrastructure.manager_builder import build_dim_manager
from src.infrastructure.recruitment_context import sync_recruitment_status_keys
from src.infrastructure.shift_allowance import derive_ploegentoeslag
from src.infrastructure.state.checkpoint import checkpoint_state, initial_checkpoint
from src.infrastructure.state.incremental_load import load_incremental_state
from src.infrastructure.workforce_snapshot import build_workforce_snapshots

logger = logging.getLogger(__name__)

MODES = ("full", "incremental")


def validate_mode(mode):
    """Only "full" and "incremental" are runs; anything else is an error."""
    if mode not in MODES:
        raise ValueError(
            f"Unknown simulation mode {mode!r}; expected one of {', '.join(MODES)}."
        )
    return mode


@dataclass(frozen=True)
class SimulationParameters:
    """Everything derived from config + seed that every weekly run needs.

    Computed in exactly one place, so the growth path is identical in a full
    run and in every incremental run.
    """

    baseline_headcount: int
    initial_headcount: int
    max_capacity: float
    annual_growth_rate: float
    weeks_before_peak_growth: int
    promotion_rate: float
    transfer_rate: float
    burn_in_years: int
    burn_in_start_date: datetime
    visible_start_date: datetime


def simulation_parameters(config, seed):
    baseline_headcount = config.baseline_headcount
    growth_cfg = config.growth

    # The growth rate is drawn once per (seed, config) - never from a stream
    # that a run consumes - so every run, full or incremental, follows the
    # same growth path (AR-51).
    annual_growth_cfg = growth_cfg.get("annual_growth_rate", {})
    annual_growth_rate = random.Random(f"{seed}:growth-rate").uniform(
        annual_growth_cfg.get("min", 0.02),
        annual_growth_cfg.get("max", 0.04),
    )

    initial_population_cfg = config.initial_population
    burn_in_years = max(0, int(initial_population_cfg.get("burn_in_years", 0)))
    career_cfg = config.career_events
    return SimulationParameters(
        baseline_headcount=baseline_headcount,
        initial_headcount=int(initial_population_cfg.get("headcount", baseline_headcount)),
        max_capacity=growth_cfg.get("max_capacity", baseline_headcount * 1.5),
        annual_growth_rate=annual_growth_rate,
        weeks_before_peak_growth=growth_cfg.get("weeks_before_peak_growth", 100),
        promotion_rate=career_cfg.get("promotion_rate", 0),
        transfer_rate=career_cfg.get("internal_transfer_rate", 0),
        burn_in_years=burn_in_years,
        burn_in_start_date=datetime(config.start_year_simulation - burn_in_years, 1, 1),
        visible_start_date=datetime(config.start_year_simulation, 1, 1),
    )


def week_seed(seed, year, week):
    """The seed of one simulated week: independent of every other week."""
    return f"{seed}:{year}:{week}"


def canonicalize_row_order(state, schema):
    """Sort every schema table by its primary key and renumber the index.

    The simulators iterate tables in row order and draw random numbers along the
    way (e.g. over `dim_role` in config order, which is not key order). A store
    returns rows in primary-key order (SQL's clustered index), so a run that was
    resumed from a store would iterate differently from the in-memory run it
    continues. Both modes therefore start the weekly loop from the same canonical
    order; new rows are appended in increasing key order, which keeps it.
    """
    for definition in schema.values():
        frame = state.get(definition["df"])
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            state[definition["df"]] = frame.sort_values(
                definition["primary_key"], kind="stable"
            ).reset_index(drop=True)
    return state


def prepare_state(mode, config, schema, seed, store, params):
    """Return (state, checkpoint) to start the weekly loop from."""
    if mode == "full":
        state = WorkforceGenerator(
            seed=seed,
            initial_date=params.burn_in_start_date,
            initial_headcount=params.initial_headcount,
            config=config,
            schema=schema,
        ).run()
        state = ensure_employee_avatars(state, config)
        state = canonicalize_row_order(state, schema)
        checkpoint = initial_checkpoint(
            seed, params.burn_in_start_date.year, 1, config
        )
        return state, checkpoint

    state, checkpoint = load_incremental_state(store, config, schema, seed)
    state = ensure_employee_avatars(state, config)
    state = canonicalize_row_order(state, schema)
    return state, checkpoint


def run_weeks(state, checkpoint, config, schema, params, seed, today):
    """Simulate every week from the checkpoint up to and including `today`'s week.

    Each week draws from its own `Random(f"{seed}:{year}:{week}")` and reseeds
    the name generator, so a week's outcome does not depend on how many weeks
    the process simulated before it (AR-05, AR-47). The checkpoint's next-week
    pointer advances past every simulated week.
    """
    year, week = checkpoint.next_year, checkpoint.next_week
    logger.info("Simulating from year %s, week %s", year, week)
    started_at = time.time()
    burn_in_end = (config.start_year_simulation, 1)

    while datetime.fromisocalendar(year, week, 1) <= today:
        if params.burn_in_years > 0 and (year, week) == burn_in_end:
            logger.info(
                "Burn-in finished after %.1f minutes (%d simulated weeks)",
                (time.time() - started_at) / 60,
                params.burn_in_years * 52,
            )

        weekly_seed = week_seed(seed, year, week)
        seed_person_names(f"{weekly_seed}:names")
        state = simulate_week(
            state,
            config,
            schema,
            year,
            week,
            params.baseline_headcount,
            params.max_capacity,
            params.annual_growth_rate,
            params.weeks_before_peak_growth,
            random.Random(weekly_seed),
            params.promotion_rate,
            params.transfer_rate,
            simulation_start_date=params.burn_in_start_date,
        )
        year, week = next_iso_week(year, week)

    checkpoint.advance_to(year, week)
    return state


def snapshot_window_start(checkpoint):
    """First day of the month containing the first week an incremental run simulates.

    Earlier month-ends cannot change any more, so an incremental run rebuilds
    only the month-ends from here on (the open month included) and merges them
    with the loaded rows.
    """
    monday = datetime.fromisocalendar(checkpoint.next_year, checkpoint.next_week, 1)
    return datetime(monday.year, monday.month, 1)


def _merge_window(loaded, rebuilt, date_column, window_start):
    """Loaded rows before the window plus the rebuilt rows of the window."""
    if loaded is None or loaded.empty or date_column not in loaded.columns:
        return rebuilt
    dates = pd.to_datetime(loaded[date_column], errors="coerce")
    kept = loaded[dates < pd.Timestamp(window_start)]
    if rebuilt is None or rebuilt.empty:
        return kept.copy()
    return pd.concat([kept, rebuilt], ignore_index=True)


def post_process(state, config, schema, params, today, snapshot_from=None):
    """Derived tables and fields, in one fixed order, for both modes.

    `snapshot_from` (incremental runs) limits the rebuilt snapshots and salary
    benchmarks to the month-ends from that date on; everything earlier is kept
    as loaded. A full run builds every month-end from the visible start.

    The per-week caches are emptied first: they still hold the last simulated
    week's entries, and re-scoring with them warm gives different satisfaction
    values than the same step after a reload (cold), which would make a run
    depend on whether it was resumed.
    """
    clear_week_caches(state)
    state = sync_employee_employment_status(state)
    state = sync_employment_hire_sources(state)
    state = sync_recruitment_status_keys(state)
    state = derive_ploegentoeslag(state, config)
    state = sync_manager_assignments(state, schema, today)
    state = build_dim_manager(state)
    state = sync_absence_satisfaction(state, config)
    loaded_snapshots = state.get("fact_workforce_snapshot")
    loaded_benchmarks = state.get("fact_salary_benchmark")
    state = build_workforce_snapshots(
        state,
        schema,
        config=config,
        start_date=snapshot_from or params.visible_start_date,
        end_date=today,
    )
    if snapshot_from is not None:
        state["fact_workforce_snapshot"] = _merge_window(
            loaded_snapshots, state["fact_workforce_snapshot"], "Snapshot_Date", snapshot_from
        )
        state["fact_salary_benchmark"] = _merge_window(
            loaded_benchmarks, state["fact_salary_benchmark"], "Benchmark_Date", snapshot_from
        )
    state = sync_departure_satisfaction(state)
    return state


def run_pipeline(mode, config, schema, seed, store, today):
    """Run one full or incremental simulation against `store`.

    `config` and `schema` are loaded once by the caller and passed down; `today`
    is explicit (nothing below reads the wall clock). Returns (state, summary)
    where `summary` is whatever `store.write` reports.
    """
    validate_mode(mode)
    logger.info("Starting %s HR simulation up to %s", mode, today)

    params = simulation_parameters(config, seed)
    state, checkpoint = prepare_state(mode, config, schema, seed, store, params)
    snapshot_from = snapshot_window_start(checkpoint) if mode == "incremental" else None
    state = run_weeks(state, checkpoint, config, schema, params, seed, today)
    state = post_process(state, config, schema, params, today, snapshot_from)

    checkpoint_state(state, schema, checkpoint)
    summary = store.write(state, checkpoint, reset=(mode == "full"))

    logger.info("%s HR simulation finished", mode.capitalize())
    return state, summary
