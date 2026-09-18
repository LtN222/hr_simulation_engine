# Backlog

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

## ✅ Added: ketenregeling (Dutch temporary-contract chain rule)

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

## Performance reviews

### ✅ Fixed: reviews permanently frozen for ~36% of tenured employees

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
need a full run to backfill (not run as part of this fix, per instruction).

## Departures

### ✅ Fixed: a departure could silently erase the last raise/promotion/transfer event on that row

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

## Gender ratio and pay gap (first-pass numbers, revisit after a longer run)

- `gender_ratio` (department defaults plus `role_overrides`) replaces the
  previous flat, role-independent 49/49/1/1 gender draw, which used to make
  it possible (and did happen) for the top earners and the entire Directie
  to randomly land as all-female. Values are calibrated by real-world
  reasoning per department/role (e.g. Productie/Techniek mannelijk-leunend,
  Kwaliteit/HR/Productontwikkelaar vrouw-leunend, Directie 70:30 - a
  deliberately optimistic rather than strictly realistic number, since this
  is a fictional "we already do slightly better" company), not against a
  specific benchmark dataset. Revisit once a longer run shows the realized
  department-level ratios at scale (small-sample noise is expected on any
  short/small test run - e.g. a department with ~30 people can plausibly
  show 0 of the minority gender even when correctly configured).
- `salary_benchmark.compa_ratio.gender_pay_gap` (`female_starting_offset`
  -0.036, `female_review_offset` -0.0018) is a deliberate, function-corrected
  gender pay gap - without it, the corrected gap would trend toward 0% since
  nothing else in the salary logic looks at gender. Calibrated on a small
  in-memory run (~250 employees, 2 simulated years, two seeds) to land the
  role-corrected gap around 4-5%, intentionally better than the CBS 2024
  bedrijfsleven benchmark (6.1% corrected) but not zero. Revisit against a
  real full-length run, where a much larger, multi-year population should
  converge more tightly on the target band than the small calibration run did.

## Safety incidents (first-pass numbers, revisit after a longer run)

- `safety.annual_incident_rate_by_department`, the shift/new-hire multipliers
  and `type_weights` are first-draft estimates (not calibrated against any
  real OHS benchmark beyond a rough safety-pyramid shape). Revisit once a
  longer run shows actual incident/LTI counts per department.

## Recruitment (first-pass numbers, revisit after a longer run)

- `recruitment.weekly_applications_by_department`, `screening_decision_rate`
  (0.6) and `interview_decision_rate` (0.3, now a per-candidate scheduling
  chance within each week's `interview_capacity_by_department` slots rather
  than a single candidate's only chance - see the fix below) are
  first-draft estimates, scaled down from the old one-shot
  `applications_per_hire_by_department` model. Revisit once a longer run
  shows actual time-to-fill per department.
- A rare edge case is now handled defensively rather than eliminated: if
  `HiringSimulator` closes a vacancy without a hire (a capacity conflict with
  a capped role - see below), any other in-progress pipeline applications for
  that vacancy are closed out as "Afgewezen" too, so nothing is left stuck at
  "In behandeling" forever. This is a backstop for an already-rare race, not
  a normal funnel outcome.

### ✅ Fixed: vacancies stuck open for months (time-to-close bug)

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

## Multi-site locations (implemented, first-pass numbers)

- `dim_location` is now config-driven (`active_from_headcount`/scope,
  capacity, capacity-streak-triggered second site, department relocation on
  open) instead of a flat static distribution. First-pass numbers to revisit
  once a longer run shows how they land: Fabriek Noord capacity 300 (8-week
  streak), Fabriek Zuid capacity 600 (double Noord's, on the reasoning that a
  second site is typically built larger - see the fix below, not yet
  validated against a real run), DC at Logistiek headcount 40 (+80 capacity
  bonus to whichever site currently hosts Logistiek), Hoofdkantoor at
  combined Finance+HR+Sales+Marketing+Directie+IT headcount 40.
- The one-time department relocation (Logistiek -> DC, office departments ->
  Hoofdkantoor) moves everyone in one batch the week the location opens,
  not gradually over a "short window" as discussed - simpler, and probably
  fine for a demo dataset, but worth knowing if the sudden batch shows up
  oddly in a single week's data.
- The Noord/Zuid location-transfer flux (`location_transfer_rate`,
  `new_site_pull_rate`, `new_site_pull_weeks` in `career_events`) has first-
  pass values (0.03 / 0.15 / 12 weeks) with no real-world anchor - revisit
  once observable in a long run.

### ✅ Fixed: crash once Fabriek Zuid opens

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

## Workforce planning

- **New `active_from_headcount`/`active_from_scope` values are a first
  draft.** They were set from a mix of specific real-world reference points
  and reasonable interpolation for roles not explicitly discussed (Productie,
  Logistiek, HR, Finance, Directie specifics). Revisit once a longer run
  (into the 300-500 headcount range) is available to see how they land in
  practice, per the plan to spread late-tier thresholds so they don't cluster.
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

## Recruitment & eligibility

- **Qualification/certification events during employment.** Qualification
  history (`fact_employee_qualification`) is now populated at hire time, but
  there is still no simulated event for gaining a qualification *during*
  employment (e.g. a VAPRO or IT certificate obtained on the job). Without
  it, an employee's credentials never change after hire, which caps how
  realistically internal promotion/transfer eligibility can evolve over a
  long career.
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

## Configuration validation

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

## Simulation validation

- **A full historical simulation has not yet run to completion** with the
  new recruitment/eligibility/qualification code exercised over many
  simulated weeks. Validate this with an in-memory, SQL-free run over a
  short time window first (per the "no full-length runs while iterating"
  guidance), before relying on a full production-scale run to surface
  issues.
- **New roles' real-world reachability is unverified.** Confirm that roles
  configured with `initially_staffed: false` and an `active_from` date can
  actually be filled over the course of a normal historical simulation
  (via growth vacancies and workforce planning) rather than only being
  reachable by being placed directly in the start population.

## Documentation

- `architecture.txt` and `README.md` have not been updated for the new
  55-role model, the qualification-history fact, or the new
  recruitment/mobility eligibility rules. `CLAUDE.md` has interim working
  notes, but the canonical docs are stale on this area.

## Data model: Dutch/English naming convention

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
