# Demo readiness assessment

Assessed 25 November 2026 after the pivot from a single-sector heavy-vehicle console to a national,
cross-sector Infrastructure Operations Centre (roads, rail, water, energy). Measured against
`design/IOC-DESIGN-SPEC.md`, the `databricks-app-design` data-UI rules and the
`databricks-impeccable` audit rubric.

**Verdict: ready to demo**, with the preparation steps below. The end-to-end story works on live
synthetic data: two feeds streamed into one medallion pipeline, readings conformed and quarantined,
a cross-sector dependency graph, an explainable likelihood × consequence score, incidents with
downstream impact on a network map, and a governed decision written as the signed-in officer. The
compliance dashboard and Genie space from the README's scope are not built; do not promise them.

## Before every demo

1. Run the pipeline job 15-30 minutes beforehand. Ages and the "All feeds current" pill are relative
   to the run; the pill shows "Data as of HH:MM" after 90 minutes.
2. Scores follow the daily load cycle, which peaks late afternoon: in testing, a 12:45 run raised
   33 incidents and a 13:20 run 42. `incident_threshold` (job parameter, 48) tunes the queue length.
3. Open the app once to warm the SQL warehouse.
4. Make sure every presenter has `CAN_USE` on the app and the grants in the app README; queries run
   as the viewer.
5. Run `npm run test:e2e` against `npm run dev` for a smoke check of the demo path.

## What the pivot built and verified

| Area | Result |
| --- | --- |
| Reference data | 599 assets in 14 classes at 57 real localities, 723 sensors with engineering limits, 282 cross-sector supply links, 2 years of inspections |
| Telemetry | about 480,000 trusted 15-minute readings over 7 days; 998 unregistered and 467 implausible readings quarantined with a reason; 3-minute median lateness |
| Hazards | 5 active warnings (heatwave ×2, flood, bushfire, storm) plus an expired one the app correctly ignores |
| Risk engine | 33 to 42 incidents depending on time of day, in all four sectors, with a real extreme tier; normal assets score near zero |
| Storylines | Penrith substation (extreme, 12 dependants across rail, water and roads), Lismore treatment plant, Traralgon transmission line, Sunshine trunk main (high with no hazard), Brisbane signalling, Grafton road flooding |
| Decision write | Dispatch, notify and monitor all recorded with `current_user()` and the evidence panels viewed; the queue, map, register and handover agree immediately |
| Responsive | No horizontal overflow at all 9 handoff viewports (360-1920 px) |
| Validation | `databricks apps validate` passes (types, AST lint, typecheck, build, 17 unit tests) |
| Deployment | App deployed to `au-pubsec` and running in production mode behind the Apps auth gate |

## Issues found and fixed during the pivot

* **Storylines depended on random placement.** The "nearest transmission line to Traralgon" was in
  Melbourne, outside the bushfire, and the Penrith substation powered no water assets. Storyline
  assets are now anchored at their locality, and the hero substation is explicitly wired.
* **Risk calibration.** The first run gave 52 low-value medium incidents, and a trunk-main burst
  with no hazard nearby could not rise above medium. Direct evidence (exceedance and anomaly) now
  outweighs context (hazard and condition), condition flags only poor grades, and the consequence
  floor was softened.
* **Sector people totals double-counted** nested supply chains (energy showed 14 million people).
  Tiles now show distinct "dependants at risk", and people stay at incident level as an upper bound.
* **Readings ran far past alarm limits** (a transformer at 135 °C against a 110 °C alarm), because
  storyline ramps stacked on hazard and daily-cycle effects. Gauges are now capped just past the
  alarm, where protection acts.
* **Map cascade was illegible** at state zoom. Selecting an incident now frames it and its direct
  dependants and lists them by name.
* **Map scroll-spy, AppKit focus ring and phone overflow** in the sector tiles, all fixed and
  re-verified.

## Design review (`databricks-impeccable`)

| # | Dimension | Score | Key finding |
| --- | --- | --- | --- |
| 1 | Accessibility | 3 | Measured AA contrast; map markers are keyboard buttons with descriptive labels; sector and severity always carry an icon or label; the queue remains the accessible primary path to every incident |
| 2 | Performance | 3 | The map sends about 600 small rows and renders as one SVG; the factor bars animate `width` (P3) |
| 3 | Theming | 3 | Fully tokenised (`--ioc-*`), sector colours from the brand's categorical palette; light only by design |
| 4 | Responsive | 3 | Clean at all 9 viewports; viewport rather than container queries |
| 5 | Anti-patterns | 3 | No side stripes (sector tiles use a top rule); KPIs carry comparisons; warning areas use warning amber, not Lava |
| 6 | Databricks brand | 3 | DM Sans / DM Mono, palette-only colours, Lava kept to the CTA, active nav, focus and extreme rings; custom components follow Du Bois patterns (P2) |
| | **Total** | **18 / 24** | Good: minor polish |

## Open items

| Priority | Item | Recommendation |
| --- | --- | --- |
| High | Compliance dashboard and Genie space are in scope but not built | An AI/BI dashboard over `gold_ops_metrics`, `gold_incident_history` and `gold_sector_status`, and a Genie space over the gold tables ("which substations inside the heatwave supply rail signalling?") |
| High | Row filters by sector and operator are not defined | The app already runs as the user; a UC row filter limiting an operator's staff to their own assets would demo the SOCI-style access story directly |
| Medium | Ingest is batch (`availableNow`) | Position it honestly, or add a frequent schedule or continuous trigger for a live feel |
| Medium | The deployed UI was verified through logs and the auth gate only | Open the app URL yourself once before the demo |
| Medium | People counts mix kinds of reliance (households, rail patronage, road traffic) | Labelled as an upper bound; a production model would use service-specific measures |
| Low | Typegen sample values in `config/queries/*.sql` name the dev catalog and schema | Used only by `npm run typegen`; runtime binds from app config |
| Low | `react-refresh/only-export-components` warning on the `Icon` map | Cosmetic, dev hot reload only |

## Housekeeping

The pivot built into a fresh schema. Schemas from the earlier heavy-vehicle runs are no longer used
and can be dropped when convenient.
