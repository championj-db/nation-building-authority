import { randomUUID } from 'node:crypto';
import type { Request, Response } from 'express';
import { createApp, analytics, genie, server, sql } from '@databricks/appkit';
import { WorkspaceClient } from '@databricks/sdk-experimental';

// Reads run on behalf of the signed-in user (.obo.sql queries and asUser below). Writes are
// append-only workflow records made by the app service principal, with the user recorded as the actor.
// `catalog`.`schema` of the use case tables: PORTFOLIO_SCHEMA locally, or derived from the full name of a
// table bound as an app resource (PORTFOLIO_TABLE, app.yaml valueFrom). Same rule as scripts/render-queries.mjs.
function resolveSchema(): string {
  const env = process.env;
  const parts = (env.PORTFOLIO_SCHEMA ? env.PORTFOLIO_SCHEMA.split('.') : (env.PORTFOLIO_TABLE ?? '').split('.').slice(0, -1))
    .map((p) => p.trim().replace(/^`|`$/g, ''));
  if (parts.length !== 2 || parts.some((p) => !/^[A-Za-z0-9_-]+$/.test(p))) {
    throw new Error('Set PORTFOLIO_SCHEMA=<catalog>.<schema> or bind a table resource to PORTFOLIO_TABLE.');
  }
  return parts.map((p) => `\`${p}\``).join('.');
}
const SCHEMA = resolveSchema();
const WAREHOUSE_ID = process.env.DATABRICKS_WAREHOUSE_ID ?? '';
const FORECAST_JOB_ID = Number(process.env.DATABRICKS_JOB_FORECAST ?? 0);
const LLM_ENDPOINT = process.env.DATABRICKS_SERVING_ENDPOINT_NAME ?? '';

const LEVER_TYPES = ['defer_months', 'accelerate_months', 'escalation_delta_pp', 'capacity_uplift_pct', 'scope_change_aud_m', 'exclude_project'];
const TARGET_TYPES = ['project', 'program', 'sector', 'capacity_category', 'portfolio'];
const SCENARIO_EVENTS = ['Submitted', 'Returned', 'Endorsed'];
const SUBMISSION_STATUSES = ['Submitted', 'Returned', 'Approved', 'Locked'];
const ASSURANCE_ACTIONS = ['Attested', 'Comment', 'Action raised', 'Closed'];
const PERIODS = ['YTD', 'CURRENT_FY', 'HORIZON'];

const client = new WorkspaceClient({});

type Param = { name: string; value: string | number | null | undefined; type?: 'STRING' | 'DOUBLE' | 'INT' | 'BIGINT' };

async function execute(statement: string, params: Param[] = []): Promise<void> {
  const response = await client.statementExecution.executeStatement({
    warehouse_id: WAREHOUSE_ID,
    statement,
    wait_timeout: '30s',
    on_wait_timeout: 'CANCEL',
    parameters: params.map((p) => ({
      name: p.name,
      value: p.value === null || p.value === undefined ? undefined : String(p.value),
      type: p.type ?? 'STRING',
    })),
  });
  const state = response.status?.state;
  if (state !== 'SUCCEEDED') {
    throw new Error(response.status?.error?.message ?? `Statement ${state ?? 'did not complete'}`);
  }
}

function actor(req: Request): string {
  return req.header('x-forwarded-email') ?? req.header('x-forwarded-preferred-username') ?? req.header('x-forwarded-user') ?? 'unknown user';
}

function text(value: unknown, max = 2000): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : null;
}

