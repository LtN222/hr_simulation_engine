# Changelog

Completed work moved out of `BACKLOG.md` (AR-30): verified fixes, finished features, calibration and verification records, and the plans that produced them. Open and partly fixed items stay in `BACKLOG.md`.

- Entries are moved verbatim. A few headers gained a status (`HP-01`, `AR-03`, `AR-10`), and the items finished on 2026-10-02 carry their final status above their original description.
- Grouped by the date an entry was first recorded in the backlog (git history). An entry that was extended later keeps its original position; the extension is part of its text.
- **✔ verified** means the finding was confirmed in the code and/or the live demo database (`db_hr_demo`). **Full run** says whether the fix changes historical output.
- Item numbers (`AR-xx`, `HP-xx`, `LF-xx`) are defined exactly once, here or in `BACKLOG.md`.
- Line numbers and paths in old entries drift; search for the named function.

## 2026-10-02

### Quick wins (AR-26, AR-27, AR-29, AR-30, AR-31, AR-39, AR-43, AR-49)

These changed no simulation output (checked with a deterministic in-memory run before and after), so no full run is needed.

**AR-26 DECIDED and DONE (2026-10-02) - Fact-to-fact foreign keys (user decision)**
Decision (user, 2026-10-02): keep `fact_workforce_snapshot.Employment_Key -> fact_employment` and `fact_recruitment.Vacancy_Key -> fact_vacancy` as SQL foreign keys, documented as accepted exceptions to the "facts relate through shared dimensions" rule. They are lineage references, not reporting relationships: the web app and Power BI must not model a relationship on them. Recorded in CLAUDE.md and AGENTS.md (the invariant), README "Datamodel" and architecture.txt. `fact_employment.Previous_Employment_Key` (a self-reference) stays a separate case. A schema test (`test_the_only_foreign_keys_between_facts_are_the_accepted_lineage_exceptions`) pins the list, so a new fact-to-fact key needs a decision. No schema or simulation change; no full run.
Original description follows.
The schema still declares `fact_workforce_snapshot.Employment_Key ->
fact_employment` and `fact_recruitment.Vacancy_Key -> fact_vacancy`, and
`get_table_write_order` treats fact-to-fact references as expected. This
conflicts with the CLAUDE.md rule that facts relate only through shared
dimensions. Decide: keep them as plain columns without SQL foreign keys, or
document them as accepted exceptions. `fact_employment.Previous_Employment_Key`
(a self-reference) is a separate case.

**AR-27 FIXED (2026-10-02) - Lock and hosting details (low; full run: no)**
Fixed: `acquire_simulation_lock` now yields a `SimulationLock`. Its `verify()` runs `SELECT APPLOCK_MODE('public', <resource>, 'Session')` on the lock connection. `write_dataset` calls it before its first write (schema evolution) and again right before the data transaction, so a lost lock never lets a write through unchecked. `function_app` hands the lock to `SqlStore`.
Follow-up (2026-10-02), recovery: the lock connection sits idle for the whole run (over 2 hours for a full run) and Azure SQL can drop it, and a lost lock only matters if another run ran in between. So right after acquiring, the lock fingerprints `simulation_state` (row exists, `next_year`, `next_week`, `last_run`; a missing table or missing columns read as None, so our own schema evolution does not change it). When `verify()` finds the lock lost (dead connection or mode other than `Exclusive`), it tries ONCE to re-acquire it on a fresh connection (`sp_getapplock`, same resource, Session owner, timeout 0, through the existing connect-with-retry). Re-acquired and fingerprint unchanged: a WARNING ("simulation lock was lost while idle and re-acquired; no other run wrote in between"), the new connection holds the lock from then on, and the release at the end releases that one. Not re-acquirable (another run holds it, or reconnecting fails) or fingerprint changed: `SimulationLockLostError`, nothing is written, and the recovery is not tried again. This also applies to a full run (a concurrent run in between means overlap). Cleanup (closing the dead connection, release at the end) never raises. `.funcignore` was extended in the same pass (see AR-31). Tests (fake connections): still held (no re-acquire), lost and re-acquired with an unchanged fingerprint (warning, the new lock released at the end; dead connection and `NoLock`, with and without a state row), `verify` twice after a recovery (no second re-acquire), a second loss recovered again, re-acquire refused, reconnect failing, changed fingerprint (also a new row or a newer `last_run`), and the fingerprint itself.
Decision: `host.json` keeps `functionTimeout: -1`. A local `func start` honours it, and a local full run takes more than 2 hours; full runs stay local by decision. The Consumption plan's 10-minute cap only affects the deployed app, which only runs the weekly incremental run. Documented in README ("Full run" and "Deployen").
Original description follows.
The lock connection sits idle for the whole run; if Azure SQL drops it, the
lock is released silently and a deployed timer run could overlap with a local
full run's write. `host.json` sets `functionTimeout: -1`, which the
Consumption plan ignores (its maximum is 10 minutes).
Direction: re-check the lock or a heartbeat row before writing; set an
explicit timeout. Keep full runs local (a deliberate decision, not a defect).

**AR-29 FIXED (2026-10-02) - Documentation contradictions (low)**
Each point was checked against the current code and schema first.
- Already fixed before this pass: the README description of `fact_safety_incident.Absence_Key` (README now says there is no such key); the CLAUDE.md claim that `eligible_internal` has no tests (CLAUDE.md lists what `test_role_eligibility.py` covers, and `movement_type` has a test); `handleiding code.md` no longer names `dim_ploegendienst`; the README already states that `Salaris` is a full-time amount, and its "Incremental run" section already describes the checkpoint (next week to simulate) and the per-week random streams, so those review points are obsolete.
- Fixed now: README `dim_ploegendienst` to `dim_shift`, `Status_Verbose` to `Status_Omschrijving`, `Candidate_Quality` to `Kandidaat_Kwaliteit`, `SalaryStep` to `Salaris_Trede`, `Ploegendienst_Key` to `Shift_Key`, and `EducationLevel_Key` to `Education_Key` (the review noted this one was missing from the list); the README "Full run" text now says that obsolete tables and deprecated columns are removed on every write (AR-07), instead of leaving the impression that columns survive; `architecture.txt` `dim_ploegendienst`/`dim_reden_vertrek` to `dim_shift`/`dim_departure_reason`; `handleiding code.md` `dim_reden_vertrek` to `dim_departure_reason`; AGENTS.md now has "Calibrating a new numeric parameter" and "Recruitment, promotion and transfer model" (copied from CLAUDE.md), plus CLAUDE.md's fact-to-fact invariant and a CHANGELOG.md line.
- Also corrected while there: the README paragraph that named `fte_ratio`, `active_from` and a working `initially_staffed` (now `target_weight`, `active_from_headcount`/`active_from_scope`/`active_from_departments`, with `initially_staffed` and `qualification_events` described as not read, see AR-43); the README `dim_role` paragraph now lists the eligibility columns; `fact_employee_qualification` is described in README and architecture.txt.
- The stale "Documentation" section of BACKLOG.md was fixed in the same way and removed.
- Not part of this item and still open: the wider, unnumbered documentation gaps of the 2026-09-30 review; see "Documentation gaps still open" in BACKLOG.md.
Original description follows.
- `README.md`:
  - still describes `fact_safety_incident.Absence_Key` as the incident-absence
    link (~lines 160-164), although elsewhere it says no such key exists;
  - mentions `Status_Verbose` (schema: `Status_Omschrijving`),
    `Candidate_Quality` (`Kandidaat_Kwaliteit`), `SalaryStep`
    (`Salaris_Trede`), `Ploegendienst_Key` (`Shift_Key`) and
    `dim_ploegendienst` (`dim_shift`);
  - does not say that obsolete columns survive a full run.
- `architecture.txt` and `handleiding code.md` still name `dim_ploegendienst`
  and `dim_reden_vertrek`.
- `CLAUDE.md` says `eligible_internal` has no tests; `test_role_eligibility.py`
  has three (leadership branches only).
- `AGENTS.md` lacks CLAUDE.md's "Calibrating a new numeric parameter" and
  "Recruitment, promotion and transfer model" sections.

**AR-30 DONE (2026-10-02) - Split this backlog into open work and a changelog (low)**
Done: completed items were moved verbatim into CHANGELOG.md, grouped by the date they were first recorded; BACKLOG.md keeps the open and partly fixed items, the deferred Power BI sections and the standing decisions. The open items of the 2026-09-30 review were moved into the "Architecture review (2026-09-25)" section and its done items into CHANGELOG.md, and architecture_review.md was deleted (nothing unique was left; git history has it). Resolved on the way: the "Outstanding work only" header (now true), the "next up" pointer, the "fix AR-01 first" paragraph (kept in CHANGELOG.md with AR-01) and the stale "Documentation" section (AR-29). The review's duplicate entry for AR-51 was dropped (BACKLOG.md's version was kept). The remark "`burn_in_years` (currently 2 ...)" sits inside a dated record in the changelog (the config now has 4) and was left as written.
Original description follows.
The header says "Outstanding work only", but about 35 sections are completed
(✅) items, and the "Documentation" item is stale. Move completed items to a
`CHANGELOG.md` or decisions file so this file lists open work only.

**AR-31 FIXED (2026-10-02) - Repo hygiene (low)**
Done: `/~/` is added to the root `Demo_Dashboards/.gitignore`, which is now tracked (committed in baed647; it was untracked when this item was written). The stray `Demo_Dashboards/~/` folder (a mis-expanded duplicate clone of mcp-sqlserver) was not deleted; the user removes it. `azure_function/src/database/__pycache__` is deleted: the layout is gone, `src/database` held only that folder. Both Azurite state locations were already ignored: `hr_data_generator/.gitignore` for the project root and `azure_function/.gitignore` for `azure_function/` (checked with `git check-ignore`). `.funcignore` was extended afterwards (2026-10-02): it now also excludes `.pytest_cache/` and the Azurite state (`.azurite/`, `AzuriteConfig`, `__azurite_db_*.json`, `__blobstorage__/`, `__queuestorage__/`); `images/` (the avatar feature) and `config/` are deliberately not excluded.
Original description follows.
- `../~/.claude/mcp-sqlserver` in the `Demo_Dashboards` git root is an
  untracked nested git repo created by a mis-expanded `~`, and `../.gitignore`
  is untracked; a `git add -A` from the parent folder would embed that repo.
- `azure_function/src/database/__pycache__` is left over from an old layout.
- Azurite state exists in both the project root and `azure_function/`.

**AR-39 FIXED (2026-10-02) - Unpinned `requirements.txt` (medium; full run: no)**
Fixed: `azure_function/requirements.txt` pins the direct dependencies to the versions in the working `.venv` (`pip freeze`): azure-functions 1.24.0, pandas 3.0.1, numpy 2.4.3 (added: it is imported directly but was not listed), sqlalchemy 2.0.48, faker 40.11.1, pyodbc 5.3.0 and azure-storage-blob 12.30.0. Nothing was upgraded; transitive dependencies stay unpinned. Note: the venv already runs pandas 3.x, which the original text below feared would break silently. The test suite, including the slow pipeline-equivalence tests, passes on it, so the pin now guards against an unnoticed future jump instead.
Original description follows.
No versions are pinned. The code relies on:
- pandas 2.2 or later (`freq="ME"`);
- SQLAlchemy 2.x (`scalar_one`, `connection.commit()`).

`numpy` is imported directly but not listed. A fresh deploy could pull pandas
3.x (copy-on-write, new string dtype) and break silently.
Direction: pin the versions from the working `.venv`.

**AR-43 FIXED (2026-10-02) - Config keys that nothing reads, and missing keys that silently default (low; full run: no)**
Fixed, without changing behaviour (a narrow in-memory harness gave identical tables before and after):
- Keys read by the code but missing from `maakindustrie.json` were added with exactly their code default: `recruitment.external_candidate_match_probability` 0.7; `growth.shock_probability` 0.0, `growth.shock_min` -20 and `growth.shock_max` 30 (the code defaults for min and max are -20 and 30, not 0; they are never used while the probability is 0); `attrition.QHSE` and `attrition.Marketing` 0.05; `absence.department_multipliers.QHSE` and `.Marketing` 1.0.
- Keys that nothing reads were removed: `career_events.salary_growth` and `contract_rules.*.zomer_kans`.
- Kept, and README now describes them correctly: `qualification_events` (reserved for the open "Qualification/certification events during employment" item; not read by the simulation) and `initially_staffed` (not read by the simulation, only by a test).
- Kept on purpose: the candidate-quality driver "Gebalanceerd profiel" in its dimension (never selected). Removing a dimension entry shifts the positional keys (AR-24).
- `HR_SIMULATION_WEEKS` / `simulation_weeks` stays under AR-25, whose typed and validated config is still open.
Original description follows.
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

**AR-49 FIXED (2026-10-02) - Hosting, security and leftovers (low)**
Fixed: the HTTP 500 reply no longer returns `str(e)` on the deployed app. It returns a generic message with a reference (a short id and a UTC timestamp) and the full exception is always logged with `logging.exception` under the same reference. When `AZURE_FUNCTIONS_ENVIRONMENT == "Development"` (set by `func start`) the reply keeps the full error text, so a failing local full run still shows its error in the reply. Tests: `test_function_app_errors.py`. `config/schemas/hr_default.json` is deleted (nothing referenced it).
Decision (user, 2026-10-02): the SQL admin login stays. `local.settings.json` connects as the SQL server admin; that is deliberate for this demo, because the generator is not public-facing. No least-privilege SQL user is planned and README gets no such recommendation.
Original description follows.
- The HTTP 500 reply returns `str(e)` (`function_app.py:147-150`). pyodbc
  errors include server and database names.
- `local.settings.json` (gitignored, not tracked, checked) connects as the SQL
  server admin. Suggest a least-privilege SQL user for the app.
- `config/schemas/hr_default.json` is unused since the first commit and would
  crash if selected (it has no `types`). Delete it.
- No SQL injection found: every f-string SQL uses schema-owned names, and the
  HTTP route reads no input.

### Verified in the full run of 2026-10-02 (fixes committed 2026-10-01 and 2026-10-02)

**HP-03 ✔ verified, FIXED - Salaries dip below the indexed legal minimum between reviews (high; full run: yes)**
Verified in the full run of 2026-10-02 (baseline_headcount 100, burn-in 4 years, up to 2026 week 40): 0 of 16,739 snapshot rows and 0 `fact_employment` rows of any event type are below the floor of their date; 102 snapshot rows (0.6%) sit exactly at it; 23 `Minimumloonaanpassing` rows (1-4 per indexation date, 2021-2026), each exactly at the step value on the first Monday on or after 1 January / 1 July; no zero-length row follows one.
Fixed: `SalaryPolicy.legal_minimum` is now step-wise (indexation on 1 January and 1 July, `legal_minimum_salary.indexation_months`), and the weekly runner adds the `Minimumloonaanpassing` event (`simulate_minimum_wage_adjustments`) as its first salary step. Decisions: own event type appended at the END of `dim_event_type` (AR-24: keys come from list position); not counted as a salary review (`_already_reviewed_this_year` keys on `Salarisaanpassing` only) and not a promotion/transfer (career momentum only reads those two); skipped for an employee whose certain annual review falls in the same week (the review applies the floor; avoids two rows on one day), but not for someone who joined this year or when `salary_increase_rate` < 1; no persisted state (weeks are contiguous), identical in full and incremental runs. Measured: step values 2020-2027 below; share exactly at the floor 0.4-3.1% per role/year (before 0.5-3.6%, no retuning); the small invariant run (60 employees, 2023-01 to 2025-01) produces 1 adjustment row in 2024 and 2 in 2025 and 0 snapshot rows below the floor (without the step: 2 of 2,484 rows, max EUR 211). Step values (1 Jan / 1 Jul): 2020 29,036 / 29,396; 2021 29,764 / 30,130; 2022 30,507 / 30,883; 2023 31,270 / 31,655; 2024 32,051 / 32,448; 2025 32,854 / 33,258; 2026 33,674 / 34,089; 2027 34,516 / 34,941. Original description follows.
Found in the first full run after HP-01 (2026-09-30, baseline_headcount 50,
as of 2026-09-16). 258 of 8,301 `fact_workforce_snapshot` rows (3.1%) are
below the floor that applies on their snapshot date, by at most EUR 965
(about 2.8%).

