# Databricks notebook source
# MAGIC %md
# MAGIC # 04 Entity resolution
# MAGIC
# MAGIC Resolves constituents across six agency systems **without a common identifier**.
# MAGIC
# MAGIC 1. **Embeddings** - each record's `identity_text` is embedded with `ai_query(<embedding endpoint>)`;
# MAGIC    cached in `er_identity_embeddings` by text hash so only new or changed records are embedded.
# MAGIC 2. **Semantic candidates** - `JOIN ... APPROX NEAREST k BY SIMILARITY vector_cosine_similarity(...)`
# MAGIC    finds each record's nearest identities. This catches pairs that deterministic blocking misses
# MAGIC    (re-ordered names, different street notation, moved house but same email) -> `er_semantic_candidates`.
# MAGIC 3. **Probabilistic linkage (Splink 4)** - Fellegi-Sunter model with blocking on DOB, email, phone,
# MAGIC    address, postcode + initial, full name and the exploded semantic pair keys. Comparisons: given name and
# MAGIC    family name (Jaro-Winkler with term frequency), DOB, email, phone, postcode, street, and the semantic
# MAGIC    neighbour tier. Lambda from deterministic rules, u by random sampling, m by EM.
# MAGIC 4. **Decisions** - auto-link at `auto_match_threshold`, human review band down to `review_threshold`.
# MAGIC    Steward decisions (`identity_review_decisions`: must_link / cannot_link) override the model.
# MAGIC 5. **Clusters + stable IDs** - union-find over accepted links; clusters inherit their majority prior
# MAGIC    `constituent_id`, otherwise a new one is minted from the control sequence.
# MAGIC 6. **Outputs** - `silver_identity_xref`, `silver_constituents` (golden record), `silver_identity_links`
# MAGIC    (identity graph), `er_pairwise_predictions`, `er_review_queue`, `er_evaluation`, `er_model_runs`.
# MAGIC
# MAGIC Splink runs on the DuckDB backend on the driver, which comfortably handles hundreds of thousands of
# MAGIC records. For national scale switch to Splink's Spark backend on classic compute.

# COMMAND ----------

# MAGIC %pip install -q "splink>=4.0.8,<5"

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
dbutils.widgets.text("semantic_neighbours", "5")
dbutils.widgets.text("semantic_hi", "0.95")
dbutils.widgets.text("semantic_lo", "0.90")
dbutils.widgets.text("auto_match_threshold", "0.95")
dbutils.widgets.text("review_threshold", "0.75")
dbutils.widgets.text("u_max_pairs", "2000000")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None
EMBED_EP = dbutils.widgets.get("embedding_endpoint")
K = int(dbutils.widgets.get("semantic_neighbours"))
SEM_HI = float(dbutils.widgets.get("semantic_hi"))
SEM_LO = float(dbutils.widgets.get("semantic_lo"))
AUTO_T = float(dbutils.widgets.get("auto_match_threshold"))
REVIEW_T = float(dbutils.widgets.get("review_threshold"))
U_MAX_PAIRS = float(dbutils.widgets.get("u_max_pairs"))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import os

import pandas as pd
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

run_id = run_id or new_run_id("ER")
ids_t = table_name("silver_source_identities")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Embeddings (cached by text hash)

# COMMAND ----------

EMB_COLS = ["source_record_id", "text_hash", "embedding", "model", "embedded_at"]
if not table_exists("er_identity_embeddings"):
    spark.sql(f"""CREATE TABLE {fqn('er_identity_embeddings')}
                  (source_record_id STRING, text_hash STRING, embedding ARRAY<FLOAT>, model STRING, embedded_at TIMESTAMP)
                  COMMENT 'Embeddings of identity_text for semantic matching, cached by text hash and model.'""")
    claim_object("er_identity_embeddings")
