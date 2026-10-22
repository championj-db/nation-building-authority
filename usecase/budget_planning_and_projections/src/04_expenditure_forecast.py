# Databricks notebook source
# MAGIC %md
# MAGIC # 04 Expenditure forecast - Working baseline
# MAGIC
# MAGIC Projects multi-year expenditure for every project from the conformed portfolio model. The forecast
# MAGIC is built in **recorded, attributable stages** (see `_common` engine), each kept as a column so the
# MAGIC variance report can explain every dollar between plan and forecast:
# MAGIC
# MAGIC | Stage | Source of the adjustment |
# MAGIC | --- | --- |
# MAGIC | `plan_aud_m` | Endorsed plan phasing (`silver_plan_phasing`, latest endorsed version) |
# MAGIC | `schedule_aud_m` | Approved **Schedule** changes: slip months and delay cost (`silver_change_register`) |
# MAGIC | `escalation_aud_m` | Current vs endorsed escalation by sector (`silver_escalation_rates`) on unspent work |
# MAGIC | `scope_aud_m` | Approved **Scope** changes |
# MAGIC | `packaging_aud_m` | Approved **Packaging** changes |
# MAGIC | `forecast_aud_m` | Actuals for closed months; thereafter packaging stage x (1 + trailing cost performance) |
# MAGIC
# MAGIC Outputs: `forecast_stages_monthly`, `forecast_project_drivers`, `dim_project`, `dim_program`,
# MAGIC `dim_financial_year`, and the run context (run id, as-of, actuals cut-off, horizon) for the
# MAGIC downstream scenario, capacity and variance tasks.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("run_type", "scheduled")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("horizon_years", "5")
dbutils.widgets.text("performance_window_months", "12")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = dbutils.widgets.get("run_id") or new_run_id()
run_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
run_type = dbutils.widgets.get("run_type")
horizon_years = int(dbutils.widgets.get("horizon_years"))
perf_window = int(dbutils.widgets.get("performance_window_months"))
as_of = (date.fromisoformat(dbutils.widgets.get("as_of_date")) if dbutils.widgets.get("as_of_date")
         else datetime.now(timezone.utc).date())


def silver(t: str) -> pd.DataFrame:
    return spark.table(table_name(t)).toPandas()


projects = silver("silver_projects")
programs = silver("silver_programs")
plan_versions = silver("silver_plan_versions")
plan_version = (plan_versions[plan_versions.status == "Endorsed"].sort_values(["approved_date", "version"]).iloc[-1].plan_version)
phasing = spark.table(table_name("silver_plan_phasing")).filter(F.col("plan_version") == plan_version).toPandas()
actuals = (spark.table(table_name("silver_actuals_monthly")).groupBy("project_id", "month")
           .agg(F.sum("actual_aud_m").alias("actual_aud_m")).toPandas())
changes = silver("silver_change_register")
escalation = silver("silver_escalation_rates")
deflator = silver("silver_price_deflator")
reviews = silver("silver_gateway_reviews")

