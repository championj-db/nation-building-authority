# Databricks notebook source
# MAGIC %md
# MAGIC # Map evidence to obligations - Automated Compliance Reporting
# MAGIC
# MAGIC Each collected document is classified into an **artefact type**; obligations declare which
# MAGIC artefact types they require, so the type is what links evidence to obligations (one document
# MAGIC can satisfy several obligations, e.g. steering committee minutes).
# MAGIC
# MAGIC | Method | When | Counts as coverage? |
# MAGIC | --- | --- | --- |
# MAGIC | **Rule** | Structured sources that classify their records (`document_class` matches a catalogue type for that source) | Yes |
# MAGIC | **AI suggestion** | Everything else (documents, minutes, unclassified records) via `ai_query` with structured output | **No** - shown as *Needs review* |
# MAGIC | **Human review** | Confirm / reject in the app (or the synthetic reviewer) | Yes, and overrides the rule |
# MAGIC
# MAGIC AI output is a recommendation only, consistent with the
# MAGIC [DTA AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework):
# MAGIC model, prompt version, confidence and rationale are stored with every suggestion.
# MAGIC
# MAGIC **Review accuracy** is measured only against the labelled evaluation set (`evidence_labels`),
# MAGIC which mapping never reads. Results are appended to `mapping_evaluation`.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("model_endpoint", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("min_confidence", "0.5")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
model_endpoint = dbutils.widgets.get("model_endpoint")
min_confidence = float(dbutils.widgets.get("min_confidence"))
assert model_endpoint, "model_endpoint parameter is required"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import uuid

PROMPT_VERSION = "evidence-classifier-v1"
RULE_ID = "RULE-SOURCE-CLASS-MATCH-v1"
run_id = f"MAP-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
today = resolve_as_of("")
print(f"run_id={run_id} model={model_endpoint} prompt={PROMPT_VERSION}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Deterministic rule mapping

# COMMAND ----------

rule_maps = spark.sql(f"""
  SELECT d.evidence_id, t.artefact_type, d.first_collected_at AS mapped_at,
         '{RULE_ID}' AS rule_id, d.source_id, d.document_class
  FROM {fqn('evidence_documents')} d
  JOIN {fqn('artefact_types')} t ON t.artefact_type = d.document_class AND t.source_id = d.source_id
""")
rule_maps.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("evidence_rule_mappings"))
spark.sql(f"COMMENT ON TABLE {fqn('evidence_rule_mappings')} IS 'Deterministic mappings: source-system document class matches a catalogue artefact type for that source.'")
print(f"rule mappings: {spark.table(fqn('evidence_rule_mappings')).count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. AI suggestions for everything the rule cannot map
# MAGIC
# MAGIC Incremental: a document is sent to the model once per (model endpoint, prompt version).
# MAGIC Candidates are limited to the artefact types that the document's source system can hold.

# COMMAND ----------

candidates = spark.sql(f"""
  SELECT source_id,
         array_sort(collect_list(artefact_type)) AS candidate_types,
         concat_ws('\\n', array_sort(collect_list(concat('- ', artefact_type, ': ', purpose)))) AS candidate_text
  FROM {fqn('artefact_types')} GROUP BY source_id
""")

todo = (
    spark.table(fqn("evidence_documents"))
    .join(spark.table(fqn("evidence_rule_mappings")).select("evidence_id"), "evidence_id", "left_anti")
    .join(
        spark.table(fqn("mapping_ai_suggestions"))
        .filter((F.col("model_endpoint") == model_endpoint) & (F.col("prompt_version") == PROMPT_VERSION))
        .select("evidence_id"),
        "evidence_id", "left_anti",
    )
    .join(candidates, "source_id")
)
n_todo = todo.count()
print(f"documents needing an AI suggestion: {n_todo}")

# COMMAND ----------

if n_todo:
    todo.createOrReplaceTempView("_ai_todo")
    suggestions = spark.sql(f"""
      WITH prompts AS (
        SELECT evidence_id, candidate_types,
          concat(
            'You classify documents collected as evidence for a government program assurance (Gateway review) report. ',
            'Choose the single artefact type the document IS from the candidate list, or NONE if it is not compliance evidence. ',
            'Do not guess: if the title and excerpt do not clearly indicate a candidate, answer NONE with low confidence.\\n\\n',
            'CANDIDATE ARTEFACT TYPES:\\n', candidate_text, '\\n\\n',
            'DOCUMENT\\nSource system: ', source_name, '\\nTitle: ', title, '\\nFile name: ', file_name,
            '\\nExcerpt: ', coalesce(content_excerpt, ''), '\\n\\n',
            'Return artefact_type exactly as written in the candidate list (or NONE), a confidence between 0 and 1, ',
            'and a one-sentence rationale that cites the words in the document you relied on.'
          ) AS prompt
        FROM _ai_todo
      ),
      scored AS (
        SELECT evidence_id, candidate_types,
          ai_query(
            :endpoint, prompt,
            responseFormat => 'STRUCT<classification: STRUCT<artefact_type: STRING, confidence: DOUBLE, rationale: STRING>>',
            modelParameters => named_struct('temperature', 0.0, 'max_tokens', 300),
            failOnError => false
          ) AS response
        FROM prompts
      ),
      parsed AS (
        SELECT evidence_id, candidate_types, response.errorMessage AS error_message,
               from_json(response.result, 'artefact_type STRING, confidence DOUBLE, rationale STRING') AS out
        FROM scored
      )
      SELECT evidence_id, candidate_types, error_message,
             coalesce(try_element_at(filter(candidate_types, c -> lower(c) = lower(trim(out.artefact_type))), 1), 'NONE') AS artefact_type,
             least(greatest(coalesce(out.confidence, 0.0), 0.0), 1.0) AS confidence,
             out.rationale AS rationale
      FROM parsed
    """, args={"endpoint": model_endpoint})

    # Persist once (a single model call per document), then split successes from failures.
    suggestions.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("_ai_mapping_staging"))
    staged = spark.table(fqn("_ai_mapping_staging"))
    failed = staged.filter(F.col("error_message").isNotNull())
    if failed.count():
        print(f"{failed.count()} model calls failed and will be retried next run; first error: {failed.first()['error_message']}")
    (staged.filter(F.col("error_message").isNull())
        .select(
            F.concat(F.lit("SUG-"), F.upper(F.substring(F.sha2(F.concat_ws("|", "evidence_id", F.lit(run_id)), 256), 1, 12))).alias("suggestion_id"),
            "evidence_id", "artefact_type", "confidence", "rationale", "candidate_types",
            F.lit(model_endpoint).alias("model_endpoint"), F.lit(PROMPT_VERSION).alias("prompt_version"),
            F.current_timestamp().alias("suggested_at"), F.lit(run_id).alias("run_id"),
        )
        .write.mode("append").saveAsTable(fqn("mapping_ai_suggestions")))
    spark.sql(f"DROP TABLE IF EXISTS {fqn('_ai_mapping_staging')}")

