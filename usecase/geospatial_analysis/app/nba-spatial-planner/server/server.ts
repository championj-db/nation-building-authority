import { analytics, createApp, getExecutionContext, getWarehouseId, server } from '@databricks/appkit';
import type { Request, Response } from 'express';
import { randomUUID } from 'node:crypto';
import type { ZodType } from 'zod';
import {
  briefSchema,
  idSchema,
  resolveMinCount,
  resolveSchema,
  reviewNoteSchema,
  savedViewSchema,
} from '../shared/contracts.js';

const { catalog, schema } = resolveSchema(process.env);
const minCount = resolveMinCount(process.env);
const table = (name: string) => `${catalog}.${schema}.${name}`;

type Param = { name: string; value?: string; type?: string };

function signedInUser(request: Request) {
  const email = request.header('x-forwarded-email') ?? request.header('x-forwarded-user') ?? null;
  const preferred = request.header('x-forwarded-preferred-username') ?? null;
  return { email, preferred, authenticated: Boolean(request.header('x-forwarded-access-token')) };
}

function parse<T>(schemaDef: ZodType<T>, body: unknown, response: Response): T | null {
  const parsed = schemaDef.safeParse(body);
  if (!parsed.success) {
    response.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid request' });
    return null;
  }
  return parsed.data;
}

function fail(response: Response, error: unknown, action: string) {
  const message = error instanceof Error ? error.message : `${action} failed`;
  const denied = /PERMISSION|INSUFFICIENT|denied|403/i.test(message);
  console.error(`[${action}]`, message);
  response.status(denied ? 403 : 502).json({
    error: denied ? `You do not have permission to ${action.toLowerCase()} in this workspace.` : `${action} failed. Try again.`,
  });
}

