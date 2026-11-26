# Improper Payments Workbench (app)

AppKit (Node + React) app for `usecase/improper_payments_detection`. See the use case
[README](../../README.md) for the pipeline and deployment order, and
[design/DESIGN-HANDOFF.md](../../design/DESIGN-HANDOFF.md) for how it maps to the design.

- **Reads**: `config/queries/*.obo.sql`, run on behalf of the signed-in investigator.
- **Writes**: case assignments and outcomes go to Lakebase (`server/state.ts`, schema `ipw`), each
  checked first against Unity Catalog as that investigator (`server/server.ts`).

```bash
cp .env.example .env    # fill in profile, warehouse, catalog, schema (and Lakebase, optional)
npm install
npm run dev             # http://localhost:8000
npm run typecheck && npm run lint && npm test
npm run test:e2e        # Playwright smoke path against BASE_URL (default localhost:8000)
```
