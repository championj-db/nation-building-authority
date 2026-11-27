# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Synthetic supplier inbox
# MAGIC
# MAGIC Builds the synthetic world on top of the public contracts staged in step 01, and lands every
# MAGIC document in the volume as a PDF or a scanned JPEG.
# MAGIC
# MAGIC * **dbldatagen** generates the tabular skeletons: supplier attributes (name parts, address,
# MAGIC   bank, GST registration, e-invoicing, invoice layout) and document specs (type, injected
# MAGIC   defect, scan, stamp, arrival day and hour, channel), from a fixed seed.
# MAGIC * `corpus.py` adds the constraints dbldatagen cannot express: purchase orders within each
# MAGIC   contract's value, invoice series within each order, duplicates of real earlier invoices,
# MAGIC   statements and letters that refer to the supplier's own invoices, and simulated history.
# MAGIC * `render.py` draws the documents in five invoice layouts.
# MAGIC
# MAGIC `mode=seed` builds the full corpus once (about six weeks of mail). Re-running is a no-op
# MAGIC unless the corpus was reset. `mode=arrivals` lands a small batch of new mail arriving now:
# MAGIC this is what the workbench's "Ingest documents" button runs.

# COMMAND ----------

# MAGIC %pip install --quiet "dbldatagen>=0.4" "reportlab>=4" "pypdfium2>=4" "pillow>=10" "holidays>=0.60"

# COMMAND ----------

import datetime as dt
import json
import os
import random
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_found = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _found is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _found)

import dbldatagen as dg  # noqa: E402

import corpus  # noqa: E402
import render  # noqa: E402
from common import BUYER_AP_EMAIL, GIC_ANNUAL_RATE_DEFAULT, fq, get_params, volume_dir  # noqa: E402

p = get_params({"catalog": "", "schema": "", "volume": "documents", "seed": "42", "as_of": "", "mode": "seed",
                "corpus_size": "600", "contracts": "140", "arrivals_batch": "12", "live_window_bd": "7",
                "gic_rate": str(GIC_ANNUAL_RATE_DEFAULT)}, dbutils)
CATALOG, SCHEMA, VOLUME = p["catalog"], p["schema"], p["volume"]
SEED, MODE = int(p["seed"]), p["mode"]
GIC = float(p["gic_rate"])
LIVE_BD = int(p["live_window_bd"])
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
assert MODE in ("seed", "arrivals"), "mode must be seed or arrivals"


def control() -> dict:
    if not spark.catalog.tableExists(f"{CATALOG}.{SCHEMA}.corpus_control"):
        return {}
    return {r.key: json.loads(r.value) for r in spark.table(t("corpus_control")).collect()}


def set_control(**kv) -> None:
    spark.createDataFrame([(k, json.dumps(v, default=str)) for k, v in kv.items()], "key STRING, value STRING").createOrReplaceTempView("ctl")
    spark.sql(f"MERGE INTO {t('corpus_control')} c USING ctl s ON c.key = s.key WHEN MATCHED THEN UPDATE SET value = s.value WHEN NOT MATCHED THEN INSERT *")


ctl = control()
AS_OF = dt.date.fromisoformat(p["as_of"] or ctl.get("as_of") or (dt.datetime.utcnow() + dt.timedelta(hours=11)).date().isoformat())
if MODE == "seed" and ctl.get("seeded"):
    dbutils.notebook.exit("corpus already seeded; reset the corpus to regenerate it")
if MODE == "arrivals" and not ctl.get("seeded"):
    raise RuntimeError("seed the corpus before landing arrivals")

HOLIDAYS = {r.cal_date for r in spark.table(t("ref_business_calendar")).where("holiday_name IS NOT NULL").collect()}

# COMMAND ----------

DOC_TYPES = ["tax_invoice", "adjustment_note", "supplier_statement", "correspondence", "quote"]
DOC_WEIGHTS = [70, 5, 9, 9, 7]
DEFECTS = ["none", "no_receipt", "missing_po", "wrong_po", "gst_error", "invalid_abn", "abn_mismatch",
           "wrong_recipient", "missing_recipient", "over_po_value", "duplicate", "not_tax_invoice"]
DEFECT_WEIGHTS = [60, 7, 6, 3, 4, 3, 2, 3, 3, 3, 3, 3]


