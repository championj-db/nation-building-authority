import { describe, expect, test } from 'vitest';
import { FACTOR_WEIGHTS, contributions, severityFor } from './model';

describe('scoring model mirror', () => {
  test('each risk type weights sum to 1, so a score is a share of 100', () => {
    for (const weights of Object.values(FACTOR_WEIGHTS)) {
      const total = Object.values(weights).reduce((sum, w) => sum + (w ?? 0), 0);
      expect(total).toBeCloseTo(1, 6);
    }
  });

  test('contributions reconstruct the pipeline score and sort largest first', () => {
    const parts = contributions('fatigue', {
      rest_window_anomaly_score: 0.86,
      night_movement_score: 0.74,
      recent_pattern_score: 0.61,
      route_variance_score: 0.2,
    });
    expect(parts.map((p) => p.factor)).toEqual(['rest_window_anomaly', 'night_movement', 'recent_pattern', 'route_variance']);
    expect(Math.round(parts.reduce((s, p) => s + p.points, 0))).toBe(Math.round(100 * (0.4 * 0.86 + 0.3 * 0.74 + 0.2 * 0.61 + 0.1 * 0.2)));
  });

  test('string scores from SQL are coerced and unknown types yield nothing', () => {
    const [top] = contributions('mass', { mass_variance_score: '1' });
    expect(top?.factor).toBe('mass_variance');
    expect(top?.points).toBeCloseTo(70, 6);
    expect(contributions('speeding', {})).toEqual([]);
  });

  test('severity bands match common.SEVERITY_BANDS', () => {
    expect([severityFor(92), severityFor(85), severityFor(84), severityFor(75), severityFor(70)]).toEqual(['critical', 'critical', 'high', 'high', 'medium']);
  });
});
