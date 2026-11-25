import { randomBytes } from 'node:crypto';
import { Readable } from 'node:stream';
import type { Application, Request, Response } from 'express';
import { getExecutionContext } from '@databricks/appkit';

/** Workspace client for the current scope: the signed-in user inside asUser(), otherwise the app service principal. */
const scopedClient = () => getExecutionContext().client;
import { z } from 'zod';
import { fqn, runSql, type Row } from './sql';

/**
 * Workflow routes: the places where a person acts on the compliance record.
 *
 * - Every decision is an INSERT into an append-only Delta table (`mapping_reviews`,
 *   `report_status_events`), executed on behalf of the signed-in user. The next pipeline run turns
 *   these rows into hash-chained audit events. Nothing here updates or deletes.
 * - Jobs (generate, reproduce, verify) run as the app service principal, with the requesting user
 *   passed as `requested_by` so the report and audit trail attribute the request correctly.
 */

interface JobHandle {
  runNow(
    params?: Record<string, unknown>
  ): Promise<{ ok: true; data: { run_id?: number } } | { ok: false; status: number; message: string }>;
  getRun(runId: number): Promise<{ ok: true; data: RunLike } | { ok: false; status: number; message: string }>;
  listRuns(options?: {
    limit?: number;
  }): Promise<{ ok: true; data: RunLike[] } | { ok: false; status: number; message: string }>;
}

interface RunLike {
  run_id?: number;
  start_time?: number;
  end_time?: number;
  run_page_url?: string;
  state?: { life_cycle_state?: string; result_state?: string; state_message?: string };
  status?: { state?: string; termination_details?: { code?: string; message?: string } };
  job_parameters?: { name?: string; value?: string; default?: string }[];
}

export interface WorkflowAppKit {
  server: { extend(fn: (app: Application) => void): void };
  jobs?: (key: string) => JobHandle;
  asUser(req: Request): { run<T>(fn: () => Promise<T>): Promise<T> };
}

class HttpError extends Error {
  constructor(
    public statusCode: number,
    message: string
  ) {
    super(message);
  }
}

const REPORT_ID = /^REP-[A-Z0-9-]{1,40}$/;
const EVIDENCE_ID = /^EV-[A-Z0-9-]{1,40}$/;
const REPORT_FILES: Record<string, string> = {
  'report.html': 'text/html; charset=utf-8',
  'findings.json': 'application/json',
  'evidence_manifest.csv': 'text/csv; charset=utf-8',
};

/** Report lifecycle. Approval and issue are human steps; the pipeline only ever creates drafts. */
const TRANSITIONS: Record<string, string[]> = {
  Draft: ['Ready for approval'],
  'Ready for approval': ['Issued', 'Draft'],
  Issued: [],
};

let devIdentity: Promise<string> | null = null;

/** The signed-in user. Behind the Apps proxy this is the forwarded email; locally, the CLI user. */
export async function currentUser(req: Request): Promise<string> {
  const forwarded = req.header('x-forwarded-email') ?? req.header('x-forwarded-preferred-username');
  if (forwarded) return forwarded;
  if (process.env.NODE_ENV === 'development') {
    devIdentity ??= scopedClient()
      .currentUser.me()
      .then((me: { userName?: string }) => me.userName ?? 'local-developer')
      .catch(() => 'local-developer');
    return devIdentity;
  }
  throw new HttpError(401, 'Sign in through Databricks Apps to use this workspace.');
}

function handle(fn: (req: Request, res: Response) => Promise<void>) {
  return async (req: Request, res: Response) => {
    try {
      await fn(req, res);
    } catch (error) {
      const status = (error as { statusCode?: number }).statusCode ?? 500;
      const message = error instanceof Error ? error.message : 'Unexpected error';
      if (status >= 500) console.error('[workflow]', req.method, req.path, error);
      if (!res.headersSent) {
        res.status(status).json({
          error:
            status === 403
              ? req.method === 'GET'
                ? `You do not have access to this compliance record. Ask the data owner for SELECT on it. (${message})`
                : `You do not have permission to record this decision. Ask the data owner for MODIFY on the target table. (${message})`
              : status >= 500
                ? `The request could not be completed: ${message}`
                : message,
        });
      }
    }
  };
}

/**
 * Workflow tables (mapping_reviews, report_status_events, report_findings, report_reproductions)
 * are read as the signed-in user, the same identity that records decisions in them. This keeps the
 * app under the 20-resource limit and means the record is only visible to people granted it.
 */
function asReader<T>(appkit: WorkflowAppKit, req: Request, fn: () => Promise<T>): Promise<T> {
  return appkit.asUser(req).run(fn);
}

