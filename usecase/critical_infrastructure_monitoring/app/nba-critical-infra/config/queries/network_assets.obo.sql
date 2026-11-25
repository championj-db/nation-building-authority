-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Every monitored asset, for the network map (about 600 rows, small enough to send whole).
SELECT asset_id, asset_code, asset_name, asset_class_label, sector, state, latitude, longitude,
       risk_score, risk_rating, priority, people_served
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_asset_risk')
WHERE length(:refresh) >= 0
