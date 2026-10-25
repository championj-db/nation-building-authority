# Databricks notebook source
# MAGIC %md
# MAGIC # 03 Standardise silver
# MAGIC
# MAGIC Rebuilds the conformed silver layer from bronze (idempotent; latest delivery wins per record):
# MAGIC
# MAGIC | Table | Grain | Purpose |
# MAGIC | --- | --- | --- |
# MAGIC | `silver_source_identities` | source identity record | typed + normalised identity attributes from six agency systems, plus `identity_text` for semantic matching |
# MAGIC | `silver_contact_points` | contact point x record | phone, email, web account and agency references -> source record (links interactions to identities) |
# MAGIC | `silver_interactions` | interaction | one schema across phone, web, email and shopfront |
# MAGIC | `silver_cases` | case | latest case snapshot (service journeys) |
# MAGIC | `silver_consent_events` | consent event | typed consent decisions captured against agency-local client references |
# MAGIC | `silver_quarantine` | rejected row | rows that failed a data quality rule, with the reason |
# MAGIC
# MAGIC Normalisation is deliberately conservative - it removes formatting differences (case, punctuation,
# MAGIC phone and email formats, street-type abbreviations, unit notation, nicknames) and leaves genuine
# MAGIC differences (typos, stale addresses, surname changes) for entity resolution to weigh.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("SILVER")
STATE_RX = "|".join(AU_STATES)
ADDR_RX = rf"^(.*),\s*([^,]+?)\s+({STATE_RX})\s+(\d{{4}})$"
AGENCY_SYSTEM = {"SNSW": "snsw_customer", "HOUSING": "housing_crm", "TRANSPORT": "transport_licence",
                 "REVENUE": "revenue_concession", "HEALTH": "community_health"}


def bronze(extract: str) -> DataFrame:
    return spark.table(table_name(f"bronze_{extract}"))


def latest(df: DataFrame, key: str, order_col: str = "_delivery") -> DataFrame:
    w = Window.partitionBy(key).orderBy(F.desc(order_col), F.desc("_ingested_at"))
    return df.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")


def parse_date(c: str, fmt: str):
    return F.expr(f"cast(try_to_timestamp({c}, '{fmt}') AS DATE)")


def parse_ts(c: str):
    return F.expr(f"try_to_timestamp({c}, 'yyyy-MM-dd HH:mm:ss')")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Identities: per-source parsing into one shape

# COMMAND ----------

ID_COLS = ["source_system", "native_id", "given_raw", "family_raw", "family_initial", "dob", "dob_raw", "email_raw",
           "phone_raw", "street_raw", "suburb_raw", "state", "postcode", "updated_at", "_delivery", "_source_file", "_ingested_at"]


def split_single_line(df: DataFrame, col: str) -> DataFrame:
    return (df.withColumn("street_raw", F.regexp_extract(col, ADDR_RX, 1))
              .withColumn("suburb_raw", F.regexp_extract(col, ADDR_RX, 2))
              .withColumn("state", F.regexp_extract(col, ADDR_RX, 3))
              .withColumn("postcode", F.regexp_extract(col, ADDR_RX, 4)))


sources = []
b = latest(bronze("snsw_customers"), "customer_ref")
sources.append(b.select(F.lit("snsw_customer").alias("source_system"), F.col("customer_ref").alias("native_id"),
                        F.col("first_name").alias("given_raw"), F.col("last_name").alias("family_raw"),
                        F.lit(None).cast("string").alias("family_initial"), parse_date("date_of_birth", "yyyy-MM-dd").alias("dob"),
                        F.col("date_of_birth").alias("dob_raw"), F.col("email").alias("email_raw"), F.col("mobile").alias("phone_raw"),
                        F.col("street_address").alias("street_raw"), F.col("suburb").alias("suburb_raw"), "state", "postcode",
                        parse_ts("updated_at").alias("updated_at"), "_delivery", "_source_file", "_ingested_at"))