In `fact_employment`, rows that copy the previous salary also start below
the floor of their own start date: "Contract verlengd" (3 rows, up to
-392) and "Uit dienst" (4 rows, up to -676). Another 9 "Aangenomen"/
"Salarisaanpassing" rows are EUR 15-17 below in a SQL approximation of the
floor formula; that is probably rounding in the check itself (not verified).

Cause: `SalaryPolicy.legal_minimum(date)` rises continuously (2.5% a
year via the market growth factor), but a salary only rises at hire,
promotion/transfer and the annual review. Someone at or near the floor
therefore falls below it within months. In reality the Dutch minimum
wage is indexed on 1 January and 1 July, and employers must raise pay on
those dates.

Proposed fix (to decide when picked up):
- Make the floor step-wise: constant from each 1 January / 1 July, still
  indexed backwards from `legal_minimum_salary.reference_year`.
- Add a minimum-wage adjustment on those dates: every active employee
  below the new floor gets a `Salarisaanpassing` row that brings `Salaris`
  up to the floor. This is either a small weekly step in the runner, or
  part of the salary-review simulator.
- Rows that copy a salary (renewal, location transfer, relocation,
  departure) never need their own floor once the step adjustment exists,
  but a test should assert that no active row is below the floor on any
  snapshot date.
- Validate with a narrow harness: 0 snapshot rows below the floor, and
  the share exactly at the floor stays low.

Bundle this with the next history-changing change; it needs a full run.

**HP-04 ✔ verified, FIXED - Satisfaction and engagement scores are far too compressed; the outer bands never occur (medium-high; full run: yes)**
Verified in the full run of 2026-10-02 (16,739 snapshot rows, 2020-01 to 2026-10), against the previous dataset (old code, up to 2026-08):
- Satisfaction: mean 6.56 -> 6.84, sd 0.56 -> 1.11, bands 0 / 18.1 / 77.8 / 4.1 / 0% -> 1.8 / 20.7 / 50.2 / 20.0 / 7.3%; between / within sd 0.56 / 0.15 -> 1.00 / 0.58.
- Engagement: mean 6.35 -> 6.49, sd 0.62 -> 1.16, bands 0.1 / 25.2 / 72.2 / 2.5 / 0% -> 3.9 / 30.7 / 46.3 / 14.8 / 4.4%; between / within sd 0.59 / 0.17 -> 1.03 / 0.65.
- Correlation 0.77 -> 0.60. Scores at the 10.0 cap: 23 satisfaction and 31 engagement rows (0.2%).
- Over 2024-2025, 90.9% of employees present for all 24 months spent at least 3 months outside their usual band; 42.9% visited at least 3 bands.
- Annualized leave-next-month rate by satisfaction band: Zeer laag 34.5%, Laag 21.4%, Neutraal 15.4%, Hoog 14.9%, Zeer hoog 7.2% (before: Laag 19.2%, Neutraal 14.8%, Hoog 11.0%), so the outer-band multipliers now apply. Overall turnover 15.8% -> 16.3% a year.
- The live means sit slightly above the harness (6.84 vs 6.74) and "Zeer laag" below it (1.8% vs 3.5%), as expected now that dissatisfied employees leave faster: the harness had no attrition selection. Accepted; no recalibration.
- Drivers: "Beloning|Negatief" 55% -> 35%; "Geen dominant" 2.0% -> 2.2% (satisfaction) and 12.7% -> 13.0% (engagement).
- Absence (verzuim): 3.4-5.0% of hours a year (before 5.0-6.4%; different population and headcount, not attributed to HP-04).
- Open observation, not caused by HP-04: Kwaliteit has the highest turnover (22.2% a year, 23 of 26 departures voluntary, against a base rate of 0.07) despite above-average satisfaction (7.08). Techniek is lowest (8.6%). The previous dataset also had Kwaliteit above its base rate (14.6%). Worth a narrow check of the other attrition multipliers (age, tenure, engagement) for Kwaliteit if it shows up again.
Fixed: the random parts are normal (`stable_normal`, each `*_spread` is a real sd), a stateless smoothed time-varying part per employee and month was added (`time_varying`: `sd`, `window_months`, `shared_fraction`), the factor effects were scaled up, and attrition/absence read their cut-offs from the band dimensions (`band_thresholds.py`; AR-23: the 4.5/6.0/7.5/8.5 satisfaction cut-offs, the 6.0/7.5 engagement cut-offs, the 6.0/8.5 category thresholds, the 6.0/7.5 reason groups and the absence 6.0/7.5 thresholds). `driver_selection.low_score/high_score` stay (driver thresholds, not bands). New config validation: five ordered, contiguous bands per dimension and sane `time_varying` values.

Final values. Satisfaction: `baseline_mean` 7.0 -> 7.2, `individual_spread` 0.45 -> 0.5, `manager_effect_spread` 0.45 -> 0.5, `team_effect_spread` 0.2 -> 0.25, `culture_effect_spread` 0.15 -> 0.2, `time_varying` {sd 0.55, window_months 6, shared_fraction 0.3}, factor effects x1.35 (compa -1.15/-0.55/+0.15/+0.25 -> -1.5525/-0.7425/+0.2025/+0.3375, `performance_effect` 0.25 -> 0.3375, tenure, department and career-momentum effects x1.35). Engagement (revised after review, see "Engagement: pay is bounded context" below): `baseline_mean` 6.7 -> 6.61, `individual_spread` 0.45 -> 0.57, new `individual_shared_fraction` 0.7, `manager_effect_spread` 0.35 -> 0.3, `satisfaction_effect` 0.5 -> 0.15, `constructive_contribution_effect` 0.7 -> 4.0, `performance_effect` 0.22 -> 0.5, `time_varying` {sd 0.6, window_months 6, shared_fraction 1.0}, `compa_ratio_adjustments` unchanged at -0.45/-0.2/0.0/+0.08/+0.12, department effects x1.7 (Productie -0.17, Logistiek -0.136, Techniek -0.05, R&D/IT/Directie +0.17, Sales +0.085) and career momentum promotion 0.35 -> 0.6, transfer 0.15 -> 0.25, stagnation -0.3 -> -0.5. The attrition multipliers, department base rates and absence multipliers were NOT changed.

Measured with a narrow harness (800 employees, real department mix, 24 month-ends; the model called directly):

| | Before | After | Target |
|---|---|---|---|
| Satisfaction mean / sd | 6.66 / 0.65 | 6.74 / 1.21 | 6.75 / ~1.2 |
| Satisfaction bands (Zeer laag..Zeer hoog) | 0 / 16.5 / 74.0 / 9.4 / 0.1 % | 3.5 / 22.7 / 46.3 / 20.9 / 6.6 % | 3 / 24 / 47 / 19 / 7 % |
| Satisfaction between / within sd | 0.65 / 0.08 | 1.10 / 0.52 | within a visible share |
| Satisfaction explained by observable factors | 58% | 31% | 25-35% |
| Engagement mean / sd | 6.36 / 0.61 | 6.40 / 1.19 | 6.4 / ~1.2 |
| Engagement bands | 0.3 / 25.6 / 71.7 / 2.4 / 0 % | 5.3 / 31.5 / 45.6 / 13.6 / 4.1 % | 6 / 31 / 45 / 14 / 4 % |
| Engagement between / within sd | 0.61 / 0.10 | 1.02 / 0.62 | |
| Engagement observable sources | (see decomposition) | contribution signals largest; pay (direct + indirect) 5.6% of variance vs 27.0% for satisfaction | contributions largest, pay <= ~half of satisfaction's share |
| Correlation satisfaction-engagement | 0.79 | 0.58 | ~0.6 |
| Employees >= 3 months outside their usual satisfaction band (24 months) | 9% | 85% | |
| Employees visiting >= 3 different satisfaction bands | 0% | 35% | |

Knock-on effects (4,000-employee sample for the per-department rows): expected annual turnover overall 12.74% -> 12.94%, per department between -2.6% and +4.0% of the original (Directie +4.0%, HR +3.5%, Productie +2.0%, IT -2.6%; all within +-10%, so no attrition multipliers were rescaled); mean absence satisfaction multiplier 1.0137 -> 1.0154 (+0.2%); performance reviews with the engagement effect: mean 3.317 -> 3.325, share >= 4.0 6.8% -> 7.3%, >= 4.5 0.43% -> 0.57% (the calibrated targets are mean ~3.36, ~7.5%, ~0.5%); satisfaction drivers: "Beloning|Negatief" 43% -> 36%, "Geen dominant aandachtspunt" 1.2% -> 0.5% (does not become dominant); engagement drivers unchanged in shape (they come from uniform contribution signals; "Geen dominant aandachtspunt" 13.2% -> 13.0%, no change to `driver_dominance_threshold` needed). Not calibrated against a real full run: recheck the live distributions after the next full run.

