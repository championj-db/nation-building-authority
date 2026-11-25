-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Highest-risk assets across all sectors, incident or not.
SELECT asset_id, asset_code, asset_name, asset_class_label, sector, operator_name, locality, state,
       risk_score, risk_rating, priority, dominant_factor, trigger_metric_label, likelihood,
       consequence_score, people_affected, minutes_since_reading, incident_threshold, run_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_asset_risk')
WHERE length(:refresh) >= 0
ORDER BY risk_score DESC, people_affected DESC
LIMIT 12
