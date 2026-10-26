import { describe, expect, test } from 'vitest';
import { accessSessionSchema, identityDecisionSchema, recordChangeSchema } from './contracts.js';

describe('governed mutation contracts', () => {
  test('requires a meaningful session justification', () => {
    expect(accessSessionSchema.safeParse({ purpose: 'housing_case_support', caseId: 'CASE-1', justification: 'short' }).success).toBe(false);
  });

  test('rejects direct or unknown change types', () => {
    expect(recordChangeSchema.safeParse({ changeType: 'Direct source update', details: 'Change it', reasonCode: 'case_management' }).success).toBe(false);
  });

  test('allows only durable identity decisions', () => {
    expect(identityDecisionSchema.safeParse({ decision: 'review', leftRecordId: 'A', rightRecordId: 'B', reason: 'Needs steward review' }).success).toBe(false);
  });
});
