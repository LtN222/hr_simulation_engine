# Architecture review - 2026-09-30

A read-only review of the whole `hr_data_generator` repo at commit `c11f734`
(working tree clean). It follows on from the "Architecture review
(2026-09-25)" section in `BACKLOG.md` (items AR-01 to AR-32). Nothing in the
code, config or schema was changed.

This file has three parts:

1. Corrections to existing AR items: what has changed since 2026-09-25.
2. New findings (AR-33 onward). None of these are on the backlog yet. Numbers
   continue the AR series so they can be moved into `BACKLOG.md` unchanged.
3. Documentation gaps.

Conventions, as in `BACKLOG.md`:
- **✔ verified** means the finding was confirmed in the code and/or the live
  demo database (`db_hr_demo`) on 2026-09-30. Everything else was reported by a
  reviewer with `path:line` evidence but not independently re-checked.
- **Full run** says whether fixing the item changes historical output.
- Paths are relative to `azure_function/`. Line numbers drift.

---

## 1. Corrections to existing AR items

| Item | Status | What changed |
| --- | --- | --- |
| AR-02 | Accurate, and the live data is worse | 16 `Open` vacancies now have an `Aangenomen` recruitment row (the backlog says 4). 428 employees have more than one open `fact_manager_assignment` row: 1,442 open rows for 800 active employees. The static-dimension refresh is now at `run_simulation_incremental.py:183-193`. |
| AR-03 | Accurate | `simulation_state` is at 2026-W40 (last run 28 Sep), so the next incremental run simulates W40 again. |
| AR-06 | Accurate, one addition | If the read of existing primary keys fails, `_filter_existing_primary_key_rows` (`write_to_sql.py:234-236`) returns the full frame. The insert then fails on the primary key, after the week counter has already moved on. |
| AR-08 | Accurate, and there is a third place with the bug | `relocate_department_group` (`location_assignment.py:143`, `**row.to_dict()`) resets experience the same way. |
| AR-10 | Accurate, wording fix | The event is called `Salarisaanpassing`, not "Salarisverhoging". |
| AR-12 | Partly outdated | The "departure context copies the last snapshot" bullet is fixed: attrition and contracts now stamp scores on the departure row (`departure_records.py:53-56`), and `sync_departure_satisfaction` only fills them when missing. The other bullets still stand. |
| AR-13 | Accurate, one addition | Internal eligibility is checked as of the vacancy's `Created_Date` (`simulation_recruitment.py:714`), which is even earlier than the application date. |
| AR-18 | Accurate, and live evidence of the "open month" problem | `_snapshot_dates` includes the current month-end. The live max `Snapshot_Date` is 2026-09-30, written on 28 Sep, and that row will never be updated. |
| AR-19 | Accurate, two additions | `_ensure_table_columns` runs up to 3 times per table (`write_to_sql.py:545,590,626`). `_normalize_dataframe_for_sql` silently skips a column whose conversion fails (`:309-310`). |
| AR-23 | Accurate, one addition | The promotion compa bumps (+0.015 + perf term in `simulation_career_events.py:113`, +0.02 in `simulation_hiring.py:322-327`) are hard-coded as well. |
| AR-24 | Partly inaccurate | `generate_dimensions` uses an explicit key when the config gives one (`dimension_factory.py:30`). These are already stable: hire source, recruitment status/stage, decline/rejection reason, education, satisfaction driver, salary scale, shift, incident type, and roles/departments. Still keyed by position: `dim_location`, `dim_absence_type`, satisfaction/engagement bands, performance/engagement/candidate-quality drivers, `dim_salary_band`, `dim_event_type`, `dim_departure_reason`. |
| AR-25 | Accurate, one addition | `function_app.py:76` runs incremental for any mode other than `full`, but `:122` builds the reply from `== "incremental"`. So `HR_SIMULATION_MODE=Full` runs incremental and replies "Full HR dataset generated". `Config.simulation_mode` is also unused. |
| AR-29 | Still fully open | See part 3. It also misses README `EducationLevel_Key` (:255). |
| AR-31 | Still open | `.funcignore` also doesn't exclude Azurite state or `.pytest_cache`, so a publish probably ships them. |

