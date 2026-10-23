-- @param data_version STRING
SELECT 'program' AS target_type, program_id AS target_id, program_name AS target_name, sector AS detail
FROM {{schema}}.dim_program WHERE :data_version IS NOT NULL
UNION ALL
SELECT 'project', project_id, project_name, concat(program_name, ' · ', schedule_flexibility, ' · tier ', priority_tier)
FROM {{schema}}.dim_project WHERE :data_version IS NOT NULL
UNION ALL
SELECT 'capacity_category', category_id, capacity_category, unit
FROM {{schema}}.dim_capacity_category WHERE :data_version IS NOT NULL
ORDER BY target_type, target_name;
