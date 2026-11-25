# Infrastructure Operations Centre (Databricks App)

AppKit (Node + React) operations app for the critical infrastructure monitoring use case: a
national, cross-sector view across roads, rail, water and energy. A duty officer sees which
incidents need action, why each asset is at risk, which hazards are active, and what else fails if
an asset fails, then records a human-in-the-loop decision: dispatch a crew, notify the responsible
operator, or keep monitoring.

The product and design specification is `../../design/IOC-DESIGN-SPEC.md`. The visual identity is
the Databricks brand (Oat surfaces, Navy text, Lava accent, DM Sans / DM Mono, vendored under SIL
OFL); see `.databricks-impeccable.md`. The network map's state outlines come from Natural Earth
(public domain), built by `scripts/build-map.py`; key freight roads and rail come from the
Department of Infrastructure (CC BY 4.0) via the pipeline, and are read from Unity Catalog.

## What runs as whom

| Surface | Runs as | Why |
| --- | --- | --- |
| Every read (`config/queries/*.obo.sql`) | The signed-in officer | Unity Catalog grants, row filters and column masks on operator-level risk data apply per officer |
| Decision write (`POST /api/reviews`) | The signed-in officer | The audit row's `officer_name` is `current_user()`, never a client-supplied name; the evidence panels viewed are recorded too |
| Build-time type generation | App service principal | Has no `SELECT` by design; falls back to the committed types (`scripts/typegen.mjs`) |

The decision write uses bound statement parameters, validates input with Zod
(`server/contracts.ts`), and only inserts when the incident is still open
(`INSERT ... SELECT ... WHERE incident_id = :incident_id`), so a stale decision returns 409.

## Prerequisites

1. Run the pipeline job in `../../` (`databricks bundle run critical_infrastructure_monitoring_pipeline`).
   It writes the tables this app reads: `gold_incident`, `gold_incident_impact`, `gold_asset_risk`,
   `gold_sector_status`, `gold_hazard_status`, `gold_ops_metrics`, `gold_incident_review_audit`,
   `gold_network_disruption`, `gold_hazard_network_exposure`, `ref_network_segment`, `ref_river` and
   `silver_reading` (for the evidence chart).
2. Each officer who uses the app needs `USE CATALOG`, `USE SCHEMA`, `SELECT` on those tables, and
   `MODIFY` on `gold_incident_review_audit`, plus `CAN_USE` on the app.

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

## Demo script (about 9 minutes)

Run the pipeline job 15-30 minutes before the demo, so "raised" ages read in minutes and the feed
pill shows "All feeds current" (it flips to "Data as of HH:MM" after 90 minutes). Scores follow the
daily load cycle, so an afternoon demo shows more energy stress than a morning one.

1. **One picture across sectors.** Read the headline, then the four sector tiles: open incidents,
   assets in alarm, assets not reporting, and dependants at risk. Point out the feed line: readings
   today, sensors reporting, median detection time against the previous run, and the share of
   readings quarantined. Bad data is held back, never scored.
2. **The network.** The map draws the real national key freight roads and rail (Department of
   Infrastructure data, fetched at run time). Each warning lists the key routes inside it: the
   Northern Rivers flood covers about 177 km of the Pacific Highway and 132 km of rail.
3. **Shared hazards.** Open the network map. Five warnings are active: a heatwave over Greater
   Western Sydney and the Hunter, a Northern Rivers flood, a Gippsland bushfire, a South East
   Queensland storm, and an Adelaide heatwave. Select the heatwave to zoom to it. The panel shows how
   many roads, rail, water and energy assets sit inside it: one warning, four sectors.
4. **The cascade.** Select the Penrith Zone Substation marker. The map frames it and draws its supply
   links: rail signalling and overhead wiring, treatment plants, road tunnels. This is the
   cross-operator view no single operator has.
5. **Network propagation.** Select the Grafton road corridor in the flood. Losing it makes the
   Pacific Highway unusable between its junctions, so traffic diverts about 500 km inland via the
   Cunningham and New England highways, which the map draws. Then select the Brisbane signalling
   incident: there is no way round, so it cuts the freight rail link to Brisbane. That is why it is
   extreme despite serving few people directly.
6. **Why it is extreme.** Open the review. Risk is likelihood × consequence: the transformer is past
   its alarm limit, inside a severe heatwave, and well above its own baseline, and about 1.6 million
   people rely on it and its dependants. Show the 24-hour chart crossing the warning and alarm
   lines, then "If this fails".
7. **Decide.** Add a note and choose *Dispatch crew*. The queue count drops, the marker dims, and the
   decision appears in the shift handover with your Unity Catalog identity and the evidence you
   viewed.
8. **Not every incident is a hazard.** Filter the queue to Water and open the Sunshine trunk main:
   a pressure drop with no warning nearby, caught by limit exceedance and anomaly alone.
9. **Governance.** Open the identity menu: every query and decision runs as you. Show
   `gold_incident_review_audit` and the lineage from the app's tables back to bronze in Catalog
   Explorer.

Talking points: all assets, operators, readings and warnings are synthetic (only place names and
map outlines are real); scores are decision support, never automatic action; people counts are an
upper bound because services overlap, which is why they are never summed by sector.
