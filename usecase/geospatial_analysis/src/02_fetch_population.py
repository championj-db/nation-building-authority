# Databricks notebook source
# Step 2 of the geospatial analysis pipeline: real population.
#
# Fetches the ABS estimated resident population (ERP) by SA2 and five-year age group from the ABS
# Data API at run time, keeps the latest published year, and derives each SA2's total population
# and share aged 65 and over. Step 4 places synthetic households in proportion to these figures,
# so the analysis has the real shape of where Australians live even though no household is real.

# COMMAND ----------

import datetime as dt
import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import ABS_ERP_ATTRIBUTION, ABS_ERP_URL, AGE_65_PLUS, fq, get_params, http_get, record_provenance, volume_dir  # noqa: E402

params = get_params({"catalog": "", "schema": "", "volume": "landing"}, dbutils)
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
LANDING = volume_dir(CATALOG, SCHEMA, VOLUME, "population")
os.makedirs(LANDING, exist_ok=True)
CSV_PATH = os.path.join(LANDING, "erp_sa2_age.csv")

# COMMAND ----------

# Request the last few years so the newest release is picked up without a code change.
start = dt.date.today().year - 4
url = f"{ABS_ERP_URL}?startPeriod={start}&detail=dataonly"
cached, err, n = False, None, None
try:
    raw = http_get(url, accept="application/vnd.sdmx.data+csv", timeout=300)
    if raw.count(b"\n") < 1000:
        raise RuntimeError("ABS Data API returned too few rows")
    with open(CSV_PATH + ".tmp", "wb") as fh:
        fh.write(raw)
    os.replace(CSV_PATH + ".tmp", CSV_PATH)
except Exception as exc:
    if not os.path.exists(CSV_PATH):
        raise RuntimeError(f"Could not fetch ERP from {url} and no cached copy exists: {exc}") from exc
    print(f"WARNING: ERP fetch failed ({exc}); using the last good copy")
    cached, err = True, str(exc)[:500]

# COMMAND ----------

erp = (spark.read.option("header", True).csv(CSV_PATH)
       .selectExpr("ASGS_2021 AS sa2_code", "AGE AS age", "CAST(TIME_PERIOD AS INT) AS year",
                   "CAST(OBS_VALUE AS DOUBLE) AS persons")
       .where("persons IS NOT NULL"))
erp.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("bronze_erp_sa2_age"))

ages_65 = ", ".join(f"'{a}'" for a in AGE_65_PLUS)
spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_population_sa2')}
COMMENT 'ABS estimated resident population by SA2 (latest published year) with the share aged 65+'
AS
WITH latest AS (SELECT max(year) AS year FROM {t('bronze_erp_sa2_age')})
SELECT e.sa2_code, e.year AS erp_year,
       CAST(sum(CASE WHEN age = 'TOT' THEN persons END) AS BIGINT) AS erp_persons,
       CAST(sum(CASE WHEN age IN ({ages_65}) THEN persons END) AS BIGINT) AS erp_persons_65_plus,
       try_divide(sum(CASE WHEN age IN ({ages_65}) THEN persons END),
                  sum(CASE WHEN age = 'TOT' THEN persons END)) AS share_65_plus
FROM {t('bronze_erp_sa2_age')} e JOIN latest l ON e.year = l.year
GROUP BY e.sa2_code, e.year
""")

summary = spark.sql(f"SELECT max(erp_year) AS year, count(*) AS sa2s, sum(erp_persons) AS persons FROM {t('silver_population_sa2')}").first()
n = summary["sa2s"]
print(f"ERP {summary['year']}: {summary['persons']:,} persons across {n:,} SA2s{' (cached copy)' if cached else ''}")

record_provenance(spark, t("ref_source"), "population", [
    ("abs_erp_sa2_age", "Australian Bureau of Statistics", url, ABS_ERP_ATTRIBUTION, "CC BY 4.0", n, cached, err),
])
