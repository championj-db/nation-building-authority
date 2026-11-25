-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = infrastructure_operations_jared_champion
-- @param refresh STRING = initial
-- The sample values above are used only by `appkit generate-types` to DESCRIBE the query.
-- At runtime the client binds the catalog/schema the server reads from app config, and a
-- refresh token that changes on every manual refresh so the per-user result cache is bypassed.
-- One row per sector for the sector health tiles.
SELECT sector, sector_label, assets, assets_in_alarm, assets_not_reporting, open_incidents,
       extreme_incidents, dependants_at_risk, run_ts
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_sector_status')
WHERE length(:refresh) >= 0
ORDER BY CASE sector WHEN 'roads' THEN 1 WHEN 'rail' THEN 2 WHEN 'water' THEN 3 ELSE 4 END