assert_owned("er_identity_embeddings")
current = spark.sql(f"SELECT source_record_id, sha2(identity_text, 256) AS text_hash, identity_text FROM {fqn('silver_source_identities')}")
cached = spark.table(table_name("er_identity_embeddings")).filter(F.col("model") == EMBED_EP)
keep = cached.join(current.select("source_record_id", "text_hash"), ["source_record_id", "text_hash"]).select(*EMB_COLS)
todo = current.join(cached.select("source_record_id", "text_hash"), ["source_record_id", "text_hash"], "left_anti")
n_todo = todo.count()
print(f"embedding {n_todo} new or changed identity records with {EMBED_EP}")
new = todo.selectExpr("source_record_id", "text_hash",
                      f"CAST(ai_query({sql_str(EMBED_EP)}, identity_text) AS ARRAY<FLOAT>) AS embedding",
                      f"{sql_str(EMBED_EP)} AS model", "current_timestamp() AS embedded_at")
if n_todo:
    # stage first so the cache is never rewritten from a half-computed plan
    write_table(keep.unionByName(new), "er_identity_embeddings__stage", "Staging for er_identity_embeddings.", layer="entity_resolution")
    write_table(spark.table(table_name("er_identity_embeddings__stage")), "er_identity_embeddings",
                "Embeddings of identity_text for semantic matching, cached by text hash and model.", layer="entity_resolution")
    drop_owned("er_identity_embeddings__stage")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Semantic candidates with `NEAREST BY`
# MAGIC
# MAGIC The ranking expression pushes a record's own row to the bottom so each record returns its `k` nearest
# MAGIC *other* identities.

# COMMAND ----------

semantic = spark.sql(f"""
  WITH e AS (
    SELECT i.source_record_id, i.source_system, x.embedding
    FROM {fqn('silver_source_identities')} i
    JOIN {fqn('er_identity_embeddings')} x
      ON x.source_record_id = i.source_record_id AND x.text_hash = sha2(i.identity_text, 256) AND x.model = {sql_str(EMBED_EP)})
  SELECT q.source_record_id AS rid_q, t.source_record_id AS rid_t,
         vector_cosine_similarity(q.embedding, t.embedding) AS similarity
  FROM e q
  JOIN e t
    APPROX NEAREST {K + 1} BY SIMILARITY
      CASE WHEN q.source_record_id = t.source_record_id THEN -2.0 ELSE vector_cosine_similarity(q.embedding, t.embedding) END
""")
pairs = (semantic.filter(f"rid_q <> rid_t AND similarity >= {SEM_LO}")
         .select(F.least("rid_q", "rid_t").alias("source_record_id_l"), F.greatest("rid_q", "rid_t").alias("source_record_id_r"), "similarity")
         .groupBy("source_record_id_l", "source_record_id_r").agg(F.max("similarity").alias("semantic_similarity"))
         .withColumn("semantic_tier", F.when(F.col("semantic_similarity") >= SEM_HI, "hi").otherwise("lo"))
         .withColumn("run_id", F.lit(run_id)))
n_sem = write_table(pairs, "er_semantic_candidates",
                    f"Semantic candidate pairs from NEAREST BY over identity embeddings (k={K}, similarity >= {SEM_LO}).",
                    column_comments={"semantic_similarity": "Cosine similarity of identity_text embeddings.",
                                     "semantic_tier": f"hi (>= {SEM_HI}) or lo (>= {SEM_LO})."},
                    layer="entity_resolution")
