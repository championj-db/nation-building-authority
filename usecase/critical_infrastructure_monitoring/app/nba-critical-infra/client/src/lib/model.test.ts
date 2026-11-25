import { describe, expect, test } from 'vitest';
import { CONSEQUENCE_FLOOR, LIKELIHOOD_WEIGHTS, contributions, ratingFor, riskScore } from './model';

describe('risk engine mirror', () => {
  test('likelihood weights sum to 1, so likelihood is a share of full evidence', () => {
    const total = Object.values(LIKELIHOOD_WEIGHTS).reduce((sum, w) => sum + w, 0);
    expect(total).toBeCloseTo(1, 6);
  });

  test('contributions reconstruct likelihood and sort largest first', () => {
    const parts = contributions({ limit_exceedance_score: 0.95, hazard_exposure_score: 0.7, condition_score: '0.25', anomaly_score: 1 });
    expect(parts.map((p) => p.factor)).toEqual(['limit_exceedance', 'anomaly', 'hazard_exposure', 'condition']);
    const likelihood = parts.reduce((s, p) => s + p.share, 0);
    expect(likelihood).toBeCloseTo(0.5 * 0.95 + 0.2 * 0.7 + 0.1 * 0.25 + 0.2 * 1, 6);
  });

  test('risk scales likelihood by consequence between the floor and 1', () => {
    expect(riskScore(1, 0)).toBe(Math.round(100 * CONSEQUENCE_FLOOR));
    expect(riskScore(1, 1)).toBe(100);
    expect(riskScore(0.5, 0.5)).toBe(43);
  });

  test('ratings match common.RISK_RATINGS', () => {
    expect([ratingFor(90), ratingFor(70), ratingFor(69), ratingFor(57), ratingFor(56), ratingFor(52), ratingFor(51)]).toEqual([
      'extreme', 'extreme', 'high', 'high', 'medium', 'medium', 'low',
    ]);
  });
});
