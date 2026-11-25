# Infrastructure Operations Centre (Databricks App)

AppKit (Node + React) operations console for the critical infrastructure monitoring use case. A
compliance officer prioritises risk alerts, reviews the evidence behind an identified vehicle and
operator, and records a human-in-the-loop decision: route to the field queue or keep monitoring.

Layout, copy and interactions follow `../../design/critical-infrastructure-operations.html`. The
visual identity is the Databricks brand (Oat surfaces, Navy text, Lava accent, DM Sans / DM Mono);
see `.databricks-impeccable.md` for the design context.

## What runs as whom

| Surface | Runs as | Why |
| --- | --- | --- |
| Every read (`config/queries/*.obo.sql`) | The signed-in officer | Unity Catalog grants, row filters and column masks on operator-level risk data apply per officer |
| Decision write (`POST /api/reviews`) | The signed-in officer | The audit row's `officer_name` is `current_user()`, never a client-supplied name |
| Build-time type generation | App service principal | Has no `SELECT` by design; falls back to the committed types (`scripts/typegen.mjs`) |

The decision write uses bound statement parameters, validates input with Zod
(`server/contracts.ts`), and only inserts when the alert is still in the current queue
(`INSERT ... SELECT ... WHERE alert_id = :alert_id`), so a stale decision returns 409.

## Prerequisites

1. Run the pipeline job in `../../` (`databricks bundle run critical_infrastructure_monitoring_pipeline`).
   It writes the gold tables this app reads: `gold_alert`, `gold_asset_risk_score`,
   `gold_ops_metrics`, `gold_risk_signal_trend`, `gold_alert_review_audit`, plus
   `bronze_sightings` and `silver_sighting`.
2. Each officer who uses the app needs `USE CATALOG`, `USE SCHEMA`, `SELECT` on those tables, and
   `MODIFY` on `gold_alert_review_audit`, plus `CAN_USE` on the app.

## Configure

Nothing environment-specific is committed. Put your values in the git-ignored
`.databricks/bundle/default/variable-overrides.json`:

```json
{ "catalog": "<catalog>", "schema": "<schema written by the pipeline>", "sql_warehouse_id": "<warehouse id>" }
```

For local development, copy `.env.example` to `.env` and fill in the same values plus your CLI profile.

The `-- @param ... = <value>` lines at the top of each SQL file are sample values used only by
`npm run typegen` to DESCRIBE the query. At runtime the client binds the catalog and schema the
server reads from app config.

## Develop

```bash
npm ci
npm run dev                # http://localhost:8000, queries run with your CLI profile
```

## Validate

```bash
npm run typegen            # after changing any SQL file; commit shared/appkit-types/analytics.d.ts
npm run typecheck && npm run lint && npm run lint:ast-grep && npm test
databricks apps validate --profile <profile>
npm run test:e2e           # browser smoke test of the demo path (against npm run dev, or BASE_URL)
```

The Playwright smoke test lives in its own package under `tests/` so the Apps build never installs it.

## Deploy

```bash
databricks bundle deploy --profile <profile>
databricks apps get nba-critical-infra --profile <profile> -o json   # app_status.state: RUNNING
databricks apps logs nba-critical-infra --profile <profile> --tail-lines 100
```

## Demo script (about 6 minutes)

Run the pipeline job 15-30 minutes before the demo so "last seen" ages read in minutes and the
status panel shows "All feeds current" (it flips to "Data as of HH:MM" after 90 minutes).

1. **Overview.** The greeting and count come from the live queue. Point at the operational status
   (latest sighting, processing lag, risk engine run) and the KPI comparisons with the previous run.
2. **Alert queue.** Ranked by priority band, then by most recent sighting: the vehicles a field
   team can still reach. Filter to *Over-mass*, search a plate.
3. **Review an alert.** Show why it was flagged: each factor's normalised value, its weight and
   its points. The score is fully explainable, because this is a transparent rules engine, not a
   black box. Show the recent movement; camera misreads resolved back to the vehicle are labelled where present.
4. **Record a decision.** Add a note, then *Route to field queue*. The queue count drops, the
   register marks the vehicle *Routed*, and the decision appears in the record with your Unity
   Catalog identity.
5. **Governance.** Open the identity menu: every query and decision runs as you. Show the audit
   row in Catalog Explorer (`gold_alert_review_audit`) and the table's lineage back to bronze.

Talking points: all data is synthetic; scores are decision support only (see the use case
README's assurance notes); a "normal" vehicle can occasionally reach the threshold, which is why an
officer's judgement is required.