print(f"AI suggestions total: {spark.table(fqn('mapping_ai_suggestions')).count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Current mapping state and evidence-to-obligation map

# COMMAND ----------

resolved = resolved_mappings(today, min_confidence)
resolved.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("evidence_mappings"))
spark.sql(f"COMMENT ON TABLE {fqn('evidence_mappings')} IS 'Current effective mapping per evidence document (human > rule > AI suggestion).'")

# Explode to obligation requirements in force today, for both confirmed and suggested mappings.
spark.sql(f"""
  CREATE OR REPLACE TABLE {fqn('evidence_obligation_map')}
  COMMENT 'Evidence document to obligation requirement links in force today. link_state Mapped = counts as coverage; Suggested = AI, awaiting review.'
  AS
  WITH reg AS (
    SELECT obligation_id, version FROM {fqn('obligation_register')}
    WHERE approval_state = 'Approved' AND effective_from <= current_date()
      AND (effective_to IS NULL OR effective_to > current_date()) AND (retired_on IS NULL OR retired_on > current_date())
  )
  SELECT m.evidence_id, q.obligation_id, q.version AS obligation_version, q.requirement_id, q.artefact_type,
         CASE WHEN m.mapping_state = 'Mapped' THEN 'Mapped' ELSE 'Suggested' END AS link_state,
         m.mapping_method, m.ai_confidence, m.ai_rationale, m.model_endpoint
  FROM {fqn('evidence_mappings')} m
  JOIN {fqn('obligation_requirements')} q
    ON q.artefact_type = CASE WHEN m.mapping_state = 'Mapped' THEN m.mapped_type
                              WHEN m.mapping_state = 'Needs review' THEN m.suggested_type END
  JOIN reg ON reg.obligation_id = q.obligation_id AND reg.version = q.version
""")
display(spark.table(fqn("evidence_mappings")).groupBy("mapping_state", "mapping_method").count().orderBy("mapping_state"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Audit events

# COMMAND ----------

rule_ev = audit_events_df(
    spark.table(fqn("evidence_rule_mappings")), event_type="mapping.rule_applied", entity_type="evidence",
    entity_id=F.col("evidence_id"), related_id=F.col("artefact_type"),
    summary=F.format_string("%s mapped to %s by rule %s", "evidence_id", "artefact_type", "rule_id"),
    actor=F.lit("mapping.rules"), occurred_at=F.col("mapped_at"),
    payload=F.to_json(F.struct("rule_id", "document_class")),
    dedup_key=F.format_string("mapping.rule_applied|%s|%s", "evidence_id", "artefact_type"),
)
ai_ev = audit_events_df(
    spark.table(fqn("mapping_ai_suggestions")), event_type="mapping.ai_suggested", entity_type="evidence",
    entity_id=F.col("evidence_id"), related_id=F.col("artefact_type"),
    summary=F.format_string("AI suggested %s for %s (confidence %.2f)", "artefact_type", "evidence_id", "confidence"),
    actor=F.col("model_endpoint"), occurred_at=F.col("suggested_at"),
    payload=F.to_json(F.struct("prompt_version", "confidence", "rationale", "run_id")),
    dedup_key=F.format_string("mapping.ai_suggested|%s", "suggestion_id"),
)
reviews = spark.table(fqn("mapping_reviews"))
human_ev = audit_events_df(
    reviews, event_type="mapping.human_reviewed", entity_type="evidence", entity_id=F.col("evidence_id"),
    related_id=F.col("artefact_type"),
    summary=F.when(F.col("decision") == "confirm", F.format_string("Evidence mapping confirmed: %s linked to %s by %s", "evidence_id", "artefact_type", "reviewer"))
             .otherwise(F.format_string("Evidence rejected as not compliance evidence: %s by %s", "evidence_id", "reviewer")),
    actor=F.col("reviewer"), occurred_at=F.col("reviewed_at"),
    payload=F.to_json(F.struct("decision", "comment", "channel")),
    dedup_key=F.format_string("mapping.human_reviewed|%s", "review_id"),
)
print(f"audit events appended: {append_audit_events(rule_ev.unionByName(ai_ev).unionByName(human_ev))}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Evaluate against the labelled set

# COMMAND ----------

spark.sql(f"""
  CREATE OR REPLACE TABLE {fqn('mapping_evaluation_detail')}
  COMMENT 'Per-document comparison of every mapping method with the labelled evaluation set (latest run).'
  AS
  WITH ai AS (
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY evidence_id ORDER BY suggested_at DESC) rn
      FROM {fqn('mapping_ai_suggestions')} WHERE model_endpoint = :endpoint AND prompt_version = :prompt
    ) WHERE rn = 1
  ),
  human AS (
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY evidence_id ORDER BY reviewed_at DESC) rn FROM {fqn('mapping_reviews')}
    ) WHERE rn = 1
  )
  SELECT d.evidence_id, d.title, d.source_id, l.true_artefact_type, l.is_noise,
         r.artefact_type AS rule_type,
         nullif(ai.artefact_type, 'NONE') AS ai_type, ai.confidence AS ai_confidence, ai.rationale AS ai_rationale,
         h.decision AS human_decision, h.artefact_type AS human_type,
         m.mapping_state AS final_state, m.mapped_type AS final_type
  FROM {fqn('evidence_documents')} d
  JOIN {fqn('evidence_labels')} l USING (evidence_id)
  LEFT JOIN {fqn('evidence_rule_mappings')} r USING (evidence_id)
  LEFT JOIN ai USING (evidence_id)
  LEFT JOIN human h USING (evidence_id)
  LEFT JOIN {fqn('evidence_mappings')} m USING (evidence_id)
""", args={"endpoint": model_endpoint, "prompt": PROMPT_VERSION})

evaluation = spark.sql(f"""
  WITH d AS (SELECT * FROM {fqn('mapping_evaluation_detail')}),
  scored AS (
    SELECT 'rule' AS method, rule_type AS pred, true_artefact_type AS truth FROM d WHERE rule_type IS NOT NULL
    UNION ALL
    SELECT 'ai', ai_type, true_artefact_type FROM d WHERE ai_confidence IS NOT NULL
    UNION ALL
    SELECT 'ai_confident', ai_type, true_artefact_type FROM d WHERE ai_confidence >= :min_conf OR (ai_confidence IS NOT NULL AND ai_type IS NULL)
    UNION ALL
    SELECT 'human', CASE WHEN human_decision = 'confirm' THEN human_type END, true_artefact_type FROM d WHERE human_decision IS NOT NULL
    UNION ALL
    SELECT 'resolved', final_type, true_artefact_type FROM d WHERE final_state IN ('Mapped', 'Rejected')
  )
  SELECT :run_id AS run_id, current_timestamp() AS evaluated_at, method,
         count(*) AS labelled_items,
         sum(CASE WHEN coalesce(pred, 'NONE') = coalesce(truth, 'NONE') THEN 1 ELSE 0 END) AS correct,
         CAST(round(avg(CASE WHEN coalesce(pred, 'NONE') = coalesce(truth, 'NONE') THEN 1.0 ELSE 0.0 END), 4) AS DOUBLE) AS accuracy,
         sum(CASE WHEN pred IS NOT NULL AND truth IS NULL THEN 1 ELSE 0 END) AS false_maps,
         sum(CASE WHEN pred IS NULL AND truth IS NOT NULL THEN 1 ELSE 0 END) AS missed,
         concat('model=', :endpoint, '; prompt=', :prompt, '; min_confidence=', CAST(:min_conf AS STRING)) AS notes
  FROM scored GROUP BY method
""", args={"run_id": run_id, "endpoint": model_endpoint, "prompt": PROMPT_VERSION, "min_conf": min_confidence})
evaluation.write.mode("append").saveAsTable(fqn("mapping_evaluation"))
display(spark.table(fqn("mapping_evaluation")).filter(F.col("run_id") == run_id).orderBy("method"))
