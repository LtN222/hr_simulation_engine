# HR Data Generator Project Guidance

## Project overview

This project generates realistic, configuration-driven synthetic HR data for Azure SQL and Power BI. The Python 3.11 Azure Function supports a full historical simulation and weekly incremental updates. The current sector configuration is `maakindustrie`.

Treat historical behavior, table grain, effective-dated context and HR metric semantics as correctness constraints, not merely demo-data details.

## Sources of truth

- `README.md` — setup, runtime behavior, data-model semantics, testing and deployment.
- `architecture.txt` — compact architecture/reporting overview.
- `azure_function/config/maakindustrie.json` — sector and simulation behavior.
- `azure_function/config/schemas/` — managed SQL schema, keys and indexes.
- `azure_function/src/` — executable behavior.

When documentation and implementation appear inconsistent, inspect the relevant code/config/schema before changing either.

## Repository map

Active application code is under `azure_function/`:

- `function_app.py` — HTTP/timer entry points and full/incremental selection.
- `config/` — runtime/sector configuration and SQL schemas.
- `src/core/` — `Config`/`ConfigLoader`: typed access to the merged runtime + sector JSON configuration.
- `src/application/` — orchestration and workforce allocation.
- `src/domain/` — employee/person/job/contract domain objects.
- `src/generator/` — initial population generation.
- `src/simulation/` — weekly HR event simulators (attrition, career events, hiring, recruitment, vacancy, absence, performance).
- `src/infrastructure/` — SQL (`database/`), state, dimensions, context builders (recruitment/departure/absence context, salary policy/band/benchmark, role eligibility, manager assignment, avatar) and reporting helpers.
- `src/validation/` — data validation.
- `src/tests/` — pytest regression tests.

Treat `src/generator/obsolete/` as legacy code, not as the preferred implementation pattern.

## Commands and operational safety

Run application/test commands from `azure_function/`, with the project virtualenv active (`.\.venv\Scripts\Activate.ps1`) — pytest and project dependencies are installed there, not in the global interpreter.

Full test suite:

```powershell
python -m pytest -q
```

Local Function App:

```powershell
azurite --location .azurite --debug .azurite\debug.log
func start
```

Do not deploy or write to an unintended Azure SQL target merely as generic validation. Before running the application against SQL, confirm that the configured target is the intended demo/development environment.

A **full run** rebuilds the initial population, re-simulates history and resets managed SQL tables. In this project that reset is expected and acceptable during development: this is a demo dataset, and full regeneration is often the simplest and most correct way to validate changes that affect historical output.

Use a full run when it is useful or required for the task, including after historical-logic, snapshot-semantic, schema, driver, recruitment, engagement, performance, relevant-experience or similar changes that incremental processing cannot realistically backfill.

Do not avoid a full run merely to preserve the current generated demo data. If full regeneration is the appropriate validation step, perform it when feasible and report the result.

## Core architecture and data invariants

Preserve these unless the task explicitly changes them:

- Simulation state is a dictionary of pandas DataFrames shared between simulation components and the schema-driven SQL writer.
- `WeeklySimulationRunner` coordinates weekly events; individual business-event logic belongs in the relevant simulator/helper rather than being duplicated in orchestration.
- Prefer schema/config-driven behavior over ad-hoc SQL or hard-coded alternatives when the project already models the concept declaratively.
- Static dimensions are configuration-owned; incremental processing must preserve existing keys so fact references remain valid.
- Facts are intended to relate through shared dimensions in Power BI, not through direct fact-to-fact relationships.
- `fact_workforce_snapshot` is employee-per-month-end grain and the primary source for headcount and employee trends, including employees with zero absence.
- `fact_employment` is event/effective-period based; do not use employment start dates as a headcount trend substitute.
- `fact_absence` is episode-grain and includes sickness and non-sickness leave. `Telt_als_verzuim` determines what counts as sickness absence; workday/hour fields are preferred for capacity and absence-rate calculations.
- Time-varying context should be stored at the appropriate effective event/snapshot time rather than inferred only from current employee state.
- Satisfaction and engagement are distinct concepts.
- Performance must not use absence, structural overtime or out-of-hours availability as performance signals.
- Engagement drivers must not use informal social events, social-media activity or out-of-hours availability.
- Relevant experience is functionally relevant experience, not age; do not infer relevant qualification from education level alone when study direction/domain relevance is unavailable.
- Preserve seeded/reproducible behavior where randomness intentionally derives from the configured simulation seed.

