-- @param data_version STRING
SELECT * EXCEPT (rn) FROM (
  SELECT
    pack_id, version, title, scenario_id, forecast_run_id, narrative, status, model, actor, created_at,
    ROW_NUMBER() OVER (PARTITION BY pack_id ORDER BY version DESC) AS rn
  FROM {{schema}}.briefing_packs
  WHERE :data_version IS NOT NULL
) WHERE rn = 1
ORDER BY created_at DESC
LIMIT 20;
