# Critical Infrastructure Monitoring

| | |
| --- | --- |
| **Category** | Smart Infrastructure |
| **Selected function** | Critical Infrastructure Monitoring |
| **Evidence anchor** | [National Heavy Vehicle Regulator](https://www.databricks.com/customers/national-heavy-vehicle-regulator) |
| **Target KPI** | 4% uplift in high-risk infringements yielded (NHVR, published) |
| **Status** | **Stub** - README and DAB skeleton only |
| **Build priority** | 1 (flagship) |

## Problem

A regulator with responsibility for a large, mobile asset estate needs to know which assets and
operators present risk *now*, not in next month's report. Risk signals arrive as high-volume
telemetry from many sources, and the window in which an intervention can prevent harm is measured
in minutes. Traditional warehousing cannot ingest the volume fast enough, so the data arrives but
the insight arrives too late to act on.

## What this use case demonstrates

Streaming telemetry ingest into a governed medallion pipeline, risk scoring that resolves to a
specific actionable entity, near real-time alerting to field staff, and self-service analysis over
the same governed tables.

## Modelled on

The [National Heavy Vehicle Regulator](https://www.databricks.com/customers/national-heavy-vehicle-regulator)
(NHVR), which regulates nearly 1 million heavy vehicles across Australia and analyses more than
4.5 million monthly vehicle sightings. NHVR has published these outcomes:

* Real-time, sub-second reporting, dashboards and alerts, enabling compliance officers to intercept
  vehicles posing imminent danger to public safety.
* A **fatigue engine** targeting drivers and operators most at risk of fatigue-related accidents,
  which delivered a **4% increase in yielding high-risk fatigue infringements**.
* A **crash prediction model** identifying a cohort of vehicles and operators with a **1-in-38
  chance of being involved in a fatal or serious incident on any given day**.
* Additional engines targeting roadworthiness and over-mass vehicles.

Three learnings we carry across:

1. **The data strategy outran the platform.** NHVR deliberately acquired large new datasets, then
   found their warehouse could not ingest them quickly enough. We size the ingest path well above
   the nominal event volume rather than for the steady state.
2. **Prediction only mattered once it was targetable.** A 1-in-38 cohort is valuable because an
   officer can be directed to a specific vehicle. Every risk score here resolves to an identified
   entity with a recommended action, not to a dashboard aggregate.
3. **They integrated rather than replaced.** Databricks was added to NHVR's existing Azure estate,
   preserving prior investment. Nothing here assumes a greenfield environment.

The NHVR figures above are *their* published results. This repository models the pattern with
synthetic data; it does not reproduce their numbers.

## Scope

**In scope**

* Streaming ingest of asset sighting and sensor telemetry
* Asset and operator identity resolution
* Medallion transformation to asset-level and operator-level risk views
* A risk scoring engine producing per-entity scores with contributing factors
* Near real-time alerting on high-risk events
* Compliance dashboard and a Genie space over the governed gold tables

**Out of scope**

* Any real telemetry, sighting, or operator data. The dataset is wholly synthetic.
* Integration with a live enforcement or dispatch system. Alerting stops at a queue.
* Reproducing NHVR's model. The scoring engine here is illustrative, and its accuracy carries no
  claim.

## Functions

| Function | Description |
| --- | --- |
| Streaming telemetry ingest | Continuous ingest of sighting and sensor events, tolerant of late and out-of-order arrival |
| Asset and operator resolution | Resolve raw sightings to known assets and the operators responsible for them |
| Medallion transformation | Bronze raw events, silver resolved and conformed, gold risk-ready aggregates |
| Risk scoring engine | Per-entity risk scores with contributing factors, refreshed on a schedule |
| Real-time alerting | Threshold and model-driven alerts routed to a field queue within minutes |
| Compliance dashboard | Operational view of current risk, intervention outcomes, and trend |
| Genie space | Natural-language analysis over the gold layer for analysts |

## Architecture

```
synthetic telemetry -> bronze raw events -> silver resolved assets/operators
                    -> gold risk features -> risk scores -> alert queue
                                                         -> dashboard + Genie
```

Lakeflow for streaming ingest and the declarative pipeline, Unity Catalog for governance and
lineage across the whole path, serverless compute throughout, AI/BI for the dashboard, Genie for
natural-language analysis.

## Data

Synthetic and seeded. See the catalogue for the modelled grain and volume; the generator is not
written yet.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Risk scores about identifiable operators are personal information, so the gold layer needs row and
column level controls and a retained audit of who viewed what. If a score were ever used to direct
enforcement action against an individual, that is a decision affecting a person and would need an
assurance assessment and an
[AI transparency statement](https://www.dta.gov.au/ai-transparency-statement) under the
[DTA's AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework).
The design intent is decision support with a human in the loop.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic data generator, no
pipeline, no risk model, no alerting, no dashboard, no Genie space.