print(f"semantic candidate pairs: {n_sem}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Probabilistic linkage (Splink)

# COMMAND ----------

rec = spark.table(ids_t).select(
    F.col("source_record_id").alias("unique_id"), "source_system", "identity_assurance", "survivorship_rank",
    "given_name", "given_name_canonical", "family_name", "family_initial", "dob_str", "email_norm", "phone_norm",
    "postcode", "suburb", "street_norm").toPandas()
sem = spark.table(table_name("er_semantic_candidates")).toPandas()
keys = {u: [] for u in rec["unique_id"]}
hi = {u: [] for u in rec["unique_id"]}
lo = {u: [] for u in rec["unique_id"]}
for r in sem.itertuples():
    k = f"{r.source_record_id_l}|{r.source_record_id_r}"
    for a, b in ((r.source_record_id_l, r.source_record_id_r), (r.source_record_id_r, r.source_record_id_l)):
        if a in keys:
            keys[a].append(k)
            lo[a].append(b)
            if r.semantic_tier == "hi":
                hi[a].append(b)
rec["sem_keys"] = rec["unique_id"].map(keys)
rec["sem_hi"] = rec["unique_id"].map(hi)
rec["sem_lo"] = rec["unique_id"].map(lo)
rec = rec.astype({c: "object" for c in rec.columns})
rec = rec.where(pd.notnull(rec), None)
print(f"records: {len(rec)}")

semantic_cmp = cl.CustomComparison(
    output_column_name="semantic",
    comparison_levels=[
        cll.CustomLevel("sem_lo_l IS NULL OR sem_lo_r IS NULL").configure(is_null_level=True),
        cll.CustomLevel("list_contains(sem_hi_l, unique_id_r) OR list_contains(sem_hi_r, unique_id_l)",
                        label_for_charts=f"semantic neighbour >= {SEM_HI}"),
        cll.CustomLevel("list_contains(sem_lo_l, unique_id_r) OR list_contains(sem_lo_r, unique_id_l)",
                        label_for_charts=f"semantic neighbour >= {SEM_LO}"),
        cll.ElseLevel(),
    ],
    comparison_description="NEAREST BY semantic neighbour tier",
)
BLOCKS = [
    block_on("dob_str"),
    block_on("email_norm"),
    block_on("phone_norm"),
    block_on("street_norm", "postcode"),
    block_on("postcode", "substr(given_name_canonical, 1, 1)"),
    block_on("family_name", "given_name_canonical"),
    block_on("sem_keys", arrays_to_explode=["sem_keys"]),
]
SEMANTIC_BLOCK = str(len(BLOCKS) - 1)
settings = SettingsCreator(
    link_type="dedupe_only",
    unique_id_column_name="unique_id",
    blocking_rules_to_generate_predictions=BLOCKS,
    comparisons=[
        cl.NameComparison("given_name_canonical").configure(term_frequency_adjustments=True),
        cl.NameComparison("family_name").configure(term_frequency_adjustments=True),
        cl.DateOfBirthComparison("dob_str", input_is_string=True),
        cl.EmailComparison("email_norm"),
        cl.ExactMatch("phone_norm").configure(term_frequency_adjustments=True),
        cl.ExactMatch("postcode"),
        cl.JaroWinklerAtThresholds("street_norm", [0.95, 0.85]),
        semantic_cmp,
    ],
    additional_columns_to_retain=["source_system"],
    retain_intermediate_calculation_columns=False,
    retain_matching_columns=True,
)
linker = Linker(rec, settings, db_api=DuckDBAPI())
linker.training.estimate_probability_two_random_records_match(
    [block_on("email_norm", "dob_str"), block_on("given_name_canonical", "family_name", "dob_str")], recall=0.7)
linker.training.estimate_u_using_random_sampling(max_pairs=U_MAX_PAIRS)
linker.training.estimate_parameters_using_expectation_maximisation(block_on("dob_str"))
linker.training.estimate_parameters_using_expectation_maximisation(block_on("postcode", "substr(given_name_canonical, 1, 1)"))
pred = linker.inference.predict(threshold_match_probability=REVIEW_T).as_pandas_dataframe()
print(f"predicted pairs >= {REVIEW_T}: {len(pred)}")

os.makedirs(MODEL_ROOT, exist_ok=True)
model_path = f"{MODEL_ROOT}/splink_model_{run_id}.json"
linker.misc.save_model_to_json(model_path, overwrite=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Decisions: model + steward overrides

# COMMAND ----------

gamma_cols = [c for c in pred.columns if c.startswith("gamma_")]
pred["source_record_id_l"] = pred[["unique_id_l", "unique_id_r"]].min(axis=1)
pred["source_record_id_r"] = pred[["unique_id_l", "unique_id_r"]].max(axis=1)
pred["match_method"] = pred["match_key"].astype(str).map(lambda k: "semantic" if k == SEMANTIC_BLOCK else "probabilistic")
pred["evidence"] = pred[gamma_cols].apply(lambda r: ", ".join(f"{c[6:]}={int(v)}" for c, v in r.items() if pd.notnull(v)), axis=1)
sem_sim = {(r.source_record_id_l, r.source_record_id_r): float(r.semantic_similarity) for r in sem.itertuples()}
pred["semantic_similarity"] = [sem_sim.get((a, b)) for a, b in zip(pred["source_record_id_l"], pred["source_record_id_r"])]

decisions = spark.sql(f"""SELECT least(source_record_id_l, source_record_id_r) AS l, greatest(source_record_id_l, source_record_id_r) AS r,
                                  max_by(decision, decided_at) AS decision
                           FROM {fqn('identity_review_decisions')} WHERE active GROUP BY 1, 2""").toPandas()
must = {(d.l, d.r) for d in decisions.itertuples() if d.decision == "must_link"}
cannot = {(d.l, d.r) for d in decisions.itertuples() if d.decision == "cannot_link"}
known_ids = set(rec["unique_id"])

edges = pred[["source_record_id_l", "source_record_id_r", "match_probability", "match_weight", "match_method",
              "semantic_similarity", "evidence"]].copy()
steward_rows = [dict(source_record_id_l=l, source_record_id_r=r, match_probability=1.0, match_weight=None, match_method="steward",
                     semantic_similarity=sem_sim.get((l, r)), evidence="steward must_link")
                for (l, r) in must if l in known_ids and r in known_ids]
if steward_rows:
    edges = pd.concat([edges[~edges.set_index(["source_record_id_l", "source_record_id_r"]).index.isin(list(must))],
                       pd.DataFrame(steward_rows)], ignore_index=True)
pair_idx = list(zip(edges["source_record_id_l"], edges["source_record_id_r"]))
edges["steward_decision"] = ["must_link" if p in must else "cannot_link" if p in cannot else None for p in pair_idx]
edges["decision"] = [
    "rejected_by_steward" if sd == "cannot_link" else "linked" if (sd == "must_link" or p >= AUTO_T) else "review"
    for sd, p in zip(edges["steward_decision"], edges["match_probability"])]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Clusters and stable constituent IDs

# COMMAND ----------

parent = {u: u for u in rec["unique_id"]}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for l, r in edges.loc[edges["decision"] == "linked", ["source_record_id_l", "source_record_id_r"]].itertuples(index=False):
    a, b = find(l), find(r)
    if a != b:
        parent[max(a, b)] = min(a, b)
clusters = pd.DataFrame({"source_record_id": list(parent)})
clusters["cluster"] = clusters["source_record_id"].map(find)

prior = (spark.table(table_name("silver_identity_xref")).select("source_record_id", "constituent_id").toPandas()
         if table_exists("silver_identity_xref") else pd.DataFrame(columns=["source_record_id", "constituent_id"]))
c = clusters.merge(prior, on="source_record_id", how="left")
size = c.groupby("cluster").size().rename("size")
votes = (c.dropna(subset=["constituent_id"]).groupby(["cluster", "constituent_id"]).size().rename("votes").reset_index()
         .merge(size.reset_index(), on="cluster").sort_values(["constituent_id", "votes", "size", "cluster"], ascending=[True, False, False, True]))
claimed = votes.drop_duplicates("constituent_id")                         # one cluster keeps each prior id (largest share)
claimed = claimed.sort_values(["cluster", "votes", "constituent_id"], ascending=[True, False, True]).drop_duplicates("cluster")
assign = dict(zip(claimed["cluster"], claimed["constituent_id"]))
seq = int(get_control("constituent_seq", 10000))
for cl_ in sorted(set(clusters["cluster"]) - set(assign)):
    seq += 1
    assign[cl_] = f"C-{seq}"
set_control("constituent_seq", seq)
clusters["constituent_id"] = clusters["cluster"].map(assign)
reused = sum(1 for v in assign.values() if v in set(prior["constituent_id"]))
print(f"constituents: {len(assign)} (reused {reused} prior ids, minted up to C-{seq})")

# confidence: mean over member records of their best accepted link within the cluster (singletons = 1.0)
cid_of = dict(zip(clusters["source_record_id"], clusters["constituent_id"]))
edges["constituent_id_l"] = edges["source_record_id_l"].map(cid_of)
edges["constituent_id_r"] = edges["source_record_id_r"].map(cid_of)
linked = edges[(edges["decision"] == "linked") & (edges["constituent_id_l"] == edges["constituent_id_r"])]
best = pd.concat([linked[["source_record_id_l", "match_probability"]].rename(columns={"source_record_id_l": "source_record_id"}),
                  linked[["source_record_id_r", "match_probability"]].rename(columns={"source_record_id_r": "source_record_id"})])
best = best.groupby("source_record_id")["match_probability"].max().rename("best_link_probability")
clusters = clusters.merge(best, on="source_record_id", how="left")
clusters["source_record_count"] = clusters.groupby("constituent_id")["source_record_id"].transform("count")
clusters["best_link_probability"] = clusters["best_link_probability"].where(clusters["source_record_count"] > 1, 1.0)
clusters["identity_confidence"] = clusters.groupby("constituent_id")["best_link_probability"].transform("mean")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Outputs

# COMMAND ----------

xref = spark.createDataFrame(clusters[["source_record_id", "constituent_id", "best_link_probability", "source_record_count",
                                       "identity_confidence"]].astype({"source_record_count": "int"}))
xref = xref.withColumn("run_id", F.lit(run_id)).withColumn("resolved_at", F.current_timestamp())
write_table(xref, "silver_identity_xref",
            "Resolved identity cross-reference: source identity record -> constituent_id (stable across runs).",
            column_comments={"best_link_probability": "Highest accepted link probability from this record to another record of the same constituent.",
                             "source_record_count": "Number of source records resolved to the constituent."},
            layer="entity_resolution")

edf = spark.createDataFrame(edges.astype(object).where(pd.notnull(edges), None),
                            "source_record_id_l string, source_record_id_r string, match_probability double, match_weight double, "
                            "match_method string, semantic_similarity double, evidence string, steward_decision string, decision string, "
                            "constituent_id_l string, constituent_id_r string")
write_table(edf.withColumn("run_id", F.lit(run_id)), "er_pairwise_predictions",
            f"Splink pairwise predictions >= {REVIEW_T} with decisions (linked >= {AUTO_T}, review band, steward overrides).",
            column_comments={"evidence": "Comparison levels (gamma) per attribute - higher is stronger agreement.",
                             "match_method": "probabilistic (found by attribute blocking) | semantic (found only by NEAREST BY) | steward",
                             "decision": "linked | review | rejected_by_steward"},
            layer="entity_resolution")

review = (edf.filter("decision = 'review' AND steward_decision IS NULL")
          .unionByName(edf.filter("decision = 'rejected_by_steward' AND constituent_id_l = constituent_id_r")))
review = (review.withColumn("review_reason", F.when(F.col("decision") == "review", F.lit("probability in review band"))
                            .otherwise(F.lit("cannot_link conflict: records still connected through other links")))
          .withColumn("pair_id", F.sha2(F.concat_ws("|", "source_record_id_l", "source_record_id_r"), 256).substr(1, 16))
          .withColumn("status", F.lit("open")).withColumn("queued_at", F.current_timestamp()).withColumn("run_id", F.lit(run_id)))
n_review = write_table(review, "er_review_queue", "Identity links queued for steward review.", layer="entity_resolution")

# golden record by survivorship: most trusted source first, then most recent
ids = spark.table(ids_t).join(spark.table(table_name("silver_identity_xref")).select("source_record_id", "constituent_id",
                                                                                  "identity_confidence", "source_record_count"), "source_record_id")


def survive(col: str, order=None):
    w = Window.partitionBy("constituent_id").orderBy(*(order or [F.col("survivorship_rank").asc(), F.col("updated_at").desc()]))
    return F.first(F.col(col), ignorenulls=True).over(w.rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing))


recent = [F.col("updated_at").desc(), F.col("survivorship_rank").asc()]
golden = (ids.select(
    "constituent_id", "identity_confidence", "source_record_count",
    survive("given_raw").alias("given_raw"), survive("family_raw").alias("family_raw"), survive("dob").alias("dob"),
    survive("email_norm", recent).alias("email"),
    F.first(F.when(F.col("phone_type") == "mobile", F.col("phone_norm")), ignorenulls=True).over(
        Window.partitionBy("constituent_id").orderBy(*recent).rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)).alias("mobile"),
    survive("street_norm", recent).alias("street"), survive("suburb", recent).alias("suburb"),
    survive("postcode", recent).alias("postcode"),
    F.max(F.when(F.col("identity_assurance") == "verified", True).otherwise(False)).over(Window.partitionBy("constituent_id")).alias("has_verified_source"),
    F.collect_set("source_system").over(Window.partitionBy("constituent_id")).alias("source_systems"),
    F.collect_set("data_domain").over(Window.partitionBy("constituent_id")).alias("data_domains"),
).dropDuplicates(["constituent_id"])
    .withColumn("given_name", F.initcap(F.lower(F.trim("given_raw"))))
    .withColumn("family_name", F.initcap(F.lower(F.trim("family_raw"))))
    .withColumn("display_name", F.concat_ws(" ", "given_name", "family_name"))
    .withColumn("initials", F.upper(F.concat(F.substring("given_name", 1, 1), F.substring("family_name", 1, 1))))
    .withColumn("street", F.initcap("street")).withColumn("suburb", F.initcap("suburb"))
    .withColumn("birth_year", F.year("dob"))
    .drop("given_raw", "family_raw")
    .withColumn("run_id", F.lit(run_id)))
