# Databricks notebook source
# MAGIC %md
# MAGIC # Shared helpers - Budget Planning & Financial Projections
# MAGIC
# MAGIC Included by every task with `%run ./_common` after the caller has read its widgets into
# MAGIC `catalog`, `schema` and `volume`. Provides:
# MAGIC
# MAGIC * table / volume naming - nothing environment-specific is hard-coded
# MAGIC * Australian Government financial-year helpers (1 July - 30 June, labelled by the year it ends)
# MAGIC * the **phasing and forecast engine** (S-curve phasing, reschedule, escalation, change spreading).
# MAGIC   The synthetic generator and the forecast task use the same functions, so the forecast can
# MAGIC   only explain the synthetic world through the drivers that are recorded as data
# MAGIC * governed table writes (table + column comments, classification tags) and run control

# COMMAND ----------

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"
assert volume, "volume parameter is required"

spark.conf.set("spark.sql.session.timeZone", "UTC")


def fqn(table: str) -> str:
    return f"`{catalog}`.`{schema}`.`{table}`"


def table_name(table: str) -> str:
    return f"{catalog}.{schema}.{table}"


def table_exists(table: str) -> bool:
    return spark.catalog.tableExists(table_name(table))


def sql_str(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


VOLUME_ROOT = f"/Volumes/{catalog}/{schema}/{volume}"
LANDING_ROOT = f"{VOLUME_ROOT}/extracts"
CHECKPOINT_ROOT = f"{VOLUME_ROOT}/_checkpoints"


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Financial years and the monthly grid
# MAGIC
# MAGIC Australian Government financial years run 1 July - 30 June and are labelled by the year in
# MAGIC which they end (`FY27` = 2026-27). All phasing runs on a fixed monthly grid from July 2015 to
# MAGIC June 2040 (`month_idx` 0..299).

# COMMAND ----------

EPOCH = date(2015, 7, 1)
N_MONTHS = 300


def fy_of(d: date) -> int:
    return d.year + 1 if d.month >= 7 else d.year


def fy_label(fy: int) -> str:
    return f"FY{fy % 100:02d}"


def fy_long(fy: int) -> str:
    return f"{fy - 1}-{fy % 100:02d}"


def fy_start(fy: int) -> date:
    return date(fy - 1, 7, 1)


def fy_end(fy: int) -> date:
    return date(fy, 6, 30)


def month_idx(d: date) -> int:
    return (d.year - EPOCH.year) * 12 + d.month - EPOCH.month


def month_start(i: int) -> date:
    y, m = divmod(EPOCH.month - 1 + int(i), 12)
    return date(EPOCH.year + y, m + 1, 1)


def month_end(i: int) -> date:
    return month_start(i + 1) - timedelta(days=1)


FY_OF_MONTH = np.array([fy_of(month_start(i)) for i in range(N_MONTHS)])
MONTH_DATES = [month_start(i) for i in range(N_MONTHS)]


def actuals_through_for(as_of: date, lag_days: int) -> date:
    """Last month-end whose ledger close (month-end + lag) is on or before `as_of`."""
    candidate = date(as_of.year, as_of.month, 1) - timedelta(days=1)
    while candidate + timedelta(days=lag_days) > as_of:
        candidate = date(candidate.year, candidate.month, 1) - timedelta(days=1)
    return candidate

# COMMAND ----------

# MAGIC %md
# MAGIC ## Phasing and forecast engine
# MAGIC
# MAGIC A spend path is a NumPy array of AUD millions on the monthly grid. `t0` is the first month that
# MAGIC is forecast (the month after actuals close). Months before `t0` are history and are never
# MAGIC changed by a driver.
# MAGIC
# MAGIC Explained forecast stages, applied in order and each recorded so variance can be attributed:
# MAGIC
# MAGIC 1. `plan` - endorsed plan phasing
# MAGIC 2. `schedule` - approved schedule changes (slip / acceleration) and their delay cost
# MAGIC 3. `escalation` - current vs endorsed construction escalation on the unspent profile
# MAGIC 4. `scope` - approved scope changes
# MAGIC 5. `packaging` - approved contract packaging changes
# MAGIC
# MAGIC The final forecast replaces history with actuals and carries recent cost performance
# MAGIC (actual vs explained, trailing 12 months) onto the unspent profile - the **unexplained** driver.

# COMMAND ----------

_GRID = np.linspace(0.0, 1.0, 2001)


def s_curve_cdf(x, a: float, b: float):
    """Regularised incomplete beta via numerical integration (no SciPy dependency)."""
    pdf = np.power(np.clip(_GRID, 1e-9, 1), a - 1) * np.power(np.clip(1 - _GRID, 1e-9, 1), b - 1)
    cdf = np.concatenate([[0.0], np.cumsum((pdf[1:] + pdf[:-1]) / 2)])
    cdf = cdf / cdf[-1]
    return np.interp(x, _GRID, cdf)


def s_curve(total: float, start: int, duration: int, a: float, b: float) -> np.ndarray:
    """Phase `total` over `duration` months from `start` with a beta S-curve."""
    out = np.zeros(N_MONTHS)
    duration = max(int(duration), 1)
    inc = np.diff(s_curve_cdf(np.arange(duration + 1) / duration, a, b))
    idx = np.arange(int(start), int(start) + duration)
    ok = (idx >= 0) & (idx < N_MONTHS)
    out[idx[ok]] = total * inc[ok]
    return out


def reschedule(path: np.ndarray, t0: int, shift: int) -> np.ndarray:
    """Move the unspent part of a path by `shift` months (negative = accelerate).

    Work not yet started shifts whole (never earlier than t0). In-flight work stretches or
    compresses its remaining duration (compression limited to half the remaining months).
    Total spend is conserved.
    """
    shift = int(round(shift))
    out = path.copy()
    if shift == 0 or path[t0:].sum() <= 0:
        return out
    nz = np.nonzero(path > 1e-12)[0]
    start, end = int(nz[0]), int(nz[-1])
    if start >= t0:
        new_start = max(t0, start + shift)
        seg = path[start:end + 1]
        out[t0:] = 0.0
        stop = min(new_start + len(seg), N_MONTHS)
        out[new_start:stop] = seg[: stop - new_start]
        out[stop - 1] += seg[stop - new_start:].sum()
        return out
    remaining = end - t0 + 1
    new_remaining = max(int(math.ceil(remaining / 2)), remaining + shift)
    new_remaining = min(new_remaining, N_MONTHS - t0)
    cum = np.concatenate([[0.0], np.cumsum(path[t0:end + 1])])
    new_cum = np.interp(np.arange(new_remaining + 1) * remaining / new_remaining, np.arange(remaining + 1), cum)
    out[t0:] = 0.0
    out[t0:t0 + new_remaining] = np.diff(new_cum)
    return out


def spread_future(path: np.ndarray, t0: int, amount: float) -> np.ndarray:
    """Distribute `amount` over the unspent profile in proportion to remaining spend."""
    add = np.zeros(N_MONTHS)
    if not amount:
        return add
    fut = path[t0:]
    total = fut.sum()
    if total > 0:
        amount = max(amount, -0.5 * total)  # a reduction can never remove more than half the unspent work
        add[t0:] = amount * fut / total
    else:
        add[min(t0, N_MONTHS - 1)] = amount
    return add


def escalation_factor_by_month(rates: pd.DataFrame, sector: str, h0: int, delta_pp: float = 0.0) -> np.ndarray:
    """Cumulative ratio of current to endorsed escalation from the first forecast FY.

    `rates` columns: sector, fy, endorsed_rate, current_rate (decimal p.a.). FYs beyond the last
    published rate reuse the last rate. `delta_pp` is a scenario override in percentage points.
    """
    r = rates[rates["sector"] == sector].sort_values("fy")
    if r.empty:
        return np.ones(N_MONTHS)
    by_fy = {int(row.fy): (float(row.endorsed_rate), float(row.current_rate)) for row in r.itertuples()}
    last = by_fy[max(by_fy)]
    factor, cum = {}, 1.0
    for fy in range(int(FY_OF_MONTH.min()), int(FY_OF_MONTH.max()) + 1):
        if fy >= h0:
            end_r, cur_r = by_fy.get(fy, last)
            cum *= (1 + cur_r + delta_pp / 100.0) / (1 + end_r)
        factor[fy] = cum if fy >= h0 else 1.0
    return np.array([factor[int(fy)] for fy in FY_OF_MONTH])


def explained_paths(plan: np.ndarray, t0: int, *, slip_months: float = 0, delay_cost: float = 0.0,
                    esc_factor: np.ndarray = None, scope: float = 0.0, packaging: float = 0.0) -> dict:
    """Apply the recorded drivers to the endorsed plan in a fixed order (see markdown above)."""
    f_sched = reschedule(plan, t0, slip_months)
    f_sched = f_sched + spread_future(f_sched, t0, delay_cost)
    f_esc = f_sched.copy()
    if esc_factor is not None:
        f_esc[t0:] = f_esc[t0:] * esc_factor[t0:]
    f_scope = f_esc + spread_future(f_esc, t0, scope)
    f_pack = f_scope + spread_future(f_scope, t0, packaging)
    return {"plan": plan, "schedule": f_sched, "escalation": f_esc, "scope": f_scope, "packaging": f_pack}


def performance_factor(actual: np.ndarray, expected: np.ndarray, t0: int, window: int = 12,
                       floor: float = -0.15, cap: float = 0.25) -> float:
    """Trailing cost performance: actual vs explained spend over the last `window` months."""
    lo = max(0, t0 - window)
    a, e = actual[lo:t0].sum(), expected[lo:t0].sum()
    if e <= max(1e-6, 0.02 * expected.sum()):
        return 0.0
    return float(np.clip(a / e - 1.0, floor, cap))

def to_paths(pdf: pd.DataFrame, value_cols: list, key: str = "project_id") -> dict:
    """Long monthly rows (key, month, values...) -> {value_col: {key: monthly array}}."""
    out = {c: {} for c in value_cols}
    idx = pdf["month"].map(lambda d: month_idx(d if isinstance(d, date) else pd.Timestamp(d).date())).to_numpy()
    keys = pdf[key].to_numpy()
    for k in np.unique(keys):
        sel = keys == k
        for c in value_cols:
            arr = np.zeros(N_MONTHS)
            np.add.at(arr, idx[sel], pdf.loc[sel, c].to_numpy(dtype=float))
            out[c][k] = arr
    return out


def paths_to_rows(paths: dict, value_cols: list, key: str = "project_id", extra: dict = None, eps: float = 1e-7) -> pd.DataFrame:
    """{value_col: {key: array}} -> long monthly rows for months where any value is non-zero."""
    frames = []
    for k in paths[value_cols[0]]:
        mat = np.vstack([paths[c].get(k, np.zeros(N_MONTHS)) for c in value_cols])
        nz = np.nonzero(np.abs(mat).max(axis=0) > eps)[0]
        if len(nz) == 0:
            continue
        f = pd.DataFrame(mat[:, nz].T, columns=value_cols)
        f.insert(0, key, k)
        f.insert(1, "month", [MONTH_DATES[i] for i in nz])
        f.insert(2, "fy", FY_OF_MONTH[nz].astype(int))
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out.insert(3, "financial_year", out["fy"].map(fy_label))
    for c, v in (extra or {}).items():
        out[c] = v
    return out


def deflator_index(deflator: pd.DataFrame, h0: int) -> dict:
    """FY -> price index (1.0 in the first horizon year) from CPI rates; used for real terms."""
    rates = {int(r.fy): float(r.cpi_rate) for r in deflator.itertuples()}
    last = rates[max(rates)] if rates else 0.025
    idx = {h0: 1.0}
    for fy in range(h0 + 1, int(FY_OF_MONTH.max()) + 2):
        idx[fy] = idx[fy - 1] * (1 + rates.get(fy, last))
    for fy in range(h0 - 1, int(FY_OF_MONTH.min()) - 2, -1):
        idx[fy] = idx[fy + 1] / (1 + rates.get(fy + 1, last))
    return idx

# COMMAND ----------

# MAGIC %md
# MAGIC ## Governed writes and run control

# COMMAND ----------

# Column documentation shared by every governed table. Genie and the app rely on these.
COLUMN_DOCS = {
    "run_id": "Forecast run that produced the row; joins to forecast_runs for assumptions and inputs.",
    "scenario_id": "Scenario identifier (BASE = Working baseline, CAP_BAL = Capacity balanced, ACCEL = Accelerated delivery, or a user draft). Join to dim_scenario.",
    "scenario_name": "Display name of the scenario.",
    "program_id": "Program identifier. Join to dim_program.",
    "program_name": "Program display name.",
    "project_id": "Project identifier. Join to dim_project.",
    "project_name": "Project display name.",
    "sector": "Infrastructure sector: Transport, Energy, Water or Social.",
    "subsector": "Infrastructure subsector (e.g. Urban rail, Transmission, Bulk water).",
    "jurisdiction": "State or territory where the asset is delivered.",
    "fy": "Australian Government financial year as an integer, labelled by the year it ends (2027 = 1 Jul 2026 - 30 Jun 2027).",
    "financial_year": "Financial year label, e.g. FY27 = 2026-27 (1 Jul 2026 - 30 Jun 2027).",
    "month": "First day of the calendar month.",
    "capacity_category": "Delivery-market input category (e.g. Skilled civil labour). Join to dim_capacity_category.",
    "plan_aud_m": "Endorsed plan (budget) expenditure, AUD millions, nominal.",
    "forecast_aud_m": "Forecast expenditure, AUD millions, nominal. Actuals for closed months, forecast thereafter.",
    "actual_aud_m": "Recorded actual expenditure from the general ledger, AUD millions, nominal.",
    "plan_real_aud_m": "Endorsed plan in real terms (constant prices of the first horizon year), AUD millions.",
    "forecast_real_aud_m": "Forecast in real terms (constant prices of the first horizon year), AUD millions.",
    "actual_real_aud_m": "Actuals in real terms (constant prices of the first horizon year), AUD millions.",
    "variance_aud_m": "Forecast minus plan, AUD millions. Positive = overspend / cost growth.",
    "figure_status": "Working (pre-decision, protected) or Published. Pre-decision figures must not be released.",
}


def write_table(df, name: str, comment: str, column_comments: dict = None, mode: str = "overwrite",
                tags: dict = None) -> int:
    """Write a governed table: column comments travel as field metadata, then table comment and tags."""
    if isinstance(df, pd.DataFrame):
        df = spark.createDataFrame(df)
    docs = {**COLUMN_DOCS, **(column_comments or {})}
    for c in df.columns:
        if c in docs:
            df = df.withMetadata(c, {"comment": docs[c]})
    writer = df.write.mode(mode)
    if mode == "overwrite":
        writer = writer.option("overwriteSchema", "true")
    writer.saveAsTable(table_name(name))
    spark.sql(f"COMMENT ON TABLE {fqn(name)} IS {sql_str(comment)}")
    tag_table(name, {**BASE_TAGS, **(tags or {})})
    return spark.table(table_name(name)).count()


# Namespaced keys so they never collide with workspace governed-tag policies.
BASE_TAGS = {"nba_usecase": "budget_planning_and_projections", "nba_classification": "protected_working_figures",
             "nba_synthetic": "true"}


def tag_table(name: str, tags: dict) -> None:
    """Best effort: governed-tag policies may restrict tag keys/values in some workspaces."""
    pairs = ", ".join(f"{sql_str(k)} = {sql_str(v)}" for k, v in tags.items())
    try:
        spark.sql(f"ALTER TABLE {fqn(name)} SET TAGS ({pairs})")
    except Exception as exc:  # noqa: BLE001
        print(f"tagging skipped for {name}: {str(exc).splitlines()[0][:160]}")


def run_context() -> dict:
    """Forecast context published by 04 and consumed by 05 / 06 / 07 in the same job run."""
    ctx = {k: get_control(k) for k in ("current_run_id", "forecast_as_of", "actuals_through", "horizon_start_fy",
                                         "horizon_years", "plan_version", "run_type")}
    assert ctx["current_run_id"], "No forecast context - run 04_expenditure_forecast first"
    ctx["t0"] = month_idx(date.fromisoformat(ctx["actuals_through"])) + 1
    ctx["h0"] = int(ctx["horizon_start_fy"])
    ctx["horizon"] = list(range(ctx["h0"], ctx["h0"] + int(ctx["horizon_years"])))
    return ctx


def get_control(key: str, default=None):
    if not table_exists("pipeline_control"):
        return default
    rows = spark.sql(f"SELECT value FROM {fqn('pipeline_control')} WHERE key = :k", args={"k": key}).collect()
    return rows[0][0] if rows else default


def set_control(key: str, value) -> None:
    spark.sql(
        f"""MERGE INTO {fqn('pipeline_control')} t
            USING (SELECT :k AS key, :v AS value) s ON t.key = s.key
            WHEN MATCHED THEN UPDATE SET value = s.value, updated_at = current_timestamp()
            WHEN NOT MATCHED THEN INSERT (key, value, updated_at) VALUES (s.key, s.value, current_timestamp())""",
        args={"k": key, "v": str(value)},
    )
