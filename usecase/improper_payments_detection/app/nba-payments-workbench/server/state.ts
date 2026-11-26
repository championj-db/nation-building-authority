import { reduceEvents, type CaseEvent, type CaseState, type OutcomeInput } from '../shared/contracts.js';

/**
 * App-owned case workflow in Lakebase Postgres, schema `ipw`. These run as the app's service
 * principal (AppKit keeps Lakebase app-only); the investigator's identity is the proxy-asserted
 * actor recorded on every row, and each write was first checked against Unity Catalog as that
 * investigator (server.ts). Both tables are append-only from the app's point of view: nothing is
 * updated or deleted, so the record shows every assignment and every decision.
 *
 * src/08_outcome_feedback.py reads ipw.case_outcome back into Unity Catalog to measure precision.
 */

interface QueryResult {
  rows: Record<string, unknown>[];
  rowCount?: number | null;
}
interface PoolClient {
  query(text: string, params?: unknown[]): Promise<QueryResult>;
  release(): void;
}
export interface LakebaseHandle {
  query(text: string, params?: unknown[]): Promise<QueryResult>;
  pool: { connect(): Promise<PoolClient> };
}

type Result = { ok: true; state: CaseState } | { ok: false; reason: string };

const DDL = [
  'CREATE SCHEMA IF NOT EXISTS ipw',
  `CREATE TABLE IF NOT EXISTS ipw.case_event (
     event_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     case_id    TEXT NOT NULL,
     event_type TEXT NOT NULL CHECK (event_type IN ('assigned', 'released', 'outcome')),
     actor      TEXT NOT NULL,
     detail     TEXT,
     created_at TIMESTAMPTZ NOT NULL DEFAULT now()
   )`,
  'CREATE INDEX IF NOT EXISTS case_event_case_idx ON ipw.case_event (case_id, created_at)',
  `CREATE TABLE IF NOT EXISTS ipw.case_outcome (
     outcome_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     case_id        TEXT NOT NULL UNIQUE,
     outcome        TEXT NOT NULL CHECK (outcome IN ('cleared', 'escalated')),
     reason_code    TEXT NOT NULL,
     notes          TEXT NOT NULL,
     risk_score     INT NOT NULL,
     risk_band      TEXT NOT NULL,
     primary_signal TEXT NOT NULL,
     decided_by     TEXT NOT NULL,
     decided_at     TIMESTAMPTZ NOT NULL DEFAULT now()
   )`,
  "COMMENT ON TABLE ipw.case_outcome IS 'Investigator triage outcomes (synthetic demonstration). One final decision per case; scores are indicators, not findings.'",
];

const iso = (v: unknown) => (v instanceof Date ? v.toISOString() : typeof v === 'string' ? v : '');

function toEvent(row: Record<string, unknown>): CaseEvent {
  return {
    event_id: String(row.event_id),
    case_id: String(row.case_id),
    event_type: row.event_type as CaseEvent['event_type'],
    actor: String(row.actor),
    detail: typeof row.detail === 'string' ? row.detail : null,
    created_at: iso(row.created_at),
  };
}

