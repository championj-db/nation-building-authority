-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param service STRING = public_hospital
-- @param geo_level STRING = sa4
-- @param region_code STRING = 105
-- @param refresh STRING = initial
-- Full note history for one region, newest first.
SELECT note_id, created_ts, officer, evidence_status, next_step, note, threshold_km
FROM IDENTIFIER(:catalog || '.' || :schema || '.app_review_note')
WHERE service_type = :service AND geo_level = :geo_level AND region_code = :region_code AND length(:refresh) >= 0
ORDER BY created_ts DESC
LIMIT 50
