# Budget Planning & Financial Projections

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
portfolio + capacity data -> bronze -> conformed portfolio model (silver)
                          -> expenditure forecast -> scenarios
                          -> capacity-constrained gold -> variance reporting
```

Lakeflow for transformation, Unity Catalog for governance, AI/BI for scenario and variance
reporting, Genie for ad hoc portfolio questions, serverless throughout.

## Data

Synthetic and seeded. The portfolio shape is modelled on the structure described in the public
Infrastructure Australia reporting; none of the figures are real.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

The React app is implemented in `src/nba-budget-portfolio`. For the selected workspace:

```bash
cd src/nba-budget-portfolio
npm run dev
databricks apps validate --path . --profile au-pubsec
databricks apps deploy --profile au-pubsec --auto-approve
```

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