AR-04, AR-05, AR-09, AR-11, AR-14, AR-15, AR-17, AR-20, AR-21, AR-22, AR-26
and AR-27 were re-checked and are still accurate as written.

---

## 2. New findings

### High

**AR-33 ✔ verified, FIXED (group 4; awaiting full run) - `Bedrijfsongeval` is drawn as ordinary sickness (high; full run: yes)**
Fixed: `absence.excluded_from_random_draw` (config) keeps it out of every absence type draw; total sickness volume is unchanged, only redistributed over kort/middellang/lang.
`dim_absence_type.Bedrijfsongeval` has `Telt_als_verzuim: true`, so
`AbsenceSimulator._choose_incident_type` (`simulation_absence.py:348-379`)
treats it as one of the sickness types. It is missing from
`absence.type_weights`, so it gets the default weight 1.0 against
0.72/0.2/0.08 for the others. Live data: 2,279 of 4,458 sickness episodes
(51%) are `Bedrijfsongeval`, against only 52 `Verzuimongeval` safety
incidents. Work accidents are hugely overstated, and none of them match a
`fact_safety_incident` row.
Direction: exclude `simulation_safety.LOST_TIME_ABSENCE_TYPE` from the absence
simulator's draw, or add a config flag such as "only created by the safety
simulator".

**AR-34 ✔ verified, FIXED (group 2; awaiting full run) - Attrition measures tenure from the current employment row (high; full run: yes)**
Fixed: `simulation_attrition.py` uses `tenure.service_years` (continuous service).
`simulation_attrition.py:114-118` uses the current `fact_employment` row's
`Startdatum`, which resets on every yearly salary review, contract renewal and
move. This is the same bug already fixed for performance reviews
(`PerformanceSimulator._tenure_days`). Live data: 765 of 800 active employees
have a current row less than 1 year old, but only 272 really have less than 1
year of service.

Effects:
- The `_tenure_multiplier` of 1.5 applies to almost everyone, and 0.7 never
  applies.
- The `tenure_years > 5` salary effect (:254) never fires.
- The departure-category and reason branches that depend on tenure (:299,
  :351) are skewed.

Direction: use `Aaneengesloten_Indienst_Datum`.

### Medium

**AR-35 FIXED (group 2; awaiting full run) - Same tenure bug in absence and safety (medium; full run: yes)**
Fixed: absence eligibility, leave `min_tenure_days` and the safety new-hire factor use `tenure.service_days`.
Three more places measure tenure from the current row's `Startdatum`:
- the absence `minimum_tenure_days` check (`simulation_absence.py:189`);
- the leave `min_tenure_days` rules (:445). Only 11 `Onbetaald verlof`
  episodes exist live; that this bug is the cause is inferred, not proven;
- the safety `new_hire_multiplier` of 1.8 within 180 days
  (`simulation_safety.py:137-141`), which effectively applies to about half of
  all employees.

Fix together with AR-34.

**AR-36 ✔ verified, FIXED (group 4; awaiting full run) - Snapshots can count a leaver on their exit date (medium; full run: no, a snapshot rebuild is enough)**
Fixed in `_active_employment`: a leaver is excluded on or after the departure date and the terminal row is never used. Still open: absence in the exit month; full-month `Beschikbare_*` for hires/leavers.
`workforce_snapshot.py:202-209` keeps rows with `Einddatum >= snapshot_date`
and doesn't exclude `Dienstverband_status == "Uit dienst"`. When someone leaves
on a month-end, the zero-length terminal row wins the dedupe and they are
counted in headcount. Live data: 12 snapshot rows point at an `Uit dienst`
employment row.

Related (low): a leaver's absence in their exit month drops out of the
snapshots, and hires and leavers get full-month `Beschikbare_*` capacity
(:327-346).

**AR-37 FIXED (group 5; awaiting full run) - Internal eligibility ignores minimum education level (medium; full run: yes; not verified)**
Fixed together with AR-09: one shared qualification + experience helper for internal and external.
`eligible_internal` (`role_eligibility.py:155-157`) checks only the
qualification name. It ignores `Min_Opleidingsniveau` and the Senior/WO rule,
which the external check enforces (:37-48, :62-70). This adds to AR-09's
internal/external consistency gap; fix them together.

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

