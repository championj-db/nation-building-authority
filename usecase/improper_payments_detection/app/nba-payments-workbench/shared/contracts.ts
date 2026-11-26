import { z } from 'zod';

/**
 * Contracts shared by the server and the client. Case data comes from the governed gold layer
 * written by ../../src (Unity Catalog); case state and investigation outcomes are app-owned
 * records in Lakebase Postgres (schema `ipw`), read back into Unity Catalog by
 * src/08_outcome_feedback.py to measure precision.
 */

export const OUTCOMES = ['cleared', 'escalated'] as const;
export type Outcome = (typeof OUTCOMES)[number];

/** Why an investigator cleared or escalated an indicator. Codes are stored; labels are shown. */
export const REASONS: Record<Outcome, readonly { code: string; label: string }[]> = {
  cleared: [
    { code: 'legitimate_relationship', label: 'Relationship is legitimate and explained' },
    { code: 'entity_match_incorrect', label: 'Records were linked in error' },
    { code: 'documents_verified', label: 'Supporting documents verified' },
    { code: 'other_cleared', label: 'Other (explained in notes)' },
  ],
  escalated: [
    { code: 'evidence_supports', label: 'Evidence supports the indicator' },
    { code: 'documents_inconsistent', label: 'Documents inconsistent or missing' },
    { code: 'conflict_of_interest', label: 'Possible undeclared conflict of interest' },
    { code: 'other_escalated', label: 'Other (explained in notes)' },
  ],
};

export function reasonLabel(code: string | null | undefined): string {
  if (!code) return '';
  for (const list of Object.values(REASONS)) {
    const hit = list.find((r) => r.code === code);
    if (hit) return hit.label;
  }
  return code;
}

export const NOTES_MIN = 12;
export const NOTES_MAX = 2000;

export const caseIdSchema = z.string().regex(/^IP-\d{4,6}$/, 'Unknown case reference');

export const outcomeSchema = z
  .object({
    outcome: z.enum(OUTCOMES),
    reasonCode: z.string().min(1, 'Choose the reason for this outcome'),
    notes: z
      .string()
      .trim()
      .min(NOTES_MIN, 'Summarise the checks completed and evidence considered')
      .max(NOTES_MAX, `Keep notes under ${NOTES_MAX} characters`),
  })
  .refine((v) => REASONS[v.outcome].some((r) => r.code === v.reasonCode), {
    message: 'That reason does not apply to this outcome',
    path: ['reasonCode'],
  });
export type OutcomeInput = z.infer<typeof outcomeSchema>;

/** Risk bands, mirroring the pipeline's case threshold (src/07_case_queue.py). */
export const HIGH_BAND_MIN = 80;
export type RiskBand = 'high' | 'medium';
export function bandFor(score: number): RiskBand {
  return score >= HIGH_BAND_MIN ? 'high' : 'medium';
}

/**
 * Case workflow. A case with no recorded event is unassigned; assignment puts it in review; an
 * outcome closes it. Release returns an in-review case to the queue.
 */
export type CaseStatus = 'unassigned' | 'review' | 'closed';
export const EVENT_TYPES = ['assigned', 'released', 'outcome'] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface CaseState {
  case_id: string;
  status: CaseStatus;
  assignee: string | null;
  updated_at: string;
  outcome: Outcome | null;
  reason_code: string | null;
}

export interface CaseEvent {
  event_id: string;
  case_id: string;
  event_type: EventType;
  actor: string;
  detail: string | null;
  created_at: string;
}

/** Collapse a case's events (any order) to its current state. An outcome is final. */
export function reduceEvents(events: readonly CaseEvent[]): CaseState | null {
  const sorted = [...events].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return sorted.reduce<CaseState | null>((state, e) => {
    if (state?.status === 'closed') return state;
    const base = { case_id: e.case_id, updated_at: e.created_at, outcome: null, reason_code: null };
    if (e.event_type === 'assigned') return { ...base, status: 'review', assignee: e.actor };
    if (e.event_type === 'released') return { ...base, status: 'unassigned', assignee: null };
    const [outcome, reason] = (e.detail ?? '').split(':');
    return {
      ...base,
      status: 'closed',
      assignee: state?.assignee ?? e.actor,
      outcome: (OUTCOMES as readonly string[]).includes(outcome ?? '') ? (outcome as Outcome) : null,
      reason_code: reason ?? null,
    };
  }, null);
}

/** Share of investigated indicators that held up (were escalated). Null when nothing is decided. */
export function precision(escalated: number, cleared: number): number | null {
  const total = escalated + cleared;
  return total > 0 ? escalated / total : null;
}

/** A Unity Catalog identifier segment; guards the catalog/schema the server interpolates. */
const ucIdentifier = /^[A-Za-z0-9_]+$/;

export function resolveSchema(env: NodeJS.ProcessEnv): { catalog: string; schema: string } {
  const catalog = env.DATABRICKS_CATALOG ?? '';
  const schema = env.DATABRICKS_SCHEMA ?? '';
  if (!ucIdentifier.test(catalog) || !ucIdentifier.test(schema)) {
    throw new Error('DATABRICKS_CATALOG and DATABRICKS_SCHEMA must be set to plain Unity Catalog identifiers');
  }
  return { catalog, schema };
}
