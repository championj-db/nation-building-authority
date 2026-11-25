# Demo readiness assessment

Assessed 25 November 2026 against the design handoff (`design/`), the `databricks-app-design`
data-UI rules and the `databricks-impeccable` audit rubric.

**Verdict: ready to demo**, with the preparation steps below. The core story works end to end on
live synthetic data: streaming-style ingest, identity resolution, an explainable risk score, an
alert queue, and a governed human-in-the-loop decision written to an audit table as the signed-in
officer. The compliance dashboard and Genie space from the README's scope are not built; do not
promise them in the demo.

## Before every demo

1. Run the pipeline job 15-30 minutes beforehand. "Last seen" ages are relative to the run, and the
   status panel shows "Data as of HH:MM" once the latest run is more than 90 minutes old.
2. Open the app once to warm the SQL warehouse (a cold start shows a "starting" toast).
3. Make sure every presenter has `CAN_USE` on the app and the Unity Catalog grants listed in the
   app README. Queries run as the viewer, so a presenter without grants sees a permission message.
4. Run `npm run test:e2e` against `npm run dev` for a smoke check of the demo path.

## What the assessment changed

### Data and pipeline (would have broken or undermined the demo)

| Finding | Effect before | Fix |
| --- | --- | --- |
| `defect_code` SQL had a misplaced parenthesis | Job failed at step 1 | Corrected `element_at(array(...), i)` |
| Nested-quote f-string | Only parses on Python 3.12+ | Rewritten portably |
| `RUN_TS` carried microseconds | Scoring step failed (`CANNOT_PARSE_TIMESTAMP`) | Second-precision local timestamps via `common.local_now()` |
| `try: spark.table(...)` used as an existence probe | Lazy under Spark Connect, so the audit table was never created and the step failed; the bronze pre-create never fired | Idempotent `CREATE TABLE IF NOT EXISTS` and `spark.catalog.tableExists` |
| The synthetic world ran in UTC | "Night movement" fatigue alerts showed daytime sightings in AEDT; some sightings were in the future | Session time zone `Australia/Sydney`; no sightings after the run time |
| Every cohort member had the same propensity, and the factor bands saturated | 77 near-identical fatigue alerts scoring 72-77; over-mass, roadworthiness and route never alerted; no criticals | Per-asset intensity, an escalation storyline, explicit factor bands, a 365-day inspection lookback, rebalanced weights (`transparent-rules-v2`): 63 alerts across all four types, 16 critical, normal vehicles scoring about 0 |
| Plates were encoded from sequential ids | Every plate began `AA0`, which reads as test data | Bijective golden-ratio scramble: `GZ41MW`, `VX07NI`, ... |
| Telemetry was appended to one landing folder | A rerun on another day doubled the data | One folder per generation; silver reads the current one |
| The pipeline bundle synced the app folder | App sources uploaded with the job | `sync.exclude: app/**` |

### App

* Built from the design: overview, alert queue, entity register, risk-signal trend, shift handover
  and review dialog, all on live data, with loading, empty, error and stale states.
* Governance: every query is `.obo.sql`, and the decision write runs as the officer with bound
  parameters, Zod validation and a 409 on stale alerts. The decision record is visible on screen.
* AppKit's result cache (1-hour TTL, keyed on parameters) would have made "Refresh" and
  post-decision updates show stale data. Every query now carries a refresh token.
* Honesty: the "Live" labels on batch data became truthful period tags; KPIs show a source line and
  a comparison with the previous run; processing lag is measured, not asserted.
* Deploy fixes: Playwright moved to a separate `tests/` package, fonts vendored (both npm packages
  returned 404 from the Apps build's registry proxy), and build-time typegen falls back to committed
  types when the service principal, by design, cannot read the OBO-only tables.

### Design review (`databricks-impeccable`)

The brand was switched from the handoff's blue and Inter to the Databricks brand, as chosen for
consistency with Constituent 360. Layout, copy and interactions still follow the handoff.

| # | Dimension | Score | Key finding |
| --- | --- | --- | --- |
| 1 | Accessibility | 3 | AA contrast measured and fixed (button fill 5.4:1, control borders 3.9:1); keyboard-operable table rows; dialog focus on the title; severity never relies on colour alone |
| 2 | Performance | 3 | 99 KB gzipped app JS plus AppKit's Arrow chunk; the factor bars animate `width` (P3) |
| 3 | Theming | 3 | Fully tokenised and namespaced (`--ioc-*`) so AppKit's dark-mode tokens cannot bleed in; light only by design |
| 4 | Responsive | 3 | No horizontal overflow at all 9 handoff viewports; 44 px targets; viewport rather than container queries |
| 5 | Anti-patterns | 3 | Side-stripe severity bar replaced with a score and severity label; KPI tiles carry comparisons; translucent sticky nav kept from the handoff (P3) |
| 6 | Databricks brand | 3 | DM Sans / DM Mono everywhere, palette-only colours, Lava fill 0.4% of the viewport, logo not recreated (not used: brand assets must not be committed to this public repo); custom components follow Du Bois patterns rather than Du Bois itself (P2) |
| | **Total** | **18 / 24** | Good: minor polish |

Brand hardlines: DM Sans loaded ✓ · colours within brand tokens ✓ · Lava ≤ 10% ✓ · logo not recreated ✓.

## Open items

| Priority | Item | Recommendation |
| --- | --- | --- |
| High | Compliance dashboard and Genie space are in scope but not built | Add an AI/BI dashboard over `gold_ops_metrics` and `gold_alert_history`, and a Genie space over the gold tables. Both strengthen the "self-service over the same governed tables" message |
| High | Row filters and column masks on operator data are not defined | The app already runs as the user, so a UC row filter by state or region would demo the assurance notes directly |
| Medium | Ingest is batch (`availableNow`) | Fine for the demo if positioned honestly; for "near real time", add a continuous trigger or a frequent schedule |
| Medium | The deployed UI was verified through server logs and the auth gate only | The automation browser was not signed in. Open the app URL once yourself before the demo |
| Medium | 63 open alerts is a busy queue for a narrative | `alert_threshold` (job parameter, default 70) tunes the volume |
| Low | Typegen sample values in `config/queries/*.sql` name the dev catalog and schema | Used only by `npm run typegen`; runtime binds from app config. Replace with your own when forking |
| Low | Committed types are the build's source of truth | Run `npm run typegen` and commit after any query change |
| Low | `react-refresh/only-export-components` warning on the `Icon` map | Cosmetic (dev hot reload only) |

## Housekeeping

If you ran the pipeline before these fixes, that earlier schema holds pre-fix output. Rebuild into a
fresh schema (override `schema` in `variable-overrides.json`) and drop the old one.
