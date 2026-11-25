import { getExecutionContext } from '@databricks/appkit';

/** Workspace client for the current scope: the signed-in user inside asUser(), otherwise the app service principal. */
const scopedClient = () => getExecutionContext().client;

/**
 * Minimal SQL Statement Execution helper for live workflow reads and app decisions.
 *
 * Analytics queries (config/queries) are cached and serve the gold tables. Workflow state that
 * changes as people act on it - report status, recent mapping decisions, chain verifications - is
 * read here instead, uncached. Writes run inside `appkit.asUser(req)` so the statement executes
 * with the signed-in user's permissions and Unity Catalog records the real actor.
 */

export type SqlParam = { name: string; value: string | null; type?: 'STRING' | 'DATE' | 'INT' | 'TIMESTAMP' };
export type Row = Record<string, string | null>;

const TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'CANCELED', 'CLOSED']);

export function fqn(table: string) {
  const catalog = process.env.DATABRICKS_CATALOG;
  const schema = process.env.DATABRICKS_SCHEMA;
  if (!catalog || !schema) throw new Error('DATABRICKS_CATALOG and DATABRICKS_SCHEMA must be set');
  const quote = (part: string) => `\`${part.replace(/`/g, '``')}\``;
  return `${quote(catalog)}.${quote(schema)}.${quote(table)}`;
}

export async function runSql(statement: string, parameters: SqlParam[] = []): Promise<Row[]> {
  const warehouseId = process.env.DATABRICKS_WAREHOUSE_ID;
  if (!warehouseId) throw new Error('DATABRICKS_WAREHOUSE_ID is not set');
  const client = scopedClient();
  let response = await client.statementExecution.executeStatement({
    warehouse_id: warehouseId,
    statement,
    parameters: parameters.map((p) => ({ name: p.name, value: p.value ?? undefined, type: p.type ?? 'STRING' })),
    wait_timeout: '30s',
    on_wait_timeout: 'CONTINUE',
    format: 'JSON_ARRAY',
    disposition: 'INLINE',
  });
  const deadline = Date.now() + 120_000;
  while (!TERMINAL.has(response.status?.state ?? '') && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    response = await client.statementExecution.getStatement({ statement_id: response.statement_id! });
  }
  if (response.status?.state !== 'SUCCEEDED') {
    const message = response.status?.error?.message ?? `Statement ${response.status?.state ?? 'timed out'}`;
    throw Object.assign(new Error(message), { statusCode: /PERMISSION|INSUFFICIENT/i.test(message) ? 403 : 502 });
  }
  const columns = response.manifest?.schema?.columns?.map((c) => c.name ?? '') ?? [];
  return (response.result?.data_array ?? []).map((values) =>
    Object.fromEntries(columns.map((name, i) => [name, (values as (string | null)[])[i] ?? null]))
  );
}
