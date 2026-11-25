-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Key freight rail routes for the network map (Department of Infrastructure, CC BY 4.0).
SELECT segment_id, state, display_coords
FROM IDENTIFIER(:catalog || '.' || :schema || '.ref_network_segment')
WHERE mode = 'rail' AND length(:refresh) >= 0
