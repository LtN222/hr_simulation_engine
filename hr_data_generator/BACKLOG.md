# Backlog

Open work only. Completed items (verified fixes, finished features, calibration records and the history of earlier plans) are in `CHANGELOG.md`, grouped by date. Item numbers (`AR-xx` architecture review, `HP-xx` high priority, `LF-xx` later features) are never reused; each is defined exactly once, here or in the changelog.

What is left of the work order agreed on 2026-09-30: speed work (the remainder of AR-17 to AR-19). Groups 1-5, the full run of 2026-10-02 and the pipeline merge (AR-20) are done; see the changelog.

## Decisions (standing)

- **`Salaris` stays a full-time (1.0 FTE) amount.** The web app does the
  part-time pro-rata calculation, so there is no separate actual-pay column.
- **Minimum wage floor (indexed, revised):** `salary_benchmark.legal_minimum_salary`
  holds `reference_year` 2026, `annual_full_time_salary` 31,179 and an
  `allowances` map (`vakantiegeld` 0.08; extra entries add up). The reference
  floor is `ceil(annual x (1 + sum(allowances)))` = €33,674 on 1 January 2026.
  Any other date scales it with `annual_market_growth_rate` (so ~€29,036 in
  2020, growing after 2026); before `base_date` it is flat, like the growth
  factor. `SalaryPolicy.apply_floor(salary, date)` serves all four salary
  paths. Update the config for a new year before a full run. **HP-03:** the
  floor is a step function (indexation on 1 January and 1 July) and the weekly
  runner raises employees below it with the new `Minimumloonaanpassing` event.
- **Salary scales:** Schaal G becomes "Boven-CAO" (key 7, code `BC`, minimum
  105,000, no maximum) for Managing Director, CFO, Operations Director and
  Commercial Director; Plant Manager stays in F. `Schaal_Max_Salaris` is NULL
  for those roles. Schaal A is now 29,100-46,000; B-F are unchanged.
  `validate_role_configuration` enforces: every role has a market median;
  market P25-P75 lies within its scale (open-ended scale: minimum only); the
  lowest scale starts at or above the indexed 2020 floor.
- **New medians:** CFO 140,000, Commercial Director 125,000, Product Manager
  62,000 (2020 money). Productiemedewerker/Magazijnmedewerker 41,000, Operator
  A 42,000, Operator B 46,000, QC Medewerker 42,500, QC Laborant, HR
  Medewerker and Financieel Medewerker 42,000.
- **Gender pay gap recalibrated:** `female_starting_offset` -0.036 to -0.043
  (review offset unchanged at -0.0018); the role-corrected gap measured 3.75%
  before and 4.45% after in the narrow harness.
- **Names (implemented in group 3):** every employee's "Voornaam Achternaam" is capped at 20
  characters, not only managers', since any employee can become a manager.
  The Dutch name lists are fine: Robin, Sam and Senna are genuinely unisex.
- **Expat names** must be both gender-correct and country-specific. Polish and
  Romanian names use Faker `pl_PL` and `ro_RO`, including the gendered Polish
  surnames (-ski/-ska). Faker `bg_BG` produces Cyrillic, so Bulgarian names
  need a Latin-script solution. Decided in group 3: transliteration with the
  Bulgarian Streamlined System, plus folding of characters CP1252 cannot store
  to ASCII (no NVARCHAR migration). Faker's `pl_PL` turned out to have no
  gendered surnames, so the -ski/-ska forms are generated in code.

### Data model: Dutch/English naming convention (standing decision)

**The intended convention (clarified; this reverses the earlier framing of
this section).** Table names and every key column (surrogate PK/FK, used
only for joins/identity) are English - structural/technical identifiers.
Every business-content column - anything likely to appear in a Power BI
visualization, KPI card, axis label or slicer, or that a future LLM feature
would need to read or reason about - should be Dutch, since the intended end
users think and prompt in Dutch and an LLM feature should never have to
switch languages between a Dutch prompt and the schema's business
vocabulary. Several tables added later in the project drifted from this
(built with English business-content columns); those are the drift to fix,
not the target style. Date columns are exempt across the board - they join
to the Power BI `dim_date` table and don't need to be in Dutch for that.
Also exempt/left as-is by explicit decision: boolean business flags
(`Is_Internal`, `Is_Final`, `Counts_As_Hire`, `Recordable`, `Is_Shift_Work`),
`Status` fields (identical loanword in Dutch), `FTE` (used unchanged in
Dutch HR contexts), `Sort_Order` (pure UI/display metadata, not itself shown
as a data point), and `Avatar_FileName`/`Avatar_URL` (technical asset
references).

The two Dutch table names (`dim_ploegendienst`, `dim_reden_vertrek`) were
already renamed to English structural names (`dim_shift`,
`dim_departure_reason`) in an earlier pass - see the fact-table migration
note below for why that stays even though this section is about the
opposite direction for columns.

## Later - new features (agreed with the user on 2026-09-30)

**LF-04 - Optional: include Ploegentoeslag in the satisfaction pay input (low-medium; full run: yes)**
The satisfaction/engagement pay input compares `Salaris` (via the compa-ratio) only, so shift workers' extra pay does not make them more satisfied with their pay. Including `Ploegentoeslag` (total pay against the benchmark) would be more realistic but shifts satisfaction, and through it attrition and absence, for every shift worker. It needs a recalibration of the satisfaction pay effect and the attrition/absence rates, so it was left out of LF-01. Decision (user, 2026-10-02): if picked up, the allowance must count clearly less than base pay in the pay input, e.g. pay input = Salaris + w x Ploegentoeslag with a configurable weight w < 1 (the allowance compensates for inconvenient hours, so it is not experienced as equivalent to base pay). If picked up: decide whether the benchmark comparison should also move to total pay for shift roles (it would otherwise compare base pay with a base-pay benchmark and total pay with the same benchmark inconsistently).