n_const = write_table(golden, "silver_constituents",
                      "Golden record per resolved constituent (survivorship: source assurance rank, then recency).",
                      column_comments={"has_verified_source": "At least one record comes from a verified identity source.",
                                       "data_domains": "Data domains holding at least one source record for the constituent."},
                      layer="entity_resolution")

# identity graph: every member record, plus review-band records from other clusters
members = ids.select("constituent_id", "source_record_id", "source_system", "source_display_name", "agency_code", "data_domain",
                     "identity_assurance", "survivorship_rank", "updated_at")
anchor_w = Window.partitionBy("constituent_id").orderBy("survivorship_rank", F.desc("updated_at"), "source_record_id")
members = (members.withColumn("is_anchor", F.row_number().over(anchor_w) == 1)
           .join(spark.table(table_name("silver_identity_xref")).select("source_record_id", "best_link_probability"), "source_record_id"))
links = members.select(
    "constituent_id", "source_record_id", "source_system", "source_display_name", "agency_code", "data_domain",
    F.when(F.col("is_anchor") & (F.col("identity_assurance") == "verified"), "verified").when(F.col("is_anchor"), "anchor")
     .otherwise("matched").alias("link_state"),
    F.when(F.col("is_anchor"), F.lit(1.0)).otherwise(F.col("best_link_probability")).alias("link_probability"),
    F.lit(None).cast("string").alias("linked_constituent_id"))
