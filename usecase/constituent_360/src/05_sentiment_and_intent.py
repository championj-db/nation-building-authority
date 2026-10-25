# Databricks notebook source
# MAGIC %md
# MAGIC # 05 Sentiment, intent and need signals
# MAGIC
# MAGIC AI signals for every interaction, computed **incrementally** (only new or changed text, keyed by
# MAGIC `interaction_id` + `text_hash`) with Databricks AI Functions:
# MAGIC
# MAGIC | Signal | Function |
# MAGIC | --- | --- |
# MAGIC | `sentiment` | `ai_analyze_sentiment` |
# MAGIC | `intent` | `ai_classify` over the reference intent list |
# MAGIC | `tone`, `urgency_score`, `needs`, `summary`, `follow_up_required` | `ai_query` with a JSON-schema `responseFormat` |
# MAGIC
# MAGIC Signals are **inferred personal information**: they are tagged `protected_inferred`, served only through
# MAGIC policy-protected tables and masked unless the purpose allows signals (`ref_purpose_domain_policy.signals_allowed`).
# MAGIC Accuracy is measured against synthetic ground truth in `ai_signal_evaluation`.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("llm_endpoint", "databricks-claude-haiku-4-5")
dbutils.widgets.text("max_rows_per_run", "0")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None
LLM = dbutils.widgets.get("llm_endpoint")
MAX_ROWS = int(dbutils.widgets.get("max_rows_per_run") or 0)

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("AI")
TONES = ["calm", "concerned", "frustrated", "distressed", "satisfied"]
SIG_DDL = ("interaction_id STRING, text_hash STRING, sentiment STRING, intent STRING, tone STRING, urgency_score INT, "
           "needs ARRAY<STRING>, summary STRING, follow_up_required BOOLEAN, ai_error STRING, model STRING, "
           "scored_at TIMESTAMP, run_id STRING")
if not table_exists("ai_interaction_signals"):
    spark.sql(f"CREATE TABLE {fqn('ai_interaction_signals')} ({SIG_DDL}) "
              f"COMMENT 'AI-derived signals per interaction. Inferred personal information.'")
    claim_object("ai_interaction_signals")
assert_owned("ai_interaction_signals")

response_format = json.dumps({"type": "json_schema", "json_schema": {"name": "interaction_signals", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["tone", "urgency_score", "needs", "summary", "follow_up_required"],
    "properties": {
        "tone": {"type": "string", "enum": TONES},
        "urgency_score": {"type": "integer", "description": "0 = no urgency, 100 = immediate risk of harm or loss of housing/income"},
        "needs": {"type": "array", "items": {"type": "string", "enum": NEED_CODES}},
        "summary": {"type": "string", "description": "One neutral sentence, at most 25 words, no names or contact details"},
        "follow_up_required": {"type": "boolean"},
    }}}})
need_desc = "; ".join(f"{c} = {d}" for c, d in NEEDS)
prompt = ("You review a government service interaction for a case officer. Classify the constituent's tone, how urgent their "
          "situation is (0-100), which underlying needs are evident (" + need_desc + "; return [] if none), whether the agency "
          "must follow up, and summarise it in one neutral sentence without names or contact details. Interaction:\n")

# COMMAND ----------

todo = spark.sql(f"""
  SELECT i.interaction_id, i.text_hash, substr(i.interaction_text, 1, 4000) AS txt
  FROM {fqn('silver_interactions')} i
  LEFT ANTI JOIN {fqn('ai_interaction_signals')} s ON s.interaction_id = i.interaction_id AND s.text_hash = i.text_hash
                                                  AND s.ai_error IS NULL""")
if MAX_ROWS > 0:
    todo = todo.orderBy("interaction_id").limit(MAX_ROWS)
n_todo = todo.count()
print(f"scoring {n_todo} interactions")