**LF-02 - Optional: a slightly more lenient education rule for internal candidates (low; full run: yes)**
Before group 5, `eligible_internal` only checked that an internal candidate
held one of the role's `relevante_opleidingen` by name, never
`Min_Opleidingsniveau`. That was de-facto more lenient than external hiring,
but it was never documented. Since AR-37 (group 5), internal and external
candidates share one qualification/experience check. The user remembers
deliberately wanting internal candidates to get a bit more room on
education, since the organisation has seen their work for years. It was
decided not to implement this in the 2026-09-30 round, because the AR-09
experience change had already doubled promotion eligibility (27.6% -> 54.9%
in a synthetic harness).

If it is picked up, make it explicit and configurable. For example,
`career_events.internal_education_level_tolerance: 1` would let an internal
candidate sit one level below the minimum, but still require a relevant
education in the right field. Alternatively, waive the level check only
after a configured number of years of relevant experience. Record it as a
deliberate rule so a later review doesn't "fix" it as an inconsistency.
Measure the eligibility change with the same narrow harness before and after.

**LF-03 - Automate deployment of the Function App (medium; full run: no) - BLOCKED (platform choice)**
Status 2026-10-02: not possible from Azure DevOps, because the user lacks the repo rights there. The alternative is GitHub Actions, but that needs a different GitHub account (the user's work account instead of the personal one). The user decides on this; until then deployment stays manual.
Planned for right after the pipeline merge (AR-20 parts A and B) is
finished, as requested by the user on 2026-09-30. Today the user deploys
manually from bash (`func azure functionapp publish ...`, see
`handleiding code.md`).

Points to settle when this is picked up:
- The CI/CD platform. The repo history shows both GitHub and Azure DevOps
  remotes; pick one as the deploy source.
- Run `python -m pytest -q` as a gate before every deploy.
- Authentication without secrets in the repo (e.g. OIDC/federated
  credentials or a service connection). `local.settings.json` stays local.
- Trigger (on merge to `main`, manual approval, or both).
- The deployment must never trigger a full run. Full runs stay local and are
  started only by the user. Document that after a history-changing change,
  the user should deploy only after the full run, so the weekly timer
  doesn't write new-logic weeks on top of old data.
- Update README "Deployen" and `handleiding code.md` afterwards.

## Architecture review (2026-09-25) - prioritized open items

A read-only architecture review of the whole repo, done on 2026-09-25 against commit `1d3a1db` plus that day's uncommitted changes, followed by a second review on 2026-09-30 (items AR-33 onward). Items are numbered `AR-xx` so they can be referenced from commits and later chats. Only open and partly fixed items are listed here; fixed ones are in `CHANGELOG.md`.

- **✔ verified** means the finding was confirmed directly in the code and/or
  the live demo database (`db_hr_demo`) on 2026-09-25. Items without that mark
  were reported by a reviewer with `path:line` evidence but not independently
  re-checked. Re-verify them before fixing.
- **Full run:** whether fixing the item changes historical output and so needs
  a full run afterwards. Per CLAUDE.md, never start a full run on your own
  initiative; flag it and let the user decide.
- Line numbers drift; search for the named function if a reference is off.

### Priority 2 - simulation correctness (affects full runs too)

**AR-12 - Satisfaction/engagement is calculated inconsistently (medium; full run: yes)**
- The pay input differs: snapshots use actual salary ÷ benchmark
  (`workforce_snapshot.py:~83-87`); simulators and `absence_context` use
  `Streef_Compa_Ratio` (`satisfaction.py:~278`).
- Absence episodes are scored at simulation time
  (`simulation_absence.py:~602`), then `sync_absence_satisfaction` re-scores
  every episode on every run (`absence_context.py:~59-91`), rewriting history.
- Departure context copies the last month-end snapshot
  (`departure_context.py:~115-133`), up to about 30 days before exit, instead
  of the value attrition actually used.
- "Stagnation" is measured from the first-ever start date, not the last move
  (`satisfaction.py:~389`, `engagement.py:~294-296`), and the career-momentum
  logic is duplicated between the two modules.
- The momentum cache is keyed on employee + date + performance
  (`satisfaction.py:~334`, `engagement.py:~245`) and ignores same-day career
  events, so absence/safety scoring after a promotion sees pre-promotion momentum.

Direction: a single "employee context as of date" resolver used by every consumer.
*Review note (2026-09-30), "Partly outdated":* The "departure context copies the last snapshot" bullet is fixed: attrition and contracts now stamp scores on the departure row (`departure_records.py:53-56`), and `sync_departure_satisfaction` only fills them when missing. The other bullets still stand.

**AR-13 - Gaps in the internal-mobility hand-off (medium; full run: yes)**
- An internal applicant is reserved only against other recruitment rows
  (`simulation_recruitment.py:~141-145`). If they leave before the offer
  resolves, `simulation_hiring.py:~81-92` just `continue`s: the vacancy stays
  Open without `Filled_Employee_Key`, the recruitment row stays `Aangenomen`,
  and all other candidates were already closed. The capacity backstop
  (`~69-77`) has the same effect. Hire counts from recruitment are overstated.
- Eligibility is checked against the role at application time; the move is
  applied from whatever role the candidate holds at hire.
- `_move_internal_employee` decides promotion vs transfer inline
  (`simulation_hiring.py:~322-324`) instead of calling
  `role_eligibility.movement_type`. It uses a +0.02 compa bump, while career
  events uses +0.015 plus a performance term.

Direction: withdraw or finalize the application in the failure paths,
re-check eligibility at hire, and route through `movement_type` plus one
shared move builder.
*Review note (2026-09-30), "Accurate, one addition":* Internal eligibility is checked as of the vacancy's `Created_Date` (`simulation_recruitment.py:714`), which is even earlier than the application date.

**AR-15 - Same-day events stack; employment-row logic duplicated (medium; full run: yes)**
The close-then-open pattern exists separately in attrition, contracts, career
events, hiring and location transfer, with five different record builders
(e.g. `_new_employment_record`, `simulation_career_events.py:~304-334`, does not
use `build_record`). Several events on the same day create zero-length rows
(`Startdatum == Einddatum`). New keys come from `max()+1` in about ten places.
Random draws also depend on the data (e.g. `_internal_candidate` draws even
when the internal source is not chosen), so one extra eligible employee shifts
every later random draw.
Direction: one employment-ledger helper (close/open/depart plus a key
allocator kept in state).

**AR-38 - Growth demand ignores open vacancies (medium; full run: yes; not verified)**
`calculate_growth_target` (`simulation_growth.py:90-97`) sets the gap as
target minus active headcount. It doesn't subtract vacancies that are already
open.
- A leaver creates a replacement vacancy and also widens the growth gap.
- Growth vacancies are raised again every week while earlier ones are still
  being recruited.

Only the weekly caps limit this. Live: 34 open `Groei` plus 25 open
`Vervanging` vacancies. That alone doesn't prove the effect; confirm it with a
narrow harness.

**AR-42 - Initial relevant experience is driven by age (low-medium; full run: yes; user decision)**
`initial_relevant_experience` (`relevant_experience.py:9-12`) uses a mean of
0.55 × (age − 19). Age doesn't only cap the value, it drives it. This is used
for the initial population, and for the hiring fallback when a recruitment
profile is lost (AR-04). It conflicts with the CLAUDE.md invariant "relevant
experience is not age". Decide whether a tenure-in-role-family basis is
wanted.

**AR-46 - Performance driver is skewed (low; full run: yes)**
`_performance_driver_key` (`simulation_performance.py:337-352`) has two
problems:
- "Vakmanschap" = min(1, exp/8) is always positive and saturates, so it
  dominates for experienced staff.
- The driver is chosen by absolute value, whether the score is high or low.

**AR-48 - Manager-assignment end dates are inconsistent (low; full run: yes)**
- A leaver's assignment closes with `Einddatum = today`
  (`manager_assignment.py:48`); a manager change closes with `today - 1 day`
  (:76).
- A leaver is closed on the date of the sync, not their actual leaving date.
  That can be up to 6 days later, so `manager_as_of` can show a manager after
  the employee has left.

### Priority 3 - run time (a full run currently takes more than 2 hours)

A cProfile of 5 simulated weeks (200 employees, in memory, no SQL) took about
15 s per week. Roughly 85% of that came from AR-16 and AR-17.

**🟡 AR-17 partially fixed (2026-09-25) - Per-employee context is rebuilt every week (was: high; about 55% of week time; full run: no for the part fixed - it is output-preserving, see below)**
Attrition scores satisfaction and engagement for every active employee every
week (`simulation_attrition.py:~75-131`). The model itself is cheap; the cost
was the context lookups:
- `satisfaction._department_name`: about 2.8 ms per call, from two boolean
  filters (role -> department) on small dimension tables, repeated
  independently in `satisfaction.py` (shared by `engagement.py`),
  `simulation_safety.py` and `simulation_absence.py`'s own private copies of
  the same helper;
- `_compute_career_momentum`: rebuilt the whole `EventType_Key -> Gebeurtenis`
  dict from scratch on every call, duplicated near-identically in
  `satisfaction.py` and `engagement.py`, even though `dim_event_type` never
  changes within a run;
- `_ploegendienst_factor` (absence and safety): the same per-call boolean
  filter on `dim_shift`.

**Fixed:** added `src/infrastructure/dimension_lookup.py`
(`department_name_for_role`, `shift_name_for_key`, `event_gebeurtenis_lookup`),
each memoized in `state`, keyed by the source dimension DataFrames' object
identity - safe because `dim_role`/`dim_department`/`dim_shift`/`dim_event_type`
are assigned to `state` exactly once, during initial population generation,
and never reassigned during the weekly loop (verified: no
`state["dim_role"] = ...`/`state["dim_department"] = ...`/
`state["dim_event_type"] = ...` anywhere outside population generation).
Wired into `satisfaction.py`, `engagement.py`, `simulation_safety.py` and
`simulation_absence.py`, replacing 4 of the duplicated per-call filters (the
5 remaining `_department_name(department_key, state)` copies in
`simulation_contracts.py`/`simulation_hiring.py`/`simulation_recruitment.py`/
`simulation_vacancy.py` take a `Department_Key` directly rather than a
`Role_Key`, are cheaper single-table filters, and are not in this per-employee
hot path - left as a smaller, separate cleanup under AR-21).

**Verified output-preserving**, not just tested: a 50-employee, 60-week,
fully in-memory scenario (no SQL) was run once on the pre-fix code and once
on the fixed code, same `simulation_seed`, and all 32 resulting tables
(`dim_employee`, `fact_employment`, `fact_absence`, `fact_safety_incident`,
`fact_performance_review`, etc.) came out byte-for-byte identical
(`pd.testing.assert_frame_equal` on every column of every table). This
required also pinning `faker`'s own seed for the comparison - see AR-32,
a new, separate finding surfaced by this check. `test_dimension_lookup.py`
adds unit coverage (including that the cache is invalidated by object
identity, not by value, and that a role whose department is missing returns
`None` rather than pandas `NaN` - the satisfaction model hashes
`department_name` into its team-fit signal, so `None` vs `NaN` is not
cosmetic there). Full suite: 227 passed.

**Still open:** AR-16 (recruitment's internal-candidate search, a different,
larger cost that *does* change the number of random draws once fixed - not
attempted here) and the "one per-week lookup context for active rows +
band-threshold arrays" part of the original direction, which goes further
than memoizing static dimension joins (e.g. `np.searchsorted` band lookups,
vectorized attrition). Revisit after AR-16 and before declaring AR-17 fully
done; benchmark actual full-run time impact at real headcount before/after
both are in (see "Suggested order").

**AR-18 - Cost grows with accumulated history (medium; ✔ confirmed 2026-09-25) - PARTLY FIXED (pipeline merge part B, awaiting full run)**
Fixed: incremental runs rebuild `fact_workforce_snapshot` and `fact_salary_benchmark` only from the open month and merge them with the loaded rows, and only changed rows are written. Still open: the simulation cost itself grows with history (O(weeks^2): full-table scans and `pd.concat` every week), and the snapshot key still limits `Employee_Key` to below 10,000.
Growing tables are appended with `pd.concat` and scanned, copied and
date-converted in full every week. Absence loops over all `dim_employee` rows,
leavers included. `sync_manager_assignments` is O(active × open) per week. So
total cost is roughly O(weeks²). Each incremental run rebuilds every monthly
snapshot back to 2020 (`run_simulation_incremental.py:~108-114`, row by row
per month), then throws almost all of it away. Snapshot keys only allow
`Employee_Key < 10000` (`workforce_snapshot.py:~393`).

**Confirmed with a partial benchmark (2026-09-25, after AR-16/AR-17):**
in-memory run (no SQL - a benchmark, not a full run), `initial_population.headcount`
overridden to 50, `burn_in_years` to 2, `baseline_headcount` left at its
config default of 200 (this was itself a mix-up - "base headcount of 50" was
read as only the *initial* population, not also lowering the growth target,
so the run kept growing toward 200+ for its whole ~8.7 simulated years
instead of staying small; stopped partway through, at week 280 of ~452,
once that was noticed). Even so, the partial data is clear evidence for
AR-18 on its own: per-week time rose from 0.61s (week 20, active=58,
`fact_employment`=85 rows) to 14.25s (week 280, active=390,
`fact_employment`=1886 rows) - a 23x increase in per-week cost against only
a 6.7x increase in active headcount over the same stretch. If cost scaled
with headcount alone, growth should track closer to 6-7x, not 23x; the gap
points at accumulated table size, not concurrent headcount, as the
super-linear driver - consistent with the `pd.concat`/full-rescan pattern
above. Full timing table and interpretation are in this session's transcript
(2026-09-26); not reproduced here since the run itself was misconfigured and
should be redone properly before relying on the exact multiplier.
Redo direction for next time: set *both* `initial_population.headcount` and
`baseline_headcount` to the same small value (e.g. 50) so the benchmark
stays a small, stable company instead of also growing toward the real
config's target - isolates the O(weeks) history effect from headcount
growth, and should finish fast enough to run to completion.

Direction: keep in-memory indexes updated incrementally, collect new rows in
lists, and snapshot only month-ends after the last stored one, re-writing the
open month (together with AR-02).
*Review note (2026-09-30), "Accurate, and live evidence of the "open month" problem":* `_snapshot_dates` includes the current month-end. The live max `Snapshot_Date` is 2026-09-30, written on 28 Sep, and that row will never be updated.

**AR-19 - SQL write performance (medium)**
Mutable tables are upserted one row at a time (UPDATE, then INSERT), for the
whole table on every incremental run. Every cell goes through a Python
conversion function. `method="multi"` bypasses pyodbc's batched mode, so
`fast_executemany` probably has no effect. `apply_constraints` re-runs
`ALTER COLUMN` on every key column every run.
Direction: bulk-load into a temp table and `MERGE` only changed rows; use
`method=None` with `fast_executemany`; convert whole columns with pandas;
apply constraints only after a reset or schema change.
*Review note (2026-09-30), "Accurate, two additions":* `_ensure_table_columns` runs up to 3 times per table (`write_to_sql.py:545,590,626`). `_normalize_dataframe_for_sql` silently skips a column whose conversion fails (`:309-310`).

### Priority 4 - structure and maintainability

**AR-21 - Re-layer `src/infrastructure/` (medium)**
It mixes:
- business rules (satisfaction, engagement, salary policy, role eligibility,
  relevant experience);
- steps that act like simulators (`open_locations`/`relocate_department_group`
  emit events weekly; `assign_managers`);
- reporting steps (snapshot, the `*_context` modules, employee status, dimensions);
- real plumbing (database, state, record builder, blob I/O).

`location_assignment.py:26` imports from `application.allocation` (the layers
are inverted). `domain/` holds only four plain data classes. Duplicate and
dead code:
- the `dim_employee`/`fact_employment` record mapping exists in both
  `employee_generation.py:~76-139` and `simulation_hiring.py:~168-230`;
- unused copies of `SalaryPolicy` methods in `salary_benchmark.py:~115-166`;
- `src/validation/data_checks.py` is never used;
- nothing imports `src/generator/obsolete/`.

Direction: `domain/` (models and rules), `simulation/` (plus locations and
manager assignment), a new `reporting/` (snapshot, contexts, dimensions) and
`infrastructure/` (database, state, blob, caches).

**AR-23 - Move hard-coded business thresholds to config (medium-low; full run: only if values change)**
- Attrition: performance/tenure/salary multipliers
  (`simulation_attrition.py:~216-256`), satisfaction cut-offs
  4.5/6.0/7.5/8.5, the seasonal factor and shock, and exit-reason weights.
- Contracts: the leave-at-end-of-contract weight.
- Career events: `_performance_factor`.
- Vacancies: the 14-56 day target.
- Recruitment: candidate-experience offsets, education-fit scores, internal
  selection weights (2.3/2.7).
- Hiring: the 0.7/0.3 quality blend.
- Eligibility: the 2.7 and 3-year thresholds.
- Performance: the driver constants.
*Review note (2026-09-30), "Accurate, one addition":* The promotion compa bumps (+0.015 + perf term in `simulation_career_events.py:113`, +0.02 in `simulation_hiring.py:322-327`) are hard-coded as well.

**AR-24 - Dimension keys depend on config order (medium) - `fact_salary_benchmark` FIXED (pipeline merge part B, awaiting full run)**
Fixed for the benchmark: `SalaryBenchmark_Key` = `yyyymm * 10000 + Role_Key * 100 + Salaris_Trede`, validated in config (Role_Key and steps below 100). The dimension keys from config order (bands, drivers, event types, locations, absence types, departure reasons) are still open.
Bands, drivers, `dim_salary_band`, `dim_event_type`, `dim_location`,
`dim_absence_type` and `dim_departure_reason` get their keys from their
position in config (`dimension_factory.py:~28-47`). Inserting or reordering an
entry silently relabels history on incremental runs. `fact_salary_benchmark`
keys are sequential too (`salary_benchmark.py:~46-76`): adding a role or step
shifts them.
Direction: explicit keys in config, validated; deterministic benchmark keys
(e.g. yyyymm + role + step).
*Review note (2026-09-30), "Partly inaccurate":* `generate_dimensions` uses an explicit key when the config gives one (`dimension_factory.py:30`). These are already stable: hire source, recruitment status/stage, decline/rejection reason, education, satisfaction driver, salary scale, shift, incident type, and roles/departments. Still keyed by position: `dim_location`, `dim_absence_type`, satisfaction/engagement bands, performance/engagement/candidate-quality drivers, `dim_salary_band`, `dim_event_type`, `dim_departure_reason`.

**AR-25 - Typed and validated config (low-medium)**
*Mode validation done in pipeline merge part A:* `function_app` rejects any mode other than `full`/`incremental` and builds its response from the same value.
`Config` exposes raw dicts with defaults scattered at the call sites.
- `simulation_weeks` is unused.
- `database` can be None (it becomes the database name "None").
- Any mode other than `full` silently runs incremental (`function_app.py:76`).
- `validate_role_configuration` only runs in tests.

Direction: dataclasses or pydantic per section, validation at load time, and
reject unknown modes.
*Review note (2026-09-30), "Accurate, one addition":* `function_app.py:76` runs incremental for any mode other than `full`, but `:122` builds the reply from `== "incremental"`. So `HR_SIMULATION_MODE=Full` runs incremental and replies "Full HR dataset generated". `Config.simulation_mode` is also unused.
*Note (2026-10-02):* AR-43 is done: the keys that were read but missing from the config now have explicit values, and the keys nothing reads were removed or documented. The typed, validated config is still open; it would catch both kinds automatically.

**AR-50 - Optional: `dim_employee.Manager_Key` has no foreign key (low)**
It is the only non-primary `_Key` column without a foreign key. It can't
simply get one, because `dim_manager` is built from `dim_employee`.
Decision (user, 2026-10-02): optional, not necessary. The web app joins on
these keys without a registered SQL foreign key. At most, record it as a
deliberate exception next to AR-26.

### Priority 5 - tests, docs and hygiene

**AR-28 - Test architecture (medium)**
There is no `conftest.py`; about 15 private `_config`/`_base_state` helpers
are copied across files. `test_employee_generation.py` is about 2,500 lines
covering about 15 unrelated modules. One contracts test takes about 27 s.
`debug_population.py` is an uncollected print script.
Missing tests:
- `movement_type`;
- `eligible_internal` beyond the leadership branches;
- incremental resume (AR-03);
- snapshot as-of rules (AR-11);
- satisfaction consistency across consumers (AR-12);
- end-to-end seed reproducibility;
- negative tests: performance ignores absence, engagement-driver exclusions;
- schema invariants: no fact-to-fact foreign keys, the naming convention,
  renamed columns marked deprecated (AR-07).

Direction: `tests/unit/<layer>/`, `tests/integration/` (marked slow),
`tests/schema/`, and shared builders in `conftest.py`.

### Smaller open points left over from completed items

These sit inside entries that are otherwise done (see `CHANGELOG.md`); they have no item number.
- Snapshots (from the fix for the leaver counted on their exit date): a leaver's absence in their exit month still drops out of the snapshots, and hires and leavers still get full-month `Beschikbare_*` capacity.
- Attrition (from the HP-04 verification): Kwaliteit had the highest turnover in the full run of 2026-10-02 (22.2% a year, 23 of 26 departures voluntary, against a base rate of 0.07) despite above-average satisfaction (7.08); the previous dataset also had Kwaliteit above its base rate (14.6%). If it shows up again, make a narrow check of the other attrition multipliers (age, tenure, engagement) for Kwaliteit.

## Documentation gaps still open

From the 2026-09-30 review; unnumbered, and not contradictions (those were AR-29). Paths are relative to the repo root. Fixed gaps are described under AR-29 in `CHANGELOG.md`.
- **Full-run duration**: README and CLAUDE.md now agree on "more than 2 hours"; the older "about an hour" figures in `CHANGELOG.md` are dated measurements and were left as written.
- **Local-only full runs and the 10-minute Consumption limit** are now in README only. Still missing in `architecture.txt` (operational notes), `CLAUDE.md`, `AGENTS.md`, `handleiding code.md` and `handleiding Azure portal.md`.
- **README.md**: the dimension list lacks `dim_location`, `dim_recruitment_stage`, `dim_decline_reason`, `dim_rejection_reason`, `dim_candidate_quality_driver`, `dim_departure_reason` and `dim_event_type`; the settings table lacks `HR_AVATAR_BLOB_CONNECTION_STRING`; the "Configuratie" list lacks about 15 sections (including `performance`, `workforce_planning`, `role_career_paths`, `dim_location`, `contract_hours_distribution` and `special_arrangements`) and `initial_population` has no size key described; the folder tree lacks `core/`, `validation/`, `tests/`, `infrastructure/database` and `infrastructure/state`; the test coverage list is outdated.
- **architecture.txt**: the execution-flow order of `WeeklySimulationRunner` is wrong. The real order (`simulation_runner.py`) is: open locations, contract lifecycle, attrition, performance, career events, location transfers, growth/vacancy/recruitment, hiring, managers, absence, safety; the doc omits contracts and locations and puts transfers last. Also missing: the recruitment dimensions and `dim_candidate_quality_driver`, the `core/`, `validation/` and database/state folders in the tree, and a note that full runs are local-only with a run time.
- **CLAUDE.md**: the repo map lacks `simulation_contracts.py` and several infrastructure modules (`config_validation`, `dimension_lookup`, `dimension_factory`, `employee_status`, `departure_records`, `record_builder`, `manager_builder`); it does not state the local-only full-run rule or the Consumption limit.
- **AGENTS.md**: still says "Azure SQL and Power BI"; the web-app-primary paragraph, the virtualenv instruction and the `src/core/` map entry are missing.
- **handleiding code.md** (the most outdated document): the project structure is wrong (`src/` is shown next to `azure_function/`, `src/database/` should be `infrastructure/database/`, schemas live in `config/schemas/`); the table lists name tables that no longer exist (`dim_education_level`, `fact_employment_attribute`) and omit about 23 current tables; "Geen dubbele data" and "schrijf alleen nieuwe records" are wrong (dimensions and mutable facts are upserted); "Full alleen voor reset" contradicts README, which requires a full run after logic or schema changes; the sector config's required `"schema"` field is not mentioned; "No Python changes needed for a new sector" is optimistic (some labels are hard-coded, such as `Verzuimongeval` and `Bedrijfsongeval`); the env var list is incomplete; a stale "1098 employees" example; the plain `azurite` command differs from README.
- **handleiding Azure portal.md**: "Alle instellingen via Environment Variables" is misleading (almost all behaviour is in `maakindustrie.json` and needs a redeploy); missing settings `SQL_CONNECTION_TEMPLATE` and `HR_AVATAR_BLOB_CONNECTION_STRING`; no warning that `full` on the deployed app will time out (it also suggests running `full` there); "Zelfde seed = reproduceerbaar" should say that each week's random stream derives from the seed, year and week.

## Recruitment & eligibility

- **Qualification/certification events during employment.** Qualification
  history (`fact_employee_qualification`) is now populated at hire time, but
  there is still no simulated event for gaining a qualification *during*
  employment (e.g. a VAPRO or IT certificate obtained on the job). Without
  it, an employee's credentials never change after hire, which caps how
  realistically internal promotion/transfer eligibility can evolve over a
  long career.

## Full-run performance (accepted as-is for now)

A real full run (~6.7 simulated years) measured at roughly: burn-in 2.5 min,
weekly simulation logic ~30 min, SQL write/post-processing ~21 min (of which
`fact_workforce_snapshot` alone was ~15 min, everything else combined ~6
min). Two causes were analyzed:

- **Simulation logic (~30 min)**: `.iterrows()` is used 27 times across 17
  simulator/infrastructure files - a known slow pandas pattern (full
  per-row `Series` construction) - and `assign_managers` rebuilds the
  *entire* manager hierarchy from scratch every single week regardless of
  whether anything actually changed. Not fixed - see below.
- **`fact_workforce_snapshot` build (~15 min)**: `_performance_as_of`,
  `_performance_driver_as_of` and `manager_as_of` each re-scanned the
  *entire* `fact_performance_review`/`fact_manager_assignment` table for
  every one of the ~15,000-20,000 employee-month rows being built, instead
  of being pre-indexed by employee once (the same file's own
  `_absence_metrics_for_month` and `_indexed()` already use that pattern
  correctly - just not applied to these three lookups).

**Attempted, measured, and reverted**: built a shared `as_of_lookup.py`
(`group_by_employee`/`latest_as_of`/`active_as_of`) and applied it to
`workforce_snapshot.py` and the identical anti-pattern in
`absence_context.py`'s `sync_absence_satisfaction` (which does the same
three full-table scans per absence episode). Correct (0 mismatches against
the old logic, full test suite green with 9 new dedicated tests for the
helper), but a direct timing measurement at the actual table sizes involved
(~3,000 performance reviews, 20,000 lookups) showed it was **not faster -
roughly a 0.7x "speedup" (i.e. slightly slower)**. Root cause of the
mismatch between theory and measurement: at this scale, pandas' fixed
per-call overhead (constructing a boolean mask, slicing, building a new
Series/DataFrame) dominates over the cost of scanning more rows - trading a
scan of the whole table for a dict lookup plus a scan of a smaller table
doesn't reduce the number of expensive pandas operations, just their size.
A real fix would need to replace the per-employee-month Python loop with a
small number of bulk vectorized operations (e.g. `pd.merge_asof` for the
"most recent row as of a date" joins) - a materially bigger rewrite of
`build_workforce_snapshots`'s actual loop structure, comparable in scope and
risk to the simulation-loop vectorization below, not a quick follow-up.

