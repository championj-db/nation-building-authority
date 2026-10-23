-- @param data_version STRING
WITH actions AS (
  SELECT record_id, action, comment, actor, created_at,
         ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY created_at DESC) AS rn,
         COUNT(*) OVER (PARTITION BY record_id) AS action_count
  FROM {{schema}}.assurance_actions
)
SELECT
  register.record_id,
  register.record,
  register.record_type,
  register.owner,
  register.confidence,
  CASE
    WHEN actions.action = 'Attested' AND register.approval_status = 'Awaiting attestation' THEN 'Attested'
    WHEN actions.action = 'Closed' AND register.approval_status = 'Action required' THEN 'Action closed'
    ELSE register.approval_status
  END AS approval_status,
  register.approval_status AS register_status,
  register.version,
  register.last_reviewed,
  register.next_review_due,
  register.evidence_reference,
  register.value_summary,
  actions.action AS last_action,
  actions.comment AS last_action_comment,
  actions.actor AS last_action_actor,
  actions.created_at AS last_action_at,
  COALESCE(actions.action_count, 0) AS action_count
FROM {{schema}}.assurance_register register
LEFT JOIN actions ON actions.record_id = register.record_id AND actions.rn = 1
WHERE :data_version IS NOT NULL
ORDER BY
  CASE register.approval_status WHEN 'Action required' THEN 1 WHEN 'Awaiting attestation' THEN 2 WHEN 'Working' THEN 3 ELSE 4 END,
  register.next_review_due
LIMIT 100;