export async function createStateStore(lb: LakebaseHandle) {
  // The app's service principal creates and owns these on first start. Later starts, and local
  // runs as another role, find them in place and must not re-run owner-only DDL (index, comment).
  const existing = await lb.query(
    `SELECT count(*)::int AS n FROM information_schema.tables
     WHERE table_schema = 'ipw' AND table_name IN ('case_event', 'case_outcome')`,
  );
  if (Number(existing.rows[0]?.n ?? 0) < 2) {
    for (const statement of DDL) await lb.query(statement);
  }

  /** Serialise all writes to one case, then read its events inside the same transaction. */
  async function withCase<T>(caseId: string, fn: (client: PoolClient, events: CaseEvent[]) => Promise<T>): Promise<T> {
    const client = await lb.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [caseId]);
      const { rows } = await client.query('SELECT * FROM ipw.case_event WHERE case_id = $1 ORDER BY created_at', [caseId]);
      const value = await fn(client, rows.map(toEvent));
      await client.query('COMMIT');
      return value;
    } catch (error) {
      await client.query('ROLLBACK').catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async function append(client: PoolClient, caseId: string, type: CaseEvent['event_type'], actor: string, detail: string | null) {
    const { rows } = await client.query(
      'INSERT INTO ipw.case_event (case_id, event_type, actor, detail) VALUES ($1, $2, $3, $4) RETURNING *',
      [caseId, type, actor, detail],
    );
    return toEvent(rows[0]);
  }

  return {
    async states() {
      const [events, total] = await Promise.all([
        lb.query('SELECT * FROM ipw.case_event ORDER BY case_id, created_at'),
        lb.query('SELECT count(*)::int AS n FROM ipw.case_outcome'),
      ]);
      const byCase = new Map<string, CaseEvent[]>();
      for (const row of events.rows) {
        const e = toEvent(row);
        byCase.set(e.case_id, [...(byCase.get(e.case_id) ?? []), e]);
      }
      const states = [...byCase.values()].map((list) => reduceEvents(list)).filter((s): s is CaseState => s != null);
      return { states, outcomesTotal: Number(total.rows[0]?.n ?? 0) };
    },

    async history(caseId: string) {
      const [events, outcome] = await Promise.all([
        lb.query('SELECT * FROM ipw.case_event WHERE case_id = $1 ORDER BY created_at DESC', [caseId]),
        lb.query('SELECT outcome, reason_code, notes, decided_by, decided_at FROM ipw.case_outcome WHERE case_id = $1', [caseId]),
      ]);
      const o = outcome.rows[0];
      return {
        events: events.rows.map(toEvent),
        outcome: o ? { ...o, decided_at: iso(o.decided_at) } : null,
      };
    },

    assign(caseId: string, actor: string): Promise<Result> {
      return withCase(caseId, async (client, events) => {
        const current = reduceEvents(events);
        if (current?.status === 'closed') return { ok: false, reason: 'This case is already closed.' };
        if (current?.status === 'review') {
          return current.assignee === actor
            ? { ok: true, state: current }
            : { ok: false, reason: `This case is already in review with ${current.assignee}.` };
        }
        const e = await append(client, caseId, 'assigned', actor, null);
        return { ok: true, state: reduceEvents([...events, e])! };
      });
    },

    release(caseId: string, actor: string): Promise<Result> {
      return withCase(caseId, async (client, events) => {
        const current = reduceEvents(events);
        if (current?.status !== 'review') return { ok: false, reason: 'Only a case in review can be returned to the queue.' };
        if (current.assignee !== actor) return { ok: false, reason: `Only ${current.assignee} can return this case.` };
        const e = await append(client, caseId, 'released', actor, null);
        return { ok: true, state: reduceEvents([...events, e])! };
      });
    },

    recordOutcome(input: OutcomeInput & { caseId: string; riskScore: number; riskBand: string; primarySignal: string; actor: string }): Promise<Result> {
      return withCase(input.caseId, async (client, events) => {
        const current = reduceEvents(events);
        if (current?.status === 'closed') return { ok: false, reason: 'An outcome has already been recorded for this case.' };
        if (current?.status === 'review' && current.assignee !== input.actor) {
          return { ok: false, reason: `This case is in review with ${current.assignee}.` };
        }
        const added: CaseEvent[] = [];
        // Deciding an unassigned case assigns it first, so the record shows who held it.
        if (!current || current.status === 'unassigned') added.push(await append(client, input.caseId, 'assigned', input.actor, null));
        await client.query(
          `INSERT INTO ipw.case_outcome (case_id, outcome, reason_code, notes, risk_score, risk_band, primary_signal, decided_by)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
          [input.caseId, input.outcome, input.reasonCode, input.notes, input.riskScore, input.riskBand, input.primarySignal, input.actor],
        );
        added.push(await append(client, input.caseId, 'outcome', input.actor, `${input.outcome}:${input.reasonCode}`));
        return { ok: true, state: reduceEvents([...events, ...added])! };
      });
    },

    async summary() {
      const [groups, recent] = await Promise.all([
        lb.query(
          `SELECT primary_signal, risk_band, outcome, count(*)::int AS decided
           FROM ipw.case_outcome GROUP BY primary_signal, risk_band, outcome`,
        ),
        lb.query(
          `SELECT case_id, outcome, reason_code, primary_signal, risk_band, risk_score, decided_by, decided_at
           FROM ipw.case_outcome ORDER BY decided_at DESC LIMIT 12`,
        ),
      ]);
      return {
        groups: groups.rows,
        recent: recent.rows.map((r) => ({ ...r, decided_at: iso(r.decided_at) })),
      };
    },
  };
}

export type StateStore = Awaited<ReturnType<typeof createStateStore>>;
