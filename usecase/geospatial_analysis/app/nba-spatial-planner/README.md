# Spatial Service Planner

Databricks App (AppKit: Node + React) for the geospatial analysis use case. See
[../../README.md](../../README.md) for what it does, how to deploy it, and the grants officers need.

| Path | What |
| --- | --- |
| `client/src/App.tsx` | Shell: tabs, draft-then-apply settings, URL state, selection |
| `client/src/components/AccessMap.tsx` | SVG map: regions / H3 layer, sites, radius rings, proposed sites, pan and zoom, search |
| `client/src/components/` | Policy settings, decision signals, evidence queue, briefs, pipeline, assurance |
| `client/src/lib/` | Queries (`analysis.ts`), row normalisation (`data.ts`), projection (`geo.ts`), rules (`model.ts`) |
| `config/queries/*.obo.sql` | Every query, run as the signed-in officer; suppression applied here |
| `server/server.ts` | Append-only write routes (notes, views, briefs, sign-off), run as the officer |
| `shared/contracts.ts` | Zod contracts shared by client and server |
| `tests/smoke.spec.ts` | Read-only Playwright demo-path check (`npm run test:e2e`, `BASE_URL=` for a deployed app) |

Design tokens and layout come from `../../design/spatial-service-planner.html`;
`.databricks-impeccable.md` records the design context.