**AR-39 - Unpinned `requirements.txt` (medium; full run: no)**
No versions are pinned. The code relies on:
- pandas 2.2 or later (`freq="ME"`);
- SQLAlchemy 2.x (`scalar_one`, `connection.commit()`).

`numpy` is imported directly but not listed. A fresh deploy could pull pandas
3.x (copy-on-write, new string dtype) and break silently.
Direction: pin the versions from the working `.venv`.

### Low / low-medium

**AR-40 ✔ verified, FIXED (group 4; awaiting full run) - Garbled `"CarriÃ¨re switch"` key (low-medium; full run: yes)**
Fixed in code and config; a validation rule now checks every `voluntary_reason_satisfaction_multipliers` key against `dim_departure_reason`.
`simulation_attrition.py:371` and config
`attrition.voluntary_reason_satisfaction_multipliers` (`maakindustrie.json:3779`)
use the mis-encoded key. `dim_departure_reason` spells it `"Carrière switch"`.
As a result, the satisfaction multiplier and the performance ≥ 4 bonus for this
reason never apply.

**AR-41 FIXED (group 5; awaiting full run) - Departure-reason semantics (low-medium; full run: yes)**
Fixed: `No-show` limited by `attrition.no_show_max_tenure_days`; `Seizoenswerker` kept but documented as unused; the unreachable `Contract niet verlengd` branch removed (its category `tijdelijk` is never drawn by attrition).
- `No-show` (weight 0.02) can be drawn for employees with any tenure,
  including 10-year veterans (`simulation_attrition.py:342`).
- `Seizoenswerker` is never produced.
- The `Contract niet verlengd` branch in `_reason_weight` (:350) can't be
  reached from attrition.

**AR-42 - Initial relevant experience is driven by age (low-medium; full run: yes; user decision)**
`initial_relevant_experience` (`relevant_experience.py:9-12`) uses a mean of
0.55 × (age − 19). Age doesn't only cap the value, it drives it. This is used
for the initial population, and for the hiring fallback when a recruitment
profile is lost (AR-04). It conflicts with the CLAUDE.md invariant "relevant
experience is not age". Decide whether a tenure-in-role-family basis is
wanted.

**AR-43 - Config keys that nothing reads, and missing keys that silently default (low; full run: only if wired in)**
Never read:
- `career_events.salary_growth`
- `qualification_events`: nothing creates in-service qualifications, so
  `Verkregen_Tijdens_Dienstverband` is always false. This overlaps the open
  "Qualification/certification events" backlog item.
- `contract_rules.*.zomer_kans`
- `initially_staffed`: 57 roles set it, but only a test reads it. README
  describes it as working.
- `HR_SIMULATION_WEEKS` / `simulation_weeks` (already in AR-25).
- the candidate-quality driver "Gebalanceerd profiel", which is never
  selected.

Read by the code but missing from config, so a default is used:
- `recruitment.external_candidate_match_probability` defaults to 0.7.
- `growth.shock_probability` / `shock_min` / `shock_max` default to 0, so the
  growth shock is off.
- `attrition` has no QHSE and no Marketing entry; both default to 0.05.
- `absence.department_multipliers` has no QHSE and no Marketing entry; both
  default to 1.0.

Direction: fold into AR-25's typed and validated config.

**AR-44 FIXED (group 5; awaiting full run) - The initial population's hire source ignores source weights (low; full run: yes)**
Fixed: `initial_population.hire_source_weights`.
`choose_hire_source` (`employee_helpers.py:14`) picks uniformly across
external sources. The `config` parameter is unused.

**AR-45 FIXED (group 5; awaiting full run) - Promotions and transfers redraw the shift (low; full run: yes)**
Fixed: `carry_or_assign_shift_key`.
`simulation_career_events.py:133,185` and `simulation_hiring.py:356` redraw
`Shift_Key` at random on every move, even within the same shift department.

**AR-46 - Performance driver is skewed (low; full run: yes)**
`_performance_driver_key` (`simulation_performance.py:337-352`) has two
problems:
- "Vakmanschap" = min(1, exp/8) is always positive and saturates, so it
  dominates for experienced staff.
