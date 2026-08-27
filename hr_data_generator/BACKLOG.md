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

## Safety incidents (first-pass numbers, revisit after a longer run)

- `safety.annual_incident_rate_by_department`, the shift/new-hire multipliers
  and `type_weights` are first-draft estimates (not calibrated against any
  real OHS benchmark beyond a rough safety-pyramid shape). Revisit once a
  longer run shows actual incident/LTI counts per department.

## Recruitment (first-pass numbers, revisit after a longer run)

- `recruitment.weekly_applications_by_department`, `screening_decision_rate`
  (0.6) and `interview_decision_rate` (0.3) are first-draft estimates, scaled
  down from the old one-shot `applications_per_hire_by_department` model.
  Revisit once a longer run shows actual time-to-fill per department.
- A rare edge case is now handled defensively rather than eliminated: if
  `HiringSimulator` closes a vacancy without a hire (a capacity conflict with
  a capped role - see below), any other in-progress pipeline applications for
  that vacancy are closed out as "Afgewezen" too, so nothing is left stuck at
  "In behandeling" forever. This is a backstop for an already-rare race, not
  a normal funnel outcome.

## Multi-site locations (implemented, first-pass numbers)

- `dim_location` is now config-driven (`active_from_headcount`/scope,
  capacity, capacity-streak-triggered second site, department relocation on
  open) instead of a flat static distribution. First-pass numbers to revisit
  once a longer run shows how they land: Fabriek Noord capacity 300 (8-week
  streak), DC at Logistiek headcount 40 (+80 capacity bonus to whichever
  site currently hosts Logistiek), Hoofdkantoor at combined
  Finance+HR+Sales+Marketing+Directie+IT headcount 40.
- The one-time department relocation (Logistiek -> DC, office departments ->
  Hoofdkantoor) moves everyone in one batch the week the location opens,
  not gradually over a "short window" as discussed - simpler, and probably
  fine for a demo dataset, but worth knowing if the sudden batch shows up
  oddly in a single week's data.
- The Noord/Zuid location-transfer flux (`location_transfer_rate`,
  `new_site_pull_rate`, `new_site_pull_weeks` in `career_events`) has first-
  pass values (0.03 / 0.15 / 12 weeks) with no real-world anchor - revisit
  once observable in a long run.

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
- **A statistically-sampled history backfill could plausibly solve (b)
  without the current simulation's runtime cost.** The idea: don't simulate
  the lookback window week by week (that's exactly as slow as today's
  forward simulation, for the same reason - discovering an emergent outcome
  requires walking the path to it). Instead, since the *ending* population is
  already known (it's the config target), compute the aggregate shape of
  history in closed form and sample specific records directly from it:
  the headcount curve as a formula rather than a stepped simulation; each
  current employee's career-event *count* over their known tenure as one
  Poisson/binomial draw rather than 350+ weekly probability checks; past
  leavers as a directly-sampled batch sized from the integral of
  headcount x attrition-rate over the window; vacancy/recruitment/absence
  history as one batch of records per known hire/absence event rather than
  a simulated funnel. This turns the dominant cost from
  `O(weeks x headcount)` into roughly `O(employees who ever existed)`, since
  most weeks are non-events for most people. The real work isn't the
  sampling itself but resolving each employee's sampled events in the right
  *dependency order* (a promotion has to respect eligibility as of its own
  sampled date, which depends on that employee's already-sampled
  qualification/experience timeline) - a small, per-employee ordering
  problem, not the large per-week global one driving today's runtime.

## Recruitment & eligibility

- **Qualification/certification events during employment.** Qualification
  history (`fact_employee_qualification`) is now populated at hire time, but
  there is still no simulated event for gaining a qualification *during*
  employment (e.g. a VAPRO or IT certificate obtained on the job). Without
  it, an employee's credentials never change after hire, which caps how
  realistically internal promotion/transfer eligibility can evolve over a
  long career.
- **`eligible_internal` has no leadership-experience check beyond the first
  management move.** `role_eligibility.eligible_internal` only applies a
  leadership-experience rule to the *first* move from a non-management role
  into a management role (`exp < 3`). Unlike `eligible_external`, it never
  checks `Min_Leidinggevende_Ervaring_Jr` for a further internal promotion
  between management roles (e.g. team lead → manager → director). Consider
  tracking real leadership tenure for internal candidates and gating further
  management promotions on it, the way external hiring already does.
- **Dedicated eligibility tests are still missing** for:
  - the WO "senior" experience exception in
    `role_eligibility._required_relevant_experience`;
  - education-direction / diploma-and-certificate matching in
    `_matching_credentials`;
  - `relevant_experience()`'s role-history logic, i.e. that experience in a
    source role counts toward a target role only when that source is the
    target itself or reachable via a configured `logische_doorgroei` /
    `laterale_transfers` path.
  (The tests added for the new external-recruitment scoring cover the new
  profile-driven scores, not these pre-existing `role_eligibility` rules.)

## Configuration validation

- **No automated validation exists for the 55-role configuration.** Add a
  config-loading check (or a dedicated test) that verifies, for every role in
  `role_career_paths` / `structure`: `Role_Key` values are unique and stable,
  `Department_Key`/department references resolve, every
  `logische_doorgroei` and `laterale_transfers` target names an existing
  role, a lateral transfer target shares the source role's
  `SalaryScale_Key`, role weights are sane (no role with a non-zero target
  weight left unreachable), and every `relevante_opleidingen` entry resolves
  to a real `dim_education` row.

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
