-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- For every open incident on the road or rail network: the section its failure closes and the
-- detour around it (or the localities cut off), with geometry for the map.
SELECT incident_id, asset_id, risk_rating, sector, network_mode, route_name, network_effect,
       section_from, section_to, section_km, detour_extra_km, detour_via, no_alternative,
       localities_cut, section_coords, detour_coords
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_network_disruption')
WHERE length(:refresh) >= 0
