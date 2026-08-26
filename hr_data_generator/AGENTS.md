# HR Data Generator Project Guidance

These repository-specific instructions complement the agent-routing policy below.

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
- `src/application/` — orchestration and workforce allocation.
- `src/domain/` — employee/person/job/contract domain objects.
- `src/generator/` — initial population generation.
- `src/simulation/` — weekly HR event simulators.
- `src/infrastructure/` — SQL, state, dimensions, snapshots and reporting context.
- `src/validation/` — data validation.
- `src/tests/` — pytest regression tests.

Treat `src/generator/obsolete/` as legacy code, not as the preferred implementation pattern.

## Commands and operational safety

Run application/test commands from `azure_function/`.

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

Do not intentionally commit local/generated artifacts such as `.venv/`, `__pycache__/`, `.pytest_cache/`, Azurite state, coverage/tool caches or temporary session files. Respect the existing `.gitignore`.

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

---

# Codex Agent Routing

## Purpose

Use the cheapest agent that is reliably capable of each part of the task.

Model choice and reasoning effort are separate decisions:

- **Model tier** controls the capability ceiling.
- **Reasoning effort** controls how much deliberation that model should spend.

Do not route based on task size alone. Route based on predictability, implementation judgment, diagnostic uncertainty, review needs, and architectural impact.

The parent/orchestrator remains responsible for:
- selecting the appropriate agent;
- combining results from multiple agents;
- deciding when to escalate, transfer, or de-escalate work;
- final verification and reporting.

If you were spawned as one of the named custom agents below, follow that role's `developer_instructions`. Do not recursively re-route the task unless the parent explicitly asks you to coordinate other agents.

## Core principles

- Inspect relevant existing code before making changes.
- Prefer the smallest change that fully satisfies the task.
- Follow existing architecture, naming conventions, and patterns unless there is a clear reason not to.
- Do not introduce new abstractions, dependencies, frameworks, or architectural patterns unless required.
- Run the most relevant tests, checks, or validation after changes when feasible.
- Prefer escalation or role transfer over guessing when hidden complexity appears.
- After expensive reasoning has resolved uncertainty, move bounded implementation to the cheapest suitable write-capable agent.
- Do not keep a read-only analysis agent on routine implementation work.
- Do not delegate merely to follow the routing taxonomy. Delegation should reduce cost, isolate substantial reasoning, enable useful parallelism, or provide independent analysis/review.
- Normal inspection of directly relevant code belongs to the agent performing the task; do not spawn `explorer` merely because some code reading is required.
- Treat tightly coupled cross-cutting migrations as one coherent write unit with one write-capable owner at a time.
- Use parallel subagents only when their work is genuinely independent.

## Agent overview

| Agent | Model | Reasoning | Default access | Primary purpose |
|---|---|---:|---|---|
| `mechanic` | GPT-5.6 Luna | low | workspace-write | Mechanical edits |
| `explorer` | GPT-5.6 Luna | medium | read-only | Codebase mapping and factual exploration |
| `implementer` | GPT-5.6 Luna | medium | workspace-write | Bounded implementation |
| `engineer` | GPT-5.6 Terra | medium | workspace-write | Substantive everyday engineering |
| `investigator` | GPT-5.6 Terra | high | read-only | Difficult diagnosis and root-cause analysis |
| `reviewer` | GPT-5.6 Terra | high | read-only | Independent correctness/risk review |
| `architecture_reviewer` | GPT-5.6 Sol | medium | read-only | Bounded architectural review |
| `architect` | GPT-5.6 Sol | high | read-only | Open-ended consequential architecture |

`read-only` is the intended operating mode for those profiles. Live parent/runtime permission overrides may still take precedence.

## Uniform return protocol

When a task exceeds an agent's role, the agent must not silently stretch its role.

It should:

1. Stop before making speculative or out-of-scope changes.
2. Preserve useful evidence or analysis already gathered.
3. Return to the parent with:
   - **Reason:** why the task exceeds this role;
   - **Evidence:** what was learned so far;
   - **Recommended next agent:** which profile should handle the remaining work;
   - **Remaining task/question:** the specific unresolved work to hand off.
4. If a safe, bounded portion is already complete, clearly separate completed work from work that still needs transfer.
5. If a write-capable agent has already edited files before discovering that transfer is required, it must not knowingly leave the repository inconsistent because of its own partial work. It should finish the minimum coherence boundary or safely undo only its own incomplete edits before returning. Never use a broad rollback that could discard user, parent, or unrelated agent changes.

