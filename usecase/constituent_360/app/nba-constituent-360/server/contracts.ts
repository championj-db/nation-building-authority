import { z } from 'zod';

export const accessSessionSchema = z.object({
  purpose: z.string().min(1).max(80),
  caseId: z.string().min(1).max(80).nullable().optional(),
  constituentId: z.string().min(1).max(80).nullable().optional(),
  justification: z.string().min(8).max(500),
});

export const recordChangeSchema = z.object({
  changeType: z.enum(['Add case note', 'Assign case owner', 'Update case status', 'Correct contact details', 'Record consent change']),
  details: z.string().min(3).max(2000),
  reasonCode: z.enum(['case_management', 'constituent_request', 'data_correction', 'consent_update']),
});

export const identityDecisionSchema = z.object({
  decision: z.enum(['must_link', 'cannot_link']),
  leftRecordId: z.string().min(1).max(200),
  rightRecordId: z.string().min(1).max(200),
  reason: z.string().min(8).max(1000),
});
