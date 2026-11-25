-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Downstream assets for every open incident: "if this fails" in the review dialog, and the
-- cascade lines on the network map.
SELECT incident_id, asset_id, downstream_asset_id, hop, dependency_type, asset_code, asset_name,
       asset_class_label, sector, locality, state, latitude, longitude, people_served,
       downstream_risk_score
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_incident_impact')
WHERE length(:refresh) >= 0
ORDER BY incident_id, hop, people_served DESC
