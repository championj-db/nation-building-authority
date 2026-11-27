# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Contracts (public AusTender data) and the business-day calendar
# MAGIC
# MAGIC Fetches recently published Australian Government contract notices from the AusTender OCDS
# MAGIC API (`api.tenders.gov.au`, public, no key) and keeps only their substance: description,
# MAGIC UNSPSC category, value, contract period and procurement method. Supplier names, supplier ids,
# MAGIC notice ids and the procuring entity are discarded here, before anything is written. A
# MAGIC description that names its own supplier is dropped. Step 02 assigns each contract to a
# MAGIC synthetic supplier and makes the fictional Nation Building Authority the buyer.
# MAGIC
# MAGIC If the API cannot be reached, the step falls back to synthetic contract notices and records
# MAGIC that in `corpus_control`, so the provenance shown downstream stays truthful.
# MAGIC
# MAGIC The business-day calendar (weekends, national and ACT public holidays) comes from the
# MAGIC open-source `holidays` package.

# COMMAND ----------

# MAGIC %pip install --quiet "holidays>=0.60" "dbldatagen>=0.4"

# COMMAND ----------

import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.request

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_found = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _found is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _found)

from common import CALENDAR_SUBDIVISION, fq, get_params  # noqa: E402

p = get_params({"catalog": "", "schema": "", "seed": "42", "as_of": "", "lookback_days": "150", "max_notices": "2500"}, dbutils)
CATALOG, SCHEMA, SEED = p["catalog"], p["schema"], int(p["seed"])
AS_OF = dt.date.fromisoformat(p["as_of"]) if p["as_of"] else (dt.datetime.utcnow() + dt.timedelta(hours=11)).date()
LOOKBACK, MAX_NOTICES = int(p["lookback_days"]), int(p["max_notices"])
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

existing = spark.catalog.tableExists(f"{CATALOG}.{SCHEMA}.stage_contract_notices")
if existing and spark.table(t("stage_contract_notices")).count() > 0:
    dbutils.notebook.exit("contract notices already staged; reset the corpus to refetch")

# COMMAND ----------

API = "https://api.tenders.gov.au/ocds/findByDates/contractPublished/{start}T00:00:00Z/{end}T00:00:00Z"
SALT = f"nba-idp-{SEED}"


def fetch(url: str, attempts: int = 4) -> dict:
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "nba-idp-demo/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            print(f"retrying after {e}")
            time.sleep(2 * (i + 1))


def notices_from(release: dict) -> list[dict]:
    parties = release.get("parties") or []
    suppliers = [x for x in parties if "supplier" in (x.get("roles") or [])]
    out = []
    for c in release.get("contracts") or []:
        period = c.get("period") or {}
        items = c.get("items") or [{}]
        supplier = suppliers[0] if suppliers else {}
        desc = " ".join(str(c.get("description") or "").split())
        name_tokens = {w.lower().strip(".,()") for w in str(supplier.get("name") or "").split() if len(w) > 3}
        if not desc or name_tokens & {w.lower().strip(".,()") for w in desc.split()}:
            continue  # describes itself by its supplier's name; drop rather than edit
        out.append({
            "description": desc,
            "unspsc": str((items[0].get("classification") or {}).get("id") or ""),
            "value": float((c.get("value") or {}).get("amount") or 0),
            "start_date": str(period.get("startDate") or "")[:10],
            "end_date": str(period.get("endDate") or "")[:10],
            "procurement_method": (release.get("tender") or {}).get("procurementMethodDetails") or "",
            # Opaque grouping key: keeps one synthetic supplier per real supplier without storing who.
            "supplier_key": hashlib.sha256((SALT + str(supplier.get("id") or c.get("id"))).encode()).hexdigest()[:16],
        })
    return out


notices, source, error = [], "austender_ocds", None
try:
    window_end = AS_OF
    while len(notices) < MAX_NOTICES and (AS_OF - window_end).days < LOOKBACK:
        start = window_end - dt.timedelta(days=14)
        url = API.format(start=start.isoformat(), end=window_end.isoformat())
        pages = 0
        while url and pages < 12 and len(notices) < MAX_NOTICES:
            data = fetch(url)
            for release in data.get("releases") or []:
                notices.extend(notices_from(release))
            nxt = (data.get("links") or {}).get("next")
            url = nxt if nxt and data.get("releases") else None
            pages += 1
        window_end = start
    print(f"AusTender notices kept: {len(notices)}")