function finite(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function fail(res: Response, status: number, message: string) {
  res.status(status).json({ error: message });
}

async function triggerForecast(): Promise<number | null> {
  if (!FORECAST_JOB_ID) return null;
  const run = await client.jobs.runNow({ job_id: FORECAST_JOB_ID, job_parameters: { run_type: 'app_scenario' } });
  return run.run_id ?? null;
}

type Rows = Array<Record<string, unknown>>;

function rowsOf(result: unknown): Rows {
  if (Array.isArray(result)) return result as Rows;
  const r = result as { data?: unknown; rows?: unknown } | null;
  if (r && Array.isArray(r.data)) return r.data as Rows;
  if (r && Array.isArray(r.rows)) return r.rows as Rows;
  return [];
}

async function draftWithLlm(system: string, user: string, maxTokens: number): Promise<string> {
  if (!LLM_ENDPOINT) throw new Error('No serving endpoint is configured for drafting.');
  // Raw invocation: reasoning models return content as typed parts (reasoning, then text), which the
  // typed SDK response flattens lossily.
  const response = (await client.apiClient.request({
    path: `/serving-endpoints/${encodeURIComponent(LLM_ENDPOINT)}/invocations`,
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    raw: false,
    payload: { max_tokens: maxTokens, messages: [{ role: 'system', content: system }, { role: 'user', content: user }] },
  })) as { choices?: Array<{ message?: { content?: unknown } }> };
  const content = response.choices?.[0]?.message?.content;
  if (typeof content === 'string') return content.trim();
  if (Array.isArray(content)) {
    const text = (content as Array<{ type?: string; text?: string }>)
      .filter((part) => part.type === 'text' || (part.type === undefined && typeof part.text === 'string'))
      .map((part) => part.text ?? '')
      .join('')
      .trim();
    if (text) return text;
  }
  throw new Error('The drafting model returned no text.');
}

const DRAFT_RULES = `Rules:
- Use only the figures in the JSON provided. Never invent numbers, projects, causes or dates.
- Quote amounts in Australian dollars as $X.Xbn or $XXXm, matching the source values.
- Financial years end on 30 June and are labelled by the year they end (FY27 = 2026-27).
- Where the data does not explain something, say so plainly ("not explained by recorded drivers").
- All figures are synthetic working figures; do not describe them as published or final.`;

createApp({
  plugins: [
    analytics(),
    genie({
      spaces: {
        default: process.env.DATABRICKS_GENIE_SPACE_ID ?? '',
      },
    }),
    server(),
  ],
  // Gold tables change when a forecast run completes; the client also passes a data_version
  // parameter so a completed run or a new workflow record is never hidden behind a cached result.
  cache: { enabled: true, ttl: 120 },
  onPluginsReady(appkit) {
    const asUserQuery = async (req: Request, statement: string, params: Record<string, ReturnType<typeof sql.string>>) =>
      rowsOf(await appkit.asUser(req).analytics.query(statement, params));

    appkit.server.extend((app) => {
      app.get('/api/whoami', (request, response) => {
        response.json({
          email: request.header('x-forwarded-email') ?? null,
          user: request.header('x-forwarded-user') ?? null,
          forecastJobConfigured: Boolean(FORECAST_JOB_ID),
          draftingModel: LLM_ENDPOINT || null,
        });
      });

      // ---- Scenarios --------------------------------------------------------------------------
      app.post('/api/scenarios', async (req, res) => {
        const body = req.body ?? {};
        const name = text(body.name, 120);
        const purpose = text(body.purpose, 400);
        const description = text(body.description, 1000);
        const base = text(body.base_scenario_id, 40) ?? 'BASE';
        const method = body.method === 'auto_sequence' ? 'auto_sequence' : 'levers';
        const existingId = text(body.scenario_id, 40);
        const levers: Array<Record<string, unknown>> = Array.isArray(body.levers) ? body.levers.slice(0, 40) : [];
        if (!name) return fail(res, 400, 'A scenario name is required.');
        if (!/^[A-Z0-9_-]+$/.test(base)) return fail(res, 400, 'Invalid base scenario.');
        for (const lever of levers) {
          if (!LEVER_TYPES.includes(String(lever.lever_type))) return fail(res, 400, `Unsupported lever ${String(lever.lever_type)}.`);
          if (!TARGET_TYPES.includes(String(lever.target_type))) return fail(res, 400, `Unsupported target ${String(lever.target_type)}.`);
          if (finite(lever.value) === null) return fail(res, 400, 'Every lever needs a numeric value.');
        }
        if (method === 'levers' && levers.length === 0) return fail(res, 400, 'Add at least one lever, or use capacity-aware sequencing.');
        try {
          let scenarioId = existingId;
          let version = 1;
          if (existingId) {
            if (!/^APP-[A-Z0-9]+$/.test(existingId)) return fail(res, 400, 'Only app-created scenarios can be revised here.');
            const rows = await asUserQuery(req, `SELECT COALESCE(MAX(version), 0) AS v FROM ${SCHEMA}.scenario_definitions WHERE scenario_id = :id`, { id: sql.string(existingId) });
            version = Number(rows[0]?.v ?? 0) + 1;
          } else {
            scenarioId = `APP-${randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()}`;
          }
          const who = actor(req);
          await execute(
            `INSERT INTO ${SCHEMA}.scenario_definitions
               (scenario_id, scenario_name, version, base_scenario_id, method, status, decision_purpose, description, created_by, created_at, source)
             VALUES (:id, :name, :version, :base, :method, 'Draft', :purpose, :description, :actor, current_timestamp(), 'app')`,
            [
              { name: 'id', value: scenarioId },
              { name: 'name', value: name },
              { name: 'version', value: version, type: 'INT' },
              { name: 'base', value: base },
              { name: 'method', value: method },
              { name: 'purpose', value: purpose },
              { name: 'description', value: description },
              { name: 'actor', value: who },
            ],
          );
          let index = 0;
          for (const lever of levers) {
            index += 1;
            await execute(
              `INSERT INTO ${SCHEMA}.scenario_levers
                 (lever_id, scenario_id, scenario_version, lever_type, target_type, target_id, value, rationale, assumption_id, created_by, created_at, source)
               VALUES (:lever_id, :id, :version, :lever_type, :target_type, :target_id, :value, :rationale, NULL, :actor, current_timestamp(), 'app')`,
              [
                { name: 'lever_id', value: `LV-${scenarioId}-V${version}-${String(index).padStart(2, '0')}` },
                { name: 'id', value: scenarioId },
                { name: 'version', value: version, type: 'INT' },
                { name: 'lever_type', value: String(lever.lever_type) },
                { name: 'target_type', value: String(lever.target_type) },
                { name: 'target_id', value: lever.target_type === 'portfolio' ? null : text(lever.target_id, 60) },
                { name: 'value', value: finite(lever.value), type: 'DOUBLE' },
                { name: 'rationale', value: text(lever.rationale, 400) },
                { name: 'actor', value: who },
              ],
            );
          }
          const runId = await triggerForecast();
          await execute(
            `INSERT INTO ${SCHEMA}.scenario_events VALUES (:event_id, :id, :version, :event, :note, :run_id, :actor, current_timestamp())`,
            [
              { name: 'event_id', value: randomUUID() },
              { name: 'id', value: scenarioId },
              { name: 'version', value: version, type: 'INT' },
              { name: 'event', value: version === 1 ? 'Created' : 'Revised' },
              { name: 'note', value: runId ? 'Recompute requested' : 'Saved; forecast job not configured' },
              { name: 'run_id', value: runId, type: 'BIGINT' },
              { name: 'actor', value: who },
            ],
          );
          res.json({ scenario_id: scenarioId, version, run_id: runId });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Scenario could not be saved.');
        }
      });

      app.post('/api/scenarios/:id/events', async (req, res) => {
        const event = String(req.body?.event ?? '');
        const version = finite(req.body?.version);
        if (!SCENARIO_EVENTS.includes(event)) return fail(res, 400, 'Unsupported scenario action.');
        if (!/^[A-Z0-9_-]+$/.test(req.params.id) || version === null) return fail(res, 400, 'Invalid scenario.');
        try {
          await execute(
            `INSERT INTO ${SCHEMA}.scenario_events VALUES (:event_id, :id, :version, :event, :note, NULL, :actor, current_timestamp())`,
            [
              { name: 'event_id', value: randomUUID() },
              { name: 'id', value: req.params.id },
              { name: 'version', value: version, type: 'INT' },
              { name: 'event', value: event },
              { name: 'note', value: text(req.body?.note, 1000) },
              { name: 'actor', value: actor(req) },
            ],
          );
          res.json({ ok: true });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Scenario action failed.');
        }
      });

      // ---- Forecast runs ----------------------------------------------------------------------
      app.post('/api/runs', async (req, res) => {
        try {
          const runId = await triggerForecast();
          if (!runId) return fail(res, 503, 'The forecast job is not configured for this app.');
          res.json({ run_id: runId, actor: actor(req) });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Forecast run could not start.');
        }
      });

      app.get('/api/runs/:runId', async (req, res) => {
        const runId = Number(req.params.runId);
        if (!Number.isFinite(runId)) return fail(res, 400, 'Invalid run.');
        try {
          const run = await client.jobs.getRun({ run_id: runId });
          const tasks = (run.tasks ?? []).map((task) => ({
            task_key: task.task_key,
            state: task.state?.life_cycle_state,
            result: task.state?.result_state,
          }));
          res.json({
            run_id: runId,
            life_cycle_state: run.state?.life_cycle_state,
            result_state: run.state?.result_state,
            state_message: run.state?.state_message,
            start_time: run.start_time,
            end_time: run.end_time,
            run_page_url: run.run_page_url,
            tasks,
          });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Run status unavailable.');
        }
      });

      // ---- Monthly forecast cycle ----------------------------------------------------------
      app.post('/api/submissions', async (req, res) => {
        const body = req.body ?? {};
        const cycle = text(body.cycle, 7);
        const programId = text(body.program_id, 20);
        const status = String(body.status ?? '');
        const role = body.role === 'Portfolio office' ? 'Portfolio office' : 'Program office';
        if (!cycle || !/^\d{4}-\d{2}$/.test(cycle) || !programId) return fail(res, 400, 'Cycle and program are required.');
        if (!SUBMISSION_STATUSES.includes(status)) return fail(res, 400, 'Unsupported submission status.');
        if (role === 'Program office' && status !== 'Submitted') return fail(res, 403, 'Program offices can only submit forecasts.');
        if (status === 'Returned' && !text(body.commentary)) return fail(res, 400, 'Say why the forecast is being returned.');
        try {
          await execute(
            `INSERT INTO ${SCHEMA}.forecast_submissions VALUES (:id, :cycle, :program, :status, :forecast, :commentary, :actor, :role, current_timestamp())`,
            [
              { name: 'id', value: randomUUID() },
              { name: 'cycle', value: cycle },
              { name: 'program', value: programId },
              { name: 'status', value: status },
              { name: 'forecast', value: finite(body.forecast_aud_m), type: 'DOUBLE' },
              { name: 'commentary', value: text(body.commentary) },
              { name: 'actor', value: actor(req) },
              { name: 'role', value: role },
            ],
          );
          res.json({ ok: true });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Submission failed.');
        }
      });

      // ---- Variance commentary --------------------------------------------------------------
      app.post('/api/commentary', async (req, res) => {
        const body = req.body ?? {};
        const period = String(body.period ?? '');
        const level = ['portfolio', 'program', 'project'].includes(body.scope_level) ? String(body.scope_level) : null;
        const scopeId = text(body.scope_id, 40);
        const commentary = text(body.commentary, 4000);
        if (!PERIODS.includes(period) || !level || !scopeId) return fail(res, 400, 'Period and scope are required.');
        if (!commentary) return fail(res, 400, 'Commentary is required.');
        try {
          await execute(
            `INSERT INTO ${SCHEMA}.variance_commentary VALUES (:id, :period, :level, :scope, :reason, :amount, :commentary, :source, :actor, current_timestamp())`,
            [
              { name: 'id', value: randomUUID() },
              { name: 'period', value: period },
              { name: 'level', value: level },
              { name: 'scope', value: scopeId },
              { name: 'reason', value: text(body.reason_code, 80) },
              { name: 'amount', value: finite(body.amount_aud_m), type: 'DOUBLE' },
              { name: 'commentary', value: commentary },
              { name: 'source', value: body.source === 'ai_draft' ? 'ai_draft' : 'user' },
              { name: 'actor', value: actor(req) },
            ],
          );
          res.json({ ok: true });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Commentary could not be saved.');
        }
      });

      // ---- Assurance attestations and actions ---------------------------------------------
      app.post('/api/assurance-actions', async (req, res) => {
        const recordId = text(req.body?.record_id, 60);
        const action = String(req.body?.action ?? '');
        if (!recordId || !ASSURANCE_ACTIONS.includes(action)) return fail(res, 400, 'Record and action are required.');
        if (action !== 'Attested' && !text(req.body?.comment)) return fail(res, 400, 'Add a comment for this action.');
        try {
          await execute(
            `INSERT INTO ${SCHEMA}.assurance_actions VALUES (:id, :record, :action, :comment, :actor, current_timestamp())`,
            [
              { name: 'id', value: randomUUID() },
              { name: 'record', value: recordId },
              { name: 'action', value: action },
              { name: 'comment', value: text(req.body?.comment) },
              { name: 'actor', value: actor(req) },
            ],
          );
          res.json({ ok: true });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Action could not be saved.');
        }
      });

      // ---- AI drafting: grounded on rows the signed-in user can read --------------------------
      app.post('/api/ai/variance-draft', async (req, res) => {
        const period = PERIODS.includes(req.body?.period) ? String(req.body.period) : 'CURRENT_FY';
        const level = req.body?.scope_level === 'program' ? 'program' : req.body?.scope_level === 'project' ? 'project' : 'portfolio';
        const scopeId = text(req.body?.scope_id, 40) ?? 'PORTFOLIO';
        try {
          const filter = level === 'project' ? 'project_id = :scope' : level === 'program' ? 'program_id = :scope' : ':scope IS NOT NULL';
          const projects = await asUserQuery(
            req,
            `SELECT project_name, program_name, ROUND(plan_aud_m, 1) AS plan_aud_m, ROUND(forecast_aud_m, 1) AS forecast_aud_m,
                    ROUND(variance_aud_m, 1) AS variance_aud_m, ROUND(escalation_aud_m, 1) AS escalation_aud_m,
                    ROUND(schedule_shift_aud_m, 1) AS schedule_shift_aud_m, ROUND(scope_change_aud_m, 1) AS scope_change_aud_m,
                    ROUND(packaging_aud_m, 1) AS packaging_aud_m, ROUND(unexplained_aud_m, 1) AS unexplained_aud_m,
                    primary_driver, slip_months, gateway_rating, outside_tolerance, attention_reasons
             FROM ${SCHEMA}.variance_project WHERE period = :period AND ${filter}
             ORDER BY ABS(variance_aud_m) DESC LIMIT 12`,
            { period: sql.string(period), scope: sql.string(scopeId) },
          );
          const changes = await asUserQuery(
            req,
            `SELECT c.project_id, c.change_type, c.status, ROUND(c.cost_impact_aud_m, 1) AS cost_impact_aud_m, c.description
             FROM ${SCHEMA}.silver_change_register c JOIN ${SCHEMA}.dim_project p USING (project_id)
             WHERE c.status = 'Approved' AND ${level === 'project' ? 'p.project_id = :scope' : level === 'program' ? 'p.program_id = :scope' : ':scope IS NOT NULL'}
             ORDER BY ABS(c.cost_impact_aud_m) DESC LIMIT 10`,
            { scope: sql.string(scopeId) },
          );
          const sources = {
            period, scope_level: level, scope_id: scopeId, projects, approved_changes: changes,
            notes: 'Driver amounts (escalation, schedule_shift, scope_change, packaging, unexplained) are the part of each driver falling in the selected period. approved_changes.cost_impact_aud_m is the whole-of-life impact of each approved change, so it will not equal a single period driver; do not treat that difference as a discrepancy. A negative schedule_shift_aud_m means spend has moved out of the period because of slip (timing), not that total cost fell; slip usually adds delay cost elsewhere.',
          };
          const draft = await draftWithLlm(
            `You draft variance commentary for an Australian Government infrastructure portfolio office. Write 3-5 sentences of plain, factual commentary a program executive would sign: the size and direction of the variance, the recorded drivers that explain it, what remains unexplained, and the one action that would most reduce uncertainty. No headings, no bullet points.\n${DRAFT_RULES}`,
            JSON.stringify(sources),
            1500,
          );
          res.json({ draft, sources, model: LLM_ENDPOINT });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Draft could not be generated.');
        }
      });

      app.post('/api/ai/briefing-draft', async (req, res) => {
        const scenarioId = /^[A-Z0-9_-]+$/.test(String(req.body?.scenario_id ?? '')) ? String(req.body.scenario_id) : 'BASE';
        try {
          const s = { scenario: sql.string(scenarioId) };
          const [kpis, scenarios, capacity, exceptions, bridge, commentary, run] = await Promise.all([
            asUserQuery(req, `SELECT scenario_name, horizon_label, ROUND(approved_portfolio_aud_m) AS forecast_aud_m, ROUND(endorsed_plan_aud_m) AS endorsed_plan_aud_m,
                                     ROUND(vs_endorsed_plan_aud_m) AS vs_endorsed_aud_m, ROUND(peak_capacity_gap_aud_m) AS peak_capacity_gap_aud_m, peak_capacity_gap_fy,
                                     ROUND(forecast_confidence_pct) AS confidence_pct, capacity_breaches, peak_category, peak_fy, ROUND(peak_demand_capacity_pct) AS peak_utilisation_pct,
                                     current_fy_label, ROUND(current_fy_forecast_aud_m) AS current_fy_forecast_aud_m, ROUND(current_fy_plan_aud_m) AS current_fy_plan_aud_m,
                                     ROUND(current_fy_unexplained_aud_m) AS current_fy_unexplained_aud_m, actuals_through, figure_status
                              FROM ${SCHEMA}.portfolio_kpis WHERE scenario_id = :scenario`, s),
            asUserQuery(req, `SELECT scenario_id, scenario_name, status, ROUND(total_forecast_aud_m) AS horizon_aud_m, ROUND(headroom_aud_m) AS headroom_aud_m,
                                     capacity_breaches, ROUND(forecast_confidence_pct) AS confidence_pct, projects_changed,
                                     ROUND(spend_beyond_horizon_aud_m) AS spend_beyond_horizon_aud_m, ROUND(indicative_delay_cost_aud_m) AS indicative_delay_cost_aud_m,
                                     ROUND(forecast_p10_aud_m) AS p10_aud_m, ROUND(forecast_p90_aud_m) AS p90_aud_m
                              FROM ${SCHEMA}.scenario_summary WHERE :scenario IS NOT NULL ORDER BY scenario_id`, s),
            asUserQuery(req, `SELECT financial_year, capacity_category, ROUND(utilisation_pct) AS utilisation_pct, status
                              FROM ${SCHEMA}.capacity_demand WHERE scenario_id = :scenario AND utilisation_pct >= 90 ORDER BY utilisation_pct DESC LIMIT 8`, s),
            asUserQuery(req, `SELECT program_name, exception_type, ROUND(delta_value, 1) AS delta_value, delta_unit, description
                              FROM ${SCHEMA}.priority_exceptions WHERE :scenario IS NOT NULL ORDER BY rank LIMIT 6`, s),
            asUserQuery(req, `SELECT period_label, driver, ROUND(amount_aud_m) AS amount_aud_m FROM ${SCHEMA}.variance_bridge
                              WHERE scope_level = 'portfolio' AND period = 'CURRENT_FY' AND :scenario IS NOT NULL ORDER BY driver_order`, s),
            asUserQuery(req, `SELECT scope_level, scope_id, reason_code, ROUND(amount_aud_m) AS amount_aud_m, commentary, actor
                              FROM ${SCHEMA}.variance_commentary WHERE :scenario IS NOT NULL ORDER BY created_at DESC LIMIT 8`, s),
            asUserQuery(req, `SELECT run_id, run_type, as_of_date, actuals_through, plan_version, capacity_model_version
                              FROM ${SCHEMA}.forecast_runs WHERE :scenario IS NOT NULL ORDER BY started_at DESC LIMIT 1`, s),
          ]);
          if (kpis.length === 0) return fail(res, 404, 'No figures are available for that scenario.');
          const sources = { scenario_id: scenarioId, headline: kpis[0], scenarios, capacity_pressure: capacity, priority_exceptions: exceptions,
            current_fy_variance_bridge: bridge, recorded_commentary: commentary, forecast_run: run[0] ?? null };
          const draft = await draftWithLlm(
            `You draft a one-page executive briefing on the national infrastructure portfolio for the Executive Budget Committee. Use Markdown with exactly these sections:
## Purpose
## Key points (3-5 bullets, each with a figure)
## Deliverability and market capacity
## Scenario options (compare the scenarios in the data; name trade-offs: affordability, capacity breaches, spend moved beyond the horizon, delay cost)
## Variance and assurance
## Recommendation
## Basis of figures (forecast run id, actuals date, plan and capacity model versions)
Keep it under 450 words. Write for a time-poor senior official.\n${DRAFT_RULES}`,
            JSON.stringify(sources),
            4000,
          );
          res.json({ draft, sources, model: LLM_ENDPOINT, forecast_run_id: (run[0]?.run_id as string | undefined) ?? null });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Briefing could not be drafted.');
        }
      });

      app.post('/api/briefings', async (req, res) => {
        const body = req.body ?? {};
        const narrative = text(body.narrative, 20000);
        const status = body.status === 'Approved' ? 'Approved' : 'Draft';
        const packId = /^PACK-[A-Z0-9]+$/.test(String(body.pack_id ?? '')) ? String(body.pack_id) : `PACK-${randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()}`;
        if (!narrative) return fail(res, 400, 'The briefing is empty.');
        try {
          const rows = await asUserQuery(req, `SELECT COALESCE(MAX(version), 0) AS v FROM ${SCHEMA}.briefing_packs WHERE pack_id = :id`, { id: sql.string(packId) });
          const version = Number(rows[0]?.v ?? 0) + 1;
          await execute(
            `INSERT INTO ${SCHEMA}.briefing_packs VALUES (:id, :version, :title, :scenario, :run, :narrative, :status, :model, :sources, :actor, current_timestamp())`,
            [
              { name: 'id', value: packId },
              { name: 'version', value: version, type: 'INT' },
              { name: 'title', value: text(body.title, 200) ?? 'Portfolio briefing' },
              { name: 'scenario', value: text(body.scenario_id, 40) },
              { name: 'run', value: text(body.forecast_run_id, 80) },
              { name: 'narrative', value: narrative },
              { name: 'status', value: status },
              { name: 'model', value: text(body.model, 120) },
              { name: 'sources', value: typeof body.sources === 'object' ? JSON.stringify(body.sources).slice(0, 60000) : null },
              { name: 'actor', value: actor(req) },
            ],
          );
          res.json({ pack_id: packId, version, status });
        } catch (error) {
          fail(res, 500, error instanceof Error ? error.message : 'Briefing could not be saved.');
        }
      });
    });
  },
}).catch(console.error);