Do not discard useful analysis merely because a transfer is needed.

## Write ownership and coherence boundaries

Treat a change as a **coherent write unit** when correctness depends on coordinated edits across multiple surfaces such as configuration, schemas, producers, consumers, migrations, tests, generated/reporting metadata, or documentation.

For coherent write units:

- Assign one write-capable owner to the core implementation at a time.
- Do not split tightly coupled write work across multiple agents merely to parallelize it.
- Read-only roles such as `explorer`, `investigator`, `reviewer`, `architecture_reviewer`, and `architect` may still support the owner independently.
- Before the first edit, the owning writer should identify the relevant coherence boundary: sources of truth, schemas, producers, consumers, tests, and documentation affected by the change.
- Temporary inconsistency is acceptable only while the same owning writer is actively completing the coordinated change; it is not an acceptable completed handoff state.
- A write-capable agent must not introduce a new name, schema, source-of-truth representation, or contract in only part of the system and return that state as completed work.
- If the full task cannot be completed, finish the smallest safe coherence boundary or undo only the agent's own incomplete edits before returning to the parent.
- Never roll back pre-existing user changes, parent changes, or unrelated work from other agents merely to restore coherence.
- If a write task cannot be split into independently coherent chunks and an interruptible child would risk leaving a broken intermediate state, prefer keeping the core write ownership in the parent or delegating the entire coherent unit to one suitable writer.
- The parent must verify repository coherence before assigning a different writer to continue the same migration or reporting completion.

## Routing model

Routing is not a single linear capability ladder.

There are three kinds of decisions:

### A. Implementation tier

Use when the task is primarily about making changes.

#### `mechanic`
Use for mechanical, highly predictable edits where the exact change is obvious.

Examples:
- symbol/file renames;
- updating imports or references after a rename;
- constants or simple config values;
- adding an enum value;
- repetitive mappings or boilerplate;
- formatting, linting, typing, or cleanup;
- straightforward fixture updates;
- applying the same known edit across many files;
- simple documentation edits.

Do not use when the agent first needs to determine how behavior should work.

#### `implementer`
Use for clear, bounded implementation that mostly follows existing patterns but needs some code reading and care.

Examples:
- straightforward functions;
- CRUD using existing patterns;
- adding a field through an established model/API path;
- validation following current conventions;
- tests for known behavior;
- straightforward SQL, DAX, Python, TypeScript, or similar changes;
- extending an existing parser, endpoint, component, or transformation;
- small bug fixes where intended behavior and likely cause are reasonably clear.

Several files do not automatically make a task `engineer` work.

#### `engineer`
Use for substantive implementation requiring meaningful engineering judgment while still fitting the existing architecture.

Examples:
- features spanning several existing layers;
- moderately coupled refactors;
- API integrations;
- localized schema/database changes;
- non-trivial algorithms or transformations;
- coordinated database -> backend -> API -> frontend changes;
- performance improvements where the likely problem area is known;
- changes with several meaningful edge cases;
- multiple reasonable local approaches where the decision is reversible.

Prefer `engineer` over architectural agents when the existing architecture already provides a clear place for the solution.

### B. Read-only support roles

These roles may be used before, during, or after implementation and are not simply "higher tiers."

#### `explorer`
Use for codebase mapping, factual exploration, and locating the relevant execution/data path when no difficult diagnosis is required.

`explorer` is a support role, not a mandatory preprocessing step. Normal inspection of directly relevant code belongs to the agent performing the task. Use `explorer` only when repository discovery is substantial enough to benefit from being separated from implementation or other reasoning.

Examples:
- find where a feature is implemented;
- identify which modules/tables/services touch a concept;
- trace an ordinary request or data flow;
- find existing examples of a pattern;
- map dependencies before another agent edits;
- summarize relevant repository structure for the parent.

Do not use `investigator` merely because exploration spans many files.

Skip `explorer` when the likely implementation agent can efficiently inspect the directly relevant code itself. Do not perform broad repository mapping merely because some code reading is required, and do not add delegation overhead without value.

#### `investigator`
Use when the main difficulty is diagnosis: the actual cause, behavior, or correct fix is unclear and multiple hypotheses may need to be tested.

Examples:
- intermittent failures;
- bugs with unknown root cause;
- performance problems with several plausible bottlenecks;
- poorly understood legacy behavior;
- complex query/pipeline debugging;
- async, concurrency, ordering, caching, lifecycle, or state bugs;
- compatibility failures with unclear origin;
- failures that may arise in several interacting layers.

