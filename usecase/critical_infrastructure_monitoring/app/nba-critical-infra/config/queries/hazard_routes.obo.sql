-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- Key freight route kilometres inside each active warning: the routes each warning threatens.
SELECT warning_id, mode, route_name, km_inside
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_hazard_network_exposure')
WHERE length(:refresh) >= 0
  AND km_inside >= 5
QUALIFY row_number() OVER (PARTITION BY warning_id ORDER BY km_inside DESC) <= 4
ORDER BY warning_id, km_inside DESC
