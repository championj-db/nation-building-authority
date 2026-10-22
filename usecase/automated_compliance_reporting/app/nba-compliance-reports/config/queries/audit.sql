-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
WITH latest_verification AS (
  SELECT status, verified_at, events_checked, head_seq, head_hash, detail
  FROM IDENTIFIER(:catalog || '.' || :schema || '.audit_chain_verifications')
  ORDER BY verified_at DESC LIMIT 1
), recent_events AS (
  SELECT event_seq, event_type, entity_id, summary, actor, occurred_at, event_hash
  FROM IDENTIFIER(:catalog || '.' || :schema || '.audit_events')
  ORDER BY event_seq DESC LIMIT 50
)
SELECT e.*, v.status AS chain_status, v.verified_at, v.events_checked, v.head_seq,
       v.head_hash, v.detail AS verification_detail
FROM recent_events e CROSS JOIN latest_verification v
ORDER BY e.event_seq DESC;