rv = edf.filter("decision = 'review' AND steward_decision IS NULL AND constituent_id_l <> constituent_id_r")
rv_nodes = (rv.select(F.col("constituent_id_l").alias("constituent_id"), F.col("source_record_id_r").alias("source_record_id"),
                      "match_probability", F.col("constituent_id_r").alias("linked_constituent_id"))
            .unionByName(rv.select(F.col("constituent_id_r").alias("constituent_id"), F.col("source_record_id_l").alias("source_record_id"),
                                   "match_probability", F.col("constituent_id_l").alias("linked_constituent_id")))
            .join(members.select("source_record_id", "source_system", "source_display_name", "agency_code", "data_domain"), "source_record_id")
            .select("constituent_id", "source_record_id", "source_system", "source_display_name", "agency_code", "data_domain",
                    F.lit("review").alias("link_state"), F.col("match_probability").alias("link_probability"), "linked_constituent_id"))
write_table(links.unionByName(rv_nodes).withColumn("run_id", F.lit(run_id)), "silver_identity_links",
            "Identity graph: source records linked to each constituent (verified / anchor / matched) and review-band candidates.",
            column_comments={"link_state": "verified | anchor | matched | review",
                             "linked_constituent_id": "For review links: the constituent the candidate record currently belongs to."},
            layer="entity_resolution")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Evaluation against synthetic ground truth

