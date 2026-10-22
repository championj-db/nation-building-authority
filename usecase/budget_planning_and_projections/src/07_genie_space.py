# Databricks notebook source
# MAGIC %md
# MAGIC # 07 Portfolio Genie space
# MAGIC
# MAGIC Creates or updates the **Portfolio Genie** agent over the governed gold tables, so planners can ask
# MAGIC natural-language questions about cost, timing and capacity (design: "Ask portfolio data" panel).
# MAGIC
# MAGIC * Idempotent: the space id is kept in `pipeline_control` (`genie_space_id`); re-runs update the same
# MAGIC   space, and a deleted space is recreated.
# MAGIC * Every example SQL is executed against the current tables before publishing, so a schema change
# MAGIC   fails this task rather than shipping a broken agent.
# MAGIC * Table names are resolved from the `catalog` / `schema` parameters - nothing is hard-coded.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("space_title", "Portfolio Genie - Budget Planning & Projections")
dbutils.widgets.text("parent_path", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
warehouse_id = dbutils.widgets.get("warehouse_id")
title = dbutils.widgets.get("space_title")
parent_path = dbutils.widgets.get("parent_path") or None
assert warehouse_id, "warehouse_id is required"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

from databricks.sdk import WorkspaceClient

ctx = run_context()
H0, HORIZON = ctx["h0"], ctx["horizon"]
T = {t: table_name(t) for t in (
    "dim_project", "dim_program", "dim_financial_year", "dim_scenario", "dim_capacity_category", "expenditure_fy",
    "portfolio_capacity_fy", "capacity_demand", "capacity_exposure", "project_confidence", "scenario_summary",
    "scenario_project_changes", "variance_project", "variance_bridge", "portfolio_attention_list", "priority_exceptions",
    "portfolio_kpis", "assurance_register", "silver_change_register", "forecast_runs")}
horizon_label = f"{fy_label(HORIZON[0])}-{fy_label(HORIZON[-1])}"

INSTRUCTIONS = f"""You are the Portfolio Genie for the Nation Building Authority (NBA), answering questions from budget planners and portfolio executives about the national infrastructure portfolio: multi-year expenditure, scenarios, delivery-market capacity, variance and assurance.

Financial years follow the Australian Government convention: 1 July - 30 June, labelled by the year in which they END (FY{str(H0)[-2:]} = 1 July {H0 - 1} - 30 June {H0}). Use the financial_year column (e.g. '{fy_label(H0)}') and fy (integer end year). The five-year planning horizon is {horizon_label}; filter is_horizon = true for 'the horizon', 'the forward estimates' or 'five years'. The current financial year is {fy_label(H0)}.

Money: all *_aud_m columns are AUD millions, nominal (then-year) dollars. *_real_aud_m columns are real terms at constant {fy_label(H0)} prices. Present large values in $bn with one decimal (divide by 1000). Never add nominal and real values together.

Scenarios: always filter scenario_id. Default to scenario_id = 'BASE' (Working baseline = the current forecast) unless the user names a scenario. ENDORSED = endorsed plan, CAP_BAL = Capacity balanced (capacity-aware sequencing), ACCEL = Accelerated delivery. scenario_summary has one row per scenario for comparisons. Plan = endorsed plan; forecast = scenario forecast; actual = recorded ledger actuals (closed months only).

Capacity: capacity_demand holds demand vs modelled supply per input category and year; utilisation_pct >= 90 is 'Constrained' and > 100 is 'Breach'. 'Labour' means capacity_category = 'Skilled civil labour' unless the user says electrical trades. 'Equipment' or 'long-lead equipment' means 'Electrical equipment'. For 'which projects are most exposed to X' use capacity_exposure: rank by gap_value_aud_m (attributed share of the capacity gap) and show share_of_demand_pct. portfolio_capacity_fy has the portfolio deliverable-spend line (capacity_aud_m) and the gap (capacity_gap_aud_m).

Variance: variance_bridge attributes forecast minus plan to Escalation, Schedule shift, Scope change, Packaging and Unexplained (they sum to the variance). Filter scope_level ('portfolio','sector','program','project') and period ('YTD','CURRENT_FY','HORIZON'); default period = 'HORIZON'. 'Unexplained' means not explained by any recorded driver. variance_project has per-project tolerance tests and attention flags.

Assurance: Gateway ratings run Green, Amber/Green, Amber, Amber/Red, Red (gateway_rating_rank 1-5, higher is worse). assurance_register lists assumptions and reviews with owner, confidence and approval_status. Change requests with status 'Pending' are not in the forecast.

All figures are working figures (figure_status) for portfolio planning, not published budget figures. All data is synthetic. Always state the scenario and financial year(s) used, and round sensibly."""

EXAMPLES = [
    ("Which projects are most exposed to skilled labour capacity in the peak year?",
     f"""SELECT e.financial_year, e.project_name, e.program_name,
       ROUND(e.gap_value_aud_m, 1) AS labour_gap_aud_m,
       ROUND(e.share_of_demand_pct, 1) AS share_of_labour_demand_pct,
       ROUND(100 * e.gap_value_aud_m / SUM(e.gap_value_aud_m) OVER (), 1) AS share_of_labour_gap_pct
FROM {T['capacity_exposure']} e
WHERE e.scenario_id = 'BASE' AND e.capacity_category = 'Skilled civil labour'
  AND e.financial_year = (SELECT financial_year FROM {T['capacity_demand']}
                          WHERE scenario_id = 'BASE' AND capacity_category = 'Skilled civil labour'
                          ORDER BY utilisation_pct DESC LIMIT 1)
ORDER BY e.gap_value_aud_m DESC
LIMIT 10"""),
    ("What is forecast expenditure by financial year compared with the endorsed plan?",
     f"""SELECT financial_year,
       ROUND(SUM(plan_aud_m) / 1000, 1) AS plan_aud_bn,
       ROUND(SUM(forecast_aud_m) / 1000, 1) AS forecast_aud_bn,
       ROUND(SUM(forecast_aud_m - plan_aud_m) / 1000, 1) AS variance_aud_bn
FROM {T['expenditure_fy']}
WHERE scenario_id = 'BASE' AND is_horizon
GROUP BY financial_year, fy
ORDER BY fy"""),
    ("Compare the scenarios on cost, affordability, confidence and capacity breaches",
     f"""SELECT scenario_name, horizon_label,
       ROUND(total_forecast_aud_m / 1000, 1) AS forecast_aud_bn,
       ROUND(vs_baseline_aud_m / 1000, 1) AS vs_baseline_aud_bn,
       ROUND(headroom_aud_m / 1000, 1) AS envelope_headroom_aud_bn,
       ROUND(forecast_confidence_pct, 0) AS confidence_pct,
       capacity_breaches, ROUND(peak_utilisation_pct, 0) AS peak_utilisation_pct, peak_category,
       projects_changed, regional_completions_deferred
FROM {T['scenario_summary']}
ORDER BY total_forecast_aud_m DESC"""),
    ("What explains the variance between plan and forecast over the horizon?",
     f"""SELECT driver, ROUND(amount_aud_m / 1000, 2) AS amount_aud_bn
FROM {T['variance_bridge']}
WHERE scope_level = 'portfolio' AND period = 'HORIZON'
ORDER BY driver_order"""),
    ("Which programs need executive attention?",
     f"""SELECT rank, program_name, assurance_rating,
       ROUND(plan_aud_m / 1000, 1) AS plan_aud_bn, ROUND(forecast_aud_m / 1000, 1) AS forecast_aud_bn,
       ROUND(variance_aud_m / 1000, 2) AS variance_aud_bn, capacity_driver, max_slip_months, ROUND(confidence_pct, 0) AS confidence_pct
FROM {T['portfolio_attention_list']}
WHERE requires_attention
ORDER BY rank"""),
    ("Which delivery inputs are constrained or in breach, and when?",
     f"""SELECT financial_year, capacity_category, ROUND(utilisation_pct, 0) AS utilisation_pct, status,
       ROUND(gap_units, 0) AS gap_units, unit
FROM {T['capacity_demand']}
WHERE scenario_id = 'BASE' AND status <> 'Within capacity'
ORDER BY fy, utilisation_pct DESC"""),
    ("Which projects are re-sequenced in the Capacity balanced scenario and why?",
     f"""SELECT project_name, program_name, finish_shift_months, ROUND(delta_aud_m, 0) AS horizon_delta_aud_m,
       completion_moves_beyond_horizon, region_type, changes
FROM {T['scenario_project_changes']}
WHERE scenario_id = 'CAP_BAL'
ORDER BY delta_aud_m"""),
    ("What are the top priority exceptions?",
     f"""SELECT rank, program_name, exception_type, ROUND(delta_value, 0) AS delta, delta_unit, description
FROM {T['priority_exceptions']}
ORDER BY rank
LIMIT 10"""),
    ("Which assumptions or reviews are awaiting attestation or need action?",
     f"""SELECT record, record_type, owner, confidence, approval_status, last_reviewed, next_review_due
FROM {T['assurance_register']}
WHERE approval_status IN ('Awaiting attestation', 'Action required')
ORDER BY next_review_due"""),
    ("Show the horizon forecast in nominal and real terms by year",
     f"""SELECT financial_year,
       ROUND(SUM(forecast_aud_m) / 1000, 1) AS nominal_aud_bn,
       ROUND(SUM(forecast_real_aud_m) / 1000, 1) AS real_aud_bn
FROM {T['expenditure_fy']}
WHERE scenario_id = 'BASE' AND is_horizon
GROUP BY financial_year, fy
ORDER BY fy"""),
]
SAMPLE_QUESTIONS = [
    "Which projects are most exposed to skilled labour capacity in the peak year?",
    f"How does the Capacity balanced scenario change {fy_label(HORIZON[2])} expenditure?",
    "What explains the variance between plan and forecast over the horizon?",
    "Which programs need executive attention?",
    "Compare the scenarios on cost, confidence and capacity breaches",
]

# Validate every example against the live tables before publishing.
for q, sql in EXAMPLES:
    n = spark.sql(sql).count()
    print(f"{n:>4} rows  {q}")
    assert n > 0, f"example returned no rows: {q}"

# COMMAND ----------


def hex_id(prefix: int, i: int) -> str:
    return f"{prefix}{i:031d}"


space = {
    "version": 2,
    "config": {"sample_questions": [{"id": hex_id(1, i), "question": [q]} for i, q in enumerate(SAMPLE_QUESTIONS, 1)]},
    "data_sources": {"tables": [{"identifier": t} for t in sorted(T.values())]},
    "instructions": {
        "text_instructions": [{"id": hex_id(3, 1), "content": [line + "\n" for line in INSTRUCTIONS.split("\n")]}],
        "example_question_sqls": [{"id": hex_id(2, i), "question": [q], "sql": [line + "\n" for line in sql.split("\n")]}
                                  for i, (q, sql) in enumerate(EXAMPLES, 1)],
    },
}
description = ("Ask about the national infrastructure portfolio: multi-year expenditure, scenarios, delivery-market capacity, "
               f"variance and assurance. Horizon {horizon_label}. Working figures, synthetic data.")

w = WorkspaceClient()
space_id = get_control("genie_space_id")
existing = None
if space_id:
    try:
        existing = w.genie.get_space(space_id)
    except Exception as e:  # deleted or no longer accessible: recreate
        print(f"stored space {space_id} not available ({type(e).__name__}); recreating")
if not existing:  # e.g. after a reset dropped pipeline_control: reuse a space with the same title
    token = None
    while not existing:
        page = w.genie.list_spaces(page_size=100, page_token=token)
        existing = next((s for s in (page.spaces or []) if s.title == title), None)
        token = page.next_page_token
        if not token:
            break
    if existing:
        space_id = existing.space_id
        set_control("genie_space_id", space_id)
if existing:
    w.genie.update_space(space_id, serialized_space=json.dumps(space), title=title, description=description, warehouse_id=warehouse_id)
    print(f"updated Genie space {space_id}")
else:
    created = w.genie.create_space(warehouse_id=warehouse_id, serialized_space=json.dumps(space), title=title,
                                   description=description, parent_path=parent_path)
    space_id = created.space_id
    set_control("genie_space_id", space_id)
    print(f"created Genie space {space_id}")
try:
    dbutils.jobs.taskValues.set("genie_space_id", space_id)
except Exception:
    pass