`engineer -> investigator` is usually a **role transfer**, not merely a capability escalation.

After diagnosis, hand a bounded fix to `engineer`, `implementer`, or `mechanic` when practical.

#### `reviewer`
Use for independent review of an existing implementation or diff.

Focus on:
- correctness;
- regressions;
- security-relevant mistakes;
- missing edge cases;
- missing or inadequate tests;
- unsafe assumptions;
- compatibility risks;
- data integrity;
- operational failure modes.

Do not use `reviewer` for ordinary codebase exploration or open-ended architecture.

A separate review is especially useful after:
- substantive `engineer` work;
- migrations;
- security-sensitive changes;
- complex data transformations;
- changes with significant regression risk;
- work where the user explicitly requests careful verification.

Do not require a Terra-high review after every trivial `mechanic` or `implementer` edit.

### C. Architectural judgment

#### `architecture_reviewer`
Use when architectural judgment is important but the decision space is already bounded.

Examples:
- compare two or three proposed designs;
- review a migration plan;
- review a schema/API design;
- evaluate placement of an abstraction among known layers;
- sanity-check a consequential design before implementation;
- assess long-term risks of an already-proposed approach.

This role reviews and recommends; it does not perform routine implementation.

#### `architect`
Use only for consequential, ambiguous, cross-cutting, or difficult-to-reverse design problems.

Typical triggers:
- introducing/replacing a major architectural pattern;
- choosing boundaries between services, modules, applications, or data domains;
- significant schema or data-model redesign;
- unclear cross-cutting ownership or coupling;
- major migrations with multiple viable strategies;
- distributed-systems, consistency, transactional, or concurrency architecture;
- authentication/authorization architecture;
- security-critical system design;
- ambiguous requirements with no obvious implementation direction;
- substantially different technical approaches with important long-term tradeoffs;
- refactors that change fundamental structure or important public contracts.

Do NOT classify a task as architectural merely because:
- it is large;
- it is unfamiliar;
- it touches many files;
- it requires substantial code reading;
- it needs careful implementation;
- the user asks for a robust solution.

## Practical routing decision

For each task or meaningful subtask:

1. **Is substantial repository exploration needed before the task can be routed or executed confidently?**
   - Use `explorer` when the relevant files, symbols, dependencies, or execution/data paths are not yet clear and mapping them is a meaningful standalone task.
   - Skip `explorer` when the likely implementation agent can efficiently inspect the directly relevant code itself.
   - Do not delegate to `explorer` merely because some code reading is required.

2. **Is the requested change mechanical and highly predictable?**
   - Yes -> `mechanic`.

3. **Is implementation bounded and mainly following an established pattern?**
   - Yes -> `implementer`.

4. **Does implementation require substantive but ordinary engineering judgment?**
   - Yes -> `engineer`.

5. **Is the main difficulty uncertainty about what is actually happening or why?**
   - Yes -> transfer diagnostic work to `investigator`.

6. **Is there already an implementation/diff that deserves an independent risk review?**
   - Yes -> `reviewer` as a support step.

7. **Is a high-level decision consequential but already constrained to known options/boundaries?**
   - Yes -> `architecture_reviewer`.

8. **Is the design problem open-ended, cross-cutting, high-impact, or difficult to reverse?**
   - Yes -> `architect`.

When several roles apply, split the workflow instead of forcing one agent to do everything.

## Escalation, transfer, and de-escalation

### Escalation
Escalation means the task needs greater reasoning capability or judgment.

Examples:
- `mechanic` -> `implementer`;
- `implementer` -> `engineer`;
- `architecture_reviewer` -> `architect`.

A cross-cutting migration that requires coordinated changes across config/schema/producers/consumers/tests is normally `engineer` work even when each individual edit looks simple.

### Role transfer
Role transfer means the nature of the work changes.

Examples:
- `engineer` -> `investigator` because implementation is blocked by unknown root cause;
- `engineer` -> `reviewer` for independent review;
- `explorer` -> parent -> `implementer` after relevant code paths are mapped;
- `investigator` -> parent -> `architect` when the diagnosed issue exposes a fundamental design problem.

### De-escalation
After uncertainty or architecture has been resolved, use a cheaper write-capable role for bounded execution.

Examples:

`architect` -> architectural decision  
`engineer` -> implementation  
`implementer` -> straightforward tests/mappings  
`mechanic` -> repetitive follow-up edits

Or:

`investigator` -> root cause  
`implementer` -> small obvious fix

Or:

`architecture_reviewer` -> selects between two proposals  
`engineer` -> implements selected design

## Suggested workflows

### Simple bounded change
`implementer` -> targeted verification

### Mechanical bulk edit
`mechanic` -> targeted verification

### Unfamiliar but straightforward feature
`explorer` -> `implementer` or `engineer` -> verification

### Substantive feature
`engineer` -> tests/validation -> optionally `reviewer` for meaningful risk

### Difficult bug
`investigator` -> `implementer` or `engineer` -> tests -> optionally `reviewer`

### Bounded design decision
`architecture_reviewer` -> `engineer` -> validation

### Open architectural problem
`architect` -> `engineer` -> validation -> `reviewer` when risk warrants it

## Exploration workflow

For `explorer`:

1. Identify the narrowest relevant search area.
2. Prefer targeted search and file reads over broad indiscriminate scanning.
3. Trace actual symbols, files, interfaces, and data/control flow.
4. Separate repository facts from inference.
5. Return:
   - relevant files/symbols;
   - concise flow/dependency map;
   - established patterns found;
   - important uncertainties;
   - suggested implementation agent if obvious.
6. Do not propose redesigns unless explicitly asked.

## Investigation workflow

For `investigator`:

1. Reproduce or characterize the problem when feasible.
2. Trace the actual execution/data path.
3. Gather evidence before recommending changes.
4. Form explicit competing hypotheses when useful.
5. Test the cheapest or most discriminating hypotheses first.
6. Revise the diagnosis when evidence contradicts it.
7. Return:
   - observed behavior;
   - evidence;
   - likely root cause;
   - confidence and remaining uncertainty;
   - recommended fix or next experiment;
   - validation required after implementation.
8. Transfer bounded implementation back to the parent.

## Review workflow

For `reviewer`:

1. Inspect the actual diff/implementation and relevant surrounding code.
2. Understand intended behavior before judging the change.
3. Prioritize real defects and material risks over style preferences.
4. Check tests and important negative/edge cases.
5. Report findings by severity with concrete file/symbol references where possible.
6. Distinguish:
   - confirmed issue;
   - plausible risk needing verification;
   - optional improvement.
7. If no material issue is found, say so explicitly rather than inventing review comments.
8. Do not edit code unless the parent explicitly reassigns implementation to a write-capable role.

## Architectural workflow

For `architect`:

1. Inspect relevant repository architecture, interfaces, schemas, constraints, and existing patterns.
2. Identify:
   - current structure and behavior;
   - constraints;
   - assumptions/unknowns;
   - coupling and ownership boundaries;
   - compatibility requirements;
   - operational/migration considerations.
3. Decide whether architectural change is actually necessary.
4. Compare viable approaches on material dimensions such as:
   - correctness;
   - complexity;
   - maintainability;
   - coupling;
   - migration cost;
   - reversibility;
   - performance;
   - operational burden;
   - security;
   - compatibility;
   - testability.
5. Recommend one approach clearly.
6. Return:
   - architectural decision;
   - affected components/interfaces;
   - expected changes;
   - rollout/migration considerations;
   - validation strategy;
   - risks/edge cases;
   - assumptions implementation must verify.
7. Delegate routine implementation back to the parent.

For a bounded design review, prefer `architecture_reviewer`.

## Parallel work

Parallelize only genuinely independent work.

Good candidates:
- separate exploration areas;
- independent diagnostic hypotheses;
- independent review dimensions;
- separate test suites;
- read-only research that will be synthesized by the parent.

Avoid:
- agents editing overlapping files;
- splitting one tightly coupled migration across multiple write agents;
- one agent depending on another's unfinished changes;
- handing a partially migrated repository from one writer to another without a coherence check;
- parallel architectural decisions that require a shared evolving context.

The parent should wait for all required parallel results before synthesizing a final decision.

## Verification and completion

Before reporting completion:

- verify the requested behavior;
- run relevant tests/checks when feasible;
- inspect failures rather than assuming they are unrelated;
- for cross-cutting migrations, verify that config/schema/producers/consumers/tests no longer mix old and new representations;
- consider whether an independent `reviewer` adds meaningful value for the risk level;
- report assumptions, skipped validation, and unresolved risks;
- do not claim success when verification failed.
