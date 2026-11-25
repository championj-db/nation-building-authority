-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = automated_compliance_reporting_jared_champion
-- @param refresh STRING = 0
-- refresh only varies the cache key so the app can re-read after a report or verification run.
SELECT event_seq, event_id, event_type, entity_type, entity_id, related_id, summary, actor, occurred_at, recorded_at,
       payload, prev_hash, event_hash
FROM IDENTIFIER(:catalog || '.' || :schema || '.audit_events')
WHERE :refresh IS NOT NULL
ORDER BY event_seq DESC
LIMIT 1000;
