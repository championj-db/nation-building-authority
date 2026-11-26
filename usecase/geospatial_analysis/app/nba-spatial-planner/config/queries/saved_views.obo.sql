-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param refresh STRING = initial
-- Saved analysis views shared across officers. Append-only: a deletion is a newer row with
-- deleted = true, so the latest row per view decides.
SELECT view_id, created_ts, officer, name, settings, officer = current_user() AS is_mine
FROM IDENTIFIER(:catalog || '.' || :schema || '.app_saved_view')
WHERE length(:refresh) >= 0
QUALIFY row_number() OVER (PARTITION BY view_id ORDER BY created_ts DESC) = 1 AND NOT deleted
ORDER BY created_ts DESC
LIMIT 100
