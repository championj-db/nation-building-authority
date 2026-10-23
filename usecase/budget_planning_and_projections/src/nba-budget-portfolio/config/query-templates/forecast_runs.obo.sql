-- @param data_version STRING
SELECT run_id, run_type, as_of_date, actuals_through, plan_version, capacity_model_version, scenario_versions, started_at, completed_at, status
FROM {{schema}}.forecast_runs
WHERE :data_version IS NOT NULL
ORDER BY started_at DESC
LIMIT 10;