**Engagement: pay is bounded context (decision, revision of the first HP-04 calibration).** The first calibration multiplied all of engagement's factor effects by 2.7, pay included, so a "well below market" employee lost about -1.55 engagement points through pay (direct -1.215 plus 0.22 x satisfaction's -1.5525), as much as their satisfaction loss, while the reported engagement driver (contribution signals only) could not explain it. Decision: pay must weigh clearly less on engagement than on satisfaction. Rule (enforced by a unit test, per compa band and on a 0.01 grid): the TOTAL pay effect on engagement (direct + `satisfaction_effect` x satisfaction's pay effect) is at most 55% of satisfaction's pay effect, in absolute value. Direct pay effects were restored to -0.45/-0.2/0.0/+0.08/+0.12 and `satisfaction_effect` lowered to 0.15 (the rule caps it near 0.155 because of the "boven" band). Total pay effect on engagement now: ratio 0.8 or lower -0.683 (satisfaction -1.552, 44%), 0.9 -0.311 (-0.743, 42%), 1.1 +0.110 (+0.203, 54%), 1.2 or higher +0.171 (+0.338, 51%). Satisfaction's calibration is unchanged. The engagement spread now comes from what engagement is about: `constructive_contribution_effect` 0.7 -> 4.0 (the aggregate stays the bounded mean of the six uniform signals; its tails were wide enough, so no normal aggregate), plus performance/career effects at a moderate level. To keep the correlation with satisfaction near 0.6 despite the lower `satisfaction_effect`, engagement shares 70% of the variance of its personal part with satisfaction's personal preference draw (`individual_shared_fraction`) and all of its time-varying part with satisfaction's life-circumstances draw (`shared_fraction` 1.0). The target "observable factors explain 25-35% of engagement" is replaced by: the contribution signals are the largest observable source and pay (direct + indirect) is at most about half of its share in satisfaction.

Engagement variance decomposition (share of the score variance; the remainder is covariance between parts):

| Part | First calibration | Now |
|---|---|---|
| Contribution signals | 0.5% | 16.6% |
| Pay (direct) | 18.1% | 2.5% |
| Pay via satisfaction | 1.4% | 0.6% |
| Other inherited satisfaction | 3.4% | 1.6% |
| Performance / career | 5.1% | 3.1% |
| Department | 1.8% | 0.7% |
| Random: personal | 19.2% | 24.5% |
| Random: manager | 6.4% | 6.4% |
| Random: time-varying | 25.7% | 25.8% |
| Covariances (remainder) | 18.5% | 18.2% |

Original description follows.
Found by the user on 2026-10-01, in the full run with baseline_headcount 50.
In `fact_workforce_snapshot`, satisfaction has a mean of 6.56, a standard
deviation of only 0.56, a range of 4.89-8.18 and a 1st-99th percentile of
5.35-7.73.
- Satisfaction: 0 rows in "Zeer laag" and 0 in "Zeer hoog".
- Engagement: mean 6.35, standard deviation 0.62, range 4.40-7.93; 11 rows
  in "Zeer laag" and 0 in "Zeer hoog".
- The standard deviation between employees (0.56) is as large as the
  total, so scores barely move over time.

Root causes (`src/infrastructure/satisfaction.py`; engagement.py has the
same pattern):
- `_stable_value` returns a uniform value in [-1, 1]. Each component is
  `uniform * spread`: individual 0.45, manager 0.45, team 0.20, culture
  0.15. So a "spread" of 0.45 is a uniform range of +-0.45 with a standard
  deviation of only about 0.26, and the total has hard limits. Reaching
  8.5 needs nearly every component at its maximum at once.
- Every component is stable per employee or manager. There is no
  time-varying part (a difficult period, a good year), so nobody passes
  through the outer bands temporarily.
- The mean sits about 0.45 below `baseline_mean` 7.0, through the pay,
  department and tenure adjustments.

Why the bands should NOT simply be moved: attrition uses the same
thresholds, hard-coded at 4.5/6.0/7.5/8.5 (`simulation_attrition.py`
~260-266 and ~292-294, AR-23). So `attrition.satisfaction_attrition_multipliers`
`zeer_laag` (1.8) and `zeer_hoog` (0.7), and the "satisfaction >= 8.5"
voluntary/employer split, never apply. Moving the band boundaries would
not fix that; it would only make the bands and the attrition logic
disagree.

Recommended direction (to confirm when picked up):
1. Make the stable components normally distributed: map the hash value
   through the inverse normal CDF (`statistics.NormalDist().inv_cdf`),
   which is still deterministic, and treat each `*_spread` as a real
   standard deviation.
2. Add a small, slowly varying personal component, deterministic per
   employee and month (for example a smoothed hash value or an AR(1) with
   seeded draws), so scores move over time and people pass through the
   outer bands for a while.
3. Calibrate with a narrow harness. Targets agreed with the user on
   2026-10-01:
   - Satisfaction: mean 6.75 (the middle of "Neutraal", 6.0-7.49),
     standard deviation about 1.2. The bands come out at about 3% "Zeer
     laag" (<= 4.49), 24% "Laag", 47% "Neutraal", 19% "Hoog" and 7% "Zeer
     hoog" (>= 8.5). This deliberately tilts slightly positive, as real
     surveys do. The pay factor's asymmetric effects may make the low tail
     slightly longer (3-4% "Zeer laag"), which is fine.
   - Engagement: mean 6.4, standard deviation about 1.2. The bands come out
     at about 6% "Zeer laag", 31% "Laag", 45% "Neutraal", 14% "Hoog" and
     4% "Zeer hoog". It is lower than satisfaction and tilts the other way,
     because engagement measures going beyond the role, not being content.
   - At about 180 employees, 3% is roughly 5 people per month-end; the
     time-varying part spreads that over more different people across a
     year. Small departments will often show 0 in a given month, which is
     expected.
   - Correlation between satisfaction and engagement: about 0.6 (real
     surveys show roughly 0.5-0.7). They move together, but stay distinct
     concepts (CLAUDE.md). Engagement inherits part of satisfaction's
     spread through `satisfaction_effect`, so calibrate both together.
   - Explained share: the known factors (pay, career/performance/tenure,
     department) explain about 25-35% of each score's variance. Scale
     those factor effects up along with the wider random parts, so pay and
     career stay visibly meaningful per employee.
   - The normal distribution only replaces the random parts (personal
     preference, manager quality, team fit, culture fit, and the new
     time-varying part). The factor-driven parts and the driver logic stay
     as they are.
4. Read the attrition satisfaction/engagement cut-offs from the band
   dimensions or config, instead of the hard-coded 4.5/6.0/7.5/8.5 (part
   of AR-23), so bands and attrition always agree.
5. Measure the knock-on effects before and after, and recalibrate where
   needed: attrition (the 1.8 / 0.7 multipliers now really apply, so
   turnover changes), absence (`satisfaction_incident_multipliers`),
   engagement (`satisfaction_effect` 0.5) and, through engagement, the
   capped performance effect. Report the turnover per department before
   and after.

Keep the bands as they are (absolute 1-10 cut-offs). They are the
reporting vocabulary, and percentile-based bands would hide real changes
over time.

**LF-01 ✔ verified, DONE - Model a shift allowance (ploegentoeslag) (medium; full run: yes)**
Verified in the full run of 2026-10-02: all 2,823 `fact_employment` rows have `Ploegentoeslag` = round(Salaris x 0 / 0.12 / 0.20) for their shift (0 mismatches, 0 NULLs); all 16,739 snapshot rows equal their employment row. Share of active employees with an allowance on 2026-09-30: Productie 67.0% (expected ~67%), Techniek 34.3% (~34%), Logistiek 25.5% (~36%; n = 47, within noise). Average allowance: 2-ploeg EUR 5,400-7,300, 3-ploeg EUR 9,300-10,100 a year.
Decisions: a separate Dutch column `Ploegentoeslag` (INT, EUR per year, the same full-time basis as `Salaris`) on `fact_employment` and `fact_workforce_snapshot`, so `Salaris` stays the base pay that the minimum-wage floor, the benchmark, `Streef_Compa_Ratio`, the gender-pay-gap calibration and the satisfaction pay input compare. Percentages of `Salaris` per shift type in `shift_allowance.percentages` (Niet van toepassing 0, Dag 0, 2-ploeg 0.12, 3-ploeg 0.20; first-pass values, not calibrated), one set for all departments; validated in config (every shift has one, 0-0.5). Computed in one helper (`src/infrastructure/shift_allowance.py`) and derived for every employment row in `post_process` from the row's own `Salaris` and `Shift_Key`, so no row builder changed and full and incremental runs match; the snapshot copies it. Not included in `Salaris`, the floor, benchmarks, compa-ratio, reviews or satisfaction/engagement. A gender pay gap on total pay will be larger than on `Salaris`. See LF-04 for the optional pay-input follow-up. Original description follows.
Shift work is modelled (`Shift_Key`, `ploegendienst_assignment`, with safety
and absence multipliers). In group 4, Techniek and Logistiek get shift roles
as well. But `Salaris` contains no shift allowance, so a 3-ploeg operator
earns the same as a day worker in the same role and step. Dutch
manufacturing CAOs typically pay a percentage on top of base pay, depending
on the shift type; a common order of magnitude is 2-ploeg about 10-15% and
3-ploeg about 20-30%.

To decide when this is picked up:
- A separate column (for example `Ploegentoeslag`, in Dutch per the naming
  convention) or included in `Salaris`? A separate column keeps `Salaris`
  comparable with the market benchmark and keeps the minimum-wage floor
  about base pay.
- Percentages in config per shift type, possibly per department.
- Effects on satisfaction/engagement (the pay input), benchmark status and
  the gender pay gap calibration.

**AR-14 ✔ verified, FIXED (group 5) - Absence episodes are not cut off at departure (medium; full run: yes)**
Verified in the full run of 2026-10-02: 0 absence episodes end after the employee's departure date and 0 leavers have an open episode. Also verified (group 4): 0 snapshot rows on or after an employee's departure date.
Fixed: `close_open_absence` in `departure_records.py`, called from attrition and contract non-renewal.
Episodes are capped only at creation (`simulation_absence.py:~587-619`).
Attrition and lapsed contracts never shorten open episodes, so
`Verzuim_Werkdagen`/hours are counted after someone has left.
Direction: a shared departure step that closes open episodes.

## 2026-09-30 - Groups 1-5, the pipeline merge and the architecture review

### Plan and decisions (work order agreed with the user on 2026-09-30)

Work order. Groups 1-4 have priority over everything else:

1. **Group 1 - Salary:** HP-01 plus AR-10. **Code, tests and docs done; awaiting the full run.**
   - All four salary paths go through one `SalaryPolicy` floor helper.
   - The lowest medians and Schaal A/B minimums are raised so the floor is
     rarely hit.
   - Calibrate with a narrow harness: under about 5% of salaries exactly at
     the floor, and the gender pay gap still at about 4-5%.
2. **Group 2 - Tenure from the continuous service date:** AR-34, AR-35 and
   AR-08. One shared continuous-service helper, plus `carried_experience`
   for renewals and relocations. **Code, tests and docs done; awaiting the
   full run.** Helper: `src/infrastructure/tenure.py`. Expected effect (narrow
   harness): attrition tenure multiplier 1.49 to 1.07 (about 13.3% to 10.0%
   expected annual turnover before satisfaction/engagement effects); safety
   new-hire multiplier share 52% to 11%. Attrition/safety config was not
   retuned; that is the user's decision.
3. **Group 3 - Names and gender:** HP-02 plus the Expat name fix.
   **Code, tests and docs done; awaiting the full run.**
4. **Group 4 - Shift work, small data-correctness fixes and safety
   recalibration:** shift roles in Techniek/Logistiek, AR-33, AR-36, AR-40 and
   the safety base rates. **Code, tests and docs done; awaiting the full
   run.** Decisions: Monteur, Teamleider Technische Dienst, Magazijnmedewerker
   and Teamleider Logistiek work shifts, with per-department mixes in
   `ploegendienst_assignment.by_department` (Techniek 40/30/30, Logistiek
   50/50/0); a leaver is excluded from a month-end snapshot on or after their
   departure date (out of scope, still open: absence in the exit month
   dropping out of snapshots, and full-month `Beschikbare_*` capacity for
   hires/leavers); attrition config unchanged (the lower turnover after group
   2 is accepted) and absence rates not retuned; safety targets live in config
   (`safety.target_incident_rate_by_department`); the shift allowance stays
   LF-01.
   **Group 5 - Consistency fixes:** AR-14, AR-11, AR-45, AR-44, AR-41, and
   AR-09 with AR-37. **Code, tests and docs done; awaiting the full run.**
   Decisions: an open absence episode is shortened to end on the departure
   date (inclusive, workdays/hours recomputed with `absence_calendar.py`) on
   every departure path (attrition incl. retirement, contract non-renewal);
   snapshots show `Aanvangs_Prestatie_Score` before the first review and keep
   the employment row's `SalaryScale_Key`; promotions/transfers/internal
   mobility keep the shift within a department (`carry_or_assign_shift_key`);
   the initial hire source uses `initial_population.hire_source_weights`
   (measured mix: Vacaturebank 52.5, Campus 14.8, Interne recruiter 14.7,
   Referral 11.4, Recruitmentbureau 6.7); `No-show` only within
   `attrition.no_show_max_tenure_days` (30) of continuous service,
   `Seizoenswerker` stays in `dim_departure_reason` (AR-24 positional keys)
   but is unused (no seasonal contracts, `zomer_kans` is dead config, AR-43),
   the unreachable `Contract niet verlengd` branch in `_reason_weight` was
   removed; internal eligibility uses `carried_experience` and the same
   qualification and experience helper as external hiring, with the internal
   performance floor and first-leadership threshold in
   `career_events.internal_min_performance` (2.7) and
   `internal_first_leadership_min_experience_years` (3). Of AR-23, only these
   two eligibility thresholds moved to config (values unchanged); the rest of
   AR-23 is still open. Promotion/transfer rates were not retuned.
5. **One full run** after groups 1-5, only after the user explicitly approves
   it. Groups are batched so a single full run covers all of them.
6. **Pipeline merge** (AR-20, absorbing AR-02 to AR-06): important, but only
   after groups 1-4.
7. **Speed work** (AR-17 remainder to AR-19): later, if there is room.

### Architecture review of 2026-09-30 (read-only, commit `c11f734`)

The review followed on from the "Architecture review (2026-09-25)" section of `BACKLOG.md`. Its new findings (AR-33 onward) are below or in `BACKLOG.md`; its corrections to older items and its documentation gaps were folded into the entries concerned. Paths are relative to `azure_function/`.

#### Checked and found clean
- No unseeded randomness: no module-level `random.` or `np.random`, and
  `DataFrame.sample` is always seeded.
- Performance doesn't use absence, overtime or availability.
- Engagement drivers exclude social events and availability.
- No new fact-to-fact keys beyond AR-26.
- Every schema foreign key points to an existing primary key with a matching
  type.

---

#### Review notes on items that were still open on 2026-09-30 and are fixed now

- **AR-02**: *"Accurate, and the live data is worse":* 16 `Open` vacancies now have an `Aangenomen` recruitment row (the backlog says 4). 428 employees have more than one open `fact_manager_assignment` row: 1,442 open rows for 800 active employees. The static-dimension refresh is now at `run_simulation_incremental.py:183-193`.

- **AR-03**: *"Accurate":* `simulation_state` is at 2026-W40 (last run 28 Sep), so the next incremental run simulates W40 again.

- **AR-06**: *"Accurate, one addition":* If the read of existing primary keys fails, `_filter_existing_primary_key_rows` (`write_to_sql.py:234-236`) returns the full frame. The insert then fails on the primary key, after the week counter has already moved on.

- **AR-08**: *"Accurate, and there is a third place with the bug":* `relocate_department_group` (`location_assignment.py:143`, `**row.to_dict()`) resets experience the same way.

- **AR-10**: *"Accurate, wording fix":* The event is called `Salarisaanpassing`, not "Salarisverhoging".

#### Groups 1-5 (salary, tenure, names, shift work and safety, consistency)

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

**HP-01 ✔ verified, FIXED (group 1) - Full-time salaries fall below the Dutch minimum wage (high; full run: yes)**
The legal minimum is about €31,179 per year at 40 hours per week. A full-time
week in this company is 40 hours (`workforce.full_time_weekly_hours`).
Requirement: no employee at 1.0 FTE may earn less than €31,179. A lower salary
is allowed only below 1.0 FTE, and then only pro rata: minimum × FTE.

Live evidence (`fact_workforce_snapshot`, `Contracturen = 40`):
- 2,736 of 23,946 rows are below €31,179;
- 354 of the 4,519 rows in 2026 are below it;
- the lowest salary is €24,676.

Why it happens (`src/infrastructure/salary_policy.py`):
- The salary is the step salary (Markt_P25 up to Markt_P75 of the role
  median) × `Streef_Compa_Ratio` (`initial_salary`, :58-69).
- The lowest medians are 33,000 (Productiemedewerker, Magazijnmedewerker), so
  P25 = 29,700.
- `compa_ratio.minimum_ratio` is 0.75, and the new-hire/initial distributions
  reach 0.75-0.80.
- The result is about €22,300 in 2020 and about €26,300 in 2026 (after
  `annual_market_growth_rate`).
- Nothing clamps the salary to a legal floor or to the scale minimum.
  `dim_salary_scale` Schaal A itself starts at 29,000.
- `review_salary` never lowers pay, so a floor has to apply both at hire and
  at review.

Important related finding: `Salaris` is never scaled by FTE. It is a
full-time amount everywhere (hire, reviews, `fact_employment`, snapshot). On
the latest snapshot, the average 16-hour employee earns €49,088. So
"pro rata for part-time" is a semantic change, not just a floor.
`Benchmark_Verschil`/`Benchmark_Status`, `SalaryBand_Key`, the satisfaction
pay input and the gender-pay-gap calibration all compare `Salaris` with a
full-time benchmark.

To decide before fixing:
- Does `Salaris` become the actual (pro-rata) pay, with a separate full-time
  equivalent column for benchmarks and bands? Or does `Salaris` stay
  full-time, with a new actual-pay column?
- Is €31,179 including or excluding holiday pay?
- Does the floor apply flat to every simulated year (2020 onward), or is it
  indexed per year? The legal minimum in 2020 was lower.
- Should the lowest scale and market ranges be raised, or only the floor
  enforced?

Needs a full run, because it changes every historical salary.

**HP-02 ✔ verified, FIXED (group 3; awaiting full run) - Manager names longer than 20 characters break the app UI (high; full run: yes, existing names change)**
Requirement: manager display names ("Voornaam Achternaam", including spaces)
may be at most 20 characters.
Fixed: `person_names.max_display_length` (20) applies to every employee, Dutch and
Expat, in `PersonFactory`: the whole name is redrawn (max 100 attempts, then a
`ValueError`, never truncation). Measured redraw rate: about 6.5% of Dutch
draws. The Expat check runs after transliteration/folding, so it measures the
stored name. Expat fix (same group): names are gender-correct and
country-specific via `special_arrangements.Expat.name_locales`
(Polen `pl_PL`, Roemenië `ro_RO`, Bulgarije `bg_BG`; other countries fall back
to gender-aware `en_US`); Faker's `pl_PL` has no gendered surnames, so the
-ski/-ska agreement is done in `person_factory.py`; Bulgarian Cyrillic is
romanized with the Streamlined System and characters CP1252 cannot store are
folded to ASCII (`src/generator/name_text.py`), instead of moving the columns
to NVARCHAR.

Facts for that discussion:
- `dim_manager` is built from `dim_employee` (`Manager_Key = Employee_Key`,
  `manager_builder.py:~415-440`). Any employee can become a manager later
  through promotion.
- So a rule only for managers means either limiting every employee's name, or
  a separate shortened display name.
- Names come from Faker `nl_NL` (`person_factory.py:108-118`); Expat names
  come from generic Faker (:189-190).
- Faker has its own seeded generator (AR-32). Redrawing a name that is too
  long therefore doesn't shift the simulation's other random draws.
- Live: 11 of 150 managers are over 20 characters (longest 30, e.g. "Kaylee
  Luitgardis van Neustrië"); 91 of 1,529 employees are.
- Schema: `dim_manager` Voornaam/Achternaam are `VARCHAR(50)`; `dim_employee`
  uses `VARCHAR(100)`.
- Redrawing names at generation needs a full run to change existing names. A
  display-name column or a shortening rule could be backfilled incrementally.

**AR-10 ✔ verified, FIXED (group 1) - Salary reviews are skipped after any event earlier in the same year (medium; full run: yes)**
`simulation_career_events.py:~231` skips an employee when the current row's
`Startdatum.year == today.year`. Renewals, location transfers and promotions
reset that date, so those employees silently miss their annual salary review.
`PerformanceSimulator._tenure_days` already fixed the same bug for
performance reviews.
Direction: base the check on the last `Salarisverhoging` event date or on
`Aaneengesloten_Indienst_Datum`, not the current row's `Startdatum`.

**AR-08 ✔ verified, FIXED (group 2; awaiting full run) - Contract renewals and location transfers reset relevant experience (high; full run: yes)**
Fixed: renewal/conversion, location transfer, department relocation and the departure row now use `carried_experience(..., same_department=True)`.
`ContractLifecycleSimulator._carried_context`
(`simulation_contracts.py:~301-317`) and the location-transfer record
(`simulation_location_transfer.py:~83`, `**row.to_dict()`) copy
`Relevante_Ervaring_Jaren_Bij_Start` unchanged but set `Startdatum = today`.
`experience_as_of` (`relevant_experience.py:16-27`) is starting value + time
since `Startdatum`, so the experience built up on the previous row is lost
(about a year per yearly renewal). Live evidence: 253 employees have 370
month-to-month decreases in `fact_workforce_snapshot.Relevante_Ervaring_Jaren`,
1.25 years on average (a share is legitimate cross-domain transfer).
This feeds snapshots and performance scores.
Direction: use `carried_experience(previous_row, today, same_department=True, config)`
in both places, as career events and hiring already do.

**AR-09 FIXED (group 5; awaiting full run) - Two different definitions of relevant experience (medium-high; full run: yes)**
Fixed: `eligible_internal` uses `carried_experience` (with AR-37's shared qualification/experience helper); `relevant_experience()` was removed and the thresholds live in config.
`role_eligibility.relevant_experience` (`role_eligibility.py:~112-125`) counts
only internal time in the target role or its feeder roles. It ignores
`Relevante_Ervaring_Jaren_Bij_Start` and the cross-domain transfer ratio,
while snapshots and performance use `experience_as_of`/`carried_experience`.
An internal candidate can therefore fail a requirement they would pass as an
external candidate. This breaks the CLAUDE.md consistency contract.
`eligible_internal` also hard-codes its thresholds (`performance < 2.7`,
3 years of first leadership; lines ~151 and ~160).
Direction: one shared experience function; move the thresholds to config.

**AR-11 FIXED (group 5; awaiting full run) - Snapshots use today's values in historical rows (medium-high; full run: yes)**
Fixed: `Aanvangs_Prestatie_Score` before the first review (snapshots and absence context) and the employment row's `SalaryScale_Key`.
- Performance before the first review falls back to the *current*
  `dim_employee.Prestatie_Score` (`workforce_snapshot.py:~73`,
  `absence_context.py:~74`). A new hire's first 6+ months of snapshots show a
  later review score. `Aanvangs_Prestatie_Score` exists but is unused here.
- The snapshot's `SalaryScale_Key` (`workforce_snapshot.py:~140`) is
  overwritten by `**benchmark_fields` (`~174`), which holds the role's current
  scale (`salary_policy.py:~139-145`), not the effective employment row's scale.

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

**AR-44 FIXED (group 5; awaiting full run) - The initial population's hire source ignores source weights (low; full run: yes)**
Fixed: `initial_population.hire_source_weights`.
`choose_hire_source` (`employee_helpers.py:14`) picks uniformly across
external sources. The `config` parameter is unused.

**AR-45 FIXED (group 5; awaiting full run) - Promotions and transfers redraw the shift (low; full run: yes)**
Fixed: `carry_or_assign_shift_key`.
`simulation_career_events.py:133,185` and `simulation_hiring.py:356` redraw
`Shift_Key` at random on every move, even within the same shift department.

#### Pipeline merge (AR-20, absorbing AR-02 to AR-06)

**AR-20 - Merge the full and incremental pipelines (medium) - DONE (parts A and B; awaiting full run)**
Part A: one `run_pipeline` (`src/application/pipeline.py`) for both modes with a Store interface (`SqlStore`, `InMemoryStore`), config/schema loaded once, explicit `today`, one growth-parameter function, one `post_process` order, and the acceptance test "full to week N = full to N-1 + one incremental week". Part B: per-table write modes, changed-row upserts, one atomic transaction with the checkpoint last, open-month snapshots/benchmarks, deterministic benchmark keys, dry run and as-of date (see AR-02, AR-06, AR-18, AR-24).
`run_simulation.py` and `run_simulation_incremental.py` are about 70% the same
code and have already drifted apart:
- `sync_recruitment_status_keys` runs after the simulation in the full path
  but before it in the incremental path;
- date normalization and static-dimension repair exist only in the
  incremental path;
- growth defaults are duplicated;
- config and schema are loaded three times per full run;
- the `sector` argument is ignored.

Direction: one pipeline, `prepare_state -> run_weeks -> post_process -> write`,
with pluggable load and write steps.

**AR-02 FIXED (pipeline merge part B, awaiting full run) - Changes made in place to rows already in SQL are never saved (high; full run: yes)**
Fixed: every schema table declares `write_mode` (`upsert`/`append`) replacing the hard-coded sets; all dimensions (static ones included), `fact_employment`, `fact_absence`, `fact_recruitment`, `fact_vacancy`, `fact_manager_assignment` and `fact_workforce_snapshot` are upserted, only changed rows are written; `fact_performance_review`, `fact_safety_incident`, `fact_employee_qualification` and `fact_salary_benchmark` are append-only. The strict `InMemoryStore` applies the same modes and the equivalence tests prove the classification.
Only `MUTABLE_FACTS = {"fact_absence", "fact_employment", "fact_recruitment"}`
(`write_to_sql.py:48`) are upserted. Every other fact only gets new primary
keys inserted (`write_to_sql.py:~607-641`). Rows changed in memory are
therefore never written:
- `fact_vacancy`: Status, `Closed_Date` and `Filled_Employee_Key` are set when
  a vacancy is filled (`simulation_hiring.py:~423-450`,
  `simulation_recruitment.py:~425`). Live evidence: 4 vacancies are `Open` in
  SQL although a hired (`Aangenomen`) recruitment row exists for them. The
  next run reloads them as open and keeps recruiting.
- `fact_manager_assignment`: `Einddatum` is closed in place
  (`manager_assignment.py:48,76`), so SQL keeps overlapping open intervals.
- `fact_workforce_snapshot`: the current month's row is written on the first
  run of that month and never updated (see AR-18).
- Static dimensions: the incremental run refreshes descriptive columns in
  memory (`run_simulation_incremental.py:~176-189`) but only new keys reach SQL.

Direction: declare the write mode per table in the schema (e.g.
`"write_mode": "static|upsert|append"`) instead of the hard-coded sets. Mark
vacancy, manager assignment and static dimensions as upsert.

**AR-03 FIXED (ISO week 53: 2026-09-25; repeated last week: pipeline merge part A, awaiting full run) - Incremental runs repeat the last week, and ISO week 53 never runs (high; full run: yes)**

*Part fixed 2026-09-25 (ISO week 53):* both loops wrapped after a hard-coded
week 52 (`run_simulation.py:104`, `run_simulation_incremental.py:91`), so
2020-W53 was skipped and 2026-W53 (starting 28 Dec 2026) would have been too.
**Fix:** added `src/core/iso_week.py` (`next_iso_week`/`has_iso_week_53`,
tested in `test_iso_week.py`) and use it in both loops instead of the
`week > 52` wrap. Needs a full run to backfill the previously-skipped weeks.

*Repeated last week - FIXED (pipeline merge part A, awaiting full run):* the checkpoint stores the NEXT week to simulate (`next_year`/`next_week`, `src/infrastructure/state/checkpoint.py`), so no week runs twice; tested by the equivalence tests.

*Was open (repeated last week):* both loops store the last week they
simulated (`run_simulation.py:108-115` before the fix,
`run_simulation_incremental.py:95-102` before the fix), and the incremental
run starts again from that same stored week, so each week is simulated twice
across two runs. This is deliberately left for the incremental/full pipeline
merge (AR-20), where "next week to simulate" becomes the natural resume point
and can be tested against "a full run to week N equals a full run to week
N-1 plus one incremental week".
Direction: store the *next* week to simulate instead of the last one
simulated, and add a resume test.

**AR-04 FIXED (pipeline merge part A, awaiting full run) - State that exists only in memory is lost between incremental runs (high; full run: no, but the next incremental runs are wrong)**
Fixed: `STATE_KEY_REGISTER` classifies every non-table state key; the persisted ones (location state, `_recruitment_pipeline_profiles`, `_vacancy_requests`) are stored in the checkpoint (`simulation_state.checkpoint_json`) and restored on load; an unclassified key fails the run.
- Location state (`_location_open`, `_location_opened_on`,
  `_location_capacity_streak`, `_location_capacity_bonus`, `_home_location`;
  `location_assignment.py:~41-50`) is rebuilt from config each run. Fabriek
  Zuid needs `capacity_streak_weeks: 8` of full capacity within one process,
  which a one-week run can never reach, so it reverts to closed.
  Headcount-triggered openings are re-opened and re-relocated every run.
- `_recruitment_pipeline_profiles` (`simulation_recruitment.py:~97,181,380`) is
  never saved. After a reload, external candidates still in the pipeline are
  screened with `{}` (0 years of experience), and accepted hires lose their
  screened education/experience.

Direction: keep an explicit list of state keys, each marked "saved" or
"rebuildable". Save the rest (e.g. a JSON column on `simulation_state`, or a
small table), or derive it from SQL (`fact_employment.Location_Key` history,
the recruitment row's candidate columns).

**AR-05 FIXED (pipeline merge part A, awaiting full run) - Each incremental run restarts the random generator from the same seed (medium; full run: no)**
Fixed: every simulated week uses `Random(f"{seed}:{year}:{week}")` and reseeds Faker with `f"{seed}:{year}:{week}:names"`; population generation has its own stream. Per-simulator sub-streams (AR-15) are not done.
`run_simulation_incremental.py:37` creates `random.Random(seed)` every run, and
each weekly run covers one or two weeks, so every incremental week consumes
nearly the same random stream (e.g. the attrition shock draw at
`simulation_attrition.py:~66-70`).
Direction: seed per simulated week from `(seed, year, week)` in both paths;
optionally one sub-stream per simulator (see AR-15 on data-dependent draws).

**AR-51 FIXED (pipeline merge part A, awaiting full run) - The incremental run redrew the annual growth rate on every run (medium; full run: yes)**
`run_simulation_incremental.py:52` drew `annual_growth_rate` from a freshly seeded `rng` on every incremental run, and the full run drew it from a different point of its stream, so the growth path changed from run to run. Fixed: the rate is derived once from `Random(f"{seed}:growth-rate")` in `simulation_parameters`, identical in every run.

**AR-06 FIXED (pipeline merge part B, awaiting full run) - Writes are not atomic; the week counter advances before the data is written (medium-high; full run: no)**
Fixed: schema evolution first, then one transaction on one connection (full: reset + inserts; incremental: upserts/appends/deletes) with the checkpoint written last; any failure rolls back and keeps the old data and checkpoint; `load_current_state` fails loudly except for a missing table. Not done: staging tables with a swap for full runs (a single transaction already keeps readers on the old data under READ_COMMITTED_SNAPSHOT; the risk is the transaction log size on a small tier).
`update_simulation_state` commits (`run_simulation.py:115`,
`run_simulation_incremental.py:102`) before `write_dataset` runs
(`function_app.py:89`). `reset_tables` and each table write commit separately.
A run that dies mid-write leaves half-written tables while `simulation_state`
says those weeks are done. During a full write, the web app and Power BI see
empty or partial tables. `load_current_state` (`load_state.py:18-22`) and
`_get_existing_primary_keys` (`write_to_sql.py:221-223`) swallow all
exceptions, so a transient read error becomes an empty table.
Direction: update `simulation_state` last, in the final transaction. For full
runs, write to staging tables and swap them in. Fail loudly on SQL read
errors except "table does not exist".

**AR-22 FIXED (pipeline merge part A, awaiting full run) - Make the weekly state contract explicit (medium-low)**
Fixed: the state keys are documented in `STATE_KEY_REGISTER`; the dead keys `vacancies` and `_latest_hires` (and their writes) were removed; the hiring simulator no longer calls `assign_managers` (it fell back to the wall clock), so `WeeklySimulationRunner` is the single owner and assigns with the simulated date. Backfill requests raised by hiring are still handled the following week; that is now explicit because `_vacancy_requests` is persisted in the checkpoint.
- `state["vacancies"]` and `_latest_hires` are written but never read.
- Backfill requests from hiring are created after `VacancySimulator` already
  ran, so they are handled a week late without that being stated.
- `assign_managers` runs twice per week: in hiring, without `today`, falling
  back to the wall clock; and in the runner.

Direction: document the required keys (see AR-04), drop the dead ones, and
make the runner the single owner of manager assignment.

**AR-47 FIXED (pipeline merge part A, awaiting full run) - A full run has two random generators with the same seed (low; full run: yes)**
Fixed: population generation uses `Random(f"{seed}:population")`; each week has its own stream.
`run_simulation.py:29` and `population.py:35` both create
`random.Random(seed)`, so population generation and the weekly loop replay the
same number stream. Fold into AR-05.

## 2026-09-25

**Important before any full run:** AR-01 (retention) also runs at the end of a
full run, so a fresh full run immediately loses every employee whose
employment chain ended more than five years ago. Fix AR-01 first, or accept
that 2020-2021 headcount undercounts.

### Architecture review of 2026-09-25: items fixed that day

**✅ AR-01 fixed (2026-09-25) - Retention deletes visible history on every write (was: high; full run: yes)**
`apply_retention` (`write_to_sql.py:725-833`, called unconditionally at the
end of `write_dataset`, ~line 864) deleted whole employment chains and their
snapshots when `MAX(Einddatum) < now - 5 years`. SQL `MAX` ignores the NULL
`Einddatum` of an active row, so an active employee whose last closed row was
older than five years got deleted too. Leavers from the visible period (which
starts 2020) disappeared as time passed. Live evidence at the time: `dim_employee`
had 242 leavers with `Datum_uitdienst < 2021-09-25`, while the earliest
`Uit dienst` row left in `fact_employment` was dated 2021-10-04. Incremental
runs re-inserted the deleted rows and retention deleted them again.
**Fix:** removed `apply_retention` and its call in `write_dataset` entirely -
the demo needs full history, so there is no retention window at all now.
Needs a full run to restore the history already lost in the live database.

**✅ AR-07 fixed (2026-09-25) - 11 renamed/removed columns still exist physically in SQL (was: medium; full run: no, a full run does not remove them)**
A full reset only deletes rows; `_ensure_table_columns` only adds columns, and
`deprecated_columns` listed only `dim_employee.Leeftijd` and
`fact_absence.AbsenceDuration_Key`. Present in SQL but not in the schema (all
confirmed NULL at the time):
- `fact_workforce_snapshot`: `Performance_Score`, `SalaryStep`, `EducationLevel_Key`, `Ploegendienst_Key`
- `fact_employment`: `Target_Compa_Ratio`, `RedenVertrek_Key`, `Ploegendienst_Key`
- `fact_safety_incident`: `Absence_Key` (still carried the removed
  fact-to-fact foreign key to `fact_absence`), `Ploegendienst_Key`
- `fact_absence.Ploegendienst_Key`, `dim_employee.EducationLevel_Key`

**Fix:** all 11 added to their table's `deprecated_columns` in
`hr_maakindustrie_schema.json`, so the existing `_drop_deprecated_columns`
step (which already handles dropping the dependent foreign key first) removes
them on the next write - no full run needed for this one, an incremental
write is enough. `test_schema_deprecated_columns.py` pins the list and
guards against a column being both live and deprecated at once.

**✅ AR-16 fixed (2026-09-25) - Internal-candidate search ran once per application (was: high; about 35% of week time; full run: yes, the results change)**
`_choose_source` called `_internal_candidate` for every application
(`simulation_recruitment.py:~573-576`), which re-filtered active rows and ran
`eligible_internal` row by row over every active employee (`~619-636`) -
*before* the source was even chosen, so this ran for every application
attempt regardless of whether "Interne mobiliteit" (weight 0.35 of ~10.5
total in the shipped config, roughly a 3% chance of being drawn) ended up
being used. Cost scaled with applications × headcount.

**Fix - two parts, both in `simulation_recruitment.py`:**
1. `_eligible_internal_pool(state, vacancy, cache)` computes and caches the
   eligible-candidate pool once per vacancy (keyed by `Vacancy_Key`) for the
   life of one `run()` call, instead of once per application drawn for that
   vacancy. Safe/pure: `fact_employment`/`dim_employee`/`dim_role` don't
   change between vacancies processed in the same weekly `run()` (the actual
   hire happens later that week, in `HiringSimulator`).
2. `_choose_source` now draws a source *first*, from a cheap weight list
   (`_weighted_hire_sources`, no eligibility check), and only calls
   `_eligible_internal_pool` if "Interne mobiliteit" is the one actually
   drawn. If it turns out to have no eligible candidate, it redraws among
   the remaining sources rather than discarding the application.

**Design decision (checked with the user first, since it changes a real
metric - internal-mobility's share of hires):** two options existed for what
happens when internal mobility wins the draw but has no eligible candidate -
(A) no application results this attempt (reduces total volume), or (B)
redraw among the remaining sources (matches the pre-fix pool-exclusion
behaviour more closely). Chose **B**. Worked out algebraically that B is
distribution-equivalent to the original pool-exclusion approach: removing an
always-infeasible option before drawing, versus drawing from all options and
redrawing only when the infeasible one is hit, give every other source
exactly the same final selection probability - confirmed empirically too
(see validation below), not just derived on paper.

**Validation - two layers, since this changes the number and sequence of
random draws (unlike AR-17, this cannot be checked via exact-output
equality):**
- **Direct, well-powered statistical check** (`test_choose_source_matches_the_configured_weights_when_internal_is_always_ineligible`,
  `test_choose_source_matches_the_configured_weight_when_internal_is_always_eligible`
  in `test_simulation_recruitment.py`): called `_choose_source` 4,000 times
  in isolation with fixed weights, both with internal-mobility always
  ineligible and always eligible. Every source's empirical selection share
  landed within the expected statistical tolerance of its configured weight
  in both cases - the clean confirmation that the fix is unbiased.
- **Full-scale run comparison** (50 employees, 60 simulated weeks, in
  memory): an *initial* single-seed comparison looked alarming - internal
  mobility's hire share dropped from 9.5% (baseline, seed 123) to 1.5%
  (fixed code, same seed) - but this metric only has 1-8 internal-mobility
  hires per 60-week run, an inherently noisy sample. Running 3 baseline
  seeds (9.5%, 0%, 1.4%) and 8 fixed-code seeds (0%-4.2%, mean ~2.0%) showed
  the baseline's 9.5% was itself a high outlier, not the typical value -
  the two sets of samples are consistent with the same underlying rate once
  more than one seed is looked at. Flagging this here because it's a real
  lesson: a single-seed comparison on a rare-event metric is not sufficient
  evidence either way, for a fix or against one.
- **Timing**: the same 50-employee/60-week scenario ran in about 44 seconds
  after the fix, versus roughly 7-8 minutes before it (in line with AR-17's
  measured baseline at the same scale) - roughly a 10x speedup at this small
  scale. This has *not* been confirmed at real headcount (1,000-1,500); the
  review's own reasoning for why this was the dominant cost (cost scales
  with applications x headcount) suggests the win should be at least as
  large, possibly larger, at real scale, but that still needs an actual
  benchmark - see "Suggested order".

Full suite: 236 passed. Needs a full run once combined with the rest of the
correctness/speed work per "Suggested order" (this fix does change history,
since it changes which random numbers get drawn from the very first time
"Interne mobiliteit" is drawn-but-infeasible in a run).

**✅ AR-32 fixed (2026-09-25, found earlier the same day) - Employee names are not reproducible from the configured seed (was: low)**
`src/generator/person_factory.py._choose_name` draws first/last names from
module-level `faker.Faker` instances (`fakeNL`, `fakeINT`), which have their
own internal random state seeded from OS entropy at import time, not from
`simulation_seed`. Every other simulated value (role, department, salary,
gender, tenure, all subsequent weekly events) is drawn from the
`random.Random(seed)` instance threaded through the whole pipeline and *is*
reproducible; only `Voornaam`/`Achternaam` (and the Expat branch's
international name/country in `_choose_special_arrangement`) were not.
Found while validating AR-17: two runs of an identical 50-employee/60-week
scenario with the same `simulation_seed` produced 31 of 32 tables
byte-for-byte identical and only `dim_employee`'s name columns differing
100%, in a full-permutation pattern consistent with each run drawing names in
a different, unrelated order.

**Fix:** added `src.generator.person_factory.seed_person_names(seed)`,
called once near where `random.Random(seed)` is already constructed in
`run_simulation.py` and `run_simulation_incremental.py`. One call is enough
for both `fakeNL` and `fakeINT` - confirmed directly (not assumed) that
`Faker.seed()` reseeds the single shared global generator every locale's
`Faker()` instance draws from, including instances already constructed
before the call, not a per-instance state; `test_person_factory.py` pins
this down (`test_seed_person_names_reseeds_the_shared_generator_used_by_every_locale`).
Names are drawn both during initial population generation and for every
weekly new hire (`simulation_hiring.py`), so the seed call sits once at the
top of each run rather than per employee/week - seeding per draw would make
every name repeat the same short sequence instead of continuing it.
The incremental path reseeds identically on every incremental run, the same
limitation `random.Random(seed)` already has there (see AR-05) - this fix
does not add a new instance of that problem, just makes names as
reproducible as everything else already was, no more, no less.
No full run needed for this fix specifically (it only affects whether future
name draws repeat, not any existing data), but the next full run will
produce different names than any run before this fix, since none of the
existing draws were on this seeded stream.

#### Suggested order

Reprioritized 2026-09-25 at the user's request: full-run speed comes before
the remaining incremental-only correctness items, and the incremental/full
merge (AR-20) is the point at which incremental resume is rebuilt properly
rather than patched item by item. Rationale: every history-changing fix ends
in the same 2+ hour full run, so making that run faster first speeds up every
later step too; and most of the remaining incremental bugs (AR-02, AR-04 to
AR-06) share one root cause - incremental is a separate code path that
doesn't restore everything a full run holds in memory - so they are better
solved together as "incremental = full run resumed from a checkpoint" than
patched individually.

1. ✅ Done: AR-01, the ISO week 53 half of AR-03, and AR-07 (see below) -
   these were cheap, and AR-01 in particular would otherwise have damaged
   the very next full run.
2. Speed (AR-16 to AR-19). Benchmark first (time per simulated week at real
   headcount, not the reviewer's 200-employee profile - AR-18-style O(n^2)
   effects may dominate at 1,000-1,500 employees). Do pure refactors that
   don't change the number of random draws first (e.g. AR-17's per-week
   lookup context) and check them for byte-for-byte identical output on a
   short in-memory run; only then do the draw-order changes (e.g. AR-16),
   checked against distributions instead of exact equality.
3. Merge the two pipelines so incremental resumes from a checkpoint (AR-20,
   absorbing AR-02, AR-04, AR-05, AR-06 and the "repeated last week" half of
   AR-03), with a test that a full run to week N equals a full run to week
   N-1 plus one incremental week.
4. Simulation correctness (AR-08 to AR-15) - these change history, so do them
   last, right before the one full run that covers everything above.
5. AR-21 to AR-27 (remaining structure), then AR-28 to AR-31 (tests/docs/hygiene).

The weekly timer keeps degrading the live data (re-recruiting filled
vacancies, resetting location state, etc.) until step 3 lands. A full run
repairs it, but if that gap matters before then, pausing the timer in Azure
is a cheap option and is the user's call.

#### Done on 2026-09-25 (awaiting the next full run)

- **Performance score rebuilt.** The old model carried over 75% of the
  previous score and re-added every bonus each year, so the long-run score
  drifted to baseline + 4 × bonuses. About 16-32% of reviews per year sat at
  exactly 5.00, and 93% stayed there. Now the score is a stable personal
  level plus a partly persistent yearly deviation, tenure and relevant
  experience are merged into one capped effect, and the new `performance`
  config section is calibrated to: mean about 3.36, about 7.5% at 4.0 or
  higher, about 0.5% at 4.5 or higher, and 5.00 practically never. Backfilled
  reviews now cover the most recent anniversaries. New hires' lower bound is
  1, not 0. `salary_benchmark...performance_midpoint` changed from 3.5 to 3.35.
- **Manager assignments are sticky.** Only employees without a valid manager,
  new hires, department movers and over-capacity overflow are reassigned.
  Leavers keep their last manager and don't use capacity. Leaders are ranked
  on continuous service. Before this, 70% of closed `fact_manager_assignment`
  intervals lasted less than 2 weeks.
- **AR-01 fixed: retention removed.** `apply_retention` and its call are gone;
  a full run no longer deletes any employment history.
- **AR-03 half-fixed: ISO week 53 no longer skipped.** New
  `src/core/iso_week.py` replaces the hard-coded `week > 52` wrap in both
  loops. The "incremental repeats the last week" half of AR-03 is still open,
  deferred to the AR-20 pipeline merge (see "Suggested order").
- **AR-07 fixed: 11 leftover columns marked deprecated.** They will be
  dropped from SQL on the next write (full or incremental - no full run
  needed for this one specifically).
- **AR-17 partially fixed: static-dimension lookups cached.**
  `src/infrastructure/dimension_lookup.py` memoizes role→department name,
  shift name and the event-type Gebeurtenis dict, replacing 4 duplicated
  per-employee, per-week `.loc[]` filters in `satisfaction.py`,
  `engagement.py`, `simulation_safety.py` and `simulation_absence.py`.
  Verified output-preserving with a before/after byte-for-byte comparison of
  all 32 tables from an identical seeded scenario - no full run needed for
  this part; the rest of AR-17's original scope is still open.
- **AR-16 fixed: internal-candidate search only scans when actually drawn.**
  Was the dominant per-week cost (review estimate: ~35%). Source is now
  picked before the expensive eligibility scan runs, with a redraw (not a
  dropped application) if internal mobility wins but has nobody eligible -
  a real design choice, checked with the user first, and confirmed
  distribution-equivalent to the old behaviour both algebraically and via a
  4,000-draw statistical test. ~10x faster on the same 50-employee/60-week
  scenario used to validate it (44s vs ~7-8 min); not yet confirmed at real
  headcount. Changes history (different random draws) - needs a full run.
- **AR-32 fixed: employee names are now seeded.** Surfaced while validating
  AR-17 above - `faker`'s own RNG, not `simulation_seed`, drove
  `Voornaam`/`Achternaam`. New `seed_person_names(seed)` in
  `person_factory.py`, called once at the top of both `run_simulation.py`
  and `run_simulation_incremental.py`. Names generated by any run before
  this fix are not reproducible from that run's seed; the next full run's
  names will differ from all earlier runs, then be reproducible from then on.

## 2026-09-21

### Gender ratio and pay gap

#### ✅ Verified against a real full run (2020-01 to 2026-09, 753 employees ever/399 active)

- **Function-corrected gender pay gap: confirmed as-is, no config change.**
  Measured properly (average `Salaris` by `Geslacht` *within* each `Role_Key`,
  then aggregated, not a flat company-wide average) on the final snapshot: **≈
  4.0-4.5%**, squarely in the intended 4-5% band and better than the CBS 2024
  bedrijfsleven benchmark (6.1% corrected). The naive raw average is
  misleading in the *opposite* direction (women average +3.8% higher pay,
  confounded by women being overrepresented in higher-paid R&D/QA/HR/IT
  leadership roles), which is exactly why the role-correction matters, not
  just a nice-to-have.
- **Directie and the male-leaning departments: confirmed as-is.** Directie
  realized 75:25 (all-time) vs. configured 70:30; top-15 company earners are
  10M/5F - the original "Directie/top-earners randomly all-female" bug stays
  fixed. Productie (82:18 vs 80:20), Techniek (93:7 vs 88:12), Logistiek
  (81:19 vs 70:30) and IT (73:27 vs 75:25) all realized in the correct
  direction and close to target. R&D looks female-leaning (71% F) despite a
  55:45 male-leaning *department* default - expected, not a bug: R&D
  headcount is dominated by `Productontwikkelaar`/`Senior Productontwikkelaar`,
  whose `role_overrides` (35:65 female-leaning) correctly take precedence.
- **✅ Confirmed as-is via a bigger full run (791 active employees) - the
  earlier undershoot was small-sample noise, as suspected.** HR: 18F/6M =
  75:25, exactly matching the configured 25:75 (M:F) target (was 50:50 on
  n=12). Kwaliteit: 63F/28M/1 Anders = ~69:31, close to the configured
  35:65 target (was ~52:48 on n=29). Both departments roughly tripled/doubled
  in sample size on this run (n=24 and n=92) and landed on target. No config
  change - `gender_ratio` confirmed correct across every department now.

### Safety incidents

#### ✅ Adjusted `annual_incident_rate_by_department` against a real full run

Measured realized annual incident rate (incidents ÷ avg headcount ÷ 6.75
simulated years) per department against the configured target on the
2020-01 to 2026-09 full run. `type_weights` (the safety-pyramid mix) matched
almost exactly (60.0/26.0/9.9/4.1% realized vs. 60/25/10/5% configured) -
**confirmed as-is, no change**. `new_hire_multiplier` (1.8x) and
`ploegendienst_multipliers` (1.15x/1.3x) are real, not just theoretical: 25%
of all incidents fell within 180 days of hire and 58% occurred on a 2- or
3-ploeg shift - but that meant they were **stacking on top of** the base
department rate in the three shift-heavy, high-turnover departments,
pushing realized rates 18-46% above target there:
- Productie: realized 0.51/emp-yr vs. configured 0.35 (1.46x) → lowered to
  **0.24**.
- Techniek: realized 0.35 vs. configured 0.30 (1.18x) → lowered to **0.25**.
- Logistiek: realized 0.30 vs. configured 0.25 (1.21x) → lowered to **0.21**.

Kwaliteit (11 incidents, 0.84x target) and every smaller department
(QHSE/R&D/Finance/HR/IT/Sales/Marketing/Directie, 0-3 incidents each) stay
unchanged - still first-pass, sample sizes too small over this run to
recalibrate reliably either way. Total incident count (481 in-window) and
lost-workday total (170 days from 23 LTIs, ~7.4 days/LTI) were sanity-checked
as reasonable for this company size and not touched.

**✅ Confirmed working as intended via a bigger full run (791 active
employees).** Realized rates: Productie 0.338, Techniek 0.329, Logistiek
0.257 - these land close to the *original* target band (0.35/0.30/0.25),
which is the intended outcome: the base rate was deliberately lowered so
that, after the still-present new-hire/shift multiplier stacking, realized
output lands back near the original target instead of near the new, lower
base numbers themselves. Confirmed these values are only reachable with the
new lowered base rates in the config - the previous overshoot (0.51/0.35/0.30
under the old 0.35/0.30/0.25 base) is gone. No further change needed.

**Recalibrated in group 4 (2026-10).** That 2025 reduction partly compensated
for the AR-35 bug (tenure measured from the reset employment row made about
half of all employees look like new hires, so the 1.8x multiplier stacked on
far too many people). With continuous-service tenure the new-hire share is
about 16-20%, and Techniek/Logistiek gained shift work, so the base rates were
re-derived rather than kept: `safety.target_incident_rate_by_department`
(Productie 0.35, Techniek 0.30, Logistiek 0.25 realized per employee-year)
divided by the expected shift and new-hire factors from
`src/infrastructure/safety_calibration.py` (flagged-role share from
`allocate_headcount` at headcount 800, the configured shift mixes and
`safety.calibration.new_hire_share_by_department` 0.197/0.169/0.157, measured
on `fact_workforce_snapshot` 2020-2026). New base rates: Productie 0.24 to
0.26, Techniek 0.25 and Logistiek 0.21 unchanged; realized -1.6%/+1.7%/-0.3%
against target. A test keeps the realized rates within 10% of the targets.

### Recruitment

#### ✅ Fixed: `fact_recruitment.Stage_Key` didn't match its own milestone date columns

Found by the app team while building a recruitment funnel view: of the 4,857
rows recorded at `Stage_Key = Gesprek`, only 31% actually had an
`Interview_Date`; `Stage_Key = Screening` never appeared as a value at all
despite `dim_recruitment_stage` defining it. A funnel built on `Stage_Key`
overcounted "reached Gesprek" by roughly 3x versus applications that
genuinely had an interview.

Root cause: `Stage_Key` and the date columns are two different tracks that
were never reconciled. `Stage_Key` is written only by `_advance_to_stage`,
which only runs on a *successful* transition (screening passed -> Gesprek;
interview passed -> Aanbod) - so it means "the furthest queue this
application was ever successfully advanced into." `_finalize` - the
function that closes out a rejected/declined/withdrawn/expired application -
sets `Status`/`Decision_Date`/reason keys but never touched `Stage_Key`, so
it stayed frozen at whatever it was when the row was last promoted, with no
relation to which milestone dates actually got set:
- A candidate rejected at screening (`Screening_Date` set, in
  `_resolve_screening`'s reject branch) stayed mislabeled at `Sollicitatie`,
  since that branch's `_finalize` call never advances the stage - this is
  also why `Stage_Key = Screening` never appeared anywhere: screening is
  resolved atomically in one call (pass -> jump straight to Gesprek, fail ->
  terminate while still labeled Sollicitatie), so nothing ever wrote that
  value.
- A candidate who passed screening and was queued for `Gesprek`, but got
  swept out before ever being interviewed - vacancy filled by someone else,
  vacancy expired, or a `gesprek_patience_days` withdrawal
  (`_close_out_remaining_pipeline`, `_expire_stale_vacancy`,
  `_withdraw_stale_candidates` all finalize with no `date_columns` at all) -
  stayed labeled `Gesprek` despite `Interview_Date` staying null.

Not random/independently-sampled, as first suspected - fully deterministic,
just never corrected on the failure/drop-out path.

Fixed by adding `_terminal_stage_key(row)`, called from `_finalize` to
recompute `Stage_Key` from the row's own date columns at the moment it
terminates (`Offer_Date` -> Aanbod; else `Interview_Date` -> Gesprek; else
`Screening_Date` -> Screening; else Sollicitatie, or Gesprek for an
internal-mobility application, which skips Sollicitatie/Screening by design
and would otherwise wrongly floor at Sollicitatie). This only runs at
finalize time, deliberately - an `"In behandeling"` row keeps its live
process-stage value (queued for Gesprek but not yet evaluated, say), which
is exactly what the still-deferred "current pipeline matrix" Power BI item
needs (current backlog by department x stage); only the terminal record gets
corrected to reflect what actually happened, which is what a historical
funnel/conversion view needs. The two were evaluated together and found not
to conflict - the bug never affected in-progress rows, only terminal ones,
so no design compromise was needed to serve both.

Regression-tested in `test_simulation_recruitment.py`: rejected-at-screening
now lands on `Screening`; swept-out-of-Gesprek-without-an-interview now
lands on `Screening`; actually-interviewed-then-rejected/withdrawn correctly
stays at `Gesprek`; an internal-mobility candidate swept out with nothing
else set floors at `Gesprek`, not `Sollicitatie`; an accepted/declined offer
(the one transition that was already correct) stays at `Aanbod`. Full test
suite green (204 passed).

This is a historical-logic fix: it only affects applications finalized by
future simulated weeks. The ~8,994 already-generated `fact_recruitment` rows
in the current dataset needed a full run to backfill - not run as part of
this fix, batched with the next full run instead.

**✅ Backfill confirmed via a bigger full run (791 active employees).**
`Stage_Key = 2` (Screening) is now the single largest bucket in
`fact_recruitment` (13,693 of 21,285 rows) rather than absent; among
`Stage_Key = 3` (Gesprek) rows, `Interview_Date` coverage jumped from the
previously-measured 31% to **88.7%**. Both signatures match the fix exactly.

- A rare edge case is now handled defensively rather than eliminated: if
  `HiringSimulator` closes a vacancy without a hire (a capacity conflict with
  a capped role - see below), any other in-progress pipeline applications for
  that vacancy are closed out as "Afgewezen" too, so nothing is left stuck at
  "In behandeling" forever. This is a backstop for an already-rare race, not
  a normal funnel outcome.

#### ✅ Verified against a real full run (2020-01 to 2026-09)

- **Time-to-fill: confirmed at scale.** The earlier narrow-run fix (median
  28 days for Productie) held almost exactly on ~4x the sample (364
  closed-with-hire Productie vacancies, median still 28 days, max 84 days).
  All 12 departments: medians 28-60 days, max time-to-fill never exceeds 84
  days anywhere. No backlog creep.
- **`vacancy_expiry_days`/`gesprek_patience_days` backstops: confirmed
  as-is, and barely needed.** Zero vacancies stuck past 90 days (34 open
  vacancies, all created 4-53 days ago); the oldest in-progress application
  is 46 days pending, under the 56-day patience threshold. These remain
  correctly-sized backstops for a failure mode that current funnel
  throughput doesn't actually hit at this scale.
- **`screening_decision_rate`/`interview_decision_rate`: not directly
  comparable, by design** - these are weekly processing-probability
  (timing) gates, not pass/fail rates; actual pass/fail comes from
  eligibility plus the quality bar. Realized causal rates (screening pass
  ≈63%, interview→offer ≈15%) are informational only, not a target to tune
  against.

#### ✅ Fixed: application-volume sampling biased low for smaller departments

`weekly_applications_by_department` (a config target) tracked tightly for
departments averaging ≥1.5 applications/week (90-100% of target: Productie,
Techniek, Logistiek, Kwaliteit, IT, Sales), but departments averaging ≤1.0
systematically undershot - R&D 69%, HR 70%, Finance 64%, Directie 44% of
their configured target. Root cause was not a config-calibration gap:
`_generate_new_applications` drew `count = max(0, int(rng.normalvariate(average,
std)))`, and `int()` truncates a normal sample toward zero (equivalent to
`floor` for a non-negative value), which biases the realized mean below
`average` - more severely the smaller `average` is. Fixed by extracting the
draw into `_sample_application_count(average)` and switching to `round()`,
which is unbiased. Regression test
(`test_sample_application_count_is_not_biased_below_the_configured_average`)
draws 5000 samples at `average=1.0` and asserts the realized mean lands near
1.0, not ~0.5. Full test suite green (199 passed). Not yet re-verified
against another full run (would require rerunning the ~hour-long full
pipeline); the existing `weekly_applications_by_department` values
themselves are left unchanged, since the departments that were on-target
under the old biased draw should now track slightly above target under the
correct one - worth a spot-check next full run.

**✅ Spot-checked against a bigger full run (791 active employees).** R&D,
HR, Finance and Directie now realize 108-129% of their configured target
(up from the previously-measured 44-70%) - the predicted "slightly above
target" swing, confirming the fix behaves as intended. `weekly_applications_by_department`
left unchanged; the modest overshoot isn't worth trimming for a demo
dataset.

### Workforce planning

#### ✅ Verified against a real full run (2020-01 to 2026-09, 399 active at end)

- **✅ Fully verified against a bigger full run (791 active employees):
  `active_from_headcount`/`active_from_scope` thresholds confirmed as-is,
  no "above ~400" gap actually exists.** Re-checked `maakindustrie.json`
  directly: no role's configured threshold exceeds 380 (`Verpakkingstechnoloog`,
  R&D, company scope, is the highest) - the earlier "thresholds above ~400
  remain unexercised" note was based on a stale assumption that higher
  thresholds existed; they don't in the current config. Every company-scope-
  gated role with a threshold in the 240-380 range fills with clean, plausible
  timing relative to when total headcount actually crossed it (e.g.
  `Verpakkingstechnoloog` at 380 first filled 2023-04-24, right after
  headcount crossed 380 in Feb 2023). `Commercial Director` (department-group
  threshold 30 on Sales+Marketing) - the one role that never filled on the
  smaller 399-active run - is now filled (2026-05-11), since that combined
  department finally exceeded 30. Zero roles found unreached despite their
  threshold being crossed. Nothing left open here.
- **New roles' real-world reachability via growth vacancies: confirmed.**
  This closes the previously-open "unverified" item below - every
  company-scope-gated role reachable at this run's headcount was in fact
  filled through the normal growth-vacancy path, not just theoretically
  eligible.

#### ✅ Fixed: internal promotion/transfer could reach a role before its `active_from_headcount` threshold

Found while verifying role thresholds against the full run:
**Senior Applicatiebeheerder** (IT, `active_from_headcount: 280`, company
scope) was filled via an internal `Promotie` on 2022-04-18, when total
company headcount was only ~165 - about 115 headcount (~2 years) before it
should have unlocked. A second seat later filled correctly via `Aangenomen`
on 2025-07-14, after headcount legitimately passed 280, proving the
threshold itself is right and the gate exists - it was just silently
bypassed by one of the two paths that can fill a role.

Root cause: `simulation_vacancy.py`'s growth-vacancy path has always
checked `role_is_active`/`active_from_headcount` before selecting a role to
grow into (`VacancySimulator._is_active_role`), but
`simulation_career_events.py`'s internal promotion/transfer candidate
selection never did - `eligible_internal` and the capacity check
(`_under_capacity`) ran, but nothing checked whether the *target role* had
actually unlocked yet at the company's current headcount.

Fixed by adding the same check to both the promotion and transfer candidate
filters in `simulate_career_events`, via a new `_is_active_role` helper
(mirroring `VacancySimulator._is_active_role`). The department-headcount
lookup it needs (`department_headcounts_by_name`) was extracted from
`VacancySimulator` into the shared `src/application/allocation.py` (next to
`role_is_active`/`scope_headcount`, which it already depended on) so both
simulators use one implementation instead of two. Company headcount is
computed once per weekly pass (internal moves redistribute headcount across
roles/departments but never change the total), while the department
breakdown is recomputed per candidate check since a transfer/promotion can
move someone between departments mid-pass.

Regression-tested in `test_simulation_career_events.py`
(`test_is_active_role_blocks_an_internal_move_before_the_company_reaches_the_threshold`,
plus the at-threshold and no-threshold-configured cases). Full test suite
green (199 passed). This is a historical-logic fix - it only affects
promotions/transfers evaluated by future simulated weeks; the already-early
`Senior Applicatiebeheerder` placement in the current dataset needed
another full run to correct, not pursued as part of this fix per instruction
to batch full-run-requiring work together.

**✅ Confirmed corrected via a bigger full run (791 active employees).** The
old early `Promotie` row (2022-04-18, headcount ~165) is gone; the role's
first-ever fill is now 2022-04-25 via `Aangenomen`, its first `Promotie` not
until 2022-11-28 - both comfortably after headcount crossed 280 (~Oct 2021).
Extended to all 29 company-scope-gated roles with threshold >= 50: zero
`Promotie`/`Transfer` rows predate their target role's threshold crossing
anywhere in the dataset. The gate holds everywhere, not just for the one
originally-documented case.

A related, weaker signal was also checked and left alone:
`simulation_vacancy.py`'s *replacement*-vacancy path (fed by attrition/
contract-non-renewal/internal-mobility-backfill requests) also never calls
`role_is_active` directly. In practice this isn't a live gap: a replacement
vacancy only exists for a role that already has (or had) an incumbent, and
that incumbent could only have reached the role via a hire (already gated,
correct) or an internal move (now gated by the fix above) - so closing the
promotion/transfer gap closes this path too, for anyone placed from here on.
No separate code change made.
- **Instant initial allocation still can't match organically-grown history,
  even after fixing the role-mix bug.** `allocate_headcount` now includes the
  right *roles* for a given starting headcount (fixed - see above), but two
  gaps remain versus a company that actually grew there over years:
  (a) it places everyone at the long-run target proportions immediately,
  while an organically-grown population at an intermediate headcount hasn't
  fully converged to that mix yet; and (b) it produces zero event history -
  no promotions, past vacancies/applications, or absence episodes, since
  nothing was ever simulated for anyone.
- **Decided against: a statistically-sampled history backfill for (b).**
  Analyzed in depth and not pursued. The idea was to skip simulating the
  lookback window week by week and instead sample the aggregate shape of
  history in closed form (a headcount curve formula, per-employee
  Poisson/binomial event counts, directly-sampled past leavers/vacancies/
  absences). Two things changed the calculus: (1) `fact_workforce_snapshot`
  - the table `Tevredenheid_Score`/`Betrokkenheid_Score`/`Prestatie_Score`
  trends actually come from - is only ever built from `visible_start_date`
  onward regardless of burn-in length, so backfilling further history
  wouldn't have extended the visible trend data anyway, only made the
  *starting* state at `visible_start_date` more mature; the front-end will
  instead filter to a recent window, which sidesteps the need entirely. (2)
  The real difficulty isn't per-employee event sampling (that part is as
  easy as it sounds) but that nearly everything in this simulator is a
  *shared* limited resource across employees (single-seat roles, team-lead
  ceilings, location capacity, the applicant/vacancy pool) - independently
  sampling each employee's career risks violating those constraints in ways
  the forward simulator never produces by construction, and reconstructing
  that bookkeeping in a sampler erodes most of the intended speed gain. A
  sampled backfill would also become a second, approximate implementation of
  eligibility/salary/vacancy rules that has to be kept in sync with the real
  simulators forever. Cheaper lever if more historical depth is ever wanted:
  raise `burn_in_years` (currently 2; `tenure_years_distribution` allows up
  to 10-20 years) - same accurate mechanism, purely a runtime-cost trade.
- Added a one-line log timestamp in `run_simulation.py` marking when burn-in
  finishes (elapsed minutes + simulated week count), so the next full run
  gives an actual measured burn-in cost instead of the config-based estimate
  used to answer "how much of the ~1 hour full run was burn-in" (~10-15%,
  reasoned from `burn_in_years: 2` at roughly-flat `baseline_headcount: 100`
  versus ~348 visible-window weeks growing toward `max_capacity: 800`).

### Incremental run reliability

#### ✅ Fixed: production incident - incremental run crashed inserting `dim_candidate_quality_driver`

The first incremental (weekly) run against the code deployed after last
Friday's full run failed with `pyodbc.DataError: Operand type clash:
datetime2 is incompatible with int`, inserting into
`dim_candidate_quality_driver`.

Root cause: `run_simulation_incremental.py`'s `_normalize_date_columns`
decided which loaded-state columns to coerce with `pd.to_datetime` using a
name heuristic - `"date" in col.lower() or "datum" in col.lower()` - instead
of the schema's own declared types. `CandidateQualityDriver_Key` (an `INT`
primary key) contains the substring "date" inside "Candi**date**", so it
matched. Running `pd.to_datetime` on that column's small integers (1-6)
interpreted them as nanoseconds since the Unix epoch, collapsing all of them
into the same indistinguishable `1970-01-01 00:00:00` once truncated to
Python's microsecond-resolution `datetime` - which Azure SQL then rejected
as an INT/datetime2 type clash on every write. Checked every other
schema column containing "date"/"datum" (20 of them, across
`dim_employee`, `fact_employment`, `fact_recruitment`, etc.) - all genuine
dates; this was the only false positive in the whole schema.

Fixed by passing `schema` into `_normalize_date_columns` and deciding per
column from `schema[table]["types"][col].startswith("DATE")` - the same
convention `map_sql_types` already uses - instead of the column name.
Regression-tested in the new `test_run_simulation_incremental.py`: confirms
`CandidateQualityDriver_Key` survives unchanged (and as an integer dtype),
confirms genuine `DATE`-typed columns are still coerced correctly, and
confirms non-schema state entries (e.g. the plain `vacancies` counter) are
left alone. Full test suite green (207 passed).

**Confirmed no data was lost.** `get_table_write_order` places
`dim_candidate_quality_driver` at position 16 of 34, with every table
written before it a static dimension - zero `fact_*` tables were written
before the crash. Both `run_simulation.py` and `run_simulation_incremental.py`
share the convention that the `current_week` stored in `simulation_state` at
the end of a run is "the week most recently simulated," which the *next*
run always re-simulates from the persisted pre-run state before continuing
forward (not treated as "already done, skip it"). So once this fix is
deployed, the next incremental run - whether the next Monday timer or a
manual trigger of `generate_hr_data` with `HR_SIMULATION_MODE=incremental` -
will naturally redo the missing week from scratch; no manual correction of
`simulation_state` or the database was needed or made.

This bug likely predates this specific incident - it would have hit any
incremental run that ever needed to insert a new
`dim_candidate_quality_driver` row - but had never surfaced in production
before, most likely because it was being silently swallowed by the
`weekly_hr_run` exception-swallowing bug fixed earlier this project (no
`raise` after `logging.exception(...)`); this is plausibly the first time
that failure has had the chance to actually show up in the logs instead of
reporting a false "Succeeded."

### Simulation validation

#### ✅ Done: a full historical simulation has now run to completion

Covers 2020-01 through 2026-09 (~6.7 simulated years, growing from 76 to 399
active employees, 753 ever hired) with the recruitment/eligibility/
qualification/ketenregeling/safety-incident code all exercised over many
real simulated weeks. General health checked directly against the resulting
Azure SQL data: no malformed rows (0 bad/null salaries, 0 null required
keys, 0 `Einddatum < Startdatum`, 0 departures before hire, 0 negative
`Verloren_Werkdagen`, 0 out-of-range `Prestatie_Score`), row counts scale
plausibly across every major fact table, and `fact_workforce_snapshot`
headcount grows smoothly month-over-month with no crash-and-partial-write
signature. One negligible cosmetic finding, not worth chasing: 2 of 8,994
`fact_recruitment` rows (0.02%) are `Status='Aangenomen'` with a null
`Employee_Key`.

New roles' real-world reachability (below) and every "first-pass numbers,
revisit after a longer run" item elsewhere in this file were verified
against this same run - see the relevant section for each (Gender ratio and
pay gap, Safety incidents, Recruitment, Multi-site locations, Workforce
planning).

#### ✅ Confirmed: new roles' real-world reachability

Every company-scope-gated role whose `active_from_headcount` threshold this
run's headcount actually crossed had at least one employee hold it via a
normal growth vacancy, not just direct start-population placement - see
"Workforce planning" above for the full breakdown (this also surfaced and
fixed a real bug: internal promotion/transfer could bypass the threshold
entirely, now fixed).

## 2026-09-18

### ✅ Added: ketenregeling (Dutch temporary-contract chain rule)

By Dutch law, an employee may have at most 3 temporary (`Tijdelijk`)
contracts, or 3 years of consecutive temporary employment, whichever comes
first - the next contract at that point must be permanent (`Vast`). Despite
`dim_event_type` already carrying `"Contract omgezet naar vast"`/`"Contract
verlengd"` and `career_events.contract_change_rate` existing in config since
the very first commit, nothing anywhere ever read `Contract_einddatum` to
decide what happens when a temporary contract expires - it was set once at
hire and simply copied forward unchanged by every later event (promotion,
transfer, salary review), forever. Live data showed employees on their 7th
temporary contract round with no conversion ever triggered.

Added `ContractLifecycleSimulator` (`simulation_contracts.py`), which runs
before `AttritionSimulator` each week and resolves every active `Tijdelijk`
contract whose `Contract_einddatum` has arrived:
- **Cap reached** (`Contract_ronde >= max_contract_rounds` (3) OR
  cumulative temporary tenure >= `max_temporary_years` (3.0), using
  `Aaneengesloten_Indienst_Datum` - true continuous tenure, not the
  resettable row `Startdatum` - the same fix already applied to the
  performance-review bug) - only two outcomes are legally valid:
  convert to `Vast` (`contract_rules.<afdeling>.keten_conversion_kans`) or
  let the contract lapse (a real departure, reason `"Contract niet
  verlengd"` - `dim_departure_reason`'s existing `"tijdelijk"` category,
  itself unreachable before this change since `AttritionSimulator` never
  selected it).
- **Cap not reached**: renew (default), or convert early. Early conversion
  is now performance-aware rather than flatly random, per the user's
  request: a live 90th-percentile threshold is computed each week from the
  active population's `Prestatie_Score`; employees at or above it use
  `chain_rule.top_performer_conversion_kans` (0.6), everyone else uses the
  previously-dormant `career_events.contract_change_rate` (0.03) as a small
  baseline chance. A modest, performance-weighted chance of early
  non-renewal exists too (poor performers, mirroring the multiplier shape
  `AttritionSimulator` already uses elsewhere).

New config: `career_events.chain_rule` (`max_contract_rounds`,
`max_temporary_years`, `renewal_duration_years`, `top_performer_percentile`,
`top_performer_conversion_kans`) and `contract_rules.<afdeling>.keten_conversion_kans` -
all first-pass values, not calibrated against a longer run yet.

Renewal/conversion reuse the established "close the row, keep its own
EventType_Key, append a new self-contained row" pattern; non-renewal reuses
the departure terminal-row mechanism built for the attrition fix, now
extracted into a shared `infrastructure/departure_records.py` helper so
neither simulator duplicates that (non-trivial, `Previous_Employment_Key`-
sensitive) logic.

**Bug found and fixed while integration-testing this** (not a bug in the new
simulator - found because nothing had ever checked this before):
`EmploymentFactory._choose_contract` computed `Contract_ronde =
tenure_years_at_hire + 1` for the *initial population* with no cap at all -
an employee backdated 7-8 years at population-generation time was created
already sitting on contract round 8, in violation of the law from the moment
they existed. `ContractLifecycleSimulator` was correctly converting these to
`Vast` the moment their contract came due (proving its own cap logic
correct), but the already-invalid historical row remained in the data.
Fixed by capping eligibility for a `Tijdelijk` placement at initial
generation: if the backdated tenure would already exceed
`max_contract_rounds`/`max_temporary_years`, the employee is placed as
`Vast` instead (a real person with that much tenure would already have
converted, long before "today"). Only affects backdated initial-population
placements - a genuine new hire always has zero tenure at hire time.

Verified with a focused unit suite (`test_simulation_contracts.py`: renewal,
conversion, non-renewal via the shared terminal-row mechanism, cap
enforcement via both the round-count and cumulative-tenure paths, continuous-
tenure correctness across a mid-contract event, and a statistical check that
top performers convert early far more often than average performers) plus a
narrow 3-year/150-headcount integration run through the real weekly
pipeline confirming `Contract_ronde` never exceeds 3 and all three outcomes
(renewal, conversion, non-renewal) occur with sane relative frequencies.
Full test suite green (195 passed).

**✅ Confirmed at real scale by a full run (2020-01 to 2026-09).** Across
432 `Tijdelijk` rows in `fact_employment`, `MAX(Contract_ronde) = 3` - the
cap is never violated. Realized outcome mix for contracts that reached
resolution: renewal 70.6% (108), conversion to `Vast` 11.1% (17),
non-renewal 18.3% (28) - all three occur at sane, non-degenerate
frequencies. No config change needed.

### Performance reviews

#### ✅ Fixed: reviews permanently frozen for ~36% of tenured employees

A live-data check (an employee with 5 years of history and a single,
never-changing performance score) found that 67 of 185 active employees with
more than 2 years' tenure (36%) had not received a performance review in
over 2 years - some frozen for 8+ years, with `dim_employee.Prestatie_Score`
stuck at whatever their last review happened to produce.

Root cause: `PerformanceSimulator.run_weekly` computed tenure as
`today - employment["Startdatum"]`, using the *current* `fact_employment`
row's start date. A routine annual salary review (or promotion/transfer)
closes the old row and opens a new one with `Startdatum` reset to that
event's date - correct for `fact_employment` itself (it is event/effective-
period based, not a tenure proxy - see the core invariants), but wrong to
reuse as "years at the company." Since the performance-review week
(`_review_week`, hashed on `employee_key * 31`) and the salary-review week
(`_salary_review_week` in `simulation_career_events.py`, hashed on
`employee_key * 37`) are both fixed per employee, the calendar gap between
them each year is constant. For a deterministic ~36% of employees that gap
is under 180 days, so the `tenure_days < 180` guard tripped every single
year, forever; for the rest the gap was long enough and reviews proceeded
normally, which is why most employees looked fine.

