import { Readable } from 'node:stream';
import { analytics, createApp, files, genie, jobs, lakebase, server, sql } from '@databricks/appkit';
import type { Request, Response } from 'express';
import {
  decisionProblem,
  decisionSchema,
  docIdSchema,
  resolveSchema,
  type GovernedSnapshot,
  type Status,
} from '../shared/contracts.js';
import { recheck } from '../shared/recheck.js';
import { createStore, type Store } from './store.js';

const { catalog, schema } = resolveSchema(process.env);
const table = (name: string) => `${catalog}.${schema}.${name}`;
const lakebaseConfigured = Boolean(process.env.LAKEBASE_ENDPOINT);
const genieConfigured = Boolean(process.env.DATABRICKS_GENIE_SPACE_ID);
const ingestConfigured = Boolean(process.env.DATABRICKS_JOB_ID);
const volumeConfigured = Boolean(process.env.DATABRICKS_VOLUME_FILES);

type Rows = Record<string, unknown>[];
function rowsOf(result: unknown): Rows {
  if (Array.isArray(result)) return result as Rows;
  const r = result as { data?: unknown; rows?: unknown } | null;
  if (r && Array.isArray(r.data)) return r.data as Rows;
  if (r && Array.isArray(r.rows)) return r.rows as Rows;
  return [];
}

/** The signed-in officer, as the Databricks Apps proxy asserts it. Never a client value. */
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
  const denied = /PERMISSION|INSUFFICIENT|denied|403|Unauthorized/i.test(message);
  console.error(`[${action}]`, message);
  response.status(denied ? 403 : 502).json({
    error: denied
      ? `You do not have permission to ${action.toLowerCase()} in this workspace.`
      : `Could not ${action.toLowerCase()}. Try again.`,
  });
}

const parseList = (v: unknown): string[] => {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v !== 'string' || !v) return [];
  try {
    const parsed: unknown = JSON.parse(v);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
};

