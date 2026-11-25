-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = critical_infrastructure_ops_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- @param asset_id BIGINT = 0
-- Recent resolved sightings for one asset: the "recent movement" evidence in the review dialog.
SELECT
  sighting_id,
  event_ts,
  road_name,
  locality,
  state,
  source_type,
  speed_kph,
  mass_ratio,
  is_night,
  is_rest_window,
  resolution_method,
  sighted_plate_raw
FROM IDENTIFIER(:catalog || '.' || :schema || '.silver_sighting')
WHERE asset_id = :asset_id
  AND event_ts <= current_timestamp()
  AND length(:refresh) >= 0
ORDER BY event_ts DESC
LIMIT 8
