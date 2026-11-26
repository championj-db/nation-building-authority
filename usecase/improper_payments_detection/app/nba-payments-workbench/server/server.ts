import { analytics, createApp, getExecutionContext, getWarehouseId, lakebase, server } from '@databricks/appkit';
import type { Request, Response } from 'express';
import { caseIdSchema, outcomeSchema, resolveSchema } from '../shared/contracts.js';
import { createStateStore, type StateStore } from './state.js';

const { catalog, schema } = resolveSchema(process.env);
const table = (name: string) => `${catalog}.${schema}.${name}`;
/** Outcome capture needs Lakebase; without it the queue still works read-only. */
const lakebaseConfigured = Boolean(process.env.LAKEBASE_ENDPOINT);

type Param = { name: string; value?: string; type?: string };

/** The signed-in investigator, as the Databricks Apps proxy asserts it. Never a client value. */
function actor(request: Request): string {
  return (
    request.header('x-forwarded-email') ??
    request.header('x-forwarded-preferred-username') ??
    request.header('x-forwarded-user') ??
    (process.env.NODE_ENV === 'development' ? 'local.developer@example.invalid' : '')
  );
}

function fail(response: Response, error: unknown, action: string) {
  const message = error instanceof Error ? error.message : `${action} failed`;
  const denied = /PERMISSION|INSUFFICIENT|denied|403/i.test(message);
  console.error(`[${action}]`, message);
  response.status(denied ? 403 : 502).json({
    error: denied
      ? `You do not have permission to ${action.toLowerCase()} in this workspace.`
      : `Could not ${action.toLowerCase()}. Try again.`,
  });
}

await createApp({
  plugins: [analytics(), ...(lakebaseConfigured ? [lakebase()] : []), server()],
  async onPluginsReady(appkit) {
    /**
     * Read one governed case as the signed-in investigator (on-behalf-of-user). Every write is
     * gated on this: if Unity Catalog will not show them the case, they cannot record against it,
     * and the score, band and signal snapshotted with an outcome are what the gold layer says,
     * not what the browser sent.
     */
    async function governedCase(request: Request, caseId: string) {
      const params: Param[] = [{ name: 'case_id', value: caseId }];
      const result = await appkit.asUser(request).run(async () => {
        const { client } = getExecutionContext();
        return client.statementExecution.executeStatement({
          warehouse_id: await getWarehouseId(),
          wait_timeout: '30s',
          on_wait_timeout: 'CANCEL',
          statement: `SELECT case_id, risk_score, risk_band, primary_signal FROM ${table('gold_case')} WHERE case_id = :case_id`,
          parameters: params,
        });
      });
      if (result.status?.state !== 'SUCCEEDED') {
        throw new Error(result.status?.error?.message ?? 'Statement did not succeed');
      }
      const row = result.result?.data_array?.[0];
      if (!row) return null;
      return {
        caseId: String(row[0]),
        riskScore: Number(row[1]),
        riskBand: String(row[2]),
        primarySignal: String(row[3]),
      };
    }

    let store: StateStore | null = null;
    if (lakebaseConfigured) {
      const kit = appkit as unknown as { lakebase: Parameters<typeof createStateStore>[0] };
      try {
        store = await createStateStore(kit.lakebase);
      } catch (error) {
        console.warn('[state] Lakebase unavailable; outcome capture disabled:', error instanceof Error ? error.message : error);
      }
    }

    const needStore = (response: Response): StateStore | null => {
      if (store) return store;
      response.status(503).json({ error: 'Outcome capture is not available: the Lakebase case store is not connected.' });
      return null;
    };

    const caseParam = (request: Request, response: Response) => {
      const parsed = caseIdSchema.safeParse(request.params.id);
      if (!parsed.success) {
        response.status(400).json({ error: 'Unknown case reference' });
        return null;
      }
      return parsed.data;
    };

    appkit.server.extend((app) => {
      app.get('/api/session', (request, response) => {
        response.json({
          email: actor(request) || null,
          preferred: request.header('x-forwarded-preferred-username') ?? null,
          catalog,
          schema,
          outcomesEnabled: Boolean(store),
        });
      });

      app.get('/api/case-state', async (_request, response) => {
        if (!store) return void response.json({ enabled: false, states: [], outcomesTotal: 0 });
        try {
          response.json({ enabled: true, ...(await store.states()) });
        } catch (error) {
          fail(response, error, 'Load case status');
        }
      });

      app.get('/api/cases/:id/history', async (request, response) => {
        const caseId = caseParam(request, response);
        const db = caseId && needStore(response);
        if (!caseId || !db) return;
        try {
          response.json(await db.history(caseId));
        } catch (error) {
          fail(response, error, 'Load case history');
        }
      });

      for (const action of ['assign', 'release'] as const) {
        app.post(`/api/cases/:id/${action}`, async (request, response) => {
          const caseId = caseParam(request, response);
          const db = caseId && needStore(response);
          if (!caseId || !db) return;
          const who = actor(request);
          if (!who) return void response.status(401).json({ error: 'Sign in to work cases.' });
          try {
            if (!(await governedCase(request, caseId))) {
              return void response.status(404).json({ error: 'That case is not in the governed queue.' });
            }
            const result = action === 'assign' ? await db.assign(caseId, who) : await db.release(caseId, who);
            if (!result.ok) return void response.status(409).json({ error: result.reason });
            response.status(201).json(result.state);
          } catch (error) {
            fail(response, error, action === 'assign' ? 'Assign the case' : 'Return the case to the queue');
          }
        });
      }

      app.post('/api/cases/:id/outcome', async (request, response) => {
        const caseId = caseParam(request, response);
        const db = caseId && needStore(response);
        if (!caseId || !db) return;
        const parsed = outcomeSchema.safeParse(request.body);
        if (!parsed.success) {
          return void response.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid outcome' });
        }
        const who = actor(request);
        if (!who) return void response.status(401).json({ error: 'Sign in to record outcomes.' });
        try {
          const snapshot = await governedCase(request, caseId);
          if (!snapshot) return void response.status(404).json({ error: 'That case is not in the governed queue.' });
          const result = await db.recordOutcome({ ...snapshot, ...parsed.data, actor: who });
          if (!result.ok) return void response.status(409).json({ error: result.reason });
          response.status(201).json(result.state);
        } catch (error) {
          fail(response, error, 'Record the outcome');
        }
      });

      app.get('/api/outcomes/summary', async (_request, response) => {
        if (!store) return void response.json({ enabled: false, groups: [], recent: [] });
        try {
          response.json({ enabled: true, ...(await store.summary()) });
        } catch (error) {
          fail(response, error, 'Load recorded outcomes');
        }
      });
    });
  },
});