def doc_specs(rows: int, seed: int, max_offset: int) -> list[dict]:
    """dbldatagen: one row per document to generate."""
    spec = (dg.DataGenerator(spark, name="doc_specs", rows=rows, partitions=1, randomSeedMethod="hash_fieldname", randomSeed=seed)
            .withColumn("doc_type", "string", values=DOC_TYPES, weights=DOC_WEIGHTS, random=True)
            .withColumn("defect", "string", values=DEFECTS, weights=DEFECT_WEIGHTS, random=True)
            .withColumn("scanned", "boolean", values=[True, False], weights=[16, 84], random=True)
            .withColumn("stamp", "boolean", values=[True, False], weights=[9, 91], random=True)
            .withColumn("bd_offset", "int", minValue=0, maxValue=max_offset, random=True)
            .withColumn("hour", "double", minValue=7.0, maxValue=18.5, random=True)
            .withColumn("channel", "string", values=["email", "portal", "peppol"], weights=[70, 22, 8], random=True))
    return [r.asDict() for r in spec.build().collect()]


def supplier_attrs(rows: int, seed: int) -> list[dict]:
    """dbldatagen: supplier attributes, joined to contracts in corpus.build_suppliers."""
    spec = (dg.DataGenerator(spark, name="supplier_attrs", rows=rows, partitions=1, randomSeedMethod="hash_fieldname", randomSeed=seed)
            .withColumn("word_a", "string", values=corpus.NAME_WORDS, random=True)
            .withColumn("word_b", "string", values=corpus.LANDFORMS, random=True)
            .withColumn("form", "string", values=corpus.ENTITY_FORMS, random=True)
            .withColumn("street_no", "int", minValue=1, maxValue=480, random=True)
            .withColumn("street_idx", "int", minValue=0, maxValue=len(corpus.STREETS) - 1, random=True)
            .withColumn("phone_suffix", "int", minValue=1000000, maxValue=9999999, random=True)
            .withColumn("bsb", "int", minValue=12000, maxValue=999999, random=True)
            .withColumn("account", "int", minValue=10000000, maxValue=99999999, random=True)
            .withColumn("gst_registered", "boolean", values=[True, False], weights=[96, 4], random=True)
            .withColumn("einvoicing", "boolean", values=[True, False], weights=[18, 82], random=True)
            .withColumn("template", "int", minValue=0, maxValue=4, random=True)
            .withColumn("scan_rate", "double", minValue=0.0, maxValue=0.3, random=True))
    return [r.asDict() for r in spec.build().collect()]

# COMMAND ----------

rng = random.Random(SEED)
if MODE == "seed":
    staged = [r.asDict() for r in spark.table(t("stage_contract_notices")).collect()]
    contracts = corpus.pseudonymise_contracts(staged, rng, int(p["contracts"]))
    suppliers = corpus.build_suppliers(contracts, supplier_attrs(400, SEED), rng)
    world = corpus.World(contracts=contracts, suppliers=suppliers)
    world.purchase_orders = corpus.build_purchase_orders(contracts, AS_OF, rng)
    specs = doc_specs(int(p["corpus_size"]), SEED, 29)
    now_local = dt.datetime.utcnow() + dt.timedelta(hours=11)
    corpus.build_documents(world, specs, AS_OF, HOLIDAYS, rng, live_window_bd=LIVE_BD, start_doc_no=1, batch_id="seed",
                           now=now_local if AS_OF == now_local.date() else None)
    corpus.build_receipts(world, HOLIDAYS, rng, AS_OF)
    corpus.build_history(world, HOLIDAYS, rng, GIC, AS_OF)
    corpus.apply_history_to_orders(world)
    new_docs = world.documents
    batch_id = "seed"