Fixed by adding `PerformanceSimulator._tenure_days(emp, today)`, which uses
`dim_employee.Aaneengesloten_Indienst_Datum` (the true continuous hire date,
already used correctly for this purpose in `simulation_career_events.py`)
instead of the active employment row's `Startdatum`. This also corrects the
"tenure-based groei" bonus inside `_calculate_score` for every employee who
has ever had a salary review, promotion or transfer, not just the frozen
36% - that bonus was silently capped near its minimum (based on time since
the last such event) rather than scaling up toward its 0.3 maximum for
genuinely long-tenured employees.

Regression-tested in `test_simulation_performance.py` (reproduces the exact
scenario: a long-tenured employee whose active employment row was reset 60
days ago by a routine event); verified the added test fails without the fix
and passes with it. Full test suite green (154 passed).

This is a historical-logic fix: it only affects reviews generated by future
simulated weeks. The already-generated frozen scores in the current dataset
needed a full run to backfill (not run as part of this fix, per instruction).

**✅ Backfill confirmed via a real full run (2020-01 to 2026-09).** Of 180
active employees with >2 years' tenure, **0** have gone more than 1.5-2
years since their last review and **0** have never been reviewed (max days
since last review: 361; average 186) - the prior 36% frozen-review rate is
fully gone.