function jobOrThrow(appkit: WorkflowAppKit, key: 'report' | 'verify') {
  const configured = key === 'report' ? process.env.DATABRICKS_JOB_REPORT : process.env.DATABRICKS_JOB_VERIFY;
  if (!configured || !appkit.jobs) throw new HttpError(503, `The ${key} job is not bound to this app.`);
  return appkit.jobs(key);
}

function summariseRun(run: RunLike) {
  const lifecycle = run.status?.state ?? run.state?.life_cycle_state ?? 'PENDING';
  const result = run.state?.result_state ?? run.status?.termination_details?.code ?? null;
  const params: Record<string, string> = {};
  for (const p of run.job_parameters ?? []) if (p.name) params[p.name] = p.value ?? p.default ?? '';
  return {
    runId: run.run_id,
    lifecycle,
    result,
    message: run.state?.state_message || run.status?.termination_details?.message || null,
    startedAt: run.start_time ? new Date(run.start_time).toISOString() : null,
    endedAt: run.end_time ? new Date(run.end_time).toISOString() : null,
    url: run.run_page_url ?? null,
    params,
  };
}

async function triggerJob(job: JobHandle, parameters: Record<string, string>) {
  const result = await job.runNow({ job_parameters: parameters });
  if (!result.ok) throw new HttpError(result.status, result.message);
  return result.data.run_id;
}

const ReviewBody = z.object({
  decision: z.enum(['confirm', 'reject']),
  comment: z.string().trim().max(500).optional(),
});

const StatusBody = z.object({
  status: z.enum(['Ready for approval', 'Issued', 'Draft']),
  comment: z.string().trim().max(500).optional(),
});

const GenerateBody = z
  .object({
    report_type: z.enum(['monthly_summary', 'gate_review']),
    gate_id: z
      .string()
      .regex(/^GATE-\d{1,2}$/)
      .optional(),
    as_of_date: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/)
      .optional(),
  })
  .refine((body) => body.report_type !== 'gate_review' || Boolean(body.gate_id), {
    message: 'Choose a review gate for a gate review report.',
  })
  .refine((body) => !body.as_of_date || body.as_of_date <= new Date().toISOString().slice(0, 10), {
    message: 'The evidence date cannot be in the future.',
  });

function parse<T>(schema: z.ZodType<T>, body: unknown): T {
  const parsed = schema.safeParse(body ?? {});
  if (!parsed.success) throw new HttpError(400, parsed.error.issues.map((issue) => issue.message).join(' '));
  return parsed.data;
}

function param(req: Request, name: string, pattern: RegExp, label: string) {
  const value = String(req.params[name] ?? '');
  if (!pattern.test(value)) throw new HttpError(400, `Invalid ${label}.`);
  return value;
}