# Actuals cut-off: the last closed month delivered by the ledger on or before the as-of date.
closed = actuals[actuals.month.map(lambda d: month_end(month_idx(d)) < as_of)]
actuals_through = month_end(int(closed.month.map(month_idx).max()))
T0 = month_idx(actuals_through) + 1
H0 = int(FY_OF_MONTH[T0])
HORIZON = list(range(H0, H0 + horizon_years))
actuals = actuals[actuals.month.map(month_idx) < T0]
print(f"run_id={run_id} as_of={as_of} plan={plan_version} actuals through {actuals_through}; "
      f"horizon {fy_label(H0)}-{fy_label(HORIZON[-1])}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recorded drivers per project

# COMMAND ----------

approved = changes[(changes.status == "Approved") & (changes.approved_date.map(lambda d: d is not None and d <= as_of))]


def total(ctype: str, col: str) -> pd.Series:
    return approved[approved.change_type == ctype].groupby("project_id")[col].sum()


slip = total("Schedule", "schedule_impact_months")
delay = total("Schedule", "cost_impact_aud_m")
scope = total("Scope", "cost_impact_aud_m")
packaging = total("Packaging", "cost_impact_aud_m")
esc = {s: escalation_factor_by_month(escalation, s, H0) for s in projects.sector.unique()}
plan_paths = to_paths(phasing, ["plan_aud_m"])["plan_aud_m"]
actual_paths = to_paths(actuals, ["actual_aud_m"])["actual_aud_m"] if len(actuals) else {}

stages = {c: {} for c in ("plan_aud_m", "schedule_aud_m", "escalation_aud_m", "scope_aud_m", "packaging_aud_m",
                          "forecast_aud_m", "actual_aud_m")}
driver_rows = []
for r in projects.itertuples():
    pid = r.project_id
    plan = plan_paths.get(pid, np.zeros(N_MONTHS))
    actual = actual_paths.get(pid, np.zeros(N_MONTHS))
    p = explained_paths(plan, T0, slip_months=float(slip.get(pid, 0)), delay_cost=float(delay.get(pid, 0.0)),
                        esc_factor=esc[r.sector], scope=float(scope.get(pid, 0.0)), packaging=float(packaging.get(pid, 0.0)))
    u = performance_factor(actual, p["packaging"], T0, perf_window)
    forecast = np.concatenate([actual[:T0], p["packaging"][T0:] * (1 + u)])
    for stage, key in (("plan", "plan_aud_m"), ("schedule", "schedule_aud_m"), ("escalation", "escalation_aud_m"),
                       ("scope", "scope_aud_m"), ("packaging", "packaging_aud_m")):
        stages[key][pid] = p[stage]
    stages["forecast_aud_m"][pid] = forecast
    stages["actual_aud_m"][pid] = actual
    nz = np.nonzero(forecast > 1e-6)[0]
    pnz = np.nonzero(plan > 1e-6)[0]
    driver_rows.append(dict(
        project_id=pid, slip_months=int(slip.get(pid, 0)), delay_cost_aud_m=float(delay.get(pid, 0.0)),
        approved_scope_aud_m=float(scope.get(pid, 0.0)), approved_packaging_aud_m=float(packaging.get(pid, 0.0)),
        cost_performance_pct=round(u * 100, 2), actual_to_date_aud_m=float(actual[:T0].sum()),
        plan_to_date_aud_m=float(plan[:T0].sum()), eac_plan_aud_m=float(plan.sum()), eac_forecast_aud_m=float(forecast.sum()),
        plan_finish=month_end(int(pnz[-1])) if len(pnz) else None, forecast_finish=month_end(int(nz[-1])) if len(nz) else None,
        pending_changes=int(((changes.project_id == pid) & (changes.status == "Pending")).sum())))
drivers = pd.DataFrame(driver_rows)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write the Working baseline forecast

# COMMAND ----------

defl = deflator_index(deflator, H0)
rows = paths_to_rows(stages, list(stages), extra={"run_id": run_id, "scenario_id": "BASE"})
for c in ("plan_aud_m", "forecast_aud_m", "actual_aud_m"):
    rows[c.replace("_aud_m", "_real_aud_m")] = rows[c] / rows.fy.map(defl)
rows["is_actual_month"] = rows.month.map(lambda d: month_idx(d) < T0)
rows["is_horizon"] = rows.fy.isin(HORIZON)
write_table(rows, "forecast_stages_monthly",
            "Working baseline (BASE) monthly forecast by project with every attributable stage from plan to forecast (AUD m, nominal; real columns at constant first-horizon-year prices).",
            {"schedule_aud_m": "Plan after approved schedule changes (slip / acceleration) and their delay cost.",
             "escalation_aud_m": "Schedule stage after current vs endorsed escalation on unspent work.",
             "scope_aud_m": "Escalation stage plus approved scope changes.",
             "packaging_aud_m": "Scope stage plus approved packaging changes = fully explained forecast.",
             "is_actual_month": "True when the month is closed and forecast equals recorded actuals.",
             "is_horizon": "True when the month falls in the five-year planning horizon."},
            tags={"nba_layer": "gold"})

drivers["run_id"] = run_id
write_table(drivers, "forecast_project_drivers", "Recorded forecast drivers per project for the Working baseline: approved changes, cost performance, EAC and finish dates.",
            {"slip_months": "Approved schedule slip, months.", "cost_performance_pct": "Trailing 12-month actual vs explained spend, % (positive = overrunning); carried onto unspent work as the unexplained driver.",
             "eac_forecast_aud_m": "Estimate at completion, AUD m nominal.", "eac_plan_aud_m": "Endorsed total cost (plan), AUD m nominal.",
             "pending_changes": "Change requests under assessment - not in the forecast."}, tags={"nba_layer": "gold"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Dimensions

# COMMAND ----------

RATING_CONFIDENCE = {"Green": 0.92, "Amber/Green": 0.82, "Amber": 0.68, "Amber/Red": 0.52, "Red": 0.35}
RATING_ORDER = {"Green": 1, "Amber/Green": 2, "Amber": 3, "Amber/Red": 4, "Red": 5}
STAGE_ADJ = {"Planning": -0.05, "Procurement": -0.02, "Delivery": 0.0, "Commissioning": 0.02}
latest_rv = reviews[reviews.is_latest][["project_id", "gate", "gate_name", "delivery_confidence", "report_date"]].rename(
    columns={"gate": "latest_gate", "gate_name": "latest_gate_name", "delivery_confidence": "gateway_rating", "report_date": "gateway_report_date"})
dim_project = (projects.drop(columns=["_delivery_date", "_source_file"])
               .merge(programs[["program_id", "program_name"]], on="program_id")
               .merge(latest_rv, on="project_id", how="left")
               .merge(drivers.drop(columns=["run_id"]), on="project_id"))
dim_project["gateway_rating_rank"] = dim_project.gateway_rating.map(RATING_ORDER)
dim_project["base_confidence_pct"] = ((dim_project.gateway_rating.map(RATING_CONFIDENCE) + dim_project.lifecycle_stage.map(STAGE_ADJ))
                                      .clip(0.2, 0.97) * 100).round(1)
dim_project["percent_complete"] = (dim_project.actual_to_date_aud_m / dim_project.eac_forecast_aud_m * 100).round(1)
dim_project["run_id"] = run_id
write_table(dim_project, "dim_project", "Project dimension: register attributes, latest Gateway rating, assurance-weighted base confidence and Working baseline forecast drivers.",
            {"gateway_rating": "Latest Gateway delivery confidence: Green, Amber/Green, Amber, Amber/Red, Red.",
             "gateway_rating_rank": "1 = Green ... 5 = Red (higher is worse).",
             "base_confidence_pct": "Forecast confidence before capacity effects: Gateway rating weight adjusted for lifecycle stage.",
             "percent_complete": "Actual to date / forecast EAC, %.", "region_type": "Metropolitan, Regional or Remote - where benefits accrue."},
            tags={"nba_layer": "gold"})

prog_dim = (dim_project.groupby(["program_id", "program_name", "sector", "subsector"], as_index=False)
            .agg(projects=("project_id", "count"), tec_p50_aud_m=("tec_p50_aud_m", "sum"), eac_forecast_aud_m=("eac_forecast_aud_m", "sum"),
                 worst_gateway_rank=("gateway_rating_rank", "max"), max_slip_months=("slip_months", "max")))
inv_rank = {v: k for k, v in RATING_ORDER.items()}
prog_dim["worst_gateway_rating"] = prog_dim.worst_gateway_rank.map(inv_rank)
prog_dim = prog_dim.merge(programs[["program_id", "lead_jurisdiction", "delivery_agency", "program_executive"]], on="program_id")
prog_dim["run_id"] = run_id
write_table(prog_dim, "dim_program", "Program dimension with project counts, cost and worst Gateway rating across its projects.",
            {"worst_gateway_rating": "Worst latest Gateway rating among the program's projects."}, tags={"nba_layer": "gold"})

fy_dim = pd.DataFrame([dict(fy=fy, financial_year=fy_label(fy), financial_year_long=fy_long(fy), fy_start=fy_start(fy), fy_end=fy_end(fy),
                            is_current=fy == H0, is_horizon=fy in HORIZON, horizon_year=(fy - H0 + 1) if fy in HORIZON else None,
                            price_index=defl.get(fy)) for fy in range(int(FY_OF_MONTH.min()), int(FY_OF_MONTH.max()) + 1)])
write_table(fy_dim, "dim_financial_year", "Australian Government financial years (1 July - 30 June, labelled by the year they end) with horizon flags and the real-terms price index.",
            {"price_index": "CPI-based index, 1.0 in the first horizon year. real = nominal / price_index.",
             "is_current": "The financial year containing the first forecast month."}, tags={"nba_layer": "gold"})

# COMMAND ----------

for k, v in {"current_run_id": run_id, "forecast_as_of": as_of.isoformat(), "actuals_through": actuals_through.isoformat(),
             "horizon_start_fy": H0, "horizon_years": horizon_years, "plan_version": plan_version, "run_type": run_type,
             "run_started_at": run_started_at, "performance_window_months": perf_window}.items():
    set_control(k, v)
w_ = WINDOW = np.isin(FY_OF_MONTH, HORIZON)
plan_h = sum(a[w_].sum() for a in stages["plan_aud_m"].values())
fc_h = sum(a[w_].sum() for a in stages["forecast_aud_m"].values())
print(f"Horizon plan ${plan_h / 1000:,.1f}bn, forecast ${fc_h / 1000:,.1f}bn ({(fc_h - plan_h) / 1000:+,.1f}bn)")
for fy in HORIZON:
    m = FY_OF_MONTH == fy
    print(f"  {fy_label(fy)} plan {sum(a[m].sum() for a in stages['plan_aud_m'].values()) / 1000:6.1f}  "
          f"forecast {sum(a[m].sum() for a in stages['forecast_aud_m'].values()) / 1000:6.1f}")