else:
    # Rebuild just enough of the world to continue it: masters, open orders and earlier invoices.
    batch_no = int(ctl.get("arrival_batches", 0)) + 1
    batch_id = f"arrivals-{batch_no:03d}"
    rng = random.Random(SEED + 7919 * batch_no)
    now = dt.datetime.utcnow() + dt.timedelta(hours=11)  # AEDT; arrivals are stamped in Canberra time
    contracts = [r.asDict() for r in spark.table(t("ref_contracts")).collect()]
    suppliers = [r.asDict() for r in spark.table(t("ref_suppliers")).collect()]
    pos = [r.asDict() for r in spark.table(t("ref_purchase_orders")).collect()]
    truth = spark.table(t("bronze_ground_truth")).join(spark.table(t("bronze_inbox_manifest")).select("doc_id", "arrival_ts", "channel"), "doc_id").collect()
    prior = []
    for r in truth:
        tr = json.loads(r.truth_json)
        prior.append({"doc_id": r.doc_id, "doc_type": r.doc_type, "defect": r.defect, "truth": tr, "lines": json.loads(r.lines_json),
                      "supplier_id": r.supplier_id, "po_number": r.po_number, "template": None, "scanned": r.scanned,
                      "arrival_ts": r.arrival_ts, "batch_id": r.batch_id, "live": True, "rel_path": r.rel_path})
    for s in suppliers:  # continue each supplier's invoice numbering
        seqs = [int(d["truth"]["invoice_number"].rsplit("-", 1)[1]) for d in prior
                if d["supplier_id"] == s["supplier_id"] and d["truth"].get("invoice_number", "").startswith(s["invoice_prefix"] + "-")]
        s["invoice_seq"] = max(seqs + [s["invoice_seq"]])
    billed = {}
    for d in prior:
        if d["doc_type"] == "tax_invoice" and d["defect"] in ("none", "no_receipt") and d["po_number"]:
            billed[d["po_number"]] = billed.get(d["po_number"], 0.0) + float(d["truth"]["total_inc_gst"] or 0)
    for po in pos:
        po["_billed"] = billed.get(po["po_number"], 0.0)
    for d in prior:
        d["template"] = next((s["template"] for s in suppliers if s["supplier_id"] == d["supplier_id"]), 0)
    world = corpus.World(contracts=contracts, suppliers=suppliers, purchase_orders=pos, documents=prior)
    specs = doc_specs(int(p["arrivals_batch"]), SEED + 7919 * batch_no, 0)
    hours = sorted(rng.uniform(0, 0.9) for _ in specs)
    for s, h in zip(specs, hours):
        s["bd_offset"], s["hour"] = 0, min(now.hour + now.minute / 60 - h, 23.9)
    start_no = max(int(d["doc_id"].split("-")[1]) for d in prior) + 1
    n_before = len(world.documents)
    corpus.build_documents(world, specs, now.date(), HOLIDAYS, rng, live_window_bd=LIVE_BD, start_doc_no=start_no, batch_id=batch_id)
    new_docs = world.documents[n_before:]
    receipts_before = len(world.receipts)
    world.documents = new_docs
    corpus.build_receipts(world, HOLIDAYS, rng, now.date())
    world.documents = prior + new_docs

print(f"{MODE}: {len(new_docs)} documents ({batch_id})")

# COMMAND ----------

# Render and land. The volume is the inbox: one file per attachment, under inbox/YYYY/MM/DD/.
suppliers_by_id = {s["supplier_id"]: s for s in world.suppliers}
docs_by_id = {d["doc_id"]: d for d in world.documents}
render_rng = random.Random(SEED * 31 + len(world.documents))
base = volume_dir(CATALOG, SCHEMA, VOLUME)
for d in new_docs:
    s = suppliers_by_id[d["supplier_id"]]
    if d["doc_type"] in ("tax_invoice", "adjustment_note"):
        blob = render.render_invoice(d, s, render_rng)
    elif d["doc_type"] == "supplier_statement":
        blob = render.render_statement(d, s, [docs_by_id[i] for i in d.get("related_invoices", []) if i in docs_by_id])
    elif d["doc_type"] == "correspondence":
        blob = render.render_letter(d, s, render_rng)
    else:
        blob = render.render_quote(d, s)
    if d["scanned"]:
        blob = render.scan(blob, render_rng)
    path = f"{base}/{d['rel_path']}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)
print(f"landed {len(new_docs)} files under {base}/inbox")

# COMMAND ----------

def subject(d: dict) -> str:
    tr = d["truth"]
    return {
        "tax_invoice": f"Invoice {tr.get('invoice_number', '')}",
        "adjustment_note": f"Adjustment note {tr.get('invoice_number', '')}",
        "supplier_statement": "Statement of account",
        "correspondence": "Re: our invoice" if tr.get("referenced_invoice_numbers") else "Correspondence",
        "quote": f"Quotation {tr.get('quote_number', '')}",
    }[d["doc_type"]]


manifest = [{
    "doc_id": d["doc_id"], "path": f"{base}/{d['rel_path']}", "rel_path": d["rel_path"], "attachment_name": d["attachment_name"],
    "arrival_ts": d["arrival_ts"], "arrival_date": d["arrival_ts"].date(), "channel": d["channel"], "batch_id": d["batch_id"],
    "sender": suppliers_by_id[d["supplier_id"]]["email"] if d["channel"] == "email" else ("Peppol access point" if d["channel"] == "peppol" else "Supplier portal"),
    "recipient": BUYER_AP_EMAIL, "subject": subject(d),
} for d in new_docs]
MANIFEST_DDL = ("doc_id STRING, path STRING, rel_path STRING, attachment_name STRING, arrival_ts TIMESTAMP_NTZ, arrival_date DATE, "
                "channel STRING, batch_id STRING, sender STRING, recipient STRING, subject STRING")
