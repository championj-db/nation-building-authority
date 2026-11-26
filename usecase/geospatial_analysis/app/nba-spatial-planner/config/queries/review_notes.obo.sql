-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param service STRING = public_hospital
-- @param geo_level STRING = sa4
-- @param refresh STRING = initial
-- Latest officer review note per region (the evidence queue status), with how many notes the
-- region has. refresh changes after a write so the per-user result cache is bypassed.
SELECT region_code, region_name, evidence_status, next_step, note, officer, created_ts, threshold_km,
       count(*) OVER (PARTITION BY region_code) AS note_count
FROM IDENTIFIER(:catalog || '.' || :schema || '.app_review_note')
WHERE service_type = :service AND geo_level = :geo_level AND length(:refresh) >= 0
QUALIFY row_number() OVER (PARTITION BY region_code ORDER BY created_ts DESC) = 1
