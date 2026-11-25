/**
 * The transparent rules engine's weights, mirrored from src/common.py (FACTOR_WEIGHTS and
 * SEVERITY_BANDS, model transparent-rules-v2). The review dialog uses them to show each factor's weighted contribution to
 * the score, so an officer can see exactly why an entity scored as it did. If the pipeline's
 * weights change, change them here too - tests/model.test.ts checks the score reconstructs.
 */
export type RiskType = 'fatigue' | 'roadworthiness' | 'mass' | 'route';
export type Factor =
  | 'rest_window_anomaly'
  | 'night_movement'
  | 'recent_pattern'
  | 'route_variance'
  | 'mass_variance'
  | 'defect_history';

export const FACTOR_WEIGHTS: Record<RiskType, Partial<Record<Factor, number>>> = {
  fatigue: { rest_window_anomaly: 0.4, night_movement: 0.3, recent_pattern: 0.2, route_variance: 0.1 },
  roadworthiness: {
    defect_history: 0.7,
    recent_pattern: 0.15,
    night_movement: 0.05,
    rest_window_anomaly: 0.05,
    route_variance: 0.05,
  },
  mass: { mass_variance: 0.7, recent_pattern: 0.15, route_variance: 0.1, night_movement: 0.05 },
  route: { route_variance: 0.7, recent_pattern: 0.15, night_movement: 0.1, rest_window_anomaly: 0.05 },
};

export const SEVERITY_BANDS = { critical: 85, high: 75 } as const;

export type FactorScores = Partial<Record<`${Factor}_score`, number | string | null>>;

export interface FactorContribution {
  factor: Factor;
  value: number; // normalised 0-1 factor
  weight: number; // weight in this risk type
  points: number; // contribution to the 0-100 score
}

const isRiskType = (value: string): value is RiskType => value in FACTOR_WEIGHTS;

/** Contributions for the entity's risk type, largest first. */
export function contributions(riskType: string, scores: FactorScores): FactorContribution[] {
  if (!isRiskType(riskType)) return [];
  return Object.entries(FACTOR_WEIGHTS[riskType])
    .map(([factor, weight]) => {
      const value = Number(scores[`${factor as Factor}_score`] ?? 0) || 0;
      return { factor: factor as Factor, value, weight: weight ?? 0, points: 100 * (weight ?? 0) * value };
    })
    .sort((a, b) => b.points - a.points);
}

export function severityFor(score: number): 'critical' | 'high' | 'medium' {
  if (score >= SEVERITY_BANDS.critical) return 'critical';
  if (score >= SEVERITY_BANDS.high) return 'high';
  return 'medium';
}
