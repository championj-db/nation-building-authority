# Portfolio Command Centre

React and TypeScript Databricks App for the Nation Building Authority synthetic infrastructure portfolio. It combines typed SQL Warehouse analytics with the governed Portfolio Genie space.

## Local preview

```bash
DATABRICKS_CONFIG_PROFILE=au-pubsec \
DATABRICKS_WAREHOUSE_ID=000000000588d809 \
DATABRICKS_GENIE_SPACE_ID=01f1ce6cec5d1881987657a5f19d7349 \
npm run dev
```

Open `http://localhost:8000`.

## Verify

```bash
npm run typegen
npm run lint
npm test
npm run build
databricks apps validate --path . --profile au-pubsec
databricks bundle validate --profile au-pubsec
```

## Deploy

```bash
databricks apps deploy --profile au-pubsec --auto-approve
databricks apps get nba-budget-portfolio --profile au-pubsec -o json
databricks apps logs nba-budget-portfolio --profile au-pubsec --tail-lines 200
```

Application source is in `client/src`, SQL queries are in `config/queries`, and the AppKit server entry point is `server/server.ts`.