- The driver is chosen by absolute value, whether the score is high or low.

**AR-47 FIXED (pipeline merge part A, awaiting full run) - A full run has two random generators with the same seed (low; full run: yes)**
Fixed: population generation uses `Random(f"{seed}:population")`; each week has its own stream.
`run_simulation.py:29` and `population.py:35` both create
`random.Random(seed)`, so population generation and the weekly loop replay the
same number stream. Fold into AR-05.

**AR-48 - Manager-assignment end dates are inconsistent (low; full run: yes)**
- A leaver's assignment closes with `Einddatum = today`
  (`manager_assignment.py:48`); a manager change closes with `today - 1 day`
  (:76).
- A leaver is closed on the date of the sync, not their actual leaving date.
  That can be up to 6 days later, so `manager_as_of` can show a manager after
  the employee has left.

**AR-49 - Hosting, security and leftovers (low)**
- The HTTP 500 reply returns `str(e)` (`function_app.py:147-150`). pyodbc
  errors include server and database names.
- `local.settings.json` (gitignored, not tracked, checked) connects as the SQL
  server admin. Suggest a least-privilege SQL user for the app.
- `config/schemas/hr_default.json` is unused since the first commit and would
  crash if selected (it has no `types`). Delete it.
- No SQL injection found: every f-string SQL uses schema-owned names, and the
  HTTP route reads no input.

**AR-51 FIXED (pipeline merge part A, awaiting full run) - The incremental run redrew the annual growth rate on every run (medium; full run: yes)**
`run_simulation_incremental.py:52` drew `annual_growth_rate` with the run's rng on every incremental run (and the full run drew it from its own stream), so the growth path changed from run to run. Fixed: derived once from `Random(f"{seed}:growth-rate")`.

**AR-50 - `dim_employee.Manager_Key` has no foreign key (low; user decision)**
It is the only non-primary `_Key` column without a foreign key. It can't
simply get one, because `dim_manager` is built from `dim_employee`. Record it
as a deliberate exception next to AR-26.

### Checked and found clean
- No unseeded randomness: no module-level `random.` or `np.random`, and
  `DataFrame.sample` is always seeded.
- Performance doesn't use absence, overtime or availability.
- Engagement drivers exclude social events and availability.
- No new fact-to-fact keys beyond AR-26.
- Every schema foreign key points to an existing primary key with a matching
  type.

---

## 3. Documentation gaps

**All docs**
- Full-run duration is inconsistent. CLAUDE.md, AGENTS.md and BACKLOG
  (:269, :634) say more than 2 hours; BACKLOG (:796-800, :838, :1310, :1574)
  says about 1 hour. Pick one current figure.
- No doc (README, architecture.txt, the handleidingen, CLAUDE.md) says that a
  full run must be started locally because of the Consumption plan's 10-minute
  limit. README "Deployen" step 3 and "handleiding Azure portal" both suggest
  running `full` against the deployed app.

**README.md**
- Stale names:
  - `dim_ploegendienst` → `dim_shift`
  - `Status_Verbose` → `Status_Omschrijving`
  - `Candidate_Quality` → `Kandidaat_Kwaliteit`
  - `SalaryStep` → `Salaris_Trede`
  - `Ploegendienst_Key` → `Shift_Key`
  - `EducationLevel_Key` → `Education_Key`
- :160-164 still describes the removed `fact_safety_incident.Absence_Key`
  link, which contradicts :338-341.
- Table lists are incomplete:
  - Missing dimensions: `dim_location`, `dim_recruitment_stage`,
    `dim_decline_reason`, `dim_rejection_reason`,
    `dim_candidate_quality_driver`, `dim_departure_reason`, `dim_event_type`.
  - Missing fact: `fact_employee_qualification`.
- :15-21 names `fte_ratio`, `active_from` and `initially_staffed`. The config
  uses `target_weight` and `active_from_headcount` / `_scope` /
  `_department(s)`, and `initially_staffed` is dead config (AR-43).
