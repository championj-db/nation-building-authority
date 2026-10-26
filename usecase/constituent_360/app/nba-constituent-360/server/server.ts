import { analytics, createApp, genie, server } from '@databricks/appkit';
import type { Request } from 'express';
import { z } from 'zod';
import { accessSessionSchema, identityDecisionSchema, recordChangeSchema } from './contracts.js';

const schema = `${process.env.DATABRICKS_CATALOG ?? 'au_pubsec_catalog'}.${process.env.DATABRICKS_SCHEMA ?? 'constituent_360_jared_champion'}`;

function userToken(request: Request): string {
  const token = request.header('x-forwarded-access-token');
  if (!token) throw new Error('A signed-in user token is required');
  return token;
}

async function executeStatement(request: Request, statement: string) {
  const host = process.env.DATABRICKS_HOST;
  const warehouseId = process.env.DATABRICKS_WAREHOUSE_ID;
  if (!host || !warehouseId) throw new Error('Databricks SQL is not configured');
  const workspaceUrl = /^https?:\/\//.test(host) ? host : `https://${host}`;
  const response = await fetch(`${workspaceUrl.replace(/\/$/, '')}/api/2.0/sql/statements`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${userToken(request)}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      warehouse_id: warehouseId,
      statement,
      wait_timeout: '50s',
      on_wait_timeout: 'CANCEL',
      disposition: 'INLINE',
    }),
  });
  const body = await response.json() as { status?: { state?: string; error?: { message?: string } }; result?: unknown };
  if (!response.ok || body.status?.state !== 'SUCCEEDED') {
    throw new Error(body.status?.error?.message ?? 'Databricks SQL request failed');
  }
  return body.result ?? {};
}

const literal = (value: string | null | undefined) => value == null ? 'NULL' : `'${value.split("'").join("''")}'`;

await createApp({
  plugins: [analytics(), genie({ spaces: { constituent360: process.env.DATABRICKS_GENIE_SPACE_ID ?? '' } }), server()],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      app.get('/api/whoami', (request, response) => {
        const email = request.header('x-forwarded-email') ?? request.header('x-forwarded-user');
        response.json({ email: email ?? null, authenticated: Boolean(email && request.header('x-forwarded-access-token')) });
      });
      app.post('/api/access-sessions', async (request, response) => {
        try {
          const input = accessSessionSchema.parse(request.body);
          const result = await executeStatement(request, `CALL ${schema}.start_access_session(${literal(input.purpose)}, ${literal(input.caseId)}, ${literal(input.constituentId)}, ${literal(input.justification)})`);
          response.status(201).json(result);
        } catch (error) { response.status(error instanceof z.ZodError ? 400 : 403).json({ error: error instanceof Error ? error.message : 'Access denied' }); }
      });
      app.delete('/api/access-sessions/current', async (request, response) => {
        try { await executeStatement(request, `CALL ${schema}.end_access_session()`); response.status(204).end(); }
        catch (error) { response.status(403).json({ error: error instanceof Error ? error.message : 'Access denied' }); }
      });
      app.post('/api/record-change-requests', async (request, response) => {
        try {
          const input = recordChangeSchema.parse(request.body);
          const result = await executeStatement(request, `CALL ${schema}.request_record_change(${literal(input.changeType)}, ${literal(input.details)}, ${literal(input.reasonCode)})`);
          response.status(201).json(result);
        } catch (error) { response.status(error instanceof z.ZodError ? 400 : 403).json({ error: error instanceof Error ? error.message : 'Change not staged' }); }
      });
      app.post('/api/identity-decisions', async (request, response) => {
        try {
          const input = identityDecisionSchema.parse(request.body);
          await executeStatement(request, `CALL ${schema}.record_identity_decision(${literal(input.decision)}, ${literal(input.leftRecordId)}, ${literal(input.rightRecordId)}, ${literal(input.reason)})`);
          response.status(201).json({ status: 'recorded' });
        } catch (error) { response.status(error instanceof z.ZodError ? 400 : 403).json({ error: error instanceof Error ? error.message : 'Decision not recorded' }); }
      });
    });
  },
});