b = split_single_line(latest(bronze("transport_licence_holders"), "licence_no"), "address")
sources.append(b.select(F.lit("transport_licence").alias("source_system"), F.col("licence_no").alias("native_id"),
                        F.col("given_names").alias("given_raw"), F.col("surname").alias("family_raw"),
                        F.lit(None).cast("string").alias("family_initial"), parse_date("dob", "dd/MM/yyyy").alias("dob"),
                        F.col("dob").alias("dob_raw"), F.lit(None).cast("string").alias("email_raw"), F.col("phone").alias("phone_raw"),
                        "street_raw", "suburb_raw", "state", "postcode", parse_ts("updated_at").alias("updated_at"),
                        "_delivery", "_source_file", "_ingested_at"))

b = latest(bronze("revenue_concession_applicants"), "applicant_id")
sources.append(b.select(F.lit("revenue_concession").alias("source_system"), F.col("applicant_id").alias("native_id"),
                        F.regexp_extract("applicant_name", r"^(\S+)", 1).alias("given_raw"),
                        F.regexp_extract("applicant_name", r"^\S+\s+(.*)$", 1).alias("family_raw"),
                        F.lit(None).cast("string").alias("family_initial"), parse_date("birth_date", "yyyy-MM-dd").alias("dob"),
                        F.col("birth_date").alias("dob_raw"), F.col("email").alias("email_raw"), F.col("contact_phone").alias("phone_raw"),
                        F.col("address_line").alias("street_raw"), F.col("locality").alias("suburb_raw"), "state", "postcode",
                        parse_ts("updated_at").alias("updated_at"), "_delivery", "_source_file", "_ingested_at"))

b = split_single_line(latest(bronze("housing_crm_clients"), "client_no"), "address")
sources.append(b.select(F.lit("housing_crm").alias("source_system"), F.col("client_no").alias("native_id"),
                        F.trim(F.regexp_extract("client_name", r",\s*(.*)$", 1)).alias("given_raw"),
                        F.trim(F.regexp_extract("client_name", r"^([^,]+),", 1)).alias("family_raw"),
                        F.lit(None).cast("string").alias("family_initial"), parse_date("dob", "dd/MM/yyyy").alias("dob"),
                        F.col("dob").alias("dob_raw"), F.lit(None).cast("string").alias("email_raw"), F.col("phone").alias("phone_raw"),
                        "street_raw", "suburb_raw", "state", "postcode", parse_ts("updated_at").alias("updated_at"),
                        "_delivery", "_source_file", "_ingested_at"))

b = latest(bronze("community_health_clients"), "patient_ref")
sources.append(b.select(F.lit("community_health").alias("source_system"), F.col("patient_ref").alias("native_id"),
                        F.col("given_name").alias("given_raw"), F.col("family_name").alias("family_raw"),
                        F.lit(None).cast("string").alias("family_initial"), parse_date("birth_date", "yyyy-MM-dd").alias("dob"),
                        F.col("birth_date").alias("dob_raw"), F.lit(None).cast("string").alias("email_raw"), F.col("phone").alias("phone_raw"),
                        F.col("address_line").alias("street_raw"), F.col("suburb").alias("suburb_raw"), F.lit("NSW").alias("state"),
                        "postcode", parse_ts("updated_at").alias("updated_at"), "_delivery", "_source_file", "_ingested_at"))

