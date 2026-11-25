-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Hourly sightings of alerting assets over the last 24 hours of the latest run.
SELECT hour_ts, risk_sightings
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_risk_signal_trend')
WHERE length(:refresh) >= 0
ORDER BY hour_ts