Given the cost/risk of that bigger rewrite versus the benefit (an
infrequently-run demo-data generator that already completes in about an
hour), **decided not to pursue this further for now** - reverted cleanly
(confirmed back to the pre-attempt 195 passing tests). If revisited, profile
the actual snapshot-building pass first (e.g. `cProfile`) rather than
optimizing from a theoretical complexity argument again - that argument is
what led to this reverted attempt in the first place.

**Simulation-loop vectorization (`.iterrows()` -> vectorized,
`assign_managers` skip-when-unchanged) - deferred, not started.** Given the
lesson just above, do not implement this from the same kind of theoretical
"O(N) per call is bad" reasoning without profiling the actual weekly
simulation loop first to confirm iterrows overhead (rather than something
else - the recruitment funnel's per-candidate processing, or per-employee
satisfaction/engagement scoring, are equally plausible dominant costs) is
really what's driving the ~30 minutes, and by how much. Also carries a
correctness-adjacent caveat independent of profiling: several of these loops
draw from `self.rng` per row, so vectorizing changes the *sequence* in which
random draws are consumed - a given seed will produce a different (still
valid) dataset than before, not an identical one computed faster. That's a
real, deliberate discontinuity to call out clearly if this is ever
attempted, not a side effect to gloss over.

## Power BI: Profiel page (deferred, not yet implemented)

