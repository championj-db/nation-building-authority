-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Major rivers as map context (Natural Earth, public domain).
SELECT river_id, name, intermittent, display_coords
FROM IDENTIFIER(:catalog || '.' || :schema || '.ref_river')
WHERE length(:refresh) >= 0