### Departures

#### ✅ Fixed: a departure could silently erase the last raise/promotion/transfer event on that row

Found by inspection: a leaver's final `fact_employment` row would sometimes
show a higher `Salaris` than the row before it, with no `Salarisaanpassing`
(or `Promotie`/`Transfer`) event recorded anywhere to explain the increase.

Root cause: `AttritionSimulator.run` closed a departing employee's *current*
active row **in place** - it set `Dienstverband_status = "Uit dienst"`,
`Einddatum = today`, and overwrote that row's `EventType_Key` to `"Uit
dienst"`, regardless of what the row's `EventType_Key` had actually recorded
about its own `Startdatum` (a hire, promotion, transfer, or routine salary
review). Every other superseded row in this table records what happened at
*its own* `Startdatum`; departure is different in kind - it's an instant
(what happens at `Einddatum`), not a continuing employment period - so
reusing the same row for both meanings meant the row's *original* event was
always destroyed the moment that same person later left.

Fixed by giving departure its own terminal row instead of overwriting the
existing one, matching how promotions/transfers/salary reviews already
close a superseded row without touching its `EventType_Key`:
- The employee's active row is closed normally: `Einddatum = today`,
  `Dienstverband_status = "Inactief"` - its own `EventType_Key` is left
  alone, so it keeps recording whatever genuinely happened at its own
  `Startdatum`.