- The settings table is missing `HR_AVATAR_BLOB_CONNECTION_STRING`.
- The "Configuratie" list is missing about 15 sections, including
  `performance`, `workforce_planning`, `role_career_paths`, `dim_location`,
  `contract_hours_distribution` and `special_arrangements`.
  `initial_population` has no size key.
- The "Full run" section doesn't mention the local-only requirement or a
  duration. It says obsolete tables are removed by a full run; in fact they
  are removed on every write, and so are deprecated columns (AR-07).
- The "Incremental run" section doesn't mention that the last week is
  simulated again (AR-03), or the identical reseed (AR-05).
- The folder tree is missing `core/`, `validation/`, `tests/`,
  `infrastructure/database` and `infrastructure/state`, and
  `run_simulation*.py`.
- The test coverage list is outdated.
- Missing: what `Salaris` means (a full-time amount, regardless of
  `Contracturen`; see the new salary backlog item).

**architecture.txt**
- The execution-flow order is wrong. The real order
  (`simulation_runner.py:81-184`) is: open locations, contract lifecycle,
  attrition, performance, career events, location transfers,
  growth/vacancy/recruitment, hiring, managers, absence, safety. The doc omits
  contracts and locations and puts transfers last.
- `dim_ploegendienst` and `dim_reden_vertrek` are stale names.
- Missing: the recruitment dimensions, `dim_candidate_quality_driver` and
  `fact_employee_qualification`.
- The folder tree is missing `core/`, `validation/` and the database/state
  subfolders.
- The operational notes don't say that full runs are local-only or give a run
  time.

**CLAUDE.md**
- :101 is wrong. `test_role_eligibility.py` does test `eligible_internal`
  (3 leadership tests), `leadership_experience`, `relevant_experience` and the
  credential helpers. Only `movement_type` has no test anywhere.
- The repo map is missing:
  - `simulation_contracts.py`;
  - `run_simulation*.py`;
  - several infrastructure modules: `config_validation`, `dimension_lookup`,
    `dimension_factory`, `employee_status`, `departure_records`,
    `record_builder`, `manager_builder`.
- Missing: the local-only full-run rule and the Consumption limit.

**AGENTS.md**
- Still says "Azure SQL and Power BI". The web-app-primary paragraph is
  missing.
- Missing sections: "Calibrating a new numeric parameter" and "Recruitment,
  promotion and transfer model" (AR-29).
- Missing: the virtualenv instruction and the `src/core/` map entry.
- The fact-to-fact rule mentions only Power BI.

**handleiding code.md** (the most outdated document)
- The project structure is wrong: `src/` is shown next to `azure_function/`,
  `src/database/` should be `infrastructure/database/`, and schemas live in
  `config/schemas/`.
- The table lists name tables that no longer exist (`dim_education_level`,
  `dim_reden_vertrek`, `fact_employment_attribute`) and omit about 23 current
  tables.
- "Geen dubbele data" and "schrijf alleen nieuwe records" are wrong: the last
  week is simulated again, and dimensions and mutable facts are upserted.
- "Full alleen voor reset" contradicts README, which says a full run is
  required after logic or schema changes.
- The sector config's required `"schema"` field isn't mentioned.
- "No Python changes needed for a new sector" is optimistic: some labels are
  hard-coded, such as `Verzuimongeval` and `Bedrijfsongeval`.
- Env var list incomplete; stale "1098 employees" example; the plain `azurite`
  command differs from README.

**handleiding Azure portal.md**
- "Alle instellingen via Environment Variables" is misleading: almost all
  behaviour is in `maakindustrie.json` and needs a redeploy.
- Missing settings: `SQL_CONNECTION_TEMPLATE` and
  `HR_AVATAR_BLOB_CONNECTION_STRING`.
- No warning that `full` on the deployed app will time out.
- "Zelfde seed = reproduceerbaar" should mention AR-05.

**BACKLOG.md**
- The header says "Outstanding work only", but the file is mostly completed
  items (AR-30).
- :51-54 ("fix AR-01 first") is stale: AR-01 is fixed.
- :1570 says `burn_in_years` is "currently 2"; the config has 4.
- The "Documentation" section (:1735-1740) is partly stale (role_career_paths
  is now documented) and doesn't cover the gaps above.