b = latest(bronze("web_accounts"), "account_id")
sources.append(b.select(F.lit("web_account").alias("source_system"), F.col("account_id").alias("native_id"),
                        F.regexp_extract("display_name", r"^(\S+)", 1).alias("given_raw"),
                        F.expr(r"CASE WHEN display_name RLIKE '^\\S+\\s+\\S\\.$' THEN NULL ELSE regexp_extract(display_name, '^\\S+\\s+(.*)$', 1) END").alias("family_raw"),
                        F.expr(r"CASE WHEN display_name RLIKE '^\\S+\\s+\\S\\.$' THEN lower(regexp_extract(display_name, '\\s(\\S)\\.$', 1)) END").alias("family_initial"),
                        F.lit(None).cast("date").alias("dob"), F.lit(None).cast("string").alias("dob_raw"),
                        F.col("email").alias("email_raw"), F.col("mobile").alias("phone_raw"), F.lit(None).cast("string").alias("street_raw"),
                        F.lit(None).cast("string").alias("suburb_raw"), F.lit(None).cast("string").alias("state"), "postcode",
                        parse_ts("last_login_at").alias("updated_at"), "_delivery", "_source_file", "_ingested_at"))

raw_ids = sources[0]
for s in sources[1:]:
    raw_ids = raw_ids.unionByName(s)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Identity normalisation

# COMMAND ----------

NICK_TO_FORMAL = {v.lower(): k.lower() for k, v in NICKNAMES.items()}
nick_map = F.create_map(*[F.lit(x) for kv in NICK_TO_FORMAL.items() for x in kv])
STREET_EXPAND = {r"\bst\b": "street", r"\brd\b": "road", r"\bave\b": "avenue", r"\bcres\b": "crescent", r"\bpde\b": "parade",
                 r"\bdr\b": "drive", r"\bpl\b": "place", r"\bct\b": "court", r"\bln\b": "lane", r"\bhwy\b": "highway"}
src_ref = spark.createDataFrame(SOURCE_SYSTEMS, "source_system string, source_display_name string, agency_code string, "
                                                "data_domain string, identity_assurance string, survivorship_rank int, extract string").drop("extract")


def norm_street(c):
    s = F.lower(F.trim(c))
    s = F.regexp_replace(s, r"[,.]", " ")
    s = F.regexp_replace(s, r"\s+", " ")
    for rx, rep in STREET_EXPAND.items():
        s = F.regexp_replace(s, rx, rep)
    s = F.regexp_replace(s, r"^unit (\w+) (\d+\w?) (.*)$", "$1/$2 $3")
    s = F.regexp_replace(s, r"^(\d+\w?) (.*) unit (\w+)$", "$3/$1 $2")
    s = F.regexp_replace(s, r"\s*/\s*", "/")
    return F.when(F.length(F.trim(s)) > 0, F.trim(s))


