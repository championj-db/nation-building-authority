-- @param scenario_id STRING
-- @param data_version STRING
-- Levers on the latest saved version, and the scenario's workflow history.
WITH latest AS (
  SELECT MAX(version) AS version FROM {{schema}}.scenario_definitions WHERE scenario_id = :scenario_id
)
SELECT
  'lever' AS record_kind,
  lever.lever_id AS record_id,
  lever.scenario_version AS version,
  lever.lever_type AS label,
  lever.target_type,
  lever.target_id,
  COALESCE(program.program_name, project.project_name, category.capacity_category, lever.target_id, 'Whole portfolio') AS target_name,
  lever.value,
  lever.rationale AS note,
  lever.created_by AS actor,
  lever.created_at,
  CAST(NULL AS BIGINT) AS job_run_id
FROM {{schema}}.scenario_levers lever
JOIN latest ON lever.scenario_version = latest.version
LEFT JOIN {{schema}}.dim_program program ON lever.target_type = 'program' AND program.program_id = lever.target_id
LEFT JOIN {{schema}}.dim_project project ON lever.target_type = 'project' AND project.project_id = lever.target_id
LEFT JOIN {{schema}}.dim_capacity_category category ON lever.target_type = 'capacity_category' AND category.category_id = lever.target_id
WHERE lever.scenario_id = :scenario_id AND :data_version IS NOT NULL
UNION ALL
SELECT
  'event', event_id, scenario_version, event, NULL, NULL, NULL, NULL, note, actor, created_at, job_run_id
FROM {{schema}}.scenario_events
WHERE scenario_id = :scenario_id AND :data_version IS NOT NULL
ORDER BY record_kind DESC, created_at DESC;