TRUTH_DDL = ("doc_id STRING, rel_path STRING, doc_type STRING, defect STRING, expected_failed_check STRING, scanned BOOLEAN, "
             "stamp BOOLEAN, supplier_id STRING, po_number STRING, related_doc_id STRING, truth_json STRING, lines_json STRING, batch_id STRING")
truth = corpus.truth_rows(corpus.World(contracts=[], suppliers=[], documents=new_docs))
mode = "overwrite" if MODE == "seed" else "append"

spark.createDataFrame(manifest, MANIFEST_DDL).write.mode(mode).saveAsTable(t("bronze_inbox_manifest"))
spark.createDataFrame(truth, TRUTH_DDL).write.mode(mode).saveAsTable(t("bronze_ground_truth"))

if MODE == "seed":
    spark.sql(f"COMMENT ON TABLE {t('bronze_inbox_manifest')} IS 'Every document landed in the inbox volume: arrival time (Canberra local), channel, sender and subject. Synthetic.'")
    spark.sql(f"COMMENT ON TABLE {t('bronze_ground_truth')} IS 'What each synthetic document really says (truth_json) and the defect injected into it. Used only to score the pipeline; the workbench never reads it.'")
    C_DDL = ("contract_id STRING, description STRING, unspsc STRING, category STRING, value_inc_gst DOUBLE, start_date STRING, "
             "end_date STRING, procurement_method STRING, supplier_id STRING, contract_manager STRING")
    spark.createDataFrame([{k: c[k] for k in C_DDL.replace(",", "").split()[::2]} for c in world.contracts], C_DDL) \
        .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("ref_contracts"))
    S_DDL = ("supplier_id STRING, name STRING, abn STRING, gst_registered BOOLEAN, einvoicing BOOLEAN, address_1 STRING, address_2 STRING, "
             "email STRING, phone STRING, bsb STRING, account STRING, template INT, scan_rate DOUBLE, invoice_prefix STRING, invoice_seq INT")
    spark.createDataFrame([{k: s[k] for k in S_DDL.replace(",", "").split()[::2]} for s in world.suppliers], S_DDL) \
        .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("ref_suppliers"))
    P_DDL = ("po_number STRING, contract_id STRING, supplier_id STRING, raised_date DATE, po_value_inc_gst DOUBLE, status STRING, "
             "description STRING, cost_centre STRING, contract_manager STRING, invoiced_to_date_inc_gst DOUBLE")
    spark.createDataFrame([{k: po[k] for k in P_DDL.replace(",", "").split()[::2]} for po in world.purchase_orders], P_DDL) \
        .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("ref_purchase_orders"))
    H_DDL = ("doc_id STRING, decision STRING, reason STRING, decided_date DATE, decided_by STRING, trigger_date DATE, paid_date DATE, "
             "pay_by_current DATE, pay_by_2027 DATE, late_days_current INT, late_days_2027 INT, interest_current DOUBLE")
    spark.createDataFrame(world.history, H_DDL).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("bronze_processing_history"))
    for name, comment in [
        ("ref_contracts", "Contracts: description, UNSPSC category, value and period from public AusTender notices; supplier replaced by a synthetic one, buyer is the fictional Nation Building Authority."),
        ("ref_suppliers", "Synthetic vendor master (dbldatagen). Names are generated; any resemblance to a real business is coincidental. ABNs pass the check-digit test but are random."),
        ("ref_purchase_orders", "Synthetic purchase orders within each contract value. invoiced_to_date is accepted, paid invoices in the simulated history."),
        ("bronze_processing_history", "SIMULATED AP decisions and payment dates for documents older than the live queue window. Not workbench decisions."),
    ]:
        spark.sql(f"COMMENT ON TABLE {t(name)} IS '{comment}'")

R_DDL = "receipt_id STRING, po_number STRING, doc_id STRING, amount_inc_gst DOUBLE, receipted_date DATE, receipted_by STRING"
receipts = world.receipts if MODE == "seed" else world.receipts[receipts_before:]
spark.createDataFrame(receipts, R_DDL).write.mode(mode).option("overwriteSchema", "true" if MODE == "seed" else "false").saveAsTable(t("ref_goods_receipts"))
if MODE == "seed":
    spark.sql(f"COMMENT ON TABLE {t('ref_goods_receipts')} IS 'Synthetic delivery acknowledgements (goods and services receipts) against purchase orders.'")
    set_control(seeded=True, as_of=AS_OF.isoformat(), live_window_bd=LIVE_BD, corpus_documents=len(new_docs), arrival_batches=0, gic_rate=GIC)
else:
    set_control(arrival_batches=batch_no, last_arrival_batch=batch_id, last_arrival_at=dt.datetime.utcnow().isoformat(timespec="seconds") + "Z")

print(f"tables written ({mode})")
