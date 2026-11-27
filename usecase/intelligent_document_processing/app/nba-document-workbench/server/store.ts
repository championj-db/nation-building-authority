import type { CorrectionRecord, DecisionInput, DecisionRecord, GovernedSnapshot } from '../shared/contracts.js';

/**
 * App-owned review records in Lakebase Postgres, schema `daw`. Writes run as the app's service
 * principal (AppKit keeps Lakebase app-only); the officer's identity is the proxy-asserted actor
 * stored on every row, and every write was first checked against Unity Catalog as that officer
 * (server.ts). Append-only: one final decision per document, and every field correction kept.
 *
 * src/05_sync_decisions.py reads both tables back into Unity Catalog.
 */

interface QueryResult {
  rows: Record<string, unknown>[];
}
interface PoolClient {
  query(text: string, params?: unknown[]): Promise<QueryResult>;
  release(): void;
}
export interface LakebaseHandle {
  query(text: string, params?: unknown[]): Promise<QueryResult>;
  pool: { connect(): Promise<PoolClient> };
}

const DDL = [
  'CREATE SCHEMA IF NOT EXISTS daw',
  `CREATE TABLE IF NOT EXISTS daw.document_decision (
     decision_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     doc_id                 TEXT NOT NULL UNIQUE,
     decision               TEXT NOT NULL CHECK (decision IN ('accepted', 'returned', 'reclassified', 'actioned')),
     reason_codes           TEXT[] NOT NULL DEFAULT '{}',
     note                   TEXT,
     doc_type               TEXT NOT NULL,
     status_seen            TEXT NOT NULL,
     lowest_confidence_seen DOUBLE PRECISION,
     fields_corrected       INT NOT NULL DEFAULT 0,
     fields_confirmed       TEXT[] NOT NULL DEFAULT '{}',
     reclassify_to          TEXT,
     handling_seconds       INT NOT NULL DEFAULT 0,
     decided_by             TEXT NOT NULL,
     decided_at             TIMESTAMPTZ NOT NULL DEFAULT now()
   )`,
  `CREATE TABLE IF NOT EXISTS daw.field_correction (
     correction_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     doc_id             TEXT NOT NULL,
     field              TEXT NOT NULL,
     extracted_value    TEXT,
     corrected_value    TEXT NOT NULL,
     routing_confidence DOUBLE PRECISION,
     corrected_by       TEXT NOT NULL,
     corrected_at       TIMESTAMPTZ NOT NULL DEFAULT now()
   )`,
  'CREATE INDEX IF NOT EXISTS field_correction_doc_idx ON daw.field_correction (doc_id)',
  "COMMENT ON TABLE daw.document_decision IS 'AP review decisions from the Document Assurance Workbench (synthetic demonstration). One final decision per document.'",
];

const iso = (v: unknown) => (v instanceof Date ? v.toISOString() : typeof v === 'string' ? v : '');
const num = (v: unknown) => (v == null ? null : Number(v));

function toDecision(r: Record<string, unknown>): DecisionRecord {
  return {
    decision_id: String(r.decision_id),
    doc_id: String(r.doc_id),
    decision: r.decision as DecisionRecord['decision'],
    reason_codes: (r.reason_codes as string[]) ?? [],
    note: (r.note as string) ?? null,
    doc_type: String(r.doc_type),
    status_seen: String(r.status_seen),
    lowest_confidence_seen: num(r.lowest_confidence_seen),
    fields_corrected: Number(r.fields_corrected ?? 0),
    fields_confirmed: (r.fields_confirmed as string[]) ?? [],
    reclassify_to: (r.reclassify_to as string) ?? null,
    handling_seconds: Number(r.handling_seconds ?? 0),
    decided_by: String(r.decided_by),
    decided_at: iso(r.decided_at),
  };
}

function toCorrection(r: Record<string, unknown>): CorrectionRecord {
  return {
    correction_id: String(r.correction_id),
    doc_id: String(r.doc_id),
    field: String(r.field),
    extracted_value: (r.extracted_value as string) ?? null,
    corrected_value: String(r.corrected_value),
    routing_confidence: num(r.routing_confidence),
    corrected_by: String(r.corrected_by),
    corrected_at: iso(r.corrected_at),
  };
}

export async function createStore(lb: LakebaseHandle) {
  // The app's service principal creates and owns these on first start. Later starts, and local
  // runs as another role, find them in place and must not re-run owner-only DDL.
  const existing = await lb.query(
    `SELECT count(*)::int AS n FROM information_schema.tables
     WHERE table_schema = 'daw' AND table_name IN ('document_decision', 'field_correction')`
  );
  if (Number(existing.rows[0]?.n ?? 0) < 2) {
    for (const statement of DDL) await lb.query(statement);
  }

  return {
    async decisions(): Promise<DecisionRecord[]> {
      const { rows } = await lb.query('SELECT * FROM daw.document_decision ORDER BY decided_at DESC');
      return rows.map(toDecision);
    },

    async forDocument(docId: string) {
      const [d, c] = await Promise.all([
        lb.query('SELECT * FROM daw.document_decision WHERE doc_id = $1', [docId]),
        lb.query('SELECT * FROM daw.field_correction WHERE doc_id = $1 ORDER BY corrected_at', [docId]),
      ]);
      return { decision: d.rows[0] ? toDecision(d.rows[0]) : null, corrections: c.rows.map(toCorrection) };
    },

    async correctionStats() {
      const { rows } = await lb.query(
        `SELECT field, count(*)::int AS corrections FROM daw.field_correction GROUP BY field ORDER BY corrections DESC`
      );
      return rows.map((r) => ({ field: String(r.field), corrections: Number(r.corrections) }));
    },

    /** Record one final decision and its corrections atomically. */
    async record(
      input: DecisionInput,
      snap: GovernedSnapshot,
      confidences: Record<string, number | null>,
      actor: string
    ): Promise<{ ok: true; decision: DecisionRecord } | { ok: false; reason: string }> {
      const client = await lb.pool.connect();
      try {
        await client.query('BEGIN');
        await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [snap.docId]);
        const prior = await client.query('SELECT decided_by, decision FROM daw.document_decision WHERE doc_id = $1', [
          snap.docId,
        ]);
        if (prior.rows[0]) {
          await client.query('ROLLBACK');
          return {
            ok: false,
            reason: `${String(prior.rows[0].decided_by)} has already recorded a decision on this document.`,
          };
        }
        const { rows } = await client.query(
          `INSERT INTO daw.document_decision (doc_id, decision, reason_codes, note, doc_type, status_seen,
             lowest_confidence_seen, fields_corrected, fields_confirmed, reclassify_to, handling_seconds, decided_by)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) RETURNING *`,
          [
            snap.docId,
            input.decision,
            input.reasonCodes,
            input.note || null,
            snap.docType,
            snap.status,
            snap.lowestConfidence,
            input.corrections.length,
            input.confirmedFields,
            input.reclassifyTo ?? null,
            input.handlingSeconds,
            actor,
          ]
        );
        for (const c of input.corrections) {
          await client.query(
            `INSERT INTO daw.field_correction (doc_id, field, extracted_value, corrected_value, routing_confidence, corrected_by)
             VALUES ($1, $2, $3, $4, $5, $6)`,
            [snap.docId, c.field, c.extracted, c.corrected, confidences[c.field] ?? null, actor]
          );
        }
        await client.query('COMMIT');
        return { ok: true, decision: toDecision(rows[0]) };
      } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined);
        throw error;
      } finally {
        client.release();
      }
    },
  };
}

export type Store = Awaited<ReturnType<typeof createStore>>;
