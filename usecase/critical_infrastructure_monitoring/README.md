# Critical Infrastructure Monitoring

| | |
| --- | --- |
| **Category** | Smart Infrastructure |
| **Selected function** | Critical Infrastructure Monitoring: a national, cross-sector Infrastructure Operations Centre |
| **Evidence anchors** | [AusNet Services](https://www.databricks.com/customers/ausnet-services) (energy) · [Sydney Water](https://www.databricks.com/blog/social-impact-using-data-and-ai-revealing-2024-finalists-data-good-award) (water) · [Dutch Railways](https://www.databricks.com/customers/dutch-railways) (rail) · [NHVR](https://www.databricks.com/customers/national-heavy-vehicle-regulator) (transport telemetry pattern) |
| **Target KPI** | Time from signal to decision (measure to instrument) |
| **Status** | **Demo-ready** - synthetic pipeline, risk engine and operations app built; dashboard and Genie space not yet |
| **Build priority** | 1 (flagship) |

## Problem

Roads, rail, water and energy are run by many operators, each watching its own assets. The
failures that hurt most cross between them. A heatwave loads the grid, heats rail track and draws
down reservoirs at the same time. A zone substation fault takes out the rail signalling, the water
pumping station and the road tunnel ventilation it powers. Each operator sees its own alarm; nobody
sees the operating picture across them, so the first sign of a cascade is the second outage.

## What this use case demonstrates

A national Infrastructure Operations Centre on one governed platform:

* operator telemetry and weather warnings streamed into one medallion pipeline
* readings conformed against an asset and sensor registry, with bad data quarantined rather than
  scored
* a cross-sector dependency graph, so every asset knows what relies on it
* an explainable likelihood × consequence risk score for every asset, where consequence includes the
  people relying on everything downstream
* incidents with a recommended first action, worked through an operations app with a network map,
  human-in-the-loop decisions and an audit trail

## Modelled on

Every sector has a published Databricks reference. These are *their* results; this repository
models the pattern with synthetic data and reproduces none of their numbers.

| Sector | Reference | What it shows |
| --- | --- | --- |
| Energy | [AusNet Services](https://www.databricks.com/customers/ausnet-services) (ANZ) | Asset condition, criticality and risk used to predict failures and schedule maintenance, starting with three asset classes and extending across the fleet. 50% data-platform cost saving, 3× faster processing. |
| Water | [Sydney Water](https://www.databricks.com/blog/social-impact-using-data-and-ai-revealing-2024-finalists-data-good-award) (ANZ) | 22,600 km of pipes and 247 reservoirs; AI pipe inspection to reduce maintenance backlogs and real-time water-quality monitoring. No outcome figures published. |
| Rail | [Dutch Railways (NS)](https://www.databricks.com/customers/dutch-railways) (international) | Real-time operational intelligence and predictive maintenance on train telemetry, including environmental risks such as ice on overhead lines. 100B+ data points a day, 70% lower analytical compute cost. |
| Roads and transport | [National Heavy Vehicle Regulator](https://www.databricks.com/customers/national-heavy-vehicle-regulator) (ANZ) | Real-time telemetry, alerting and risk engines at national scale, where a score matters because it resolves to a specific target for intervention. |

Four learnings carry across: asset risk earns its keep when it drives maintenance and intervention;
start with a few asset classes and extend; keep real-time and analytical work on one platform; and
make every score resolve to a specific asset, operator and action.

## Scope

**In scope**

* Streaming ingest of operator telemetry and weather warnings
* Conformance to an asset and sensor registry, deduplication, late arrival and quarantine
* A cross-sector dependency graph (power and water supply links)
* Hazard exposure from active warnings
* A transparent likelihood × consequence risk engine with incidents and recommended actions
* An operations app: sector health, incident queue, network map, review and decision audit
* Compliance dashboard and a Genie space over the gold tables

**Out of scope**

* Any real asset, operator, telemetry or warning data. All of it is synthetic; only the place names
  and map outlines are real public geography.
* Integration with a live dispatch, SCADA or warning system. Decisions stop at the audit table.
* A production risk model. The engine is illustrative, and its accuracy carries no claim.
* Generic sensor-estate management (see `iot_sensor_data_management`) and generic spatial analysis
  (see `geospatial_analysis`).

## Architecture

```
operator telemetry ─┐                                   ┌─ gold_asset_features ─ gold_asset_risk ─┬─ gold_incident (+ impact)
weather warnings ───┴─ bronze (Auto Loader) ─ silver ───┤                                         ├─ gold_sector_status / hazard_status
asset + sensor + dependency registry ───────────────────┘  dependency graph (2 hops)              └─ gold_ops_metrics
                                                                                                        │
                       Infrastructure Operations Centre app (OBO) ── decisions ──> gold_incident_review_audit
```

Lakeflow Jobs with Auto Loader for ingest, Unity Catalog for governance and lineage, serverless
compute throughout, a Databricks App (AppKit) running every query as the signed-in officer, AI/BI
for the dashboard and Genie for natural-language analysis.

## Data

Synthetic and seeded (`seed=42`):

| Table | Contents |
| --- | --- |
| `dim_asset` | 599 assets in 14 classes across roads, rail, water and energy, at 57 real Australian localities |
| `dim_sensor` | 723 sensors (one per asset metric) with engineering warning and alarm limits |
| `dim_dependency` | about 280 supply links: assets that need power fed by their nearest zone substation, substations by transmission lines, reservoirs by treatment plants |
| `dim_inspection` | two years of condition inspections, some overdue |
| `silver_reading` | about 480,000 trusted 15-minute readings over 7 days |
| `silver_hazard_warning` | heatwave, flood, bushfire and storm warnings with a centre and radius |

How the synthetic world behaves (`src/common.py`):

* **Physics first.** A reading is baseline + a daily load cycle + noise, plus the effect of any
  active warning the asset sits inside (`HAZARD_EFFECTS`, scaled by severity, proximity and how long
  the warning has run). A heatwave raises transformer temperature, line load and rail temperature
  and draws down reservoirs; a flood puts water over roads and raises turbidity. Readings are capped
  just past the alarm limit, where real protection acts.
* **Storylines** (`STORYLINES`) give the demo a narrative on every run: a heatwave-stressed Penrith
  substation whose failure would take out rail signalling, overhead wiring, a treatment plant and
  road tunnels; a Gippsland transmission line inside a bushfire warning; flood runoff at a Lismore
  treatment plant; and a trunk-main burst in Melbourne's west that is caught with no hazard nearby.
  A slow reservoir draw-down near Mandurah deliberately stays just below the incident threshold: a
  gradual change carries little anomaly signal, so it is a watch item, not an incident.
* **Real-feed defects.** Late arrival (3%), duplicates, unregistered sensors and implausible
  spikes, which silver deduplicates or quarantines with a reason.
* **Local time.** The centre runs on Canberra time; today's readings stop at the run time.
* **Generations.** Each run lands in a `generation=<data version>_<as_of>` folder and silver reads
  only the current one, so reruns rebuild a clean world instead of stacking data.

## Risk engine

`ioc-likelihood-consequence-v1`, the vocabulary infrastructure operators already use:

| Factor (0-1) | Weight | Meaning |
| --- | --- | --- |
| Limit exceedance | 0.50 | how far the worst metric has moved from normal toward its alarm limit |
| Anomaly | 0.20 | the last two hours against the asset's own seven-day baseline |
| Hazard exposure | 0.20 | inside an active warning, by severity, sector relevance and proximity |
| Condition | 0.10 | a poor inspection grade (3-5), plus a penalty for an overdue inspection |

`risk = 100 × likelihood × (0.7 + 0.3 × consequence)`, where consequence maps the people relying on
the asset and everything up to two hops downstream onto 0-1 (1,000 people → 0, 1,000,000 → 1).
Ratings: **extreme** ≥ 70, **high** ≥ 57, **medium** ≥ 48 (the incident threshold, a job
parameter). People counts can overlap between services, so they are an upper bound for
prioritisation and are never summed at sector level.

## Deploy

```bash
# pipeline: schema, volume, synthetic data, medallion tables, risk and incidents
databricks bundle deploy --target dev --var catalog=<YOUR_CATALOG>
databricks bundle run critical_infrastructure_monitoring_pipeline --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to, or put
`catalog` (and optionally `schema`) in the git-ignored
`.databricks/bundle/dev/variable-overrides.json`. Then deploy the operations app: see
[app/nba-critical-infra/README.md](app/nba-critical-infra/README.md), which includes a demo script.
[docs/DEMO-READINESS.md](docs/DEMO-READINESS.md) records the readiness assessment and open items, and
[design/IOC-DESIGN-SPEC.md](design/IOC-DESIGN-SPEC.md) the product and design specification.

## Assurance notes

Real data of this kind is security-sensitive. Asset locations, condition, dependencies and
vulnerabilities for critical infrastructure can be *protected information* under the
[Security of Critical Infrastructure Act 2018](https://www.legislation.gov.au/Details/C2018A00029),
where unauthorised use or disclosure is an offence. A real deployment would need access scoped by
sector and operator (Unity Catalog row filters and column masks, which the app is ready for because
every query runs as the signed-in user), plus a retained audit of who viewed and decided what. The
design intent is decision support with a human in the loop: no score directs an action without an
officer's recorded decision. Any automated action affecting people would need an assurance
assessment under the [DTA's AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework).

## Not built yet

* The compliance dashboard (AI/BI) and the Genie space over the gold layer.
* Row filters and column masks by sector and operator. The app already runs every query as the
  user, so policies take effect as soon as they are defined.
* A continuous streaming trigger. Bronze uses Auto Loader with `availableNow`, so "near real time"
  means "as often as the job runs".

See [docs/DEMO-READINESS.md](docs/DEMO-READINESS.md) for the full list and recommendations.