From a review of the Profiel (single-employee profile) page:

- **Current-role/department fields on `dim_employee`.** ✅ Implemented.
  `Role_Key`/`Department_Key` are now current-state convenience columns on
  `dim_employee`, synced by `assign_managers` from the same
  `_current_employment_rows`/"prefer active, else last known" context used
  for `Manager_Key` - not a replacement for `fact_employment`'s history, same
  as `Manager_Key`. Additive schema columns and FKs; picked up automatically
  by `_ensure_table_columns` on the next full or incremental SQL write, no
  manual migration needed. The Afdeling/Functie (and future Contracttype or
  salary-band) slicers can now filter `dim_employee` directly.
- **Role/department average as a second comparison reference**, alongside
  the current organization-wide average, on the KPI comparison cards
  (salary, tenure, absence, etc.) - comparing a Productiemedewerker to the
  whole-company average is a less fair comparison than to their own
  department or role. Requires editing the custom vega bar chart code -
  deferred until the user revisits it.
- **Conditional bar coloring for "lower is better" metrics** (e.g. Aantal
  dagen verzuim per jaar) - the KPI cards use one teal color regardless of
  metric direction, so a short bar reads as "notable" without indicating
  whether that's good (low absence) or bad (low salary/tenure). Also
  requires editing the custom vega bar chart code - deferred.
