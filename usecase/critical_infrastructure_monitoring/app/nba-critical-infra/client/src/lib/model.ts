/**
 * The risk engine's parameters, mirrored from src/common.py (LIKELIHOOD_WEIGHTS, CONSEQUENCE_FLOOR,
 * RISK_RATINGS; model ioc-likelihood-consequence-v1). The review dialog uses them to show each
 * factor's contribution to likelihood and how consequence scales the score, so an officer can see
 * exactly why an incident ranks where it does. If the pipeline changes, change these too -
 * model.test.ts checks the score reconstructs.
 */
export type Factor = 'limit_exceedance' | 'hazard_exposure' | 'condition' | 'anomaly';

export const LIKELIHOOD_WEIGHTS: Record<Factor, number> = {
  limit_exceedance: 0.5,
  anomaly: 0.2,
  hazard_exposure: 0.2,
  condition: 0.1,
};

export const FACTOR_LABELS: Record<Factor, string> = {
  limit_exceedance: 'Limit exceedance',
  hazard_exposure: 'Hazard exposure',
  condition: 'Asset condition',
  anomaly: 'Anomaly vs baseline',
};

export const FACTOR_HELP: Record<Factor, string> = {
  limit_exceedance: 'How far the worst metric has moved from normal toward its alarm limit',
  hazard_exposure: 'Inside an active warning, by severity, sector relevance and proximity',
  condition: 'Poor inspection grade (3 to 5), with a penalty when the inspection is overdue',
  anomaly: 'Last two hours against the asset’s own seven-day baseline',
};

export const CONSEQUENCE_FLOOR = 0.7;

export const RISK_RATINGS = [
  { rating: 'extreme', min: 70 },
  { rating: 'high', min: 57 },
  { rating: 'medium', min: 48 },
] as const;

export type Rating = 'extreme' | 'high' | 'medium' | 'low';

export function ratingFor(score: number): Rating {
  return RISK_RATINGS.find((r) => score >= r.min)?.rating ?? 'low';
}

export type FactorScores = Partial<Record<`${Factor}_score`, number | string | null>>;

export interface FactorContribution {
  factor: Factor;
  value: number; // normalised 0-1 factor
  weight: number; // weight in likelihood
  share: number; // contribution to likelihood (0-1)
}

/** Likelihood contributions, largest first. */
export function contributions(scores: FactorScores): FactorContribution[] {
  return (Object.entries(LIKELIHOOD_WEIGHTS) as [Factor, number][])
    .map(([factor, weight]) => {
      const value = Number(scores[`${factor}_score`] ?? 0) || 0;
      return { factor, value, weight, share: weight * value };
    })
    .sort((a, b) => b.share - a.share);
}

/** risk = 100 x likelihood x (floor + (1 - floor) x consequence) */
export function riskScore(likelihood: number, consequence: number): number {
  return Math.round(100 * likelihood * (CONSEQUENCE_FLOOR + (1 - CONSEQUENCE_FLOOR) * consequence));
}

export type Sector = 'roads' | 'rail' | 'water' | 'energy';

export const SECTORS: Sector[] = ['roads', 'rail', 'water', 'energy'];

export const SECTOR_LABELS: Record<Sector, string> = { roads: 'Roads', rail: 'Rail', water: 'Water', energy: 'Energy' };

export const isSector = (value: unknown): value is Sector => typeof value === 'string' && value in SECTOR_LABELS;

export const DISPOSITION_LABELS: Record<string, string> = {
  dispatch: 'Crew dispatched',
  notify: 'Operator notified',
  monitor: 'Monitoring',
};

export const STATUS_LABELS: Record<string, string> = {
  dispatched: 'Crew dispatched',
  notified: 'Operator notified',
  monitoring: 'Monitoring',
};

export const HAZARD_LABELS: Record<string, string> = {
  heatwave: 'Heatwave',
  flood: 'Flood',
  bushfire: 'Bushfire',
  storm: 'Severe storm',
};