await createApp({
  plugins: [
    analytics(),
    server(),
    ...(lakebaseConfigured ? [lakebase()] : []),
    ...(genieConfigured ? [genie()] : []),
    ...(ingestConfigured ? [jobs()] : []),
    // Page images: only reads, only as a real signed-in user (on behalf of them, so Unity Catalog
    // grants on the volume apply), and in practice only after the governed lookup below.
    ...(volumeConfigured
      ? [
          files({
            volumes: {
              files: {
                auth: 'on-behalf-of-user',
                policy: (action, _resource, user) => action === 'download' && user.isServicePrincipal !== true,
              },
            },
          }),
        ]
      : []),
  ],
  // The gold layer is rebuilt by the arrivals and feedback jobs; keep cached reads short-lived.
  cache: { enabled: true, ttl: 30 },
  async onPluginsReady(appkit) {
    const kit = appkit as unknown as {
      asUser(req: Request): {
        analytics: { query(statement: string, params: Record<string, unknown>): Promise<unknown> };
      };
      lakebase: Parameters<typeof createStore>[0];
      files?: (key: string) => {
        asUser(req: Request): { download(path: string): Promise<{ contents?: unknown; 'content-type'?: string }> };
      };
      jobs?: (key: string) => {
        runNow(params?: Record<string, unknown>): Promise<unknown>;
        getRun(runId: number): Promise<unknown>;
      };
      server: { extend(fn: (app: import('express').Application) => void): void };
    };

    /** Read as the signed-in officer, so Unity Catalog grants decide what they can see. */
    const asUser = async (request: Request, statement: string, params: Record<string, string>) => {
      const bound = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, sql.string(v)]));
      return rowsOf(await kit.asUser(request).analytics.query(statement, bound));
    };

    /** The gold layer's view of a document at the moment of decision; null when not visible. */
    async function snapshot(
      request: Request,
      docId: string,
      corrections: Record<string, string> = {}
    ): Promise<{ snap: GovernedSnapshot; confidences: Record<string, number | null> } | null> {
      const doc = await asUser(
        request,
        `SELECT d.doc_id, d.doc_type, d.status, a.lowest_required_confidence,
                to_json(a.fields_below_threshold) AS held, to_json(a.failed_checks) AS failed,
                s.abn AS vendor_abn, s.gst_registered AS vendor_gst_registered
         FROM ${table('gold_documents')} d LEFT JOIN ${table('gold_invoice_assessment')} a ON a.doc_id = d.doc_id
         LEFT JOIN ${table('ref_suppliers')} s ON s.supplier_id = a.supplier_id
         WHERE d.doc_id = :doc_id`,
        { doc_id: docId }
      );
      const row = doc[0];
      if (!row) return null;
      const fields = await asUser(
        request,
        `SELECT field, routing_confidence, type_valid, value FROM ${table('gold_extracted_fields')} WHERE doc_id = :doc_id`,
        { doc_id: docId }
      );
      return {
        snap: {
          docId,
          docType: typeof row.doc_type === 'string' ? row.doc_type : '',
          status: (typeof row.status === 'string' ? row.status : 'processing') as Status,
          lowestConfidence: row.lowest_required_confidence == null ? null : Number(row.lowest_required_confidence),
          heldFields: parseList(row.held),
          // Judge the decision on the officer's corrected values, not the misread ones.
          failedChecks: recheck(
            parseList(row.failed),
            Object.fromEntries(fields.map((f) => [String(f.field), typeof f.value === 'string' ? f.value : null])),
            corrections,
            {
              docType: typeof row.doc_type === 'string' ? row.doc_type : '',
              vendorAbn: typeof row.vendor_abn === 'string' ? row.vendor_abn : null,
              gstRegistered: String(row.vendor_gst_registered) !== 'false',
            }
          ).failed,
          invalidFields: fields
            .filter((f) => f.value != null && String(f.type_valid) !== 'true')
            .map((f) => String(f.field)),
        },
        confidences: Object.fromEntries(
          fields.map((f) => [String(f.field), f.routing_confidence == null ? null : Number(f.routing_confidence)])
        ),
      };
    }

    let store: Store | null = null;
    if (lakebaseConfigured) {
      try {
        store = await createStore(kit.lakebase);
      } catch (error) {
        console.warn(
          '[store] Lakebase unavailable; decisions disabled:',
          error instanceof Error ? error.message : error
        );
      }
    }

    const docParam = (request: Request, response: Response) => {
      const parsed = docIdSchema.safeParse(request.params.id);
      if (!parsed.success) {
        response.status(400).json({ error: 'Unknown document reference' });
        return null;
      }
      return parsed.data;
    };

    kit.server.extend((app) => {
      app.get('/api/session', (request, response) => {
        response.json({
          email: actor(request) || null,
          preferred: request.header('x-forwarded-preferred-username') ?? null,
          catalog,
          schema,
          decisionsEnabled: Boolean(store),
          genieEnabled: genieConfigured,
          ingestEnabled: ingestConfigured,
          pagesEnabled: volumeConfigured,
        });
      });

      app.get('/api/decisions', async (_request, response) => {
        if (!store) return void response.json({ enabled: false, decisions: [] });
        try {
          response.json({ enabled: true, decisions: await store.decisions() });
        } catch (error) {
          fail(response, error, 'Load decisions');
        }
      });

      app.get('/api/corrections/stats', async (_request, response) => {
        if (!store) return void response.json({ enabled: false, fields: [] });
        try {
          response.json({ enabled: true, fields: await store.correctionStats() });
        } catch (error) {
          fail(response, error, 'Load corrections');
        }
      });

      app.get('/api/documents/:id/decision', async (request, response) => {
        const docId = docParam(request, response);
        if (!docId) return;
        if (!store) return void response.json({ decision: null, corrections: [] });
        try {
          response.json(await store.forDocument(docId));
        } catch (error) {
          fail(response, error, 'Load the decision');
        }
      });

      app.post('/api/documents/:id/decision', async (request, response) => {
        const docId = docParam(request, response);
        if (!docId) return;
        if (!store)
          return void response
            .status(503)
            .json({ error: 'Decisions cannot be recorded: the review store is not connected.' });
        const parsed = decisionSchema.safeParse(request.body);
        if (!parsed.success)
          return void response.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid decision' });
        const who = actor(request);
        if (!who) return void response.status(401).json({ error: 'Sign in to record decisions.' });
        try {
          const governed = await snapshot(
            request,
            docId,
            Object.fromEntries(parsed.data.corrections.map((c) => [c.field, c.corrected]))
          );
          if (!governed)
            return void response.status(404).json({ error: 'That document is not in the governed register.' });
          const problem = decisionProblem(parsed.data, governed.snap);
          if (problem) return void response.status(422).json({ error: problem });
          const result = await store.record(parsed.data, governed.snap, governed.confidences, who);
          if (!result.ok) return void response.status(409).json({ error: result.reason });
          response.status(201).json(result.decision);
        } catch (error) {
          fail(response, error, 'Record the decision');
        }
      });

      /** One rendered page, after checking the officer can see the document in Unity Catalog. */
      app.get('/api/documents/:id/pages/:page', async (request, response) => {
        const docId = docParam(request, response);
        if (!docId) return;
        const page = Number(request.params.page);
        if (!Number.isInteger(page) || page < 0 || page > 499)
          return void response.status(400).json({ error: 'Unknown page' });
        if (!kit.files)
          return void response
            .status(503)
            .json({ error: 'Page images are not available: the document volume is not bound.' });
        try {
          const rows = await asUser(
            request,
            `SELECT to_json(page_images) AS pages FROM ${table('gold_documents')} WHERE doc_id = :doc_id`,
            { doc_id: docId }
          );
          const path = parseList(rows[0]?.pages)[page];
          if (!path) return void response.status(404).json({ error: 'That page has not been rendered.' });
          const download = await kit.files('files').asUser(request).download(path);
          response.setHeader('Content-Type', /\.png$/i.test(path) ? 'image/png' : 'image/jpeg');
          response.setHeader('Cache-Control', 'private, max-age=3600');
          response.setHeader('X-Content-Type-Options', 'nosniff');
          const body = download.contents;
          if (body && typeof (body as ReadableStream).getReader === 'function') {
            Readable.fromWeb(body as import('node:stream/web').ReadableStream).pipe(response);
          } else if (body instanceof Readable) {
            body.pipe(response);
          } else {
            response.status(502).json({ error: 'The page image could not be read.' });
          }
        } catch (error) {
          fail(response, error, 'Load the page');
        }
      });

      app.post('/api/ingest', async (_request, response) => {
        if (!kit.jobs) return void response.status(503).json({ error: 'Ingestion is not configured for this app.' });
        try {
          const result = (await kit.jobs('default').runNow({})) as { run_id?: number; data?: { run_id?: number } };
          response.status(202).json({ runId: result.run_id ?? result.data?.run_id ?? null });
        } catch (error) {
          fail(response, error, 'Start ingestion');
        }
      });

      app.get('/api/ingest/:runId', async (request, response) => {
        if (!kit.jobs) return void response.status(503).json({ error: 'Ingestion is not configured for this app.' });
        const runId = Number(request.params.runId);
        if (!Number.isInteger(runId)) return void response.status(400).json({ error: 'Unknown run' });
        try {
          const run = (await kit.jobs('default').getRun(runId)) as {
            state?: { life_cycle_state?: string; result_state?: string };
            data?: {
              state?: { life_cycle_state?: string; result_state?: string };
              tasks?: { task_key?: string; state?: { life_cycle_state?: string; result_state?: string } }[];
            };
            tasks?: { task_key?: string; state?: { life_cycle_state?: string; result_state?: string } }[];
          };
          const data = run.data ?? run;
          const tasks = (data.tasks ?? []).map((t) => ({
            key: t.task_key,
            state: t.state?.result_state ?? t.state?.life_cycle_state,
          }));
          response.json({
            lifecycle: data.state?.life_cycle_state ?? null,
            result: data.state?.result_state ?? null,
            tasks,
          });
        } catch (error) {
          fail(response, error, 'Check ingestion');
        }
      });
    });
  },
});