- A new row is appended: `Startdatum = Einddatum = today` (the departure
  instant, not a period), `Dienstverband_status = "Uit dienst"`,
  `EventType_Key` = "Uit dienst", `Previous_Employment_Key` pointing at the
  row it closes, carrying the same final Role/Location/Shift/SalaryScale/
  Streef_Compa_Ratio/Salaris/Contract context as a self-contained snapshot
  (matching the "every event row is self-contained" convention
  `simulation_career_events.py` already follows), plus the
  satisfaction/engagement-at-exit fields.

This is a genuinely new row shape for `fact_employment`: a zero-duration row
(`Startdatum == Einddatum`). Every consumer that picks a "current" or
"representative" row per employee was audited before implementing this
(`manager_builder._current_employment_rows`, `employee_status.
sync_employee_employment_status`/`_continuous_service_start`,
`workforce_snapshot._active_employment`, `manager_assignment.
sync_manager_assignments`, `departure_context.sync_departure_satisfaction`) -
all either already filter to `Dienstverband_status == "Actief"` first (so a
departed employee's rows, old or new shape, never reach them) or already
handle a departed employee's "latest row" correctly given the new row
carries the same context fields as before. `_continuous_service_start`
specifically needed `Previous_Employment_Key` to be set correctly on the new
terminal row, or it would have reported `Aaneengesloten_Indienst_Datum` as
the departure date instead of the true continuous hire date - verified with
a dedicated regression test that a multi-event chain still resolves the
original hire date through a same-day terminal row. A second regression test
confirms `assign_managers` still resolves `Role_Key`/`Department_Key` from
the new terminal row for a departed employee.

`EventType_Key = "Uit dienst"` continues to be set (on the new row, not the
old one), since the application reads it there. Full test suite green
(187 passed, including two new targeted regression tests plus updated
existing attrition/retirement tests reflecting the two-row shape).

### Recruitment & eligibility (done parts)

- ✅ **Fixed: `eligible_internal` had no leadership-experience check beyond
  the first management move.** `role_eligibility.eligible_internal` used to
  apply a leadership-experience rule only to the *first* move from a
  non-management role into a management role (`exp < 3`, a
  general-relevant-experience proxy, since a first-time internal candidate
  has no leadership tenure to measure yet); unlike `eligible_external`, it
  never checked `Min_Leidinggevende_Ervaring_Jr` for a *further* internal
  promotion between management roles (e.g. team lead → manager → director).
  Fixed by adding `leadership_experience(state, employee_key, date)` next to
  `relevant_experience()` (sums time in any role where `Leidinggevend ==
  True` from the employee's own `fact_employment` history - the internal
  equivalent of the `Leidinggevende_Ervaring_Jaren` external candidate
  profiles already carry), and gating a further leadership move (both
  `source_role.Leidinggevend` and `target_role.Leidinggevend` true - the
  first move is handled separately and unaffected) on
  `leadership_experience(...) >= target_role.Min_Leidinggevende_Ervaring_Jr * discount`.
  `discount` is the new `career_events.internal_leadership_experience_discount`
  (first-pass value 0.6) - deliberately lower than the external bar, since
  an internal candidate's leadership track record is already directly
  observed by the organization rather than self-reported. Tested in
  `test_role_eligibility.py`: rejects a further leadership move below the
  discounted bar, accepts one above it, and confirms the original
  first-move rule is unaffected.
- ✅ **Dedicated eligibility tests added** in `test_role_eligibility.py` for
  the WO "senior" experience exception in `_required_relevant_experience`,
  education-direction / diploma-and-certificate matching in
  `_matching_credentials`, and `relevant_experience()`'s role-history logic
  (a source role counts only when it is the target itself or reachable via a
  configured `logische_doorgroei`/`laterale_transfers` path, and only up to
  the as-of date).
- ✅ **Fixed: `_matching_credentials` could never accept a DataFrame of
  credentials.** `_credential_rows`'s `if not credentials:` guard ran before
  its own `isinstance(credentials, pd.DataFrame)` branch; pandas raises
  `ValueError: The truth value of a DataFrame is ambiguous` on that check for
  *any* DataFrame (empty or not), so the DataFrame-handling branch was dead
  code. Harmless in practice (every real caller, `simulation_recruitment.py`,
  always passes a plain list), but the function's own docstring and
  `isinstance` branch already declared DataFrame support as part of its
  contract, so fixed rather than removed: check `isinstance` first, then the
  falsiness check for `None`/an empty list. Tested with both a populated and
  an empty DataFrame. Full test suite green (187 passed).

### Configuration validation

- ✅ **Automated validation added for the 55-role configuration.**
  `src/infrastructure/config_validation.py` (`validate_role_configuration`)
  checks, for every role in `role_career_paths`/`structure`: `role_key`
  values are unique, every role within a department agrees on that
  department's `department_key` and no two departments share one, every
  `logische_doorgroei`/`laterale_transfers` target names an existing role, a
  lateral transfer target shares the source role's `salary_scale_code`, no
  role with a non-zero `target_weight`/`fte_ratio` has an
  `active_from_headcount` beyond `growth.max_capacity` (i.e. is
  structurally unreachable), and every `relevante_opleidingen` entry
  resolves to a real `dim_education` row. `test_config_validation.py` unit-
  tests each rule against small broken fixtures and also runs the validator
  against the real `maakindustrie.json` via `ConfigLoader` - it currently
  passes with zero problems. Not yet wired into `ConfigLoader.load()` itself
  (that would make a config error fail loudly at startup instead of only
  when this test runs) - worth doing once there's appetite for that being a
  hard startup failure rather than a test-suite check.

## 2026-09-03

### Recruitment

#### ✅ Fixed: vacancies stuck open for months (time-to-close bug)

A live-data check found Productie vacancies open 100-180+ days, with dozens
of candidates piling up "In behandeling" at Gesprek and never reaching a
hire. Root-caused to two compounding issues, both fixed:

- **`source_profiles.Vacaturebank.minimum_offer_quality` was miscalibrated.**
  Every other source has its quality bar comfortably below its own
  `candidate_quality_mean` (so most candidates pass); Vacaturebank had it
  *above* its mean (3.25 vs. 2.6 - only ~16% of candidates could ever clear
  it), and Vacaturebank is by far Productie's dominant source
  (`application_volume_weight` 4.8, plus a 1.6x Productie-specific
  multiplier - roughly half of all Productie applicants). Lowered to 2.5,
  putting its pass rate (~57%) in line with Campus, the other open-channel
  source (~53%).
- **Interview throughput was structurally incapable of keeping up with
  inflow.** `_resolve_interview` evaluated exactly one Gesprek candidate per
  vacancy per week (at a 30% chance even then), while an outstanding Aanbod
  offer froze *all* evaluation for that vacancy until it resolved (up to 28
  days). Productie's Gesprek inflow (~1.8/week) vastly exceeded this
  throughput, so the backlog could only grow. Fixed in
  `simulation_recruitment.py`:
  - `interview_capacity_by_department` (new config) lets multiple Gesprek
    candidates be evaluated per week, scaled to each department's actual
    application volume (Productie/Techniek/Logistiek/Sales get 2-3;
    low-volume departments keep 1, since they never had a queueing problem).
  - Extending an actual offer is still serial (only one candidate is ever
    at Aanbod per vacancy), but evaluating *other* Gesprek candidates no
    longer freezes while that offer is outstanding - a candidate who clears
    the quality gate in the meantime waits, already evaluated
    (`_promote_queued_candidate`), for the next free Aanbod slot.
  - Internal-mobility candidates are no longer pre-marked as interviewed at
    application time - a pre-existing quirk that would have silently
    exempted them from the new "not yet evaluated" bookkeeping; they now go
    through the same interview quality gate as external candidates, as the
    class docstring already claimed.

  Two additional backstops guard against a recurrence of this failure mode
  in general, not just this specific bug:
  - `gesprek_patience_days` (56) - a candidate who has waited too long in
    Gesprek withdraws (`Kandidaat heeft zich teruggetrokken`, a new
    `dim_decline_reason` entry), shrinking a stuck backlog directly rather
    than only processing it faster.
  - `vacancy_expiry_days` (90) - a vacancy still open past this threshold
    closes without a hire (`Vacature ingetrokken`, a new
    `dim_rejection_reason` entry); the normal understaffing check raises a
    fresh vacancy on a later week if the seat is still needed.
  - `max_pending_pipeline_per_vacancy` (15) - stops sourcing new
    applications once a vacancy already has more candidates queued than it
    can plausibly work through.

  Verified with a 90-simulated-week in-memory run (seed 3, full production
  pipeline, real config): 87 of 95 Productie vacancies closed within the
  window, median time-to-close 28 days (was 100+), max 91 days; 86 of those
  87 closed via an actual hire (only one via the expiry backstop); max
  simultaneous backlog per vacancy was 8, well under the 15 cap; 21
  candidates withdrew via the new patience mechanism. Full test suite green
  (142 passed) plus updated/added unit tests for the new interview-capacity,
  offer-serialization, and internal-candidate-evaluation behavior.

  All four new config values (`interview_capacity_by_department`,
  `gesprek_patience_days`, `max_pending_pipeline_per_vacancy`,
  `vacancy_expiry_days`) are first-draft numbers themselves - revisit
  alongside the other recruitment estimates once a longer real run is
  available.

## 2026-08-27 and earlier

### Multi-site locations (implemented, first-pass numbers)

- `dim_location` is now config-driven (`active_from_headcount`/scope,
  capacity, capacity-streak-triggered second site, department relocation on
  open) instead of a flat static distribution.
- **✅ Verified against a real full run (2020-01 to 2026-09, ended at 399
  active employees): DC and Hoofdkantoor confirmed as-is.** Both opened
  exactly when their configured `active_from_headcount:40` threshold was
  crossed (Logistiek headcount for DC, combined
  Finance+HR+Sales+Marketing+Directie+IT for Hoofdkantoor), each as a single
  batch of exactly 40 `Locatietransfer` rows in one week - confirms the
  documented "batch, not gradual" relocation behaves as designed, not as an
  anomaly. No config change.
- **✅ Verified against a bigger full run (same 2020-01 to 2026-09 window,
  791 active employees this time): Fabriek Zuid opened, and the Noord/Zuid
  transfer-flux rates confirmed as-is.** Noord: 337, Zuid: 244, DC: 102,
  Hoofdkantoor: 108 (sums to 791). Noord's raw headcount actually passed 300
  back in Apr/May 2023 but didn't trigger Zuid for over a year - not a bug:
  `open_locations` compares against `capacity + capacity_bonus`, and Noord
  had been carrying DC's `capacity_bonus_amount: 80` since DC opened in Oct
  2021 (Logistiek's home site before it relocated), making the *effective*
  trigger 380, not the nominal 300. Noord crossed 380 in Aug 2024 and held
  it for the required 8-week streak; Zuid's first `Locatietransfer` fired
  2024-09-30. Previously undocumented in intuitive terms, not a defect -
  worth remembering next time "why didn't Zuid open yet" comes up.
  Ordinary Noord<->Zuid flux: 31 events (on top of the same 40+41 one-time
  DC/Hoofdkantoor relocation batches as before), all dated after Zuid's
  open date, with a visible early cluster tapering to a steady trickle -
  back-of-envelope expected count from the configured rates (~478
  multi-site-eligible employees, ~103 weeks Zuid was open) is ~32. No
  config change - `location_transfer_rate`/`new_site_pull_rate`/
  `new_site_pull_weeks` (0.03/0.15/12 weeks) confirmed reasonable as first-pass
  numbers. No recurrence of the `_remaining_headroom` crash below, and no
  data-quality issues (no Zuid rows before its open date, no orphaned
  Location_Key references, exactly the configured `multi_site` role set
  present at Zuid).

#### ✅ Fixed: crash once Fabriek Zuid opens

Found incidentally while calibrating the gender pay gap on an unrelated small
in-memory run. `dim_location.Fabriek Zuid` had no `capacity` configured,
unlike Fabriek Noord (300). `_remaining_headroom` in `location_assignment.py`
defaults a missing capacity to `float("inf")`. Once both Noord and Zuid were
open production sites at the same time, `resolve_location`'s
`rng.choices(open_sites, weights=weights)` received an infinite weight for
Zuid and crashed with `ValueError: Total of weights must be finite` for
every `multi_site` role hire/transfer/promotion from that point on - this
would have happened in any sufficiently long real full run once Fabriek
Noord's headcount reached 300, not just in an edge-case test.

Fixed by giving `Fabriek Zuid` an explicit `capacity: 600` - deliberately
double Fabriek Noord's 300, on the reasoning that a production company
opening a second site (after outgrowing the first) typically builds it
larger for future growth, not equal or smaller.

The test fixture in `test_location_assignment.py` had the identical gap
(no capacity on its own `Fabriek Zuid` fixture), which is exactly why no
existing test had caught this: none of them called `resolve_location` with
both sites open and no `preferred_location_key` - the one path that actually
reaches the weighted `rng.choices` call. Fixed the fixture the same way
(`capacity: 20`, double its `Fabriek Noord`'s 10) and added
`test_resolve_location_multi_site_chooses_between_multiple_open_sites_without_crashing`,
which exercises exactly that path. Verified the new test fails with the
original `ValueError` when the fixture capacity is reverted, and passes with
it restored. Full test suite green (155 passed).

### Data model: Dutch/English naming convention (done parts)

**✅ Fact tables (done).** Producer/consumer code, the schema and
`maakindustrie.json`'s `recruitment.candidate_quality_weights` keys were
updated together; full test suite green (142 passed) plus a direct
`SalaryPolicy`/`SalaryBenchmarkBuilder` smoke check. Renamed:
- `fact_employment.Target_Compa_Ratio` → `Streef_Compa_Ratio`.
- `fact_safety_incident.Lost_Workdays` → `Verloren_Werkdagen`.
- `fact_vacancy.Vacancy_Reason` → `Vacature_Reden`.
- `fact_recruitment.Vacancy_Reason` → `Vacature_Reden`;
  `Candidate_Quality` → `Kandidaat_Kwaliteit`; `Candidate_Experience_Score`
  → `Kandidaat_Ervaring_Score`; `Candidate_Education_Relevance_Score` →
  `Kandidaat_Opleiding_Relevantie_Score`; `Candidate_Technical_Skills_Score`
  → `Kandidaat_Technische_Vaardigheden_Score`; `Candidate_Soft_Skills_Score`
  → `Kandidaat_Sociale_Vaardigheden_Score`; `Candidate_Motivation_Score` →
  `Kandidaat_Motivatie_Score`; `Days_To_Decision` → `Dagen_Tot_Beslissing`.
  Date columns (`Application_Date`, `Decision_Date`, `Screening_Date`,
  `Interview_Date`, `Offer_Date`) left as-is per the date exemption.
- `fact_workforce_snapshot.Performance_Score` → `Prestatie_Score`;
  `SalaryStep` → `Salaris_Trede`.
- `fact_salary_benchmark.SalaryStep` → `Salaris_Trede`;
  `Scale_Min_Salaris` → `Schaal_Min_Salaris`; `Scale_Max_Salaris` →
  `Schaal_Max_Salaris`; `Market_P25` → `Markt_P25`; `Market_Median` →
  `Markt_Mediaan`; `Market_P75` → `Markt_P75`. `Benchmark_Date` left as-is
  (date exemption).
- `fact_performance_review.Performance_Score` → `Prestatie_Score`.
  `Review_Datum` left as-is (date exemption).

Note the resulting asymmetry is intentional and temporary:
`dim_employee.Performance_Score`/`Initial_Performance_Score` were
deliberately **not** touched in this pass (dims are the second phase, done
separately so a Power BI fix-up doesn't have to happen all at once) - the
fact-side columns feeding from them (`fact_workforce_snapshot`,
`fact_performance_review`) are now `Prestatie_Score` while the dim-side
source stays `Performance_Score` until that second phase lands.

**✅ Fact-table stored values (done, separate follow-up pass).** Column
names are not the only thing that can be English - a column can have a
correctly-Dutch name while the literal values stored in it are still
English. Checked every fact table's free-text columns (dates/numbers/keys
excluded - nothing to check there) against their producer code; two
columns held English values:
- `fact_vacancy.Status`: `"Closed"` → `"Gesloten"` (`"Open"` unchanged - the
  same word in Dutch).
- `fact_vacancy.Vacature_Reden` and `fact_recruitment.Vacature_Reden` (same
  shared concept and values): `"Replacement"` → `"Vervanging"`, `"Growth"`
  → `"Groei"`, `"Internal mobility backfill"` → `"Interne doorstroom"`.

`fact_recruitment.Status` (`"Aangenomen"`/`"Afgewezen"`/`"Geweigerd"`/`"In
behandeling"`), `fact_employment.Dienstverband_status`/`Contracttype`, and
`fact_workforce_snapshot.Benchmark_Status` were already Dutch - confirmed,
not changed. Full test suite green (142 passed) after this pass too.

**Bug found and fixed after this pass**: a full run surfaced
`KeyError: 'Performance_Score'` in
`src/infrastructure/absence_context.py::_performance_as_of` -
`sync_absence_satisfaction`'s per-episode performance lookup still read
`fact_performance_review`'s old column name; it now reads `Prestatie_Score`.
This file had shown up in the original discovery grep for the
`fact_performance_review.Performance_Score` rename but was missed when the
rest of that rename's call sites were fixed, since it isn't exercised by the
unit suite's mocked-state fixtures (only a fuller run reaches this
`fact_performance_review`-populated path). Re-verified with a direct
reproduction of the exact code path (a non-empty performance-review match)
plus a full grep sweep of every remaining `Performance_Score` reference in
`src/` - all others confirmed to genuinely read `dim_employee`'s
still-English column, not the renamed fact column.

**✅ Dim tables (done).** Every business-content column below was renamed
to Dutch; keys/table names stayed English, and the boolean flags
(`Is_Shift_Work`, `Recordable`) were left English per the flag exemption
rather than folded in automatically. For the generic config-driven
dimensions (list-of-dicts shape, e.g. `dim_hire_source`,
`dim_recruitment_status`), `maakindustrie.json`'s own field names had to be
renamed to match, since the generic `generate_dimensions()` factory maps
config fields to schema columns by exact name - a silent-blank-data risk if
missed, not just a crash. For the bespoke-built ones (`dim_department`,
`dim_role`, `dim_departure_reason`) only the builder function's output and
its consumers changed; the config's own internal shape was untouched:
- `dim_department`: `Department_Name` → `Afdeling_Naam`.
- `dim_role`: `Department_Name` (denormalized copy) → `Afdeling_Naam`;
  `Role_Name` → `Functie_Naam`.
- `dim_location`: `Location_Name` → `Vestiging_Naam`.
- `dim_hire_source`: `HireSource_Name` → `Bron_Naam`; `Source_Group` →
  `Bron_Groep`; `Source_Description` → `Bron_Omschrijving`.
- `dim_recruitment_status`: `Status_Name` → `Status_Naam`; `Status_Verbose`
  → `Status_Omschrijving`; `Status_Group` → `Status_Groep`.
- `dim_recruitment_stage`: `Stage_Name` → `Fase_Naam`.
- `dim_decline_reason`: `DeclineReason_Name` → `Weigeringsreden_Naam`;
  `Category` → `Categorie`.
- `dim_rejection_reason`: `RejectionReason_Name` → `Afwijzingsreden_Naam`;
  `Category` → `Categorie`.
- `dim_education`: `Education_Name` → `Opleiding_Naam`; `Education_Level` →
  `Opleidingsniveau`; `Education_Direction` → `Opleidingsrichting`.
- `dim_absence_type`: `AbsenceType_Name` → `Verzuim_Type_Naam`.
- `dim_satisfaction_band`: `SatisfactionBand_Name` →
  `Tevredenheidsband_Naam`.
- `dim_satisfaction_driver`: `Driver_Name` → `Factor_Naam`; `Direction` →
  `Richting`.
- `dim_engagement_band`: `EngagementBand_Name` → `Betrokkenheidsband_Naam`.
- `dim_performance_driver`, `dim_engagement_driver`,
  `dim_candidate_quality_driver`: `Driver_Name` → `Factor_Naam` (all three).
- `dim_salary_band`: `SalaryBand_Name` → `Salarisband_Naam`.
- `dim_salary_scale`: `SalaryScale_Code` → `Salarisschaal_Code`;
  `SalaryScale_Name` → `Salarisschaal_Naam`.
- `dim_shift`: `Shift_Name` → `Ploegendienst_Naam` (`Is_Shift_Work` stays -
  flag exemption).
- `dim_incident_type`: `IncidentType_Name` → `Incidenttype_Naam`
  (`Recordable` stays - flag exemption).
- `dim_employee`: `Gender` → `Geslacht`; `Performance_Score` →
  `Prestatie_Score`; `Initial_Performance_Score` →
  `Aanvangs_Prestatie_Score` (this also resolves the temporary asymmetry
  noted in the fact-table section above - the dim and fact sides now share
  the same Dutch name).
- `dim_departure_reason`: `DepartureReason` → `Vertrekreden`; `Category` →
  `Categorie`.
- `dim_event_type`: `EventType` → `Gebeurtenis`.

Verified via the full test suite (142 passed) plus an in-memory,
SQL-free 60-simulated-week run through the real production pipeline
(`WorkforceGenerator` → weekly simulation → `sync_absence_satisfaction` →
`build_workforce_snapshots`, the same code path that surfaced the
fact-table rename's `absence_context.py` bug) - every dim table's actual
generated columns were inspected directly and matched the renamed set
exactly, with no stale/blank columns.

### The old BACKLOG header list (everything implemented and verified before 2026-09-18)

Outstanding work only. Anything already implemented and verified (external
recruitment eligibility screening, the profile hand-off from recruitment into
hiring, the `fact_employee_qualification` row on new hires, the
`credentials_for` column-name bug, headcount-based role activation via
`active_from_headcount`/`active_from_scope`, the softened under-minimum
growth selection, the Marketing/Product Manager addition, the removal of
`IT Support`, and the per-role headcount ceiling - `max_count` for flat
single-seat roles plus the `Productiemanager`-specific
`secondary_site_manager_threshold`, the new `CFO`/`Commercial Director`
Directie seats, enforced in initial allocation, growth-vacancy selection and
internal promotion/transfer; the team-lead span-of-control fix (`max_team_size`
now applies every week, not just at initial allocation, and gives the
department's team-lead role a matching dynamic ceiling); and candidate-side
decline reasons plus employer-side rejection reasons on `fact_recruitment`
(`dim_decline_reason`, `dim_rejection_reason`), the rejection reason derived
causally from whichever eligibility/quality check actually failed rather than
sampled independently; and the multi-stage recruitment funnel (`fact_recruitment`
now genuinely persists and mutates across real simulated weeks through
Sollicitatie -> Screening -> Gesprek -> Aanbod, with `dim_recruitment_stage`,
an `"In behandeling"` status, and per-stage dates; screening/interview
pass-fail is causal (eligibility, then a quality bar), only the timing of
each stage's resolution is probabilistic; internal mobility skips straight to
Gesprek since `eligible_internal` already screened it; at most one Aanbod
offer is outstanding per vacancy at a time, filled from the longest-waiting
Gesprek candidate); and safety incidents (`fact_safety_incident` +
`dim_incident_type`, weekly risk driven by department, shift and a new-hire
multiplier, a configured safety-pyramid type mix, and a lost-time incident
also creating the matching `fact_absence` episode - type `Bedrijfsongeval` -
so it feeds the same verzuim reporting rather than living in an isolated
table) - is intentionally left off this list.
