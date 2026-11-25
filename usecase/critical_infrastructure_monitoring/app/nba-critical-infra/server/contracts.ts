import { z } from 'zod';

/** Dispositions an officer can record, mirroring common.DISPOSITIONS in the pipeline. */
export const DISPOSITIONS = ['route', 'monitor'] as const;

/** Evidence panels the review dialog can show; recorded so the audit says what was seen. */
export const EVIDENCE = ['risk_score', 'contributing_factors', 'recent_movement', 'operator_context'] as const;

export const reviewDecisionSchema = z.object({
  alertId: z
    .string()
    .trim()
    .min(1)
    .max(64)
    // alert ids are "<asset_id>:<risk_type>" - reject anything else before it reaches SQL
    .regex(/^\d+:(fatigue|roadworthiness|mass|route)$/, 'Unknown alert id'),
  disposition: z.enum(DISPOSITIONS),
  evidenceViewed: z.array(z.enum(EVIDENCE)).min(1).max(EVIDENCE.length),
  notes: z.string().trim().max(500).optional().default(''),
});

export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;

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