except Exception as e:  # noqa: BLE001
    error = str(e)[:500]
    print(f"AusTender API unavailable ({error}); falling back to synthetic contract notices")

# COMMAND ----------

if len(notices) < 60:
    # Fallback: synthetic notices with dbldatagen, so the use case still runs offline.
    import dbldatagen as dg

    source = "synthetic_fallback"
    descriptions = ["Professional services - program assurance", "ICT managed services", "Engineering design services",
                    "Facilities maintenance", "Training delivery", "Legal services", "Communications campaign services",
                    "Environmental assessment", "Freight and logistics", "Data and analytics services"]
    unspsc = ["80101500", "43230000", "81100000", "72100000", "86100000", "80120000", "82100000", "77100000", "78100000", "81110000"]
    spec = (dg.DataGenerator(spark, name="fallback_notices", rows=400, partitions=1, randomSeedMethod="hash_fieldname", randomSeed=SEED)
            .withColumn("i", "int", minValue=0, maxValue=len(descriptions) - 1, random=True)
            .withColumn("value", "double", minValue=25000, maxValue=2500000, random=True)
            .withColumn("start_offset", "int", minValue=60, maxValue=700, random=True)
            .withColumn("length_days", "int", minValue=180, maxValue=1100, random=True)
            .withColumn("supplier_n", "int", minValue=0, maxValue=140, random=True))
    rows = spec.build().collect()
    notices = [{
        "description": descriptions[r.i], "unspsc": unspsc[r.i], "value": round(float(r.value), 2),
        "start_date": (AS_OF - dt.timedelta(days=r.start_offset)).isoformat(),
        "end_date": (AS_OF - dt.timedelta(days=r.start_offset) + dt.timedelta(days=r.length_days)).isoformat(),
        "procurement_method": "Open tender", "supplier_key": f"fallback-{r.supplier_n}",
    } for r in rows]

spark.createDataFrame(notices, "description STRING, unspsc STRING, value DOUBLE, start_date STRING, end_date STRING, procurement_method STRING, supplier_key STRING") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("stage_contract_notices"))
spark.sql(f"COMMENT ON TABLE {t('stage_contract_notices')} IS 'Contract notice substance from AusTender (public) with supplier identity, notice id and procuring entity removed. Staging only; step 02 pseudonymises.'")

# COMMAND ----------

import holidays  # noqa: E402

years = [AS_OF.year - 1, AS_OF.year, AS_OF.year + 1]
hol = holidays.Australia(subdiv=CALENDAR_SUBDIVISION, years=years)
days = []
d = dt.date(years[0], 1, 1)
while d <= dt.date(years[-1], 12, 31):
    name = hol.get(d)
    days.append({"cal_date": d, "is_weekend": d.weekday() >= 5, "holiday_name": name,
                 "is_business_day": d.weekday() < 5 and name is None})
    d += dt.timedelta(days=1)
cal = spark.createDataFrame(days, "cal_date DATE, is_weekend BOOLEAN, holiday_name STRING, is_business_day BOOLEAN")
cal.createOrReplaceTempView("cal")
spark.sql(f"""
CREATE OR REPLACE TABLE {t('ref_business_calendar')}
COMMENT 'Business-day calendar: weekends, national and ACT public holidays (holidays package). business_day_seq counts business days, so the difference between two dates is a business-day count.'
AS SELECT cal_date, is_weekend, holiday_name, is_business_day,
          SUM(CASE WHEN is_business_day THEN 1 ELSE 0 END) OVER (ORDER BY cal_date) AS business_day_seq
FROM cal
""")

control = {"contracts_source": source, "contracts_fetched_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "contracts_error": error, "as_of": AS_OF.isoformat(), "seed": SEED, "notice_count": len(notices)}
spark.createDataFrame([(k, json.dumps(v)) for k, v in control.items()], "key STRING, value STRING").createOrReplaceTempView("ctl")
spark.sql(f"CREATE TABLE IF NOT EXISTS {t('corpus_control')} (key STRING, value STRING) COMMENT 'Provenance and run control for the synthetic corpus.'")
spark.sql(f"MERGE INTO {t('corpus_control')} c USING ctl s ON c.key = s.key WHEN MATCHED THEN UPDATE SET value = s.value WHEN NOT MATCHED THEN INSERT *")
print(control)