# COMMAND ----------

checks = [("constituents_resolved", n_const > 0, "critical", n_const, "> 0")]
if table_exists("synthetic_truth_source_records"):
    ev = spark.sql(f"""
      WITH x AS (SELECT x.source_record_id, x.constituent_id, t.person_id
                 FROM {fqn('silver_identity_xref')} x JOIN {fqn('synthetic_truth_source_records')} t USING (source_record_id)),
      pp AS (SELECT a.source_record_id l, b.source_record_id r FROM x a JOIN x b
             ON a.constituent_id = b.constituent_id AND a.source_record_id < b.source_record_id),
      tp AS (SELECT a.source_record_id l, b.source_record_id r FROM x a JOIN x b
             ON a.person_id = b.person_id AND a.source_record_id < b.source_record_id),
      m AS (SELECT (SELECT count(*) FROM pp) predicted, (SELECT count(*) FROM tp) actual,
                   (SELECT count(*) FROM pp JOIN tp USING (l, r)) correct),
      clus AS (SELECT person_id, count(DISTINCT constituent_id) n_c FROM x GROUP BY person_id),
      pure AS (SELECT constituent_id, count(DISTINCT person_id) n_p FROM x GROUP BY constituent_id)
      SELECT predicted, actual, correct,
             correct / nullif(predicted, 0) AS pair_precision, correct / nullif(actual, 0) AS pair_recall,
             (SELECT avg(IF(n_c = 1, 1.0, 0.0)) FROM clus) AS persons_fully_resolved,
             (SELECT avg(IF(n_p = 1, 1.0, 0.0)) FROM pure) AS constituents_pure,
             (SELECT count(*) FROM pure) AS constituents, (SELECT count(*) FROM clus) AS persons
      FROM m""").first()
    p_, r_ = float(ev.pair_precision or 0), float(ev.pair_recall or 0)
    f1 = 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0
    evdf = spark.createDataFrame([(run_id, int(ev.predicted), int(ev.actual), int(ev.correct), p_, r_, f1,
                                   float(ev.persons_fully_resolved), float(ev.constituents_pure), int(ev.constituents),
                                   int(ev.persons), int(n_review), int(n_sem), AUTO_T, REVIEW_T)],
                                 "run_id string, predicted_pairs long, true_pairs long, correct_pairs long, pair_precision double, "
                                 "pair_recall double, pair_f1 double, persons_fully_resolved double, constituents_pure double, "
                                 "constituents long, persons long, review_queue long, semantic_candidates long, "
                                 "auto_match_threshold double, review_threshold double").withColumn("evaluated_at", F.current_timestamp())
    write_table(evdf, "er_evaluation", "Entity resolution accuracy against synthetic ground truth, per run.", mode="append",
                layer="entity_resolution")
    print(f"precision={p_:.4f} recall={r_:.4f} f1={f1:.4f} persons_fully_resolved={ev.persons_fully_resolved:.4f} "
          f"constituents_pure={ev.constituents_pure:.4f} constituents={ev.constituents} persons={ev.persons}")
    checks.append(("er_pair_f1", f1 > 0, "info", round(f1, 4), "see 08_validate for threshold"))

run = spark.createDataFrame([(run_id, json.dumps(dict(embedding_endpoint=EMBED_EP, k=K, semantic_hi=SEM_HI, semantic_lo=SEM_LO,
                                                     auto_match_threshold=AUTO_T, review_threshold=REVIEW_T,
                                                     blocking=["dob", "email", "phone", "street+postcode", "postcode+initial",
                                                               "family+given", "semantic_keys"])),
                              model_path, len(rec), len(pred), n_sem, n_review, n_const)],
                            "run_id string, parameters string, model_path string, records long, predicted_pairs long, "
                            "semantic_candidates long, review_queue long, constituents long").withColumn("ran_at", F.current_timestamp())
write_table(run, "er_model_runs", "Entity resolution runs: parameters, Splink model location and volumes.", mode="append",
            layer="entity_resolution")
failed = record_checks("04_entity_resolution", run_id, checks)
assert not failed, f"critical checks failed: {failed}"