if n_todo:
    todo.createOrReplaceTempView("c360_ai_todo")
    batch = spark.sql(f"""
      WITH r AS (
        SELECT interaction_id, text_hash,
               ai_analyze_sentiment(txt) AS sentiment,
               ai_classify(txt, {sql_array(INTENT_CODES)}) AS intent,
               ai_query({sql_str(LLM)}, concat({sql_str(prompt)}, txt),
                        responseFormat => {sql_str(response_format)}, failOnError => false) AS q
        FROM c360_ai_todo)
      SELECT interaction_id, text_hash, sentiment, intent, j.tone,
             CAST(least(greatest(j.urgency_score, 0), 100) AS INT) AS urgency_score,
             filter(j.needs, x -> x IN ({', '.join(sql_str(n) for n in NEED_CODES)})) AS needs,
             j.summary, j.follow_up_required, q.errorMessage AS ai_error,
             {sql_str(LLM)} AS model, current_timestamp() AS scored_at, {sql_str(run_id)} AS run_id
      FROM (SELECT *, from_json(q.result, 'tone STRING, urgency_score INT, needs ARRAY<STRING>, summary STRING, follow_up_required BOOLEAN') AS j
            FROM r)""")
    # materialise once (AI calls are the expensive part), then merge
    write_table(batch, "ai_interaction_signals__batch", "Staging batch for ai_interaction_signals.", layer="ai_signals",
                classification="protected_inferred")
    spark.sql(f"""
      MERGE INTO {fqn('ai_interaction_signals')} t
      USING {fqn('ai_interaction_signals__batch')} s ON t.interaction_id = s.interaction_id
      WHEN MATCHED THEN UPDATE SET *
      WHEN NOT MATCHED THEN INSERT *""")
    drop_owned("ai_interaction_signals__batch")

# drop signals for interactions that no longer exist upstream
spark.sql(f"""DELETE FROM {fqn('ai_interaction_signals')} s
              WHERE NOT EXISTS (SELECT 1 FROM {fqn('silver_interactions')} i WHERE i.interaction_id = s.interaction_id)""")
for c, d in {"sentiment": COLUMN_DOCS["sentiment"], "intent": COLUMN_DOCS["intent"], "tone": COLUMN_DOCS["tone"],
             "urgency_score": COLUMN_DOCS["urgency_score"],
             "needs": "AI-derived need codes evident in the interaction (see ref_needs). Inferred personal information.",
             "summary": "AI one-sentence neutral summary without names or contact details.",
             "text_hash": "Hash of the scored text; signals are recomputed only when it changes.",
             "ai_error": "Structured-output error, if any; the row is retried next run."}.items():
    spark.sql(f"ALTER TABLE {fqn('ai_interaction_signals')} ALTER COLUMN {c} COMMENT {sql_str(d)}")
tag_table("ai_interaction_signals", {**BASE_TAGS, "nba_layer": "ai_signals", "nba_classification": "protected_inferred"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluation against synthetic ground truth

# COMMAND ----------

stats = spark.sql(f"SELECT count(*) n, avg(IF(ai_error IS NULL, 1.0, 0.0)) ok FROM {fqn('ai_interaction_signals')}").first()
checks = [("signals_present", stats.n > 0, "critical", stats.n, "> 0"),
          ("structured_output_success", (stats.ok or 0) >= 0.95, "warning", round(stats.ok or 0, 4), ">= 0.95")]
if table_exists("synthetic_truth_interactions"):
    ev = spark.sql(f"""
      SELECT count(*) AS n,
             avg(IF(s.intent = t.intent, 1.0, 0.0)) AS intent_accuracy,
             avg(IF(s.sentiment = t.sentiment_label OR (t.sentiment_label = 'negative' AND s.sentiment = 'mixed'), 1.0, 0.0)) AS sentiment_agreement,
             sum(size(array_intersect(s.needs, t.needs))) / nullif(sum(size(s.needs)), 0) AS needs_precision,
             sum(size(array_intersect(s.needs, t.needs))) / nullif(sum(size(t.needs)), 0) AS needs_recall
      FROM {fqn('ai_interaction_signals')} s JOIN {fqn('synthetic_truth_interactions')} t USING (interaction_id)
      WHERE s.ai_error IS NULL AND t.direction = 'inbound'""").first()
    write_table(spark.createDataFrame([(run_id, LLM, int(ev.n), float(ev.intent_accuracy or 0), float(ev.sentiment_agreement or 0),
                                        float(ev.needs_precision or 0), float(ev.needs_recall or 0))],
                                      "run_id string, llm_endpoint string, evaluated_rows long, intent_accuracy double, "
                                      "sentiment_agreement double, needs_precision double, needs_recall double")
                .withColumn("evaluated_at", F.current_timestamp()),
                "ai_signal_evaluation", "AI signal accuracy against synthetic ground truth (inbound interactions), per run.",
                mode="append", layer="ai_signals")
    print(ev)
    checks.append(("intent_accuracy", (ev.intent_accuracy or 0) >= 0.6, "warning", round(ev.intent_accuracy or 0, 4), ">= 0.60"))
failed = record_checks("05_sentiment_and_intent", run_id, checks)
assert not failed, f"critical checks failed: {failed}"
