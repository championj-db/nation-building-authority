# AI-Enabled Eligibility Determination

| | |
| --- | --- |
| **Category** | Benefit Administration |
| **Selected function** | AI-Enabled Eligibility Determination |
| **Evidence anchor** | [Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector) - "Citizen 360 and AI-enabled eligibility" |
| **Target KPI** | Record processing time (measure to instrument) |
| **Status** | **Implemented** - Synthetic data, pipelines, rules engine, AI triage, app |

## Problem

Eligibility assessment is the bottleneck in benefit and grant administration. A caseworker must
gather evidence from several systems, apply criteria that are written in policy rather than code,
and justify the outcome. Straightforward cases wait behind complex ones, and the applicant waits
for all of it.

## What this use case demonstrates

Separating the deterministic part of eligibility from the judgement part: apply hard criteria as
code, let an agent assemble and explain the evidence for borderline cases against the policy text,
and put a prioritised, fully auditable queue in front of a human who makes the decision.

## Modelled on

Databricks' [Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector)
page names "Citizen 360 and AI-enabled eligibility" as a core health and human services use case,
alongside analysing program data to identify trends and optimise resources.
[Reinventing Government with the Databricks Data + AI Platform](https://www.databricks.com/blog/reinventing-government-databricks-data-intelligence-platform)
(31 October 2025) describes the surrounding pattern: a unified lakehouse, Unity Catalog governance,
AI/BI for self-service analysis, and agency-specific AI agents.

The design deliberately stops short of automating the determination. Under the
[DTA's AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework)
an automated decision affecting an individual attracts assurance obligations and an
[AI transparency statement](https://www.dta.gov.au/ai-transparency-statement), and the
history of automated compliance in Australian benefits administration is reason enough to keep the
decision with a person. The 80% processing improvement is pursued through evidence assembly and
triage, not through removing the human.

## Scope

**In scope**

* Application and supporting evidence intake
* Applicant 360 assembly across source systems
* A deterministic rules engine for hard eligibility criteria
* Agentic triage of borderline cases, citing the applicable policy
* Caseworker queue prioritisation
* A complete decision audit trail

**Out of scope**

* Any real applicant data. Wholly synthetic.
* Automating the determination itself. The system recommends; a human decides.
* Payment processing or benefit calculation.

## Functions

| Function | Description |
| --- | --- |
| Application intake | Ingest applications and supporting evidence |
| Applicant 360 | Assemble the applicant view from across source systems |
| Rules engine | Apply hard eligibility criteria deterministically, as versioned code |
| Agentic triage | Summarise borderline cases with citations to the applicable policy |
| Queue prioritisation | Rank the caseworker queue by complexity and urgency |
| Decision audit trail | Record every input, rule version, recommendation and human decision |

## Architecture

```
applications + evidence -> bronze -> applicant 360 (silver)
                        -> rules engine -> deterministic outcomes
                        -> agentic triage (borderline only) -> caseworker queue
                        -> decision audit trail
```

Lakeflow for intake and transformation, Unity Catalog for governance and lineage, Agent Bricks for
triage and policy citation, serverless throughout. Document intake reuses the bronze layer from
`intelligent_document_processing`.

## Data

Synthetic and seeded, including a synthetic policy document set for the agent to cite against.

## Deploy

Supply the environment-specific values in `.databricks/bundle/<target>/variable-overrides.json`
(git-ignored) or with `--var`:

```json
{ "catalog": "<YOUR_CATALOG>", "warehouse_id": "<YOUR_WAREHOUSE_ID>" }
```

Replace each angle-bracket placeholder (brackets included) with a catalog you can write to and a
SQL warehouse ID.

```bash
databricks bundle validate --strict --target dev
databricks bundle deploy --target dev
databricks bundle run ai_enabled_eligibility_determination --target dev   # build the data
databricks bundle run eligibility_workbench --target dev                  # deploy + start the app
```

The job runs end to end: setup → synthetic data → applicant 360 → rules engine → agentic triage → queue.

## Eligibility Review Workbench (Databricks App)

| Concern | Implementation |
| --- | --- |
| UI | `app/static/` — direct port of `design/eligibility-review-workbench.html` (tokens, layout, breakpoints, tabs, filters, decision dialog) with real loading, empty, error and decided states |
| API | `app/main.py` — FastAPI; entry point `uvicorn main:app` |
| Governed reads | Databricks SQL Statement Execution **on behalf of the signed-in user** (`user_api_scopes: [sql]`), so Unity Catalog grants, row filters and column masks apply per caseworker |
| Human actions | Lakebase Autoscaling Postgres (`resources/eligibility_workbench_lakebase.yml`): append-only `decisions`, `review_checklist`, `app_audit_events`, in an app-owned schema |
| Attribution | Every Lakebase row records the OBO-resolved caseworker, never the app service principal |
| Assurance | Decision snapshots the agent verdict, rules outcome, ruleset version and model endpoint read under the caseworker's own permissions; audit trail keeps system and human events distinct |

Access prerequisites for caseworkers: `USE CATALOG`, `USE SCHEMA` and `SELECT` on the use case
schema, and `CAN_USE` on the SQL warehouse (user authorisation means their own permissions apply).
The identity scopes `iam.current-user:read` and `iam.access-control:read` are granted to the app
automatically and must not be declared in `user_api_scopes`.

## Assurance notes

This is the use case in the catalogue with the most direct effect on individuals, so the assurance
posture is part of the design rather than a wrapper around it. The rules engine must be versioned
so any past decision can be reproduced against the rules in force at the time. The agent's output
is a recommendation with citations, never a determination, and the audit trail must distinguish
clearly between what the system suggested and what the human decided. An
[AI transparency statement](https://www.dta.gov.au/ai-transparency-statement) would be required in
a real deployment.

## What is built

* `src/00_setup.py` — Schema, volume, and infrastructure setup
* `src/01_generate_synthetic_data.py` — Seeded synthetic data generator (24 applicants, 4 programs, policies, evidence, source system records)
* `src/02_applicant_360.py` — Silver-layer applicant 360 from four source domains
* `src/03_rules_engine.py` — Deterministic, versioned rules engine with audit-reproducible evaluations
* `src/04_agentic_triage.py` — AI-powered triage of borderline cases via `ai_query`, with policy citations
* `src/05_queue_prioritisation.py` — Priority-scored caseworker queue and seeded audit trail
* `resources/eligibility_determination_job.yml` — Lakeflow Job chaining all six steps
* `resources/eligibility_workbench_app.yml` — Databricks App resource for the caseworker UI
* `resources/eligibility_workbench_lakebase.yml` — Lakebase project backing workbench decisions and audit events
* `app/main.py`, `app/backend/`, `app/static/` — FastAPI Eligibility Review Workbench (queue, 360, rules, evidence, policy library, audit, decision recording)
* `design/` — HTML design prototype and handoff manifest
