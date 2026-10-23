# Budget Planning & Financial Projections

![](design/app_ui.png)

| | |
| --- | --- |
| **Category** | Resource Allocation |
| **Selected function** | Budget Planning & Financial Projections |
| **Evidence anchor** | [2025 Infrastructure Market Capacity Report](https://www.infrastructureaustralia.gov.au/reports/2025-infrastructure-market-capacity-report) |
| **Target KPI** | Planning cycle productivity (measure to instrument) |
| **Status** | **Implemented** - React Databricks App, typed analytics and Genie integration |


## Problem

A portfolio of programs and projects competes for a fixed budget across multiple years. Each has
its own cost profile, schedule, and benefit case, and they draw on the same constrained delivery
market. Planning happens in spreadsheets, so scenarios cannot be compared consistently, and the
question that actually matters - can the market deliver what we have funded, and when - is hard to
answer at all.

## What this use case demonstrates

Modelling a project and program portfolio as data: expenditure forecasting, scenario comparison
against capacity constraints, and variance reporting that explains the gap between plan and actual.

## Modelled on

Infrastructure Australia's
[2025 Infrastructure Market Capacity Report](https://www.infrastructureaustralia.gov.au/reports/2025-infrastructure-market-capacity-report),
which establishes the national Major Public Infrastructure Pipeline as the central dataset for
sector planning and market capacity analysis. The
[Australian Government Grants Framework](https://www.finance.gov.au/government/commonwealth-grants/australian-government-grants-framework)
defines the funding administration obligations, and the
[Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process)
supplies the assurance and delivery-confidence data that should feed the forecast.

The capacity constraint is what distinguishes this from ordinary financial forecasting. A pipeline
that is affordable on paper can still be undeliverable, so an allocation scenario that ignores
market capacity is not a plan.

## Scope

**In scope**

* A project and program portfolio model with cost, schedule and benefit profiles
* Multi-year expenditure forecasting
* Scenario construction and comparison
* Capacity constraint analysis against the modelled delivery market
* Variance reporting between plan, forecast and actual

**Out of scope**

* Any real budget, project, or market capacity data. Wholly synthetic.
* Integration with a financial system of record.
* Benefit realisation measurement, which needs outturn data a demo cannot credibly synthesise.

## Functions

| Function | Description |
| --- | --- |
| Portfolio model | Projects and programs with cost, schedule and benefit profiles |
| Expenditure forecast | Project multi-year expenditure from the portfolio profiles |
| Scenario comparison | Construct and compare allocation scenarios side by side |
| Capacity analysis | Test scenarios against modelled delivery market capacity |
| Variance reporting | Explain the gap between plan, forecast and actual |

## Architecture

```
synthetic source systems (01, dbldatagen)
  -> UC volume landing/extracts/<extract>/delivery_date=... , gl_transactions/period=YYYY-MM
  -> bronze_* (02, Auto Loader availableNow, schema evolution, _rescued_data)
  -> silver_*  (03, conformed portfolio model, 27 data quality rules -> dq_results)
  -> forecast_stages_monthly, dim_* (04, Working baseline expenditure forecast)
  -> expenditure_*, capacity_*, scenario_* (05, scenarios + capacity-aware sequencing)
  -> variance_*, portfolio_*, priority_exceptions, assurance_register, forecast_runs (06)
  -> Portfolio Genie space (07)
```

Serverless Lakeflow Jobs, Unity Catalog governance (table/column comments and `nba_*` tags on every
table), Genie for ad hoc portfolio questions. The command-centre design is in `design/`.

| Source | Notebook | What it does |
| --- | --- | --- |
| `src/_common.py` | shared | Naming, AU financial-year calendar, phasing / forecast engine, governed writes, run control |
| `src/00_setup.py` | setup | Schema, volume, control and app-writable tables (`reset=true` rebuilds) |
| `src/01_generate_synthetic_data.py` | generate | `bootstrap`: whole world + history; `incremental`: next ledger month and register deliveries |
| `src/02_ingest_bronze.py` | bronze | Auto Loader for 17 extracts |
| `src/03_conform_silver.py` | silver | Types, AUD m, latest-delivery dedupe, DQ rules (error = drop, warn = keep), scenario seed MERGE |
| `src/04_expenditure_forecast.py` | gold | Staged forecast: plan -> schedule -> escalation -> scope -> packaging -> forecast |
| `src/05_scenarios_and_capacity.py` | gold | Builds every active scenario, tests it against 12 delivery-market inputs, confidence |
| `src/06_variance_reporting.py` | gold | Variance bridge, attention list, exceptions, KPIs, assurance register, run record |
| `src/07_genie_space.py` | Genie | Creates / updates the Portfolio Genie space; validates example SQL first |

## Modelling approach

**Financial years** follow the Australian Government convention: 1 July - 30 June, labelled by the
year they end (FY27 = 1 Jul 2026 - 30 Jun 2027). The five-year horizon starts at the FY containing
the first forecast month. The design mock-up labels the same window FY26-30 (start-year labels); the
data uses end-year labels throughout.

**Forecast.** Each project's endorsed plan phasing is moved through recorded, attributable stages:
approved schedule changes (slip and delay cost), current vs endorsed escalation on unspent work,
approved scope and packaging changes, then trailing cost performance (actual vs explained spend over
the last 12 closed months) applied to the remaining work. Closed months are actuals. Every stage is
kept, so the variance bridge drivers always sum exactly to forecast minus plan; *Unexplained* is what
no recorded driver accounts for.

**Scenarios** are data (`scenario_definitions`, `scenario_levers`, versioned, Delta CDF on, writable by
an app). Methods: `plan`, `as_forecast`, `levers` (defer / accelerate / escalation delta / scope /
exclude / capacity uplift on a project, program, sector or the portfolio) and `auto_sequence` (levers,
then a greedy sequencer that defers *Deferrable* work - lowest priority and largest contributor first -
accepting only moves that reduce total over-utilisation, with every decision logged).

**Capacity.** Demand for 12 inputs (skilled civil labour, electrical trades, engineering services,
electrical equipment, TBMs, concrete, steel, ...) = project spend x subsector demand intensity.
Utilisation = demand / modelled supply; >= 90% Constrained, > 100% Breach. The deliverable-spend line is
forecast / peak utilisation. Project confidence = Gateway-based confidence less exposure to breached
inputs.

## Data

Synthetic and seeded (`synthetic_seed`, world anchor date stored in `pipeline_control`). The portfolio
shape is modelled on the structure described in the public Infrastructure Australia reporting; none
of the figures are real. Default world: 16 programs, 86 projects, endorsed plan calibrated to
$171.8bn over the horizon, ledger history from FY16 with ~150 GL postings per project-month
(dbldatagen; suppliers with realistic concentration). Seeded stories: Eastern Transit Corridor
(labour-driven cost growth), North Grid Resilience (long-lead equipment slip), Regional Water Security
(packaging saving), Western Freight Link (unexplained variance), Metro Renewal (labour demand).

### Gold data contract (one current run; `run_id` on every row)

| Table | Grain | Use |
| --- | --- | --- |
| `portfolio_kpis` | scenario | Headline cards: portfolio total, vs endorsed, peak gap, confidence, constrained inputs, YTD |
| `portfolio_capacity_fy` | scenario x FY | Plan / forecast / actual / deliverable capacity line and gap, envelope |
| `expenditure_fy`, `expenditure_monthly` | scenario x project x FY / month | Multi-year expenditure, nominal and real |
| `forecast_stages_monthly`, `forecast_project_drivers` | project x month / project | Working baseline stages and drivers (EAC, slip, cost performance) |
| `scenario_summary`, `scenario_comparison` | scenario / scenario x FY | Scenario studio comparison |
| `scenario_project_changes`, `scenario_sequencing_decisions` | scenario x project / decision | What moved and why |
| `capacity_demand` | scenario x FY x input | Utilisation heatmap and status |
| `capacity_exposure`, `project_confidence` | scenario x FY x input x project / scenario x project | Exposure and confidence |
| `variance_bridge` | period x scope level x driver | Driver attribution (YTD, CURRENT_FY, HORIZON) |
| `variance_project` | period x project | Tolerance tests and executive-attention flags |
| `portfolio_attention_list`, `priority_exceptions` | program / exception | Ranked attention and exceptions |
| `assurance_register` | record | Assumptions and Gateway reviews with owner, confidence and approval |
| `dim_project`, `dim_program`, `dim_scenario`, `dim_capacity_category`, `dim_financial_year` | dimension | Lookups |
| `forecast_runs`, `dq_results`, `pipeline_control` | run / rule / key | Run record with every input version; DQ outcomes; run context |

## Deploy

```bash
databricks bundle deploy --target dev --var catalog=<YOUR_CATALOG> --var warehouse_id=<YOUR_WAREHOUSE_ID>
databricks bundle run budget_bootstrap --target dev
```


The React app is implemented in `src/nba-budget-portfolio`. For the selected workspace:

```bash
cd src/nba-budget-portfolio
npm run dev
databricks apps validate --path . --profile au-pubsec
databricks apps deploy --profile au-pubsec --auto-approve
```

Replace `<YOUR_CATALOG>` and `<YOUR_WAREHOUSE_ID>` (angle brackets included) with a catalog you can
write to and a SQL warehouse id for Genie, or put them in
`.databricks/bundle/dev/variable-overrides.json`. The catalog must already exist; the schema and
volume are created. Jobs:

* `budget_bootstrap` - full build and Genie space (`reset=true` to rebuild; `world_anchor_date` to pin the world).
* `budget_daily` - scheduled: next deliveries -> bronze -> silver -> forecast -> scenarios -> variance.
* `budget_forecast` - on demand after a scenario is saved; `as_of_date` reproduces an earlier forecast.


## Assurance notes

Pre-decision budget data is typically sensitive and often cabinet-in-confidence in real settings,
so access controls and a clear separation between published and working figures matter more here
than the modelling. Forecasts should carry their assumptions as data rather than as narrative, so a
scenario can be re-run and audited later. Nothing in this use case should produce a number without
a traceable basis.

## Application

The Portfolio Command Centre provides live portfolio KPIs, expenditure and capacity analysis,
scenario comparison, variance reporting, an assurance register and governed natural-language
questions through the Portfolio Genie space. All displayed values remain synthetic.
