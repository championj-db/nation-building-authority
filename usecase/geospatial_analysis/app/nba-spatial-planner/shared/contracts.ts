import { z } from 'zod';

/** Service types, mirroring SERVICE_TYPES in the pipeline's src/common.py. */
export const SERVICES = ['public_hospital', 'urgent_care', 'residential_aged_care', 'ambulance_station'] as const;
/** Geographies, mirroring GEO_LEVELS in src/common.py. */
export const GEO_LEVELS = ['sa4', 'sa3', 'sa2', 'lga', 'ra', 'state'] as const;
/** Analysis scope: one state or territory, or the whole country. */
export const SCOPES = ['AUS', 'NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT', 'OT'] as const;
export const EVIDENCE_STATUSES = ['needs_validation', 'ready_for_review', 'validated', 'no_action'] as const;

export const THRESHOLD_MIN_KM = 5;
export const THRESHOLD_MAX_KM = 150;
export const MAX_PROPOSED_SITES = 5;

const regionCode = z
  .string()
  .trim()
  .regex(/^[0-9A-Za-z]{1,11}$/, 'Unknown region code');

export const proposedSiteSchema = z.object({
  lon: z.number().min(96).max(168),
  lat: z.number().min(-55).max(-9),
});

/** Everything that defines an analysis view. Saved views and briefs persist exactly this. */
export const analysisSettingsSchema = z.object({
  service: z.enum(SERVICES),
  geoLevel: z.enum(GEO_LEVELS),
  scope: z.enum(SCOPES),
  threshold: z.number().int().min(THRESHOLD_MIN_KM).max(THRESHOLD_MAX_KM),
  suppress: z.boolean(),
  boundaries: z.boolean(),
  layer: z.enum(['regions', 'hexagons']),
  sites: z.array(proposedSiteSchema).max(MAX_PROPOSED_SITES),
});
export type AnalysisSettings = z.infer<typeof analysisSettingsSchema>;

export const reviewNoteSchema = z.object({
  service: z.enum(SERVICES),
  geoLevel: z.enum(GEO_LEVELS),
  regionCode,
  regionName: z.string().trim().min(1).max(120),
  thresholdKm: z.number().int().min(THRESHOLD_MIN_KM).max(THRESHOLD_MAX_KM),
  evidenceStatus: z.enum(EVIDENCE_STATUSES),
  nextStep: z.string().trim().max(160).optional().default(''),
  note: z.string().trim().max(1000).optional().default(''),
});
export type ReviewNote = z.infer<typeof reviewNoteSchema>;

export const savedViewSchema = z.object({
  name: z.string().trim().min(1, 'Give the view a name').max(80),
  settings: analysisSettingsSchema,
});

/** A snapshot of the headline figures at preparation time, so a brief cannot drift. */
export const findingsSchema = z.object({
  scopeLabel: z.string().max(80),
  serviceLabel: z.string().max(80),
  geographyLabel: z.string().max(80),
  persons: z.number().nullable(),
  personsBeyond: z.number().nullable(),
  shareBeyond: z.number().nullable(),
  persons65Beyond: z.number().nullable(),
  householdsNoVehicleBeyond: z.number().nullable(),
  medianKm: z.number().nullable(),
  regionsBeyond: z.number().int(),
  regionsTotal: z.number().int(),
  priorities: z
    .array(
      z.object({
        regionName: z.string().max(120),
        personsBeyond: z.number().nullable(),
        shareBeyond: z.number().nullable(),
        medianKm: z.number().nullable(),
        accessClass: z.string().max(20),
        evidenceStatus: z.string().max(30).nullable(),
      }),
    )
    .max(10),
  scenario: z
    .object({
      sites: z.number().int(),
      personsGained: z.number().nullable(),
    })
    .nullable(),
  dataRefreshed: z.string().max(40).nullable(),
});

export const briefSchema = z.object({
  title: z.string().trim().min(3).max(140),
  policyQuestion: z.string().trim().min(10, 'State the policy question this brief answers').max(600),
  accessBasis: z.string().trim().min(3, 'Record the basis for accessing this analysis').max(300),
  audience: z.string().trim().min(3, 'Record who the brief is for').max(200),
  settings: analysisSettingsSchema,
  findings: findingsSchema,
});

export const idSchema = z.string().uuid('Unknown id');

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

/** Disclosure threshold for small-count suppression (persons); 10 unless configured. */
export function resolveMinCount(env: NodeJS.ProcessEnv): number {
  const raw = Number(env.SUPPRESSION_MIN_COUNT ?? 10);
  return Number.isInteger(raw) && raw >= 3 && raw <= 100 ? raw : 10;
}
