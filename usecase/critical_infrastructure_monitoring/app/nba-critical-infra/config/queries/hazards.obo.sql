-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Active warnings with their footprint and the assets inside it, by sector.
SELECT warning_id, title, hazard_type, hazard_label, severity, centre_lat, centre_lon, radius_km,
       valid_from, valid_to, hours_remaining, exposed_assets, exposed_roads, exposed_rail,
       exposed_water, exposed_energy, people_in_zone, linked_incidents, issuer
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_hazard_status')
WHERE length(:refresh) >= 0
ORDER BY CASE severity WHEN 'extreme' THEN 1 WHEN 'severe' THEN 2 WHEN 'moderate' THEN 3 ELSE 4 END,
         linked_incidents DESC
