-- @param sector STRING
SELECT
  exception.rank,
  exception.program_name,
  exception.exception_type,
  exception.delta_value,
  exception.delta_unit,
  exception.description,
  exception.status
FROM au_pubsec_catalog.budget_planning_and_projections_jared_champion.priority_exceptions exception
LEFT JOIN au_pubsec_catalog.budget_planning_and_projections_jared_champion.portfolio_attention_list attention
  ON attention.program_id = exception.program_id
WHERE (:sector = 'ALL' OR attention.sector = :sector)
ORDER BY exception.rank
LIMIT 5;
