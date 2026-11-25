import { describe, expect, test } from 'vitest';
import { resolveSchema, reviewDecisionSchema } from './contracts.js';

const valid = { incidentId: '1042:transformer_temp_c', disposition: 'dispatch', evidenceViewed: ['risk_score', 'contributing_factors'] };

describe('reviewDecisionSchema', () => {
  test('accepts a well-formed decision and defaults notes', () => {
    expect(reviewDecisionSchema.parse(valid)).toEqual({ ...valid, notes: '' });
  });

  test.each([
    ['non-numeric asset', { ...valid, incidentId: 'abc:hazard' }],
    ['SQL in the incident id', { ...valid, incidentId: "1'; DROP TABLE x;--" }],
    ['upper-case trigger', { ...valid, incidentId: '1042:HAZARD' }],
    ['unknown disposition', { ...valid, disposition: 'route' }],
    ['no evidence viewed', { ...valid, evidenceViewed: [] }],
    ['unknown evidence', { ...valid, evidenceViewed: ['gut_feel'] }],
    ['oversized notes', { ...valid, notes: 'x'.repeat(501) }],
  ])('rejects %s', (_label, input) => {
    expect(reviewDecisionSchema.safeParse(input).success).toBe(false);
  });
});

describe('resolveSchema', () => {
  test('returns plain identifiers', () => {
    expect(resolveSchema({ DATABRICKS_CATALOG: 'main', DATABRICKS_SCHEMA: 'ops_dev' })).toEqual({ catalog: 'main', schema: 'ops_dev' });
  });
  test.each([{}, { DATABRICKS_CATALOG: 'main' }, { DATABRICKS_CATALOG: 'main', DATABRICKS_SCHEMA: 'a.b' }, { DATABRICKS_CATALOG: 'm`ain', DATABRICKS_SCHEMA: 's' }])(
    'refuses to start with %o',
    (env) => {
      expect(() => resolveSchema(env)).toThrow();
    },
  );
});
