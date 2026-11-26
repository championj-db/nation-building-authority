import { EVIDENCE_STATUSES } from '../../../shared/contracts';
import { km, people } from './format';

export type AccessClass = 'beyond' | 'near' | 'within' | 'suppressed' | 'no_population';
export type EvidenceStatus = (typeof EVIDENCE_STATUSES)[number];

export interface RegionShape {
  region_code: string;
  region_name: string;
  state_abbr: string;
  ra_class: string | null;
  geom: unknown;
  label_lon: number;
  label_lat: number;
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
  persons: number;
  area_sqkm: number | null;
}

export interface StateOutline {
  region_code: string;
  state_abbr: string;
  geom: unknown;
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
}

export interface RegionAccess {
  region_code: string;
  region_name: string;
  state_abbr: string;
  ra_class: string | null;
  persons: number | null;
  access_class: AccessClass;
  median_km: number | null;
  p90_km: number | null;
  persons_beyond: number | null;
  beyond_suppressed: boolean;
  share_beyond: number | null;
  persons_65_beyond: number | null;
  households_no_vehicle_beyond: number | null;
}

export interface ScopeSummary {
  persons: number | null;
  households: number | null;
  persons_65_plus: number | null;
  households_no_vehicle: number | null;
  persons_beyond: number | null;
  persons_65_beyond: number | null;
  households_no_vehicle_beyond: number | null;
  median_km: number | null;
  p90_km: number | null;
}

export interface RemotenessRow {
  ra_class: string;
  ra_label: string;
  persons: number | null;
  persons_beyond: number | null;
  share_beyond: number | null;
}

export interface ServiceSite {
  site_id: string;
  name: string;
  address: string | null;
  suburb: string | null;
  state_abbr: string | null;
  longitude: number;
  latitude: number;
  capacity_places: number | null;
  catchment_persons: number | null;
  catchment_median_km: number | null;
  catchment_p90_km: number | null;
}

export interface HexCell {
  hex_id: string;
  ring: unknown;
  persons: number;
  persons_beyond: number | null;
  median_km: number | null;
  access_class: AccessClass;
}

export interface ScenarioRow {
  region_code: string | null;
  region_name: string | null;
  persons_gained: number | null;
  persons_65_gained: number | null;
  households_no_vehicle_gained: number | null;
}

export interface DistributionRow {
  bucket_km: number;
  persons: number | null;
  suppressed: boolean;
}

export interface ReviewNoteRow {
  region_code: string;
  region_name: string | null;
  evidence_status: EvidenceStatus;
  next_step: string | null;
  note: string | null;
  officer: string;
  created_ts: string;
  threshold_km: number | null;
  note_count: number;
}

export interface CatalogRow {
  service_type: string;
  label: string;
  description: string;
  default_threshold_km: number;
  publisher: string;
  source_url: string;
  attribution: string;
  sort_order: number;
  sites: number;
  fetched_at: string | null;
  from_cache: boolean | null;
}

export const ACCESS_CLASS_LABEL: Record<AccessClass, string> = {
  beyond: 'Beyond threshold',
  near: 'Near threshold',
  within: 'Within threshold',
  suppressed: 'Suppressed',
  no_population: 'No residents',
};

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  needs_validation: 'Needs validation',
  ready_for_review: 'Ready for review',
  validated: 'Validated',
  no_action: 'No action needed',
};

/** Until an officer records a status, a region's evidence status follows its access class. */
export function defaultEvidence(accessClass: AccessClass): EvidenceStatus {
  return accessClass === 'beyond' ? 'needs_validation' : accessClass === 'near' ? 'ready_for_review' : 'no_action';
}

/** Plain-language recommended next step for a region, before an officer sets one. */
export function recommendedStep(row: RegionAccess): string {
  switch (row.access_class) {
    case 'beyond':
      return (row.persons_beyond ?? 0) >= 2_000 ? 'Test a new-site scenario' : 'Assess outreach or telehealth options';
    case 'near':
      return 'Monitor quarterly';
    case 'within':
      return 'No immediate action';
    case 'suppressed':
      return 'Review at a coarser geography';
    default:
      return 'No residents to assess';
  }
}

/** One-line rationale for a review priority card. */
export function priorityRationale(row: RegionAccess, serviceLabel: string, threshold: number, minCount: number) {
  const service = serviceLabel.toLowerCase().replace(/s$/, '');
  const median = row.median_km != null ? `The median resident is ${km(row.median_km)} from the nearest ${service}` : '';
  const beyond =
    row.persons_beyond === 0
      ? 'no residents are beyond the threshold'
      : `${people(row.persons_beyond, minCount)} people live more than ${threshold} km away`;
  return `${median}${median ? '; ' : ''}${beyond}.`;
}

/** Regions officers should look at first: beyond, then near, by people beyond the threshold. */
export function priorities(rows: RegionAccess[], limit = 3) {
  const rank: Partial<Record<AccessClass, number>> = { beyond: 0, near: 1 };
  return rows
    .filter((r) => r.access_class === 'beyond' || r.access_class === 'near')
    .sort(
      (a, b) =>
        (rank[a.access_class] ?? 9) - (rank[b.access_class] ?? 9) || (b.persons_beyond ?? 0) - (a.persons_beyond ?? 0)
    )
    .slice(0, limit);
}
