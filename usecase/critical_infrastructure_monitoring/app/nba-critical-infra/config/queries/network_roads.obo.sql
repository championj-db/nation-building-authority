-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Key freight road routes for the network map (Department of Infrastructure, CC BY 4.0).
-- display_coords is JSON: a list of parts, each a list of [lon, lat], simplified to about 1 km.
SELECT segment_id, name, route_no, display_coords
FROM IDENTIFIER(:catalog || '.' || :schema || '.ref_network_segment')
WHERE mode = 'road' AND length(:refresh) >= 0