- **Show the employee's actual qualification**, not just the
  Opleidingsniveau filter level, from `fact_employee_qualification` - e.g.
  their highest/most relevant diploma.
- **Show a safety-incident count/flag** on the profile, now that
  `fact_safety_incident` exists.

## Power BI: page architecture - splitting Werknemers and Recruitment

Both pages have grown too large for one page each and need a redesign. Same
underlying logic for both splits, kept consistent across the report rather
than each page inventing its own rationale: process/objective content on
one page, outcome/experience content on the other.

### Werknemers -> Samenstelling (Composition & Headcount) + Beleving & Performance

**Samenstelling (Composition & Headcount)** - the objective "who are we,
how many" page. This absorbs the previously-separate composition-page idea
rather than ending up with two pages both showing department-sliced
headcount data:
- Existing: headcount trend (stacked area by department), avg years active
  by department, active-vs-ended by department - via the existing
  Afdeling/Functie/Bron/Opleidingsniveau/Performance tab pattern.
- New tabs on that same pattern: **Vestiging** (`Location_Key`) and
  **Ploegendienst** (`Shift_Key`).
- **Contract composition**: % Vast vs Tijdelijk, average FTE
  (`Contracttype`/`FTE`/`Contracturen`, already on the snapshot).
- **Gender and age composition** (`dim_employee.Gender`/`Geboortedatum`) -
  currently only visible as the leave-reasons chart's color legend.