await createApp({
  plugins: [analytics(), server()],
  onPluginsReady(appkit) {
    /**
     * Every write runs as the signed-in officer (on-behalf-of-user), so Unity Catalog decides
     * whether they may write, and `officer` is current_user() as Unity Catalog sees it - never a
     * name the client supplied. Tables are append-only: corrections and deletions are newer rows.
     */
    async function execute(request: Request, statement: string, parameters: Param[]) {
      const result = await appkit.asUser(request).run(async () => {
        const { client } = getExecutionContext();
        return client.statementExecution.executeStatement({
          warehouse_id: await getWarehouseId(),
          wait_timeout: '30s',
          on_wait_timeout: 'CANCEL',
          statement,
          parameters,
        });
      });
      if (result.status?.state !== 'SUCCEEDED') {
        throw new Error(result.status?.error?.message ?? 'Statement did not succeed');
      }
      // INSERT returns [num_affected_rows, num_inserted_rows]
      return Number(result.result?.data_array?.[0]?.[0] ?? 0);
    }

    appkit.server.extend((app) => {
      app.get('/api/session', (request, response) => {
        response.json({ ...signedInUser(request), catalog, schema, minCount });
      });

      app.post('/api/notes', async (request, response) => {
        const input = parse(reviewNoteSchema, request.body, response);
        if (!input) return;
        try {
          const noteId = randomUUID();
          await execute(
            request,
            `INSERT INTO ${table('app_review_note')}
               (note_id, created_ts, officer, service_type, geo_level, region_code, region_name, threshold_km,
                evidence_status, next_step, note)
             VALUES (:id, current_timestamp(), current_user(), :service, :geo, :region, :name, :threshold,
                     :status, :next_step, :note)`,
            [
              { name: 'id', value: noteId },
              { name: 'service', value: input.service },
              { name: 'geo', value: input.geoLevel },
              { name: 'region', value: input.regionCode },
              { name: 'name', value: input.regionName },
              { name: 'threshold', value: String(input.thresholdKm), type: 'INT' },
              { name: 'status', value: input.evidenceStatus },
              { name: 'next_step', value: input.nextStep },
              { name: 'note', value: input.note },
            ],
          );
          response.status(201).json({ noteId });
        } catch (error) {
          fail(response, error, 'Record a review note');
        }
      });

      app.post('/api/views', async (request, response) => {
        const input = parse(savedViewSchema, request.body, response);
        if (!input) return;
        try {
          const viewId = randomUUID();
          await execute(
            request,
            `INSERT INTO ${table('app_saved_view')} (view_id, created_ts, officer, name, settings, deleted)
             VALUES (:id, current_timestamp(), current_user(), :name, :settings, false)`,
            [
              { name: 'id', value: viewId },
              { name: 'name', value: input.name },
              { name: 'settings', value: JSON.stringify(input.settings) },
            ],
          );
          response.status(201).json({ viewId });
        } catch (error) {
          fail(response, error, 'Save a view');
        }
      });

      // Only the officer who saved a view can remove it.
      app.delete('/api/views/:id', async (request, response) => {
        const id = parse(idSchema, request.params.id, response);
        if (!id) return;
        try {
          const inserted = await execute(
            request,
            `INSERT INTO ${table('app_saved_view')} (view_id, created_ts, officer, name, settings, deleted)
             SELECT view_id, current_timestamp(), current_user(), name, settings, true
             FROM ${table('app_saved_view')}
             WHERE view_id = :id
             QUALIFY row_number() OVER (PARTITION BY view_id ORDER BY created_ts DESC) = 1
               AND NOT deleted AND officer = current_user()`,
            [{ name: 'id', value: id }],
          );
          if (inserted < 1) {
            response.status(404).json({ error: 'That view no longer exists, or was saved by another officer.' });
            return;
          }
          response.status(204).end();
        } catch (error) {
          fail(response, error, 'Remove a view');
        }
      });

      app.post('/api/briefs', async (request, response) => {
        const input = parse(briefSchema, request.body, response);
        if (!input) return;
        if (!input.settings.suppress) {
          response.status(422).json({ error: 'Turn small-count suppression on before preparing a brief.' });
          return;
        }
        try {
          const briefId = randomUUID();
          await execute(
            request,
            `INSERT INTO ${table('app_brief')}
               (brief_id, created_ts, officer, title, policy_question, access_basis, audience, settings, findings,
                suppression_applied, status, signed_off_by, signed_off_ts)
             VALUES (:id, current_timestamp(), current_user(), :title, :question, :basis, :audience, :settings,
                     :findings, true, 'draft', NULL, NULL)`,
            [
              { name: 'id', value: briefId },
              { name: 'title', value: input.title },
              { name: 'question', value: input.policyQuestion },
              { name: 'basis', value: input.accessBasis },
              { name: 'audience', value: input.audience },
              { name: 'settings', value: JSON.stringify(input.settings) },
              { name: 'findings', value: JSON.stringify(input.findings) },
            ],
          );
          response.status(201).json({ briefId });
        } catch (error) {
          fail(response, error, 'Prepare a brief');
        }
      });

      // Sign-off appends a signed_off row carrying the draft's content, so the record shows both
      // who prepared the brief and who approved it for circulation.
      app.post('/api/briefs/:id/sign-off', async (request, response) => {
        const id = parse(idSchema, request.params.id, response);
        if (!id) return;
        try {
          const inserted = await execute(
            request,
            `INSERT INTO ${table('app_brief')}
             SELECT brief_id, current_timestamp(), officer, title, policy_question, access_basis, audience, settings,
                    findings, suppression_applied, 'signed_off', current_user(), current_timestamp()
             FROM ${table('app_brief')}
             WHERE brief_id = :id
             QUALIFY row_number() OVER (PARTITION BY brief_id ORDER BY created_ts DESC) = 1 AND status = 'draft'`,
            [{ name: 'id', value: id }],
          );
          if (inserted < 1) {
            response.status(409).json({ error: 'This brief has already been signed off.' });
            return;
          }
          response.status(201).json({ status: 'signed_off' });
        } catch (error) {
          fail(response, error, 'Sign off a brief');
        }
      });
    });
  },
});
