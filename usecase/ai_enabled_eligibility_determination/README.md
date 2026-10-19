# AI-Enabled Eligibility Determination

| | |
| --- | --- |
| **Category** | Benefit Administration |
| **Selected function** | AI-Enabled Eligibility Determination |
| **Evidence anchor** | [Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector) - "Citizen 360 and AI-enabled eligibility" |
| **Target KPI** | Record processing time (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

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

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

This is the use case in the catalogue with the most direct effect on individuals, so the assurance
posture is part of the design rather than a wrapper around it. The rules engine must be versioned
so any past decision can be reproduced against the rules in force at the time. The agent's output
is a recommendation with citations, never a determination, and the audit trail must distinguish
clearly between what the system suggested and what the human decided. An
[AI transparency statement](https://www.dta.gov.au/ai-transparency-statement) would be required in
a real deployment.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
applicant 360, no rules engine, no triage agent, no queue, no audit trail.