- **In/out flow, not just net stock**: hires vs. departures per month, from
  `fact_employment[EventType_Key]` (`Aangenomen` vs `Uit dienst`).

**Beleving & Performance (Experience & Performance)** - the subjective page:
- Existing: Tevredenheid/Performance/Betrokkenheid trend + driver callout,
  satisfaction-with-bandwidth by department.
- Existing: leave-reasons chart (departure motivation is a sentiment
  question, fits here better than on the counts page).
- New: turn "Belangrijkste driver volledige periode" into a **ranked driver
  breakdown** (which drivers dominate most often, and in which direction),
  using `dim_satisfaction_driver`/`dim_engagement_driver`.
- New: **attrition rate by satisfaction band** - do employees in the lowest
  band actually leave at a higher rate; satisfaction band, attrition and
  departure reason already connect for this.

(Internal mobility rate and salary/compa-ratio were also discussed as
Werknemers candidates, but already have, or will have, their own dedicated
pages - not needed on either of these two.)

### Recruitment -> Vacatures & Pipeline + Kandidaten & Resultaten

**Vacatures & Pipeline** - is the recruiting *process* running well:
- Existing: open-vacancy KPIs (open, time to fill, >30 days open, vervuld
  totaal), time-to-fill by department.
- New: **aging open-vacancies table** - still-open vacancies sorted by days
  open (`Today - Created_Date`), flagged past the existing 30-day
  threshold - distinct from time-to-fill, which only covers vacancies that
  have already closed.
