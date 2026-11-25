-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- @param asset_id BIGINT = 0
-- @param metric STRING = transformer_temp_c
-- The last 24 hours of the triggering metric for one asset: the evidence chart in the review dialog.
SELECT event_ts, value, warn_limit, alarm_limit, unit, metric_label, direction
FROM IDENTIFIER(:catalog || '.' || :schema || '.silver_reading')
WHERE asset_id = :asset_id
  AND metric = :metric
  AND event_ts >= current_timestamp() - INTERVAL 24 HOURS
  AND length(:refresh) >= 0
ORDER BY event_ts
