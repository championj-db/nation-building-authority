import { useMemo } from 'react';
import type { z } from 'zod';
import { findingsSchema } from '../../../shared/contracts';
import type { Analysis } from './analysis';
import { sql, useBaseParams, useRows, useScope } from './data';
import { defaultEvidence, priorities } from './model';
import { GEO_LEVEL_LABELS, SCOPE_LABELS, parseStoredSettings, samePolicy, type AnalysisSettings } from './settings';

export type Findings = z.infer<typeof findingsSchema>;

export interface BriefRow {
  brief_id: string;
  created_ts: string;
  officer: string;
  title: string;
  policy_question: string;
  access_basis: string;
  audience: string;
  settings: unknown;
  findings: unknown;
  suppression_applied: boolean;
  status: 'draft' | 'signed_off';
  signed_off_by: string | null;
  signed_off_ts: string | null;
  prepared_ts: string;
  prepared_by: string;
}

export function useBriefs() {
  const base = useBaseParams();
  const { writes } = useScope();
  const params = useMemo(() => ({ ...base, refresh: sql.string(writes) }), [base, writes]);
  const result = useRows('briefs', params);
  const rows = (result.data ?? []) as BriefRow[];
  return { ...result, rows };
}

/** The most recent brief prepared from the same policy settings as `settings`, if any. */
export function briefForSettings(rows: BriefRow[], settings: AnalysisSettings) {
  return rows.find((b) => {
    const s = parseStoredSettings(b.settings);
    return s != null && samePolicy(s, settings);
  });
}

export function parseFindings(raw: unknown): Findings | null {
  let value = raw;
  if (typeof raw === 'string') {
    try {
      value = JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }
  const parsed = findingsSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/** Snapshot the analysis as it stands, so a brief records exactly what the officer saw. */
export function buildFindings(
  analysis: Analysis,
  settings: AnalysisSettings,
  serviceLabel: string,
  refreshed: string | null
): Findings {
  const s = analysis.summary.row;
  const rows = analysis.access.rows;
  return {
    scopeLabel: SCOPE_LABELS[settings.scope],
    serviceLabel,
    geographyLabel: GEO_LEVEL_LABELS[settings.geoLevel],
    persons: s?.persons ?? null,
    personsBeyond: s?.persons_beyond ?? null,
    shareBeyond: s?.persons && s.persons_beyond != null ? s.persons_beyond / s.persons : null,
    persons65Beyond: s?.persons_65_beyond ?? null,
    householdsNoVehicleBeyond: s?.households_no_vehicle_beyond ?? null,
    medianKm: s?.median_km ?? null,
    regionsBeyond: rows.filter((r) => r.access_class === 'beyond').length,
    regionsTotal: rows.filter((r) => r.access_class !== 'no_population').length,
    priorities: priorities(rows, 8).map((r) => ({
      regionName: r.region_name,
      personsBeyond: r.persons_beyond,
      shareBeyond: r.share_beyond,
      medianKm: r.median_km,
      accessClass: r.access_class,
      evidenceStatus: analysis.notes.byRegion.get(r.region_code)?.evidence_status ?? defaultEvidence(r.access_class),
    })),
    scenario: settings.sites.length
      ? { sites: settings.sites.length, personsGained: analysis.scenario.total?.persons_gained ?? null }
      : null,
    dataRefreshed: refreshed,
  };
}