export function setupWorkflowRoutes(appkit: WorkflowAppKit) {
  appkit.server.extend((app) => {
    app.get(
      '/api/config',
      handle(async (req, res) => {
        res.json({
          catalog: process.env.DATABRICKS_CATALOG ?? null,
          schema: process.env.DATABRICKS_SCHEMA ?? null,
          user: await currentUser(req).catch(() => null),
          capabilities: {
            generateReports: Boolean(process.env.DATABRICKS_JOB_REPORT),
            verifyChain: Boolean(process.env.DATABRICKS_JOB_VERIFY),
          },
        });
      })
    );

    // ---------------------------------------------------------------- Evidence decisions

    app.get(
      '/api/evidence/decisions',
      handle(async (req, res) => {
        const [[overview], rows] = await Promise.all([
          runSql(`SELECT max(refreshed_at) AS refreshed_at FROM ${fqn('compliance_overview')}`),
          asReader(appkit, req, () =>
            runSql(
              `SELECT review_id, evidence_id, decision, artefact_type, reviewer, reviewed_at, comment
               FROM ${fqn('mapping_reviews')}
               WHERE channel = 'app' AND reviewed_at > current_timestamp() - INTERVAL 90 DAYS
               ORDER BY reviewed_at DESC
               LIMIT 200`
            )
          ),
        ]);
        const refreshed = overview?.refreshed_at ? Date.parse(overview.refreshed_at) : 0;
        res.json({
          decisions: rows.map((row) => ({ ...row, pending: Date.parse(row.reviewed_at ?? '') > refreshed })),
        });
      })
    );

    app.post(
      '/api/evidence/:evidenceId/review',
      handle(async (req, res) => {
        const evidenceId = param(req, 'evidenceId', EVIDENCE_ID, 'evidence ID');
        const body = parse(ReviewBody, req.body);
        const user = await currentUser(req);
        const [item] = await runSql(
          `SELECT evidence_id, mapping_state, artefact_type FROM ${fqn('evidence_inbox')} WHERE evidence_id = :id`,
          [{ name: 'id', value: evidenceId }]
        );
        if (!item) throw new HttpError(404, `${evidenceId} is not in the evidence inbox.`);
        if (body.decision === 'confirm' && !item.artefact_type)
          throw new HttpError(409, `${evidenceId} has no suggested artefact type to confirm.`);
        if (body.decision === 'reject' && !body.comment)
          throw new HttpError(400, 'Give a reason when rejecting evidence. It is kept in the audit trail.');
        const reviewId = `REV-${randomBytes(5).toString('hex').toUpperCase()}`;
        await appkit.asUser(req).run(() =>
          runSql(
            `INSERT INTO ${fqn('mapping_reviews')}
               (review_id, evidence_id, decision, artefact_type, reviewer, reviewed_at, comment, channel)
             VALUES (:review_id, :evidence_id, :decision, :artefact_type, :reviewer, current_timestamp(), :comment, 'app')`,
            [
              { name: 'review_id', value: reviewId },
              { name: 'evidence_id', value: evidenceId },
              { name: 'decision', value: body.decision },
              { name: 'artefact_type', value: body.decision === 'confirm' ? item.artefact_type : null },
              { name: 'reviewer', value: user },
              {
                name: 'comment',
                value: body.comment || (body.decision === 'confirm' ? 'Confirmed against evidence requirement' : null),
              },
            ]
          )
        );
        res.status(201).json({ reviewId, evidenceId, decision: body.decision, reviewer: user });
      })
    );

    // ---------------------------------------------------------------- Reports

    app.get(
      '/api/reports/workflow',
      handle(async (req, res) => {
        const [events, reproductions] = await asReader(appkit, req, () =>
          Promise.all([
            runSql(
              `SELECT report_id, status, changed_by, changed_at, comment FROM ${fqn('report_status_events')}
             ORDER BY report_id, changed_at`
            ),
            runSql(
              `SELECT reproduction_id, report_id, reproduced_at, matches, reproduced_by, reproduced_digest
             FROM ${fqn('report_reproductions')} ORDER BY reproduced_at DESC`
            ),
          ])
        );
        const byReport: Record<string, { status: string; history: Row[]; reproductions: Row[] }> = {};
        for (const event of events) {
          const entry = (byReport[event.report_id!] ??= { status: 'Draft', history: [], reproductions: [] });
          entry.history.push(event);
          entry.status = event.status ?? entry.status;
        }
        for (const reproduction of reproductions) {
          (byReport[reproduction.report_id!] ??= {
            status: 'Draft',
            history: [],
            reproductions: [],
          }).reproductions.push(reproduction);
        }
        res.json({ reports: byReport });
      })
    );

    app.get(
      '/api/reports/:reportId/findings',
      handle(async (req, res) => {
        const reportId = param(req, 'reportId', REPORT_ID, 'report ID');
        const findings = await asReader(appkit, req, () =>
          runSql(
            `SELECT obligation_id, obligation_version, obligation_title, gate_id, owner_role, requirement_id, artefact_type,
                  status, gap_reason, evidence_id, artefact_version, checksum, expires_on, days_to_expiry
           FROM ${fqn('report_findings')} WHERE report_id = :id
           ORDER BY CASE status WHEN 'Gap' THEN 1 WHEN 'Expiring' THEN 2 ELSE 3 END, obligation_id, requirement_id`,
            [{ name: 'id', value: reportId }]
          )
        );
        res.json({ findings });
      })
    );

    app.post(
      '/api/reports/:reportId/status',
      handle(async (req, res) => {
        const reportId = param(req, 'reportId', REPORT_ID, 'report ID');
        const body = parse(StatusBody, req.body);
        const user = await currentUser(req);
        const history = await asReader(appkit, req, () =>
          runSql(
            `SELECT status, changed_by FROM ${fqn('report_status_events')} WHERE report_id = :id ORDER BY changed_at DESC`,
            [{ name: 'id', value: reportId }]
          )
        );
        if (!history.length) throw new HttpError(404, `${reportId} has no status history.`);
        const current = history[0].status ?? 'Draft';
        if (!TRANSITIONS[current]?.includes(body.status))
          throw new HttpError(409, `${reportId} is ${current}; it cannot move to ${body.status}.`);
        if (body.status === 'Draft' && !body.comment)
          throw new HttpError(400, 'Say why the report is being returned so the preparer can act on it.');
        if (body.status === 'Issued') {
          const submitter = history.find((event) => event.status === 'Ready for approval')?.changed_by;
          if (submitter && submitter.toLowerCase() === user.toLowerCase())
            throw new HttpError(
              409,
              'You submitted this report for approval. Another person must approve and issue it (separation of duties).'
            );
        }
        await appkit.asUser(req).run(() =>
          runSql(
            `INSERT INTO ${fqn('report_status_events')} (report_id, status, changed_by, changed_at, comment)
             VALUES (:report_id, :status, :changed_by, current_timestamp(), :comment)`,
            [
              { name: 'report_id', value: reportId },
              { name: 'status', value: body.status },
              { name: 'changed_by', value: user },
              { name: 'comment', value: body.comment || null },
            ]
          )
        );
        res.status(201).json({ reportId, status: body.status, changedBy: user });
      })
    );

    app.post(
      '/api/reports/generate',
      handle(async (req, res) => {
        const body = parse(GenerateBody, req.body);
        const user = await currentUser(req);
        const runId = await triggerJob(jobOrThrow(appkit, 'report'), {
          report_type: body.report_type,
          gate_id: body.report_type === 'gate_review' ? (body.gate_id ?? '') : '',
          as_of_date: body.as_of_date ?? '',
          reproduce_report_id: '',
          requested_by: user,
        });
        res.status(202).json({ runId });
      })
    );

    app.post(
      '/api/reports/:reportId/reproduce',
      handle(async (req, res) => {
        const reportId = param(req, 'reportId', REPORT_ID, 'report ID');
        const user = await currentUser(req);
        const runId = await triggerJob(jobOrThrow(appkit, 'report'), {
          report_type: 'monthly_summary',
          gate_id: '',
          as_of_date: '',
          reproduce_report_id: reportId,
          requested_by: user,
        });
        res.status(202).json({ runId });
      })
    );

    app.get(
      '/api/reports/:reportId/files/:fileName',
      handle(async (req, res) => {
        const reportId = param(req, 'reportId', REPORT_ID, 'report ID');
        const fileName = String(req.params.fileName);
        const contentType = REPORT_FILES[fileName];
        if (!contentType) throw new HttpError(404, 'Unknown report file.');
        const [report] = await runSql(`SELECT output_path FROM ${fqn('compliance_reports')} WHERE report_id = :id`, [
          { name: 'id', value: reportId },
        ]);
        const base = report?.output_path;
        if (!base || !base.startsWith('/Volumes/')) throw new HttpError(404, `${reportId} has no output package.`);
        const download = await scopedClient().files.download({ file_path: `${base.replace(/\/$/, '')}/${fileName}` });
        const contents = download.contents as ReadableStream | undefined;
        if (!contents) throw new HttpError(404, `${fileName} is missing from the ${reportId} package.`);
        res.setHeader('Content-Type', contentType);
        res.setHeader('X-Content-Type-Options', 'nosniff');
        if (fileName === 'report.html') {
          // View inline, but sandboxed: no scripts, opaque origin.
          res.setHeader(
            'Content-Security-Policy',
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
          );
          res.setHeader('Content-Disposition', `inline; filename="${reportId}-report.html"`);
        } else {
          res.setHeader('Content-Disposition', `attachment; filename="${reportId}-${fileName}"`);
        }
        Readable.fromWeb(contents as import('node:stream/web').ReadableStream).pipe(res);
      })
    );

    // ---------------------------------------------------------------- Audit

    app.post(
      '/api/audit/verify',
      handle(async (req, res) => {
        const user = await currentUser(req);
        const runId = await triggerJob(jobOrThrow(appkit, 'verify'), { requested_by: user });
        res.status(202).json({ runId });
      })
    );

    app.get(
      '/api/audit/verification',
      handle(async (_req, res) => {
        const [latest] = await runSql(
          `SELECT v.verification_id, v.verified_at, v.events_checked, v.head_seq, v.head_hash, v.status,
                  v.first_broken_seq, v.detail, e.max_seq AS latest_seq
           FROM (SELECT * FROM ${fqn('audit_chain_verifications')} ORDER BY verified_at DESC LIMIT 1) v
           CROSS JOIN (SELECT max(event_seq) AS max_seq FROM ${fqn('audit_events')}) e`
        );
        res.json({ verification: latest ?? null });
      })
    );

    // ---------------------------------------------------------------- Job runs

    app.get(
      '/api/runs/:job',
      handle(async (req, res) => {
        const key = req.params.job === 'verify' ? 'verify' : 'report';
        const result = await jobOrThrow(appkit, key).listRuns({ limit: 10 });
        if (!result.ok) throw new HttpError(result.status, result.message);
        res.json({ runs: (result.data ?? []).map(summariseRun) });
      })
    );

    app.get(
      '/api/runs/:job/:runId',
      handle(async (req, res) => {
        const key = req.params.job === 'verify' ? 'verify' : 'report';
        const runId = Number.parseInt(String(req.params.runId), 10);
        if (!Number.isFinite(runId)) throw new HttpError(400, 'Invalid run ID.');
        const result = await jobOrThrow(appkit, key).getRun(runId);
        if (!result.ok) throw new HttpError(result.status, result.message);
        res.json({ run: summariseRun(result.data) });
      })
    );
  });
}