If a requested change conflicts with one of these semantics, surface the conflict instead of silently redefining the metric.

### Recruitment, promotion and transfer model (active area)

This part of the simulation is under active revision, so treat these as the current contract rather than assumed-stable legacy behavior:

- `dim_role` is the single source of role identity/eligibility. Its `Min_Relevante_Ervaring_Jr`, `Formele_Kwalificatie_Vereist`, `Min_Opleidingsniveau`, `Leidinggevend` and `Min_Leidinggevende_Ervaring_Jr` columns are generated from `role_career_paths` in `maakindustrie.json`, plus `Relevante_Opleidingen`/`Logische_Doorgroei`/`Laterale_Transfers` string lists for reporting.
- `role_career_paths.<Role_Name>` in the sector config carries the structured fields (`relevante_opleidingen`, `logische_doorgroei`, `laterale_transfers`) that drive both eligibility and the readable `dim_role` list columns — keep the two in sync when either changes.
- `azure_function/src/infrastructure/role_eligibility.py` is the single place that decides whether a move is a `Promotie` or `Transfer` (`movement_type`) and whether an employee/candidate is eligible for a target role (`eligible_internal`, `eligible_external`). Promotion targets come only from `logische_doorgroei`; a higher salary scale is not itself a promotion criterion. Transfers are lateral moves from `laterale_transfers` and require the same `SalaryScale_Key`.
- `azure_function/src/simulation/simulation_career_events.py` turns eligible internal moves into new `fact_employment` rows (`_simulate_salary_reviews`, then promotion/transfer sampling per active employee).
- `azure_function/src/simulation/simulation_vacancy.py` creates vacancy demand (replacement + growth) from `dim_role`/`config.structure`, and `simulation_recruitment.py` (`RecruitmentSimulator`) runs the funnel, including the `Interne mobiliteit` source that reuses `eligible_internal` to pick an internal candidate instead of generating a new person.
- Relevant experience carried across a move (`carried_experience` in `relevant_experience.py`) is full within the same functional domain and reduced by `career_events.relevant_experience_transfer_ratio` across a domain change — this must stay consistent between promotions, transfers and the internal-mobility hire path.
- `azure_function/src/tests/test_workforce_planning.py` and `test_employee_generation.py` are the closest existing coverage for allocation/eligibility; there is not yet a dedicated test file for `role_eligibility.py` itself — consider adding one when changing its logic, since it currently has no direct unit tests.

## Configuration, schema and documentation changes

When changing simulation behavior, first check whether the concept belongs in `config/maakindustrie.json` rather than hard-coding it.

For schema/reporting changes:

- update the relevant schema under `config/schemas/`;
- update the code that generates/enriches the field or table;
- preserve primary/foreign-key integrity and intended grain;
- consider both full and incremental behavior;
- determine whether historical data requires a full run;
- update `README.md` and/or `architecture.txt` when data-model or operational semantics change.

Update canonical documentation when setup, configuration, runtime behavior, schema, table grain, metric meaning, or full/incremental requirements change.

## Secrets and local artifacts

Never commit secrets. `azure_function/local.settings.json` must remain local.

Do not intentionally commit local/generated artifacts such as `.venv/`, `__pycache__/`, `.pytest_cache/`, Azurite state (`.azurite/`, `AzuriteConfig`, `__azurite_db_*.json`, `__blobstorage__/`), coverage/tool caches or temporary session files. Respect the existing `.gitignore`.

`azure_function/images/` contains source assets used by the avatar feature; do not treat those images as disposable generated files.

## Definition of done

For code changes, as applicable:

1. Inspect the relevant implementation and tests before editing.
2. Keep the change focused and avoid unrelated cleanup.
3. Add/update focused tests for changed behavior.
4. Run narrow tests during implementation and `python -m pytest -q` for substantive changes when feasible.
5. Check grain, keys and historical/effective-date implications for generated-data changes.
6. Check both full and incremental behavior when simulation/schema logic changes.
7. Update canonical documentation when behavior or semantics changed.
8. Review the final diff for generated files, local settings, secrets and unrelated edits.
9. When changed behavior requires historical regeneration, run a full simulation when feasible rather than leaving it as an unnecessary manual follow-up.
10. Report validation that could not be performed and any remaining required follow-up.
