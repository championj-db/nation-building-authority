SELECT
  record_id,
  record,
  record_type,
  owner,
  confidence,
  approval_status,
  version,
  last_reviewed,
  next_review_due,
  evidence_reference,
  value_summary
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.assurance_register
ORDER BY
  CASE approval_status WHEN 'Action required' THEN 1 WHEN 'Awaiting attestation' THEN 2 WHEN 'Working' THEN 3 ELSE 4 END,
  next_review_due
LIMIT 100;