ids = (raw_ids
       .withColumn("source_record_id", F.concat_ws(":", "source_system", "native_id"))
       .withColumn("given_name", F.regexp_extract(F.regexp_replace(F.lower(F.trim("given_raw")), r"[^a-z\s-]", ""), r"^([a-z-]+)", 1))
       .withColumn("given_name", F.when(F.length("given_name") > 0, F.col("given_name")))
       .withColumn("given_name_canonical", F.coalesce(F.try_element_at(nick_map, F.col("given_name")), F.col("given_name")))
       .withColumn("family_name", F.regexp_replace(F.lower(F.trim("family_raw")), r"[^a-z]", ""))
       .withColumn("family_name", F.when(F.length("family_name") > 0, F.col("family_name")))
       .withColumn("email_norm", F.lower(F.trim("email_raw")))
       .withColumn("email_norm", F.when(F.col("email_norm").rlike(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"), F.col("email_norm")))
       .withColumn("email_norm", F.when(F.col("email_norm").rlike("@(gmail|googlemail)\\.com$"),
                                        F.concat(F.regexp_replace(F.regexp_replace(F.split("email_norm", "@")[0], r"\+.*$", ""), r"\.", ""),
                                                 F.lit("@gmail.com"))).otherwise(F.col("email_norm")))
       .withColumn("phone_digits", F.regexp_replace("phone_raw", r"[^0-9]", ""))
       .withColumn("phone_norm", F.when((F.length("phone_digits") == 11) & F.col("phone_digits").startswith("61"),
                                        F.concat(F.lit("0"), F.substring("phone_digits", 3, 9))).otherwise(F.col("phone_digits")))
       .withColumn("phone_norm", F.when(F.length("phone_norm") == 10, F.col("phone_norm")))
       .withColumn("phone_type", F.when(F.col("phone_norm").startswith("04"), "mobile").when(F.col("phone_norm").isNotNull(), "landline"))
       .withColumn("street_norm", norm_street(F.col("street_raw")))
       .withColumn("suburb", F.when(F.length(F.trim("suburb_raw")) > 0, F.lower(F.trim("suburb_raw"))))
       .withColumn("postcode", F.when(F.col("postcode").rlike(r"^\d{4}$"), F.col("postcode")))
       .withColumn("state", F.when(F.length("state") > 0, F.upper("state")))
       .withColumn("dob_str", F.date_format("dob", "yyyy-MM-dd"))
       .withColumn("birth_year", F.year("dob"))
       .join(src_ref, "source_system"))

# identity_text: compact natural-language rendering for embedding / semantic matching
ids = ids.withColumn("identity_text", F.concat_ws(", ",
    F.initcap(F.concat_ws(" ", F.col("given_name"), F.coalesce(F.col("family_name"), F.col("family_initial")))),
    F.when(F.col("dob").isNotNull(), F.concat(F.lit("born "), F.date_format("dob", "d MMMM yyyy"))),
    F.when(F.col("street_norm").isNotNull() | F.col("suburb").isNotNull() | F.col("postcode").isNotNull(),
           F.concat(F.lit("lives at "), F.concat_ws(" ", "street_norm", F.initcap("suburb"), "postcode"))),
    F.when(F.col("email_norm").isNotNull(), F.concat(F.lit("email "), F.col("email_norm"))),
    F.when(F.col("phone_norm").isNotNull(), F.concat(F.lit("phone "), F.col("phone_norm")))))

reasons = F.concat_ws("; ",
    F.when(F.col("native_id").isNull() | (F.length("native_id") == 0), F.lit("missing native id")),
    F.when(F.col("given_name").isNull() & F.col("family_name").isNull(), F.lit("no usable name")))
ids = ids.withColumn("dq_reject", reasons).withColumn("dq_warnings", F.concat_ws("; ",
    F.when(F.col("dob_raw").isNotNull() & (F.length("dob_raw") > 0) & F.col("dob").isNull(), F.lit("unparseable date of birth")),
    F.when(F.col("email_raw").isNotNull() & (F.length("email_raw") > 0) & F.col("email_norm").isNull(), F.lit("invalid email")),
    F.when(F.col("phone_raw").isNotNull() & (F.length("phone_raw") > 0) & F.col("phone_norm").isNull(), F.lit("invalid phone"))))

ID_OUT = ["source_record_id", "source_system", "source_display_name", "native_id", "agency_code", "data_domain",
          "identity_assurance", "survivorship_rank", "given_raw", "family_raw", "given_name", "given_name_canonical",
          "family_name", "family_initial", "dob", "dob_str", "birth_year", "email_norm", "phone_norm", "phone_type",
          "street_norm", "suburb", "state", "postcode", "identity_text", "dq_warnings", "updated_at", "_delivery", "_source_file"]
quarantine = [ids.filter("length(dq_reject) > 0").select(F.lit("silver_source_identities").alias("target_table"),
                                                          F.col("source_record_id").alias("record_key"),
                                                          F.col("dq_reject").alias("reason"), "_source_file", "_delivery")]
n_ids = write_table(ids.filter("length(dq_reject) = 0").select(*ID_OUT), "silver_source_identities",
                    "Silver: one row per source identity record across six agency systems, typed and normalised. "
                    "No common identifier - see silver_identity_xref for the resolved constituent.",
                    column_comments={
                        "given_name_canonical": "Lower-case given name with common short forms mapped to the formal name (Bob -> robert).",
                        "family_name": "Lower-case family name with punctuation and spaces removed (O'Brien -> obrien).",
                        "family_initial": "Family-name initial when the source only holds an initial (web display names).",
                        "email_norm": "Lower-case email; Gmail dots and +tags removed.",
                        "phone_norm": "Australian phone number as 10 digits (+61 converted to 0).",
                        "street_norm": "Street line lower-cased, street types expanded, unit notation as unit/number.",
                        "identity_text": "Natural-language rendering of the identity used for embedding and NEAREST BY semantic matching.",
                        "survivorship_rank": "Attribute trust order for the golden record (1 = most trusted).",
                        "dq_warnings": "Non-fatal data quality findings for the record."},
                    layer="silver", classification="protected")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Contact points

# COMMAND ----------

sid = spark.table(table_name("silver_source_identities"))
contact_points = (sid.select(F.lit("phone").alias("contact_type"), F.col("phone_norm").alias("contact_value"), "source_record_id", "source_system")
                  .unionByName(sid.select(F.lit("email").alias("contact_type"), F.col("email_norm").alias("contact_value"), "source_record_id", "source_system"))
                  .unionByName(sid.select(F.lit("agency_ref").alias("contact_type"), F.col("source_record_id").alias("contact_value"), "source_record_id", "source_system"))
                  .filter("contact_value IS NOT NULL").distinct())
write_table(contact_points, "silver_contact_points",
            "Silver: contact points (phone, email, agency reference) that link channel interactions to source identity records. "
            "A phone shared by a household maps to several records.",
            column_comments={"contact_type": "phone | email | agency_ref", "contact_value": "Normalised value (agency_ref = source_record_id)."},
            layer="silver")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Interactions: four channels, one schema

# COMMAND ----------

agency_system = F.create_map(*[F.lit(x) for kv in AGENCY_SYSTEM.items() for x in kv])
agency_domain = F.create_map(*[F.lit(x) for kv in AGENCY_DOMAIN.items() for x in kv])
channel_label = F.create_map(*[F.lit(x) for kv in CHANNELS for x in kv])


def phone_norm_col(c):
    d = F.regexp_replace(c, r"[^0-9]", "")
    d = F.when((F.length(d) == 11) & d.startswith("61"), F.concat(F.lit("0"), F.substring(d, 3, 9))).otherwise(d)
    return F.when(F.length(d) == 10, d)


def email_norm_col(c):
    e = F.lower(F.trim(c))
    return F.when(e.rlike("@(gmail|googlemail)\\.com$"),
                  F.concat(F.regexp_replace(F.regexp_replace(F.split(e, "@")[0], r"\+.*$", ""), r"\.", ""), F.lit("@gmail.com"))).otherwise(e)


INT_OUT = ["interaction_id", "channel", "direction", "agency_code", "event_ts", "subject", "interaction_text", "contact_type",
           "contact_value", "agency_ref_record_id", "case_ref", "outcome", "handled_by", "duration_seconds", "attachment_name",
           "_delivery", "_source_file"]
calls = latest(bronze("contact_centre_calls"), "call_id").select(
    F.col("call_id").alias("interaction_id"), F.lit("phone").alias("channel"), "direction", "agency_code",
    parse_ts("started_at").alias("event_ts"), F.lit(None).cast("string").alias("subject"), F.col("transcript").alias("interaction_text"),
    F.lit("phone").alias("contact_type"), phone_norm_col(F.col("caller_number")).alias("contact_value"),
    F.when(F.length("account_ref") > 0, F.concat_ws(":", F.element_at(agency_system, F.col("agency_code")), "account_ref")).alias("agency_ref_record_id"),
    F.col("case_ref"), F.col("wrap_outcome").alias("outcome"), F.col("agent_id").alias("handled_by"),
    F.col("duration_seconds").cast("int").alias("duration_seconds"), F.lit(None).cast("string").alias("attachment_name"),
    "_delivery", "_source_file")
web = latest(bronze("web_form_submissions"), "submission_id").select(
    F.col("submission_id").alias("interaction_id"), F.lit("web").alias("channel"), F.lit("inbound").alias("direction"), "agency_code",
    parse_ts("submitted_at").alias("event_ts"), F.col("form_type").alias("subject"), F.col("message").alias("interaction_text"),
    F.lit("agency_ref").alias("contact_type"), F.concat_ws(":", F.lit("web_account"), "account_id").alias("contact_value"),
    F.concat_ws(":", F.lit("web_account"), "account_id").alias("agency_ref_record_id"), "case_ref", F.col("status").alias("outcome"),
    F.lit("web").alias("handled_by"), F.lit(None).cast("int").alias("duration_seconds"), "attachment_name", "_delivery", "_source_file")
emails = latest(bronze("email_messages"), "message_id").select(
    F.col("message_id").alias("interaction_id"), F.lit("email").alias("channel"), "direction", "agency_code",
    parse_ts("received_at").alias("event_ts"), "subject", F.col("body").alias("interaction_text"), F.lit("email").alias("contact_type"),
    email_norm_col(F.when(F.col("direction") == "inbound", F.col("from_address")).otherwise(F.col("to_address"))).alias("contact_value"),
    F.lit(None).cast("string").alias("agency_ref_record_id"), "case_ref", F.lit(None).cast("string").alias("outcome"),
    F.lit("mailbox").alias("handled_by"), F.lit(None).cast("int").alias("duration_seconds"), F.lit(None).cast("string").alias("attachment_name"),
    "_delivery", "_source_file")
shop = latest(bronze("shopfront_visits"), "visit_id").select(
    F.col("visit_id").alias("interaction_id"), F.lit("shopfront").alias("channel"), F.lit("inbound").alias("direction"), "agency_code",
    parse_ts("visited_at").alias("event_ts"), F.col("service").alias("subject"), F.col("officer_notes").alias("interaction_text"),
    F.lit("agency_ref").alias("contact_type"),
    F.when(F.length("customer_ref") > 0, F.concat_ws(":", F.lit("snsw_customer"), "customer_ref")).alias("contact_value"),
    F.when(F.length("customer_ref") > 0, F.concat_ws(":", F.lit("snsw_customer"), "customer_ref")).alias("agency_ref_record_id"),
    "case_ref", "outcome", F.concat(F.lit("centre:"), "centre").alias("handled_by"), F.lit(None).cast("int").alias("duration_seconds"),
    F.lit(None).cast("string").alias("attachment_name"), "_delivery", "_source_file")

inter = calls.unionByName(web).unionByName(emails).unionByName(shop)
inter = (inter.withColumn("case_ref", F.when(F.length("case_ref") > 0, F.col("case_ref")))
         .withColumn("data_domain", F.try_element_at(agency_domain, F.col("agency_code")))
         .withColumn("channel_label", F.element_at(channel_label, F.col("channel")))
         .withColumn("text_hash", F.sha2(F.coalesce("interaction_text", F.lit("")), 256))
         .withColumn("dq_reject", F.concat_ws("; ",
                     F.when(F.col("event_ts").isNull(), F.lit("unparseable timestamp")),
                     F.when(F.col("interaction_text").isNull() | (F.length("interaction_text") == 0), F.lit("empty text")),
                     F.when(F.col("data_domain").isNull(), F.lit("unknown agency")))))
quarantine.append(inter.filter("length(dq_reject) > 0").select(F.lit("silver_interactions").alias("target_table"),
                                                               F.col("interaction_id").alias("record_key"), F.col("dq_reject").alias("reason"),
                                                               "_source_file", "_delivery"))
n_int = write_table(inter.filter("length(dq_reject) = 0").select(*INT_OUT[:3], "channel_label", "agency_code", "data_domain",
                                                                 *INT_OUT[4:], "text_hash"),
                    "silver_interactions",
                    "Silver: every channel interaction (phone, web, email, shopfront) in one schema. Not yet resolved to a constituent.",
                    column_comments={"interaction_text": "Transcript, message body, form text or officer note. Personal information.",
                                     "contact_type": "How the channel identified the person: phone | email | agency_ref.",
                                     "contact_value": "Normalised contact value used to link to silver_contact_points.",
                                     "agency_ref_record_id": "Source identity record quoted in the interaction (account / customer / client reference), if any.",
                                     "case_ref": "Case quoted in the interaction, if any.",
                                     "text_hash": "SHA-256 of the text; AI signals are recomputed only when it changes."},
                    layer="silver")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cases and consent

# COMMAND ----------

cases = latest(bronze("service_cases"), "case_id").select(
    "case_id", "agency_code", F.element_at(agency_domain, F.col("agency_code")).alias("data_domain"), "service_type", "case_status",
    F.concat_ws(":", "client_ref_system", "client_ref").alias("client_record_id"),
    parse_ts("opened_at").alias("opened_at"), parse_ts("due_at").alias("due_at"), parse_ts("closed_at").alias("closed_at"),
    F.when(F.length("owner_principal") > 0, F.col("owner_principal")).alias("owner_principal"),
    parse_ts("last_updated_at").alias("last_updated_at"), "_delivery")
st = spark.createDataFrame(SERVICE_TYPES, "data_domain string, service_type string, service_line string").drop("data_domain")
write_table(cases.join(st, "service_type", "left"), "silver_cases",
            "Silver: latest snapshot of each agency case (service journey).",
            column_comments={"client_record_id": "Source identity record of the case client in the owning agency's system.",
                             "service_line": "Reporting service line (Housing, Licensing, Transport, Cost of living, Health)."},
            layer="silver")

consent = latest(bronze("consent_events"), "consent_event_id").select(
    "consent_event_id", F.col("captured_by_agency").alias("agency_code"), F.concat_ws(":", "client_ref_system", "client_ref").alias("client_record_id"),
    "purpose_code", "data_domain", "decision", parse_ts("captured_at").alias("captured_at"), parse_ts("expires_at").alias("expires_at"),
    "capture_channel", "notice_version", "_delivery")
write_table(consent, "silver_consent_events",
            "Silver: consent decisions captured by an agency against its own client reference, per purpose of use and data domain.",
            column_comments={"decision": "granted | declined | withdrawn",
                             "client_record_id": "Source identity record the consent was captured against; resolved to a constituent in 07."},
            layer="silver")

q = quarantine[0]
for x in quarantine[1:]:
    q = q.unionByName(x)
n_q = write_table(q.withColumn("run_id", F.lit(run_id)).withColumn("quarantined_at", F.current_timestamp()), "silver_quarantine",
                  "Rows rejected by silver data quality rules, with reasons.", layer="silver")

# COMMAND ----------

profile = spark.sql(f"""SELECT count(*) n, avg(IF(dob IS NULL AND source_system <> 'web_account', 1, 0)) dob_missing,
                              avg(IF(length(dq_warnings) > 0, 1, 0)) warn_rate FROM {fqn('silver_source_identities')}""").first()
linked = spark.sql(f"""SELECT avg(IF(contact_value IS NOT NULL OR agency_ref_record_id IS NOT NULL, 1, 0)) FROM {fqn('silver_interactions')}""").first()[0]
failed = record_checks("03_standardise_silver", run_id, [
    ("identities_not_empty", n_ids > 0, "critical", n_ids, "> 0"),
    ("interactions_not_empty", n_int > 0, "critical", n_int, "> 0"),
    ("quarantine_rate", n_q <= 0.02 * (n_ids + n_int), "warning", n_q, f"<= 2% of {n_ids + n_int}"),
    ("dob_missing_rate", (profile.dob_missing or 0) < 0.1, "warning", round(profile.dob_missing or 0, 4), "< 0.10"),
    ("interactions_with_identifier", (linked or 0) > 0.9, "warning", round(linked or 0, 4), "> 0.90"),
])
assert not failed, f"critical checks failed: {failed}"
