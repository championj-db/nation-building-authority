import { analytics, createApp, getExecutionContext, getWarehouseId, server } from '@databricks/appkit';
import type { Request } from 'express';
import { z } from 'zod';
import { resolveSchema, reviewDecisionSchema } from './contracts.js';

const { catalog, schema } = resolveSchema(process.env);
const auditTable = `${catalog}.${schema}.gold_incident_review_audit`;
const incidentTable = `${catalog}.${schema}.gold_incident`;

function signedInUser(request: Request) {
  const email = request.header('x-forwarded-email') ?? request.header('x-forwarded-user') ?? null;
  const preferred = request.header('x-forwarded-preferred-username') ?? null;
  return { email, preferred, authenticated: Boolean(request.header('x-forwarded-access-token')) };
}

await createApp({
  plugins: [analytics(), server()],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      // Who the app is acting for, and which governed schema it reads. The client passes
      // catalog/schema back as query parameters, so the SQL files carry no environment literal.
      app.get('/api/session', (request, response) => {
        response.json({ ...signedInUser(request), catalog, schema });
      });

      // Human-in-the-loop decision record. Runs as the signed-in officer (OBO) so the audit row's
      // officer_name is current_user() as Unity Catalog sees it - never a client-supplied name -
      // and the write is refused unless that officer holds MODIFY on the audit table.
      app.post('/api/reviews', async (request, response) => {
        const parsed = reviewDecisionSchema.safeParse(request.body);
        if (!parsed.success) {
          response.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid decision' });
          return;
        }
        const input = parsed.data;
        try {
          const result = await appkit.asUser(request).run(async () => {
            const { client } = getExecutionContext();
            return client.statementExecution.executeStatement({
              warehouse_id: await getWarehouseId(),
              wait_timeout: '30s',
              on_wait_timeout: 'CANCEL',
              // INSERT ... SELECT only writes when the incident is still in the current queue.
              statement: `INSERT INTO ${auditTable}
                  (review_id, incident_id, reviewed_ts, officer_name, disposition, evidence_viewed, notes)
                SELECT uuid(), incident_id, current_timestamp(), current_user(), :disposition, :evidence, :notes
                FROM ${incidentTable}
                WHERE incident_id = :incident_id`,
              parameters: [
                { name: 'incident_id', value: input.incidentId },
                { name: 'disposition', value: input.disposition },
                { name: 'evidence', value: input.evidenceViewed.join(',') },
                { name: 'notes', value: input.notes },
              ],
            });
          });
          if (result.status?.state !== 'SUCCEEDED') {
            throw new Error(result.status?.error?.message ?? 'Decision was not recorded');
          }
          const inserted = Number(result.result?.data_array?.[0]?.[0] ?? 0);
          if (inserted < 1) {
            response.status(409).json({ error: 'This incident is no longer open - refresh and try again.' });
            return;
          }
          response.status(201).json({ status: 'recorded', disposition: input.disposition });
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Decision was not recorded';
          const denied = /PERMISSION|INSUFFICIENT|denied|403/i.test(message);
          response.status(denied ? 403 : error instanceof z.ZodError ? 400 : 502).json({
            error: denied ? 'You do not have permission to record decisions on this queue.' : message,
          });
        }
      });
    });
  },
});