- New: **funnel chart** (Power BI's native Funnel visual) - Sollicitatie ->
  Screening -> Gesprek -> Aanbod -> Aangenomen, count reaching each stage;
  conversion % between stages comes free with that visual type.
- New: **current pipeline matrix** - rows = department, columns = stage,
  values = count of applications currently `"In behandeling"` right now -
  shows where recruiting effort is stuck today, which no historical KPI
  can show.
- New: **time-in-stage bar chart** - average days for Application ->
  Screening, Screening -> Gesprek, Gesprek -> Aanbod, Aanbod -> Decision
  (from `Screening_Date`/`Interview_Date`/`Offer_Date`/`Decision_Date`) -
  pinpoints which specific stage is the bottleneck, rather than one blended
  "time to fill" number.

**Kandidaten & Resultaten** - who applies and what happens to them:
- Existing: totaal sollicitaties KPI, the Afdeling -> Functie -> Bron
  decomposition tree of application volume, gemiddelde kandidaatskwaliteit.
- Existing: outcome distribution (Aangenomen/Afgewezen/Geweigerd) and
  candidate-quality distribution, by Afdeling/Functie/Bron.
- New: **decline and rejection reasons chart**, mirroring the leave-reasons
  chart on Werknemers (one for `dim_decline_reason`, one for
  `dim_rejection_reason`) - both dimensions exist precisely for this and
  are currently unused anywhere on the dashboard.
- Bron (source) breakdown belongs here, not on the pipeline page - "which
  channel gives us the best candidates" is an outcomes question, not a
  process one.

## Power BI: Salary page

- **Gender pay gap view** (compa-ratio or median salary by gender within
  role/department) - `dim_employee.Gender` combined with the existing
  `Salaris`/benchmark fields on the snapshot. A standard equal-pay check
  that's fully available today and currently absent from the page.
- **Compa-ratio trend over time**, not just the peildatum point-in-time KPI -
  is "% gemiddeld t.o.v. benchmark" improving or worsening year over year.
  Same fields as the point KPI, just plotted across `Snapshot_Date` the way
  the LFL salary-growth chart already does.
- **Salary vs. tenure progression** (does pay grow appropriately with
  service years) - `Aaneengesloten_Indienst_Datum` plus `Salaris`, both
  already on the snapshot.

## Power BI: Absence page

- ~~A verzuim-rate trend over time~~ - reconsidered per discussion: the page
  already has a Datum-range slicer for exploring any window, and the
  tenure/shift scatter is a more insightful view (a relationship, not just
  up-or-down) than a plain aggregate trend would add. Not pursuing this.
- **Seasonality view instead**: average verzuim% per *calendar month*
  (Jan-Dec, collapsed across all years) rather than a time-ordered trend.
  `absence.seasonal_multipliers` already drives a real recurring pattern
  into the generated data (e.g. a winter peak) that's currently invisible
  from the KPIs, the scatter, or a plain YoY trend - and unlike a generic
  trend, this is directly actionable for staffing (know which months need
  buffer coverage).
- Optional: a **Bradford-factor-style recurring-absence flag** (frequency x
  duration), fully computable from existing `fact_absence` episode data, if
  a more advanced attendance-pattern metric is wanted later.

## Power BI: Incidents page

- **No department/role/location breakdown at all**, despite
  `fact_safety_incident` carrying `Department_Key`/`Role_Key`/`Location_Key`
  specifically for this. Concretely: reuse the same tab pattern already
  established on Werknemers/Salary (Afdeling/Functie/Locatie tabs driving a
  bar-by-type chart) - same visual language already used elsewhere in the
  report, not a new one to design.
- **A recordable-incident-rate KPI** (using `dim_incident_type.Recordable`,
  already modeling the real OHS "recordable" concept) - recordable
  incidents per 100 FTE/year, styled like the Absence page's "Target: <5%"
  card, in the currently-empty bottom-left card slot.
- **Total lost workdays** as its own KPI/trend, separate from the incident
  *count* - concretely, reuse the exact quarterly stacked-bar chart already
  on the page, just swap the measure from count to `SUM(Lost_Workdays)`.
- **Ploegendienst (shift) breakdown** - the model specifically gives shift
  work a risk multiplier for incidents, so without this the relationship
  can't be seen or validated on the dashboard at all. Concretely: reuse the
  Absence page's shift-colored stacked-bar pattern directly, same visual,
  same data shape, applied to `fact_safety_incident` instead.
- **"Dagen sinds laatste incident" per department** - a safety-culture
  staple in real EHS dashboards (a "days since last incident" board per
  site/department). The overall version of this KPI already exists on the
  page; this just slices it by department.
