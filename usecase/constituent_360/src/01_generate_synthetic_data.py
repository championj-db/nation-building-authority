# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Generate synthetic source extracts
# MAGIC
# MAGIC Builds a **wholly synthetic** population and lands, in the landing volume, the raw extracts that each
# MAGIC agency's systems would deliver. Nothing here is real constituent, contact or correspondence data.
# MAGIC
# MAGIC | Extract (landing folder) | Simulated source system | Format | Carries |
# MAGIC | --- | --- | --- | --- |
# MAGIC | `snsw_customers` | Service NSW verified customer register | CSV | identity |
# MAGIC | `web_accounts` | Service NSW web account | JSON | identity (self-asserted, no DOB) |
# MAGIC | `housing_crm_clients` | Housing CRM | CSV | identity (stale addresses, re-registrations) |
# MAGIC | `transport_licence_holders` | Transport licensing | CSV | identity (legal names, upper case) |
# MAGIC | `revenue_concession_applicants` | Cost of living concessions | JSON | identity |
# MAGIC | `community_health_clients` | Community health | CSV | identity (sensitive domain) |
# MAGIC | `contact_centre_calls` | Telephony / contact centre | JSON | transcripts, caller number, optional account ref |
# MAGIC | `web_form_submissions` | Web forms | JSON | free text, web account id |
# MAGIC | `email_messages` | Agency mailboxes | JSON | inbound and outbound mail |
# MAGIC | `shopfront_visits` | Service centre queueing | CSV | officer notes, customer ref |
# MAGIC | `service_cases` | Agency case systems | CSV | case snapshot (journeys) |
# MAGIC | `consent_events` | Consent capture | JSON | consent decisions by purpose and domain |
# MAGIC
# MAGIC **No common identifier** links the extracts. The identity noise follows real failure modes: nicknames,
# MAGIC transliteration and typing errors, surname change, stale addresses after a move, day/month swaps, missing
# MAGIC fields, shared household phones and addresses, and within-source duplicate registrations.
# MAGIC
# MAGIC `dbldatagen` generates the population, households and the interaction skeleton at scale; person-dependent
# MAGIC attributes use seeded hashing so the same seed always rebuilds the same world. Three personas carry the
# MAGIC stories visible in the design (Amara Okafor - housing, urgent; Leo Nguyen - licensing, repeat contact;
# MAGIC Priya Sharma - cost of living, new document).
# MAGIC
# MAGIC Ground truth (`synthetic_truth_*`) is kept only to measure entity resolution and AI accuracy.
# MAGIC
# MAGIC **Modes.** `bootstrap` creates the world and lands every extract with `history_days` of interactions.
# MAGIC `incremental` reuses the stored world and lands the interactions, case updates and consent changes that
# MAGIC happened since the last delivery.

# COMMAND ----------

# MAGIC %pip install -q dbldatagen==0.4.0.post1

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.dropdown("mode", "bootstrap", ["bootstrap", "incremental"])
dbutils.widgets.text("seed", "42")
dbutils.widgets.text("population_size", "3000")
dbutils.widgets.text("history_days", "180")
dbutils.widgets.text("interactions_per_person", "4")
dbutils.widgets.text("as_of_ts", "")
dbutils.widgets.text("timezone_id", "Australia/Sydney")
dbutils.widgets.text("demo_officer_principal", "")
dbutils.widgets.dropdown("dry_run", "false", ["true", "false"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
mode = dbutils.widgets.get("mode")
TZ = dbutils.widgets.get("timezone_id")
DEMO_OFFICER = dbutils.widgets.get("demo_officer_principal") or None
DRY_RUN = dbutils.widgets.get("dry_run").lower() == "true"
IPP = float(dbutils.widgets.get("interactions_per_person"))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import dbldatagen as dg

now = datetime.now(timezone.utc).replace(microsecond=0)
AS_OF = datetime.fromisoformat(dbutils.widgets.get("as_of_ts")) if dbutils.widgets.get("as_of_ts") else now
if AS_OF.tzinfo is None:
    AS_OF = AS_OF.replace(tzinfo=timezone.utc)

if mode == "bootstrap":
    SEED = int(dbutils.widgets.get("seed"))
    N = int(dbutils.widgets.get("population_size"))
    HISTORY_DAYS = int(dbutils.widgets.get("history_days"))
    WINDOW_START = AS_OF - timedelta(days=HISTORY_DAYS)
else:
    assert get_control("last_landed_ts"), "No synthetic world recorded - run the bootstrap job first"
    SEED = int(get_control("seed"))
    N = int(get_control("population_size"))
    HISTORY_DAYS = int(get_control("history_days"))
    WINDOW_START = datetime.fromisoformat(get_control("last_landed_ts"))
    DEMO_OFFICER = DEMO_OFFICER or get_control("demo_officer_principal")
    if AS_OF <= WINDOW_START:
        dbutils.notebook.exit("nothing to land: as_of is not after the last delivery")

WINDOW_DAYS = (AS_OF - WINDOW_START).total_seconds() / 86400.0
WINDOW_SECONDS = int((AS_OF - WINDOW_START).total_seconds())
DELIVERY = AS_OF.strftime("%Y-%m-%dT%H%M%S")
AS_OF_SQL = f"timestamp'{AS_OF:%Y-%m-%d %H:%M:%S}'"
WINDOW_START_SQL = f"timestamp'{WINDOW_START:%Y-%m-%d %H:%M:%S}'"
AS_OF_DATE_SQL = f"DATE'{AS_OF:%Y-%m-%d}'"
PARTS = max(4, min(96, N // 1500 + 4))
print(f"mode={mode} seed={SEED} population={N} window={WINDOW_START} -> {AS_OF} ({WINDOW_DAYS:.2f} days) dry_run={DRY_RUN}")


def U(salt: str, *cols: str) -> str:
    return u_sql(SEED, salt, *cols)


def sql_arr_nullable(values) -> str:
    return "array(" + ", ".join("CAST(NULL AS STRING)" if v is None else sql_str(v) for v in values) + ")"


def sql_map_arr(d: dict) -> str:
    return "map(" + ", ".join(f"{sql_str(k)}, {sql_array(v)}" for k, v in d.items()) + ")"


def sql_map_num(d: dict) -> str:
    return "map(" + ", ".join(f"{sql_str(k)}, CAST({float(v)} AS DOUBLE)" for k, v in d.items()) + ")"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Banks: names, places, phrases

# COMMAND ----------

GIVEN_F = ["Olivia", "Charlotte", "Mia", "Isla", "Ava", "Grace", "Chloe", "Emily", "Sophie", "Priya", "Aisha", "Fatima",
           "Mei", "Lan", "Linh", "Hannah", "Zoe", "Ruby", "Elizabeth", "Katherine", "Jennifer", "Margaret", "Rebecca",
           "Jessica", "Patricia", "Samantha", "Sarah", "Maria", "Ana", "Leila", "Yasmin", "Chiara", "Niamh", "Siobhan",
           "Aroha", "Kiri", "Jasmine", "Nadia", "Alexandra", "Amara", "Ngozi", "Thi", "Hoa", "Sakura", "Ji-woo"]
GIVEN_M = ["Leo", "Oliver", "Noah", "Jack", "William", "Thomas", "James", "Lucas", "Henry", "Ethan", "Mohammed",
           "Ahmed", "Omar", "Ali", "Raj", "Arjun", "Vikram", "Minh", "Duc", "Wei", "Jun", "Hiroshi", "Robert", "Michael",
           "Christopher", "Daniel", "Joseph", "Matthew", "Nicholas", "Anthony", "Alexander", "Benjamin", "Samuel",
           "Liam", "Connor", "Sean", "Tane", "Mateo", "Giorgos", "Kwame", "Jonathan", "Chinedu", "Quang", "Hamid"]
FAMILY = ["Smith", "Jones", "Williams", "Brown", "Wilson", "Taylor", "Nguyen", "Tran", "Le", "Pham", "Lee", "Martin",
          "Anderson", "Thompson", "White", "Walker", "Ali", "Hassan", "Khan", "Chen", "Li", "Wang", "Zhang", "Kim",
          "Park", "Singh", "Kaur", "Patel", "Sharma", "Okafor", "Adeyemi", "Mensah", "Kowalski", "Papadopoulos",
          "Rossi", "Murphy", "O'Brien", "McDonald", "MacKenzie", "Kelly", "Ryan", "Campbell", "Stewart", "Robinson",
          "Clarke", "Wright", "Mitchell", "Hughes", "Edwards", "Nikolaidis", "Haddad", "Abboud", "Fernandes", "Silva",
          "Garcia", "Lopez", "Ito", "Sato", "Ngata", "Tuilagi", "Mohammed", "Huang", "Wu", "Do", "Vu", "Hoang"]
SURNAME_VARIANTS = {"Nguyen": "Ngyuen", "O'Brien": "OBrien", "McDonald": "MacDonald", "Papadopoulos": "Papadopolous",
                    "Kowalski": "Kovalski", "Zhang": "Chang", "Abboud": "Aboud", "Haddad": "Hadad", "MacKenzie": "McKenzie",
                    "Fernandes": "Fernandez", "Mohammed": "Muhammad", "Huang": "Wong", "Hoang": "Huang", "Nikolaidis": "Nicolaidis",
                    "Tuilagi": "Tuilangi", "Thompson": "Thomson", "Clarke": "Clark", "Pham": "Phan"}
SUBURBS = [("Parramatta", "2150"), ("Granville", "2142"), ("Penrith", "2750"), ("Blacktown", "2148"), ("Liverpool", "2170"),
           ("Campbelltown", "2560"), ("Bankstown", "2200"), ("Fairfield", "2165"), ("Auburn", "2144"), ("Hurstville", "2220"),
           ("Chatswood", "2067"), ("Hornsby", "2077"), ("Ryde", "2112"), ("Strathfield", "2135"), ("Newtown", "2042"),
           ("Marrickville", "2204"), ("Mount Druitt", "2770"), ("Wollongong", "2500"), ("Newcastle", "2300"),
           ("Maitland", "2320"), ("Gosford", "2250"), ("Wyong", "2259"), ("Dubbo", "2830"), ("Orange", "2800"),
           ("Bathurst", "2795"), ("Wagga Wagga", "2650"), ("Albury", "2640"), ("Tamworth", "2340"), ("Lismore", "2480"),
           ("Coffs Harbour", "2450"), ("Port Macquarie", "2444"), ("Queanbeyan", "2620"), ("Goulburn", "2580")]
STREETS = ["Smith", "King", "George", "Church", "Victoria", "Albert", "Railway", "Station", "High", "Park", "Macquarie",
           "Hunter", "Elizabeth", "Bridge", "Pitt", "Oxford", "Marion", "Rose", "Wattle", "Banksia", "Waratah", "Bay",
           "Lake", "Hill", "Mountain", "River", "Ocean", "Jacaranda", "Kurrajong", "Bligh"]
EMAIL_DOMAINS = ["gmail.com", "outlook.com", "bigpond.com", "icloud.com", "yahoo.com.au", "hotmail.com", "optusnet.com.au"]
CENTRES = ["Parramatta", "Penrith", "Blacktown", "Liverpool", "Wollongong", "Newcastle", "Dubbo", "Chatswood"]
WHEN_PHRASES = ["Friday", "next Tuesday", "the end of the month", "the 14th", "next week"]

SUB_NAMES = sql_array([s[0] for s in SUBURBS])
SUB_PCS = sql_array([s[1] for s in SUBURBS])
TYPE_FULL = sql_array([t[0] for t in STREET_TYPES])
TYPE_ABBR = sql_array([t[1] for t in STREET_TYPES])
NICK_MAP = sql_map(NICKNAMES)
SURNAME_MAP = sql_map(SURNAME_VARIANTS)
AGENCY_NAME_MAP = sql_map({a[0]: a[1] for a in AGENCIES})
DOMAIN_AGENCY_MAP = sql_map({v: k for k, v in AGENCY_DOMAIN.items()})
INTENT_LABEL_MAP = sql_map(dict(INTENTS))

DOMAIN_SVC = {
    "housing": ["Housing Support application", "emergency accommodation request", "rent relief application", "priority housing assessment"],
    "transport_licensing": ["licence renewal", "licence class upgrade", "toll relief application", "concession travel card"],
    "cost_of_living": ["energy rebate", "cost of living concession", "family energy rebate", "seniors savings application"],
    "health": ["community care plan", "home care assessment", "allied health referral", "care coordination appointment"],
    "customer_service": ["MyService account", "address update", "digital licence", "service centre appointment"],
}
DOMAIN_DOC = {
    "housing": ["proof of income", "rental ledger", "lease agreement", "Centrelink income statement", "notice to vacate"],
    "transport_licensing": ["medical assessment form", "proof of identity", "eyesight test result", "concession card"],
    "cost_of_living": ["electricity bill", "concession card", "bank statement", "Centrelink income statement"],
    "health": ["GP referral", "care plan", "medication list", "Medicare card copy"],
    "customer_service": ["proof of address", "photo ID", "utility bill", "change of name certificate"],
}
DOMAIN_INTENTS = {  # weighted by repetition
    "housing": ["status_enquiry"] * 4 + ["document_submission"] * 3 + ["evidence_question"] * 2 + ["payment_or_debt"] * 2
               + ["new_application", "complaint", "change_of_details"],
    "transport_licensing": ["status_enquiry"] * 3 + ["document_submission"] * 2 + ["new_application"] * 2
                           + ["appointment_booking"] * 2 + ["change_of_details"] * 2 + ["payment_or_debt", "complaint"],
    "cost_of_living": ["status_enquiry"] * 3 + ["new_application"] * 3 + ["document_submission"] * 2
                      + ["evidence_question"] * 2 + ["payment_or_debt", "complaint"],
    "health": ["appointment_booking"] * 4 + ["status_enquiry"] * 2 + ["general_information"] * 2 + ["change_of_details", "complaint"],
    "customer_service": ["general_information"] * 4 + ["change_of_details"] * 3 + ["status_enquiry"] * 2
                        + ["appointment_booking", "complaint"],
}
INTENT_TPL = {
    "status_enquiry": ["I'm checking on my {svc}. I applied a few weeks ago and haven't heard anything.",
                       "Can you tell me where my {svc} is up to?",
                       "I wanted to know if my {svc} has been approved yet."],
    "document_submission": ["I've uploaded my {doc} for the {svc}.",
                            "Attached is the {doc} you asked for in relation to my {svc}.",
                            "I'm handing in my {doc} for the {svc}."],
    "new_application": ["I'd like to apply for the {svc}.",
                        "How do I start a new {svc}? I think I'm eligible.",
                        "I want to lodge a {svc} today."],
    "evidence_question": ["Which documents do you still need for my {svc}? Is a {doc} enough?",
                          "I'm not sure whether my {doc} counts as evidence for the {svc}.",
                          "Do I need to provide a {doc} again for the {svc}?"],
    "payment_or_debt": ["I've received a notice about money owed on my {svc} and I can't pay it all at once.",
                        "Can I set up a payment plan? I've fallen behind with the {svc}.",
                        "My payment for the {svc} hasn't come through."],
    "complaint": ["I want to make a complaint about how my {svc} has been handled.",
                  "Nobody has returned my calls about the {svc}. This isn't good enough.",
                  "I was given the wrong information about my {svc}."],
    "change_of_details": ["I need to update my address and phone number for my {svc}.",
                          "I've moved and need my details changed on the {svc}.",
                          "Please update my contact email for the {svc}."],
    "appointment_booking": ["I need to book an appointment for my {svc}.",
                            "Can I reschedule my {svc} appointment to next week?",
                            "I'd like an appointment about the {svc}, mornings if possible."],
    "general_information": ["What's the process for a {svc}?",
                            "I couldn't log in to my account to check the {svc}.",
                            "Where can I find information about the {svc}?"],
}
NEED_TPL = {
    "housing_stability": ["I have to leave my rental by {when} and I don't have anywhere lined up.",
                          "The rent has gone up again and we're staying with family, which can't last.",
                          "We've been given a notice to vacate and I have two kids."],
    "financial_pressure": ["Money is very tight since my hours were cut.",
                           "I'm struggling to keep up with the bills this month.",
                           "I'm behind on rent and the energy bill."],
    "mobility_access": ["I need my licence to get to work.",
                        "Without the concession I can't afford to travel to my appointments.",
                        "I rely on driving to care for my mother."],
    "health_wellbeing": ["I've been unwell and couldn't get to the appointment.",
                         "My carer usually helps me with these forms.",
                         "My health has made it hard to keep on top of this."],
    "document_burden": ["I've already sent this document twice.",
                        "I keep being asked for the same paperwork.",
                        "I don't understand which forms are still missing."],
    "digital_access": ["The upload kept failing on my phone.",
                       "I couldn't log in to the website.",
                       "I don't have a computer at home so the online form is hard."],
}
SENT_TPL = {"negative": ["I'm really worried about this.", "Honestly I'm frustrated - nobody has got back to me.",
                         "This is very stressful and I need an answer soon."],
            "neutral": ["", "Just checking where things are at.", "Thanks."],
            "positive": ["Thanks so much for the help last time.", "The guidance you sent was really clear.",
                         "I appreciate how quickly this was sorted."]}
REPEAT_TPL = ["This is the third time I've contacted you about this.", "I called last week about the same thing.",
              "I'm following up again because I haven't heard back."]
AGENT_TPL = {"resolved": ["Agent confirmed the details and resolved the enquiry.",
                          "Agent explained the next steps and the caller was satisfied."],
             "follow_up": ["Agent logged a follow-up for the case officer.", "Agent advised a callback within two business days."],
             "referred": ["Agent referred the caller to the owning agency.", "Agent transferred the caller to the case team."],
             "received": ["Document received and attached to the case.", "Document checked and accepted."],
             "sent": [""]}
OUTBOUND_TPL = ["Eligibility checklist for your {svc} sent with plain-language guidance.",
                "Callback made to confirm the {svc} status; outcome explained.",
                "Reminder sent: the {doc} for your {svc} is due by {when}.",
                "Your {svc} has moved to assessment. No further action is needed right now."]
INTENT_SENT_BASE = {"complaint": -0.8, "payment_or_debt": -0.45, "status_enquiry": -0.2, "evidence_question": -0.1,
                    "document_submission": 0.05, "new_application": 0.0, "change_of_details": 0.15,
                    "appointment_booking": 0.1, "general_information": 0.2}
DOMAIN_STRESS = {"housing": -0.25, "health": -0.1, "cost_of_living": -0.15, "transport_licensing": 0.0, "customer_service": 0.05}
RESOLVE_P = {"general_information": 0.85, "change_of_details": 0.9, "appointment_booking": 0.85, "document_submission": 0.8,
             "status_enquiry": 0.45, "evidence_question": 0.6, "new_application": 0.7, "payment_or_debt": 0.4, "complaint": 0.25}
DOMAIN_NEED = {"housing": "housing_stability", "cost_of_living": "financial_pressure",
               "transport_licensing": "mobility_access", "health": "health_wellbeing"}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Population and households (dbldatagen)

# COMMAND ----------

PERSON_COLS = [
    "person_id", "gender", "given_name", "family_name", "prior_family_name", "dob", "age", "mobile", "landline",
    "email", "alt_email", "has_email", "household_id", "unit_no", "street_no", "street_name", "type_ix", "suburb",
    "postcode", "moved", "p_unit_no", "p_street_no", "p_street_name", "p_type_ix", "p_suburb", "p_postcode",
    "pref_channel", "pref_time", "in_snsw", "in_web", "in_housing", "in_transport", "in_revenue", "in_health",
    "dup_housing", "dup_web", "need_score", "persona_key",
]

PERSONAS = [
    dict(person_id="P-900001", persona_key="amara", gender="F", given_name="Amara", family_name="Okafor", dob=date(1988, 3, 2),
         mobile="0412 555 018", landline="02 9635 2210", email="amara.okafor@outlook.com", alt_email="amarao88@gmail.com",
         household_id="H-900001", unit_no=4, street_no=12, street_name="Smith", type_ix=0, suburb="Parramatta",
         postcode="2150", moved=True, p_unit_no=None, p_street_no=37, p_street_name="Railway", p_type_ix=4,
         p_suburb="Granville", p_postcode="2142", pref_channel="phone", pref_time="mornings", in_snsw=True, in_web=True,
         in_housing=True, in_transport=False, in_revenue=False, in_health=True, dup_housing=True, dup_web=False),
    dict(person_id="P-900002", persona_key="leo", gender="M", given_name="Leo", family_name="Nguyen", dob=date(1991, 7, 14),
         mobile="0433 555 207", landline=None, email="leo.nguyen91@gmail.com", alt_email="leon91@outlook.com",
         household_id="H-900002", unit_no=None, street_no=8, street_name="Rose", type_ix=2, suburb="Penrith", postcode="2750",
         moved=False, pref_channel="phone", pref_time="afternoons", in_snsw=True, in_web=True, in_housing=False,
         in_transport=True, in_revenue=False, in_health=False, dup_housing=False, dup_web=False),
    dict(person_id="P-900003", persona_key="priya", gender="F", given_name="Priya", family_name="Sharma", dob=date(1979, 11, 23),
         mobile="0450 555 391", landline="02 9671 4402", email="priya.sharma@bigpond.com", alt_email="psharma79@gmail.com",
         household_id="H-900003", unit_no=2, street_no=41, street_name="King", type_ix=0, suburb="Blacktown", postcode="2148",
         moved=False, pref_channel="email", pref_time="mornings", in_snsw=True, in_web=False, in_housing=False,
         in_transport=True, in_revenue=True, in_health=False, dup_housing=False, dup_web=False),
]


def build_population() -> DataFrame:
    hh_n = max(1, int(N / 2.1))
    households = (
        dg.DataGenerator(spark, name="households", rows=hh_n, partitions=PARTS, randomSeedMethod="hash_fieldname", randomSeed=SEED)
        .withIdOutput()
        .withColumn("hh_family", "string", values=FAMILY, random=True)
        .withColumn("suburb_ix", "int", minValue=0, maxValue=len(SUBURBS) - 1, random=True)
        .withColumn("street_no", "int", minValue=1, maxValue=240, random=True)
        .withColumn("street_ix", "int", minValue=0, maxValue=len(STREETS) - 1, random=True)
        .withColumn("type_ix", "int", minValue=0, maxValue=len(STREET_TYPES) - 1, random=True)
        .withColumn("unit_no", "int", minValue=1, maxValue=48, random=True, percentNulls=0.72)
        .build()
        # Phone numbers are derived from a seeded hash of the row id rather than a dbldatagen text template:
        # templates re-seed per partition with a fixed seed, which repeats numbers across partitions and makes
        # one number look shared by several unrelated households.
        .withColumn("_ll", F.expr(f"lpad(CAST(pmod(xxhash64({SEED}, 'landline', id), 10000000) AS STRING), 7, '0')"))
        .withColumn("landline", F.expr(f"IF({U('llnull', 'id')} < 0.6, NULL, "
                                       f"concat('02 9', substr(_ll, 1, 3), ' ', substr(_ll, 4, 4)))"))
        .drop("_ll")
        .withColumnRenamed("id", "hh_ix")
    )
    people = (
        dg.DataGenerator(spark, name="persons", rows=N, partitions=PARTS, randomSeedMethod="hash_fieldname", randomSeed=SEED + 1)
        .withIdOutput()
        .withColumn("gender", "string", values=["F", "M", "X"], weights=[50, 49, 1], random=True)
        .withColumn("given_f", "string", values=GIVEN_F, random=True)
        .withColumn("given_m", "string", values=GIVEN_M, random=True)
        .withColumn("own_family", "string", values=FAMILY, random=True)
        .withColumn("hh_ix", "long", minValue=0, maxValue=hh_n - 1, random=True)
        .withColumn("dob", "date", data_range=dg.DateRange("1936-01-01 00:00:00", "2007-12-31 00:00:00", "days=1"), random=True)
        .withColumn("email_domain", "string", values=EMAIL_DOMAINS, weights=[34, 22, 12, 12, 8, 7, 5], random=True)
        .withColumn("alt_domain", "string", values=EMAIL_DOMAINS, random=True)
        .withColumn("pref_channel", "string", values=["phone", "web", "email", "shopfront"], weights=[35, 35, 18, 12], random=True)
        .withColumn("pref_time", "string", values=["mornings", "afternoons", "evenings"], weights=[45, 35, 20], random=True)
        .withColumn("p_suburb_ix", "int", minValue=0, maxValue=len(SUBURBS) - 1, random=True)
        .withColumn("p_street_no", "int", minValue=1, maxValue=240, random=True)
        .withColumn("p_street_ix", "int", minValue=0, maxValue=len(STREETS) - 1, random=True)
        .withColumn("p_type_ix", "int", minValue=0, maxValue=len(STREET_TYPES) - 1, random=True)
        .withColumn("p_unit_no", "int", minValue=1, maxValue=48, random=True, percentNulls=0.7)
        .build()
        .withColumn("_mb", F.expr(f"lpad(CAST(pmod(xxhash64({SEED}, 'mobile', id), 100000000) AS STRING), 8, '0')"))
        .withColumn("mobile", F.expr("concat('04', substr(_mb, 1, 2), ' ', substr(_mb, 3, 3), ' ', substr(_mb, 6, 3))"))
        .drop("_mb")
    )
    p = (people.join(households.select("hh_ix", "hh_family", "suburb_ix", "street_no", "street_ix", "type_ix", "unit_no", "landline"), "hh_ix")
         .selectExpr(
             "id", "concat('P-', lpad(cast(id + 1 AS STRING), 6, '0')) AS person_id", "gender",
             "CASE WHEN gender = 'M' OR (gender = 'X' AND id % 2 = 0) THEN given_m ELSE given_f END AS given_name",
             f"CASE WHEN {U('fam', 'id')} < 0.85 THEN hh_family ELSE own_family END AS family_name",
             "own_family", "hh_family", "dob", f"floor(datediff({AS_OF_DATE_SQL}, dob) / 365.25) AS age", "mobile", "landline",
             "email_domain", "alt_domain", "pref_channel", "pref_time",
             "concat('H-', lpad(cast(hh_ix + 1 AS STRING), 6, '0')) AS household_id",
             "unit_no", "street_no", f"element_at({sql_array(STREETS)}, street_ix + 1) AS street_name", "type_ix",
             f"element_at({SUB_NAMES}, suburb_ix + 1) AS suburb", f"element_at({SUB_PCS}, suburb_ix + 1) AS postcode",
             f"{U('moved', 'id')} < 0.22 AS moved", "p_unit_no", "p_street_no",
             f"element_at({sql_array(STREETS)}, p_street_ix + 1) AS p_street_name", "p_type_ix",
             f"element_at({SUB_NAMES}, p_suburb_ix + 1) AS p_suburb", f"element_at({SUB_PCS}, p_suburb_ix + 1) AS p_postcode",
             f"cast(pmod(xxhash64({SEED}, 'emn', id), 90) + 10 AS STRING) AS nn",
         )
         .selectExpr(
             "*",
             f"CASE WHEN gender = 'F' AND family_name = hh_family AND own_family <> hh_family AND {U('maiden', 'id')} < 0.08 "
             f"THEN own_family END AS prior_family_name",
             "regexp_replace(lower(given_name), '[^a-z]', '') AS gl", "regexp_replace(lower(family_name), '[^a-z]', '') AS fl",
             f"{U('email_style', 'id')} AS es",
             f"{U('need_h', 'id')} < CASE WHEN age < 35 THEN 0.2 ELSE 0.13 END AS in_housing",
         )
         .selectExpr(
             "*",
             "concat(CASE WHEN es < 0.35 THEN concat(gl, '.', fl) WHEN es < 0.6 THEN concat(gl, fl, nn) "
             "WHEN es < 0.8 THEN concat(substr(gl, 1, 1), fl, nn) ELSE concat(fl, '.', gl, nn) END, '@', email_domain) AS email",
             "concat(gl, cast(pmod(xxhash64(id, 'alt'), 900) + 100 AS STRING), '@', alt_domain) AS alt_email",
             f"{U('rev', 'id')} < CASE WHEN in_housing THEN 0.6 WHEN age >= 65 THEN 0.45 ELSE 0.25 END AS in_revenue",
             f"age >= 17 AND {U('trn', 'id')} < 0.74 AS in_transport",
             f"{U('hlt', 'id')} < CASE WHEN age >= 65 THEN 0.3 ELSE 0.1 END AS in_health",
             f"{U('web', 'id')} < CASE WHEN age >= 75 THEN 0.25 ELSE 0.66 END AS in_web",
         )
         .selectExpr(
             "*",
             f"(in_web AND {U('snsw_w', 'id')} < 0.92) OR {U('snsw', 'id')} < 0.78 AS in_snsw",
             f"in_web OR {U('hasem', 'id')} < 0.8 AS has_email",
             f"in_housing AND {U('duph', 'id')} < 0.06 AS dup_housing",
             f"in_web AND {U('dupw', 'id')} < 0.05 AS dup_web",
             "3 * cast(in_housing AS INT) + 1.5 * cast(in_revenue AS INT) + 1.5 * cast(in_health AS INT) "
             f"+ 0.5 * cast(in_transport AS INT) + 1.5 * {U('act', 'id')} AS need_score",
             "CAST(NULL AS STRING) AS persona_key",
         )
         .withColumn("pref_channel", F.expr("CASE WHEN pref_channel = 'web' AND NOT in_web THEN 'phone' "
                                            "WHEN pref_channel = 'email' AND NOT has_email THEN 'phone' ELSE pref_channel END"))
         .withColumn("p_unit_no", F.expr("IF(moved, p_unit_no, NULL)"))
         .withColumn("need_score", F.col("need_score").cast("double"))
         .withColumn("age", F.col("age").cast("int"))
         .select(*PERSON_COLS))
    schema_ = T.StructType([T.StructField(f.name, f.dataType, True) for f in p.schema.fields])
    rows = []
    for d in PERSONAS:
        d = {**d, "prior_family_name": None, "has_email": True, "need_score": -1.0,
             "age": int((AS_OF.date() - d["dob"]).days // 365.25)}
        for k in ("p_unit_no", "p_street_no", "p_street_name", "p_type_ix", "p_suburb", "p_postcode"):
            d.setdefault(k, None)
        rows.append(tuple(d.get(f.name) for f in schema_.fields))
    return p.unionByName(spark.createDataFrame(rows, schema_))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Identity extracts: one per agency system, each with its own noise profile

# COMMAND ----------

# p = probability that a given defect appears in a record from that system
NOISE = {
    "snsw_customer": dict(nick=0.02, typo=0.01, variant=0.0, maiden=0.0, stale=0.05, dob_missing=0.0, dob_swap=0.0, email=0.85, alt=0.03, landline=0.0, phone_null=0.02),
    "transport_licence": dict(nick=0.0, typo=0.02, variant=0.04, maiden=0.35, stale=0.25, dob_missing=0.0, dob_swap=0.01, email=0.25, alt=0.1, landline=0.1, phone_null=0.1),
    "revenue_concession": dict(nick=0.1, typo=0.04, variant=0.05, maiden=0.2, stale=0.35, dob_missing=0.1, dob_swap=0.02, email=0.9, alt=0.1, landline=0.2, phone_null=0.1),
    "housing_crm": dict(nick=0.15, typo=0.06, variant=0.1, maiden=0.3, stale=0.45, dob_missing=0.04, dob_swap=0.03, email=0.55, alt=0.15, landline=0.35, phone_null=0.05),
    "community_health": dict(nick=0.05, typo=0.04, variant=0.06, maiden=0.4, stale=0.5, dob_missing=0.02, dob_swap=0.02, email=0.3, alt=0.1, landline=0.4, phone_null=0.05),
    "web_account": dict(nick=0.35, typo=0.05, variant=0.05, maiden=0.1, stale=0.3, dob_missing=1.0, dob_swap=0.0, email=1.0, alt=0.08, landline=0.0, phone_null=0.4),
}
DUP_NOISE = dict(stale=1.0, typo=0.3, nick=0.3, email=0.35, alt=0.9)


def typo_sql(x: str) -> str:
    k = f"cast(floor(u_pos * greatest(length({x}) - 2, 1)) + 2 AS INT)"
    return (f"CASE WHEN length({x}) <= 3 THEN {x} "
            f"WHEN u_kind < 0.4 THEN concat(substr({x}, 1, {k} - 1), substr({x}, {k} + 1, 1), substr({x}, {k}, 1), substr({x}, {k} + 2)) "
            f"WHEN u_kind < 0.7 THEN concat(substr({x}, 1, {k} - 1), substr({x}, {k} + 1)) "
            f"ELSE concat(substr({x}, 1, {k}), substr({x}, {k})) END")


def render_identity(base: DataFrame, system: str, variant: str) -> DataFrame:
    c = NOISE[system] if variant == "main" else {**NOISE[system], **DUP_NOISE}
    k = f"{system}:{variant}"
    clean = "(CASE WHEN persona_key IS NOT NULL THEN 0.0 ELSE 1.0 END)"       # personas carry curated noise only
    stale_factor = clean if variant == "main" else "1.0"
    a = base.selectExpr(
        "*",
        f"coalesce(moved AND {U(k + ':prior', 'person_id')} < {c['stale']} * {stale_factor}, false) AS use_prior",
        f"CASE WHEN {U(k + ':nick', 'person_id')} < {c['nick']} * {clean} AND try_element_at({NICK_MAP}, given_name) IS NOT NULL "
        f"THEN try_element_at({NICK_MAP}, given_name) ELSE given_name END AS g0",
        f"CASE WHEN persona_key = 'leo' AND '{system}' = 'transport_licence' THEN 'Ngyuen' "
        f"WHEN prior_family_name IS NOT NULL AND {U(k + ':maiden', 'person_id')} < {c['maiden']} THEN prior_family_name "
        f"WHEN {U(k + ':svar', 'person_id')} < {c['variant']} * {clean} AND try_element_at({SURNAME_MAP}, family_name) IS NOT NULL "
        f"THEN try_element_at({SURNAME_MAP}, family_name) ELSE family_name END AS f0",
        f"{U(k + ':typo', 'person_id')} < {c['typo']} * {clean} AS do_typo",
        f"{U(k + ':typo_side', 'person_id')} < 0.5 AS typo_given",
        f"{U(k + ':typo_pos', 'person_id')} AS u_pos", f"{U(k + ':typo_kind', 'person_id')} AS u_kind",
        f"{U(k + ':fmt', 'person_id')} AS u_fmt", f"{U(k + ':fmt2', 'person_id')} AS u_fmt2",
        f"'{system}' AS source_system", f"'{variant}' AS variant",
    )
    return a.selectExpr(
        "*",
        f"CASE WHEN do_typo AND typo_given THEN {typo_sql('g0')} ELSE g0 END AS given_r",
        f"CASE WHEN do_typo AND NOT typo_given THEN {typo_sql('f0')} ELSE f0 END AS family_r",
        f"CASE WHEN {U(k + ':dobmiss', 'person_id')} < {c['dob_missing']} * IF('{system}' = 'web_account', 1.0, {clean}) THEN NULL "
        f"WHEN {U(k + ':dobswap', 'person_id')} < {c['dob_swap']} * {clean} AND day(dob) <= 12 AND day(dob) <> month(dob) "
        f"THEN make_date(year(dob), day(dob), month(dob)) ELSE dob END AS dob_r",
        f"CASE WHEN persona_key IS NOT NULL AND variant = 'dup' THEN NULL WHEN NOT has_email THEN NULL "
        f"WHEN {U(k + ':em', 'person_id')} >= {c['email']} THEN NULL "
        f"WHEN {U(k + ':alt', 'person_id')} < {c['alt']} * {clean} THEN alt_email ELSE email END AS email_r",
        f"CASE WHEN persona_key IS NOT NULL AND variant = 'dup' THEN landline "
        f"WHEN {U(k + ':phnull', 'person_id')} < {c['phone_null']} * {clean} THEN NULL "
        f"WHEN landline IS NOT NULL AND {U(k + ':ll', 'person_id')} < {c['landline']} THEN landline ELSE mobile END AS phone_r",
        "cast(IF(use_prior, p_unit_no, unit_no) AS STRING) AS unit_r", "cast(IF(use_prior, p_street_no, street_no) AS STRING) AS street_no_r",
        "IF(use_prior, p_street_name, street_name) AS street_name_r", "IF(use_prior, p_type_ix, type_ix) AS type_ix_r",
        "IF(use_prior, p_suburb, suburb) AS suburb_r", "IF(use_prior, p_postcode, postcode) AS postcode_r",
        f"{AS_OF_SQL} - make_interval(0, 0, 0, cast(floor({U(k + ':upd', 'person_id')} * {720 if variant == 'dup' else 240}) AS INT) "
        f"+ {400 if variant == 'dup' else 1}, 0, 0, 0) AS updated_at_r",
    )


def street_sql(style: str, abbr: str) -> str:
    t = f"IF({abbr}, element_at({TYPE_ABBR}, type_ix_r + 1), element_at({TYPE_FULL}, type_ix_r + 1))"
    core = f"concat(street_no_r, ' ', street_name_r, ' ', {t})"
    slash = f"concat(IF(unit_r IS NULL, '', concat(unit_r, '/')), {core})"
    word = f"concat(IF(unit_r IS NULL, '', concat('Unit ', unit_r, ', ')), {core})"
    suffix = f"concat({core}, IF(unit_r IS NULL, '', concat(' Unit ', unit_r)))"
    if style == "mixed":
        return f"CASE WHEN u_fmt < 0.34 THEN {slash} WHEN u_fmt < 0.67 THEN {word} ELSE {suffix} END"
    return {"slash": slash, "word": word, "suffix": suffix}[style]


def phone_sql(style: str) -> str:
    d = "regexp_replace(phone_r, '[^0-9]', '')"
    intl = f"concat('+61 ', substr({d}, 2, 3), ' ', substr({d}, 5, 3), ' ', substr({d}, 8, 3))"
    paren = f"concat('(', substr({d}, 1, 2), ') ', substr({d}, 3, 4), ' ', substr({d}, 7, 4))"
    return {"plain": "phone_r", "digits": d, "intl": intl,
            "mixed": f"CASE WHEN u_fmt2 < 0.4 THEN phone_r WHEN u_fmt2 < 0.7 THEN {d} WHEN u_fmt2 < 0.85 THEN {intl} ELSE {paren} END"}[style]


TS_FMT = "yyyy-MM-dd HH:mm:ss"


def with_native(df: DataFrame, prefix: str, width: int, start: int) -> DataFrame:
    w = Window.orderBy(F.xxhash64(F.lit(SEED), F.col("source_system"), F.col("variant"), F.col("person_id")))
    return df.withColumn("native_id", F.concat(F.lit(prefix), F.lpad((F.row_number().over(w) + start).cast("string"), width, "0")))


def project(system: str, r: DataFrame) -> DataFrame:
    upd = f"date_format(updated_at_r, '{TS_FMT}') AS updated_at"
    if system == "snsw_customer":
        return r.selectExpr("native_id AS customer_ref", "given_r AS first_name", "family_r AS last_name",
                            "date_format(dob_r, 'yyyy-MM-dd') AS date_of_birth", f"{phone_sql('plain')} AS mobile", "email_r AS email",
                            f"{street_sql('word', 'false')} AS street_address", "suburb_r AS suburb", "'NSW' AS state",
                            "postcode_r AS postcode", "'Y' AS identity_verified", upd)
    if system == "transport_licence":
        return r.selectExpr("native_id AS licence_no", "upper(family_r) AS surname", "upper(given_r) AS given_names",
                            "date_format(dob_r, 'dd/MM/yyyy') AS dob",
                            f"upper(concat({street_sql('slash', 'true')}, ', ', suburb_r, ' NSW ', postcode_r)) AS address",
                            f"{phone_sql('digits')} AS phone",
                            f"{pick_sql(['C', 'C', 'C', 'C', 'R', 'LR', 'MR', 'HR'], 'u_fmt2')} AS licence_class",
                            f"date_format(date_add({AS_OF_DATE_SQL}, cast(floor(u_fmt * 1800) AS INT) - 120), 'dd/MM/yyyy') AS licence_expiry", upd)
    if system == "revenue_concession":
        return r.selectExpr("native_id AS applicant_id", "concat(given_r, ' ', family_r) AS applicant_name",
                            "date_format(dob_r, 'yyyy-MM-dd') AS birth_date", "email_r AS email", f"{phone_sql('intl')} AS contact_phone",
                            f"{street_sql('slash', 'false')} AS address_line", "suburb_r AS locality", "'NSW' AS state",
                            "postcode_r AS postcode",
                            f"{pick_sql(['Energy rebate', 'Seniors energy rebate', 'Low income household rebate', 'Family energy rebate'], 'u_fmt2')} AS concession_type",
                            upd)
    if system == "housing_crm":
        return r.selectExpr("native_id AS client_no", "concat(upper(family_r), ', ', given_r) AS client_name",
                            "date_format(dob_r, 'dd/MM/yyyy') AS dob", f"{phone_sql('mixed')} AS phone",
                            f"concat({street_sql('mixed', 'u_fmt2 < 0.5')}, ', ', upper(suburb_r), ' NSW ', postcode_r) AS address",
                            "cast(floor(u_fmt2 * 5) + 1 AS STRING) AS household_size", upd)
    if system == "community_health":
        return r.selectExpr("native_id AS patient_ref", "family_r AS family_name", "given_r AS given_name",
                            "date_format(dob_r, 'yyyy-MM-dd') AS birth_date", f"{phone_sql('plain')} AS phone",
                            f"{street_sql('word', 'true')} AS address_line", "upper(suburb_r) AS suburb", "postcode_r AS postcode", upd)
    if system == "web_account":
        return r.selectExpr("native_id AS account_id",
                            "CASE WHEN u_fmt < 0.5 THEN concat(given_r, ' ', family_r) WHEN u_fmt < 0.8 "
                            "THEN concat(given_r, ' ', substr(family_r, 1, 1), '.') ELSE lower(concat(given_r, ' ', family_r)) END AS display_name",
                            "email_r AS email", f"{phone_sql('digits')} AS mobile", "postcode_r AS postcode",
                            f"date_format(updated_at_r - make_interval(0, 0, 0, cast(floor(u_fmt2 * 900) AS INT), 0, 0, 0), '{TS_FMT}') AS created_at",
                            f"date_format(updated_at_r, '{TS_FMT}') AS last_login_at")
    raise ValueError(system)


SYSTEM_SPEC = {
    # system: (membership flag, duplicate flag, native prefix, width, start)
    "snsw_customer": ("in_snsw", None, "SC", 7, 1040000),
    "transport_licence": ("in_transport", None, "", 8, 20450000),
    "revenue_concession": ("in_revenue", None, "RA-", 6, 310000),
    "housing_crm": ("in_housing", "dup_housing", "HC", 6, 540000),
    "community_health": ("in_health", None, "CH-", 7, 7700000),
    "web_account": ("in_web", "dup_web", "W", 9, 880000000),
}


def build_identity_extracts(persons: DataFrame):
    extracts, truth = {}, []
    for system, (flag, dup_flag, prefix, width, start) in SYSTEM_SPEC.items():
        r = render_identity(persons.filter(flag), system, "main")
        if dup_flag:
            r = r.unionByName(render_identity(persons.filter(dup_flag), system, "dup"))
        r = with_native(r, prefix, width, start)
        extracts[SOURCE_BY_SYSTEM[system][6]] = project(system, r)
        truth.append(r.selectExpr("person_id", "source_system", "native_id", "concat(source_system, ':', native_id) AS source_record_id",
                                  "variant", "use_prior AS has_stale_address", "do_typo AS has_typo",
                                  "(f0 <> family_name) AS has_name_variant"))
    truth_df = truth[0]
    for t in truth[1:]:
        truth_df = truth_df.unionByName(t)
    return extracts, truth_df


def refs_pivot(truth_sources: DataFrame) -> DataFrame:
    """person -> native id of the main record in each system (used by channels, cases and consent)."""
    m = truth_sources.filter("variant = 'main'")
    return m.groupBy("person_id").agg(*[F.max(F.when(F.col("source_system") == s, F.col("native_id"))).alias(f"ref_{s}")
                                        for s in SYSTEM_SPEC])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cases (service journeys)

# COMMAND ----------

CASE_DOMAINS = [
    # data_domain, membership flag, probability, case prefix, agency, identity system
    ("housing", "in_housing", 0.9, "HSG", "HOUSING", "housing_crm"),
    ("transport_licensing", "in_transport", 0.3, "TRN", "TRANSPORT", "transport_licence"),
    ("cost_of_living", "in_revenue", 0.55, "COL", "REVENUE", "revenue_concession"),
    ("health", "in_health", 0.5, "HLT", "HEALTH", "community_health"),
]
officer = {o[3]: [] for o in SYNTH_OFFICERS}
for o in SYNTH_OFFICERS:
    officer[o[3]].append(o[0])
OWNER_POOLS = {  # weighted by repetition; None = unassigned
    "HOUSING": ([DEMO_OFFICER] * 7 if DEMO_OFFICER else []) + officer["HOUSING"][:1] * 5 + officer["HOUSING"][1:2] * 4 + [None] * 4,
    "TRANSPORT": officer["TRANSPORT"] * 7 + [None] * 3,
    "REVENUE": officer["REVENUE"] * 7 + [None] * 3,
    "HEALTH": officer["HEALTH"] * 8 + [None] * 2,
}
OPEN_STATUSES = ["open", "open", "awaiting_evidence", "awaiting_evidence", "pending_decision", "in_review"]
CASE_COLS = ["case_id", "person_id", "data_domain", "agency_code", "client_ref", "client_ref_system", "service_type",
             "case_status", "opened_at", "due_at", "closed_at", "owner_principal", "last_updated_at"]


def build_cases(persons: DataFrame, refs: DataFrame) -> DataFrame:
    parts = []
    for dom, flag, p, prefix, agency, system in CASE_DOMAINS:
        st = [s[1] for s in SERVICE_TYPES if s[0] == dom]
        owners = sql_arr_nullable(OWNER_POOLS[agency])
        c = (persons.filter(f"{flag} AND persona_key IS NULL AND {U('case:' + dom, 'person_id')} < {p}")
             .join(refs.select("person_id", F.col(f"ref_{system}").alias("client_ref")), "person_id")
             .selectExpr("person_id", "client_ref", f"'{system}' AS client_ref_system", f"'{dom}' AS data_domain",
                         f"'{agency}' AS agency_code", f"{pick_sql(st, U('cst:' + dom, 'person_id'))} AS service_type",
                         f"{AS_OF_SQL} - make_interval(0, 0, 0, cast(floor({U('copen:' + dom, 'person_id')} * {HISTORY_DAYS + 60}) AS INT) + 1, "
                         f"cast(floor({U('copenh:' + dom, 'person_id')} * 9) AS INT), 0, 0) AS opened_at",
                         f"{U('cclose:' + dom, 'person_id')} AS u_close", f"{U('cstat:' + dom, 'person_id')} AS u_stat",
                         f"{U('cown:' + dom, 'person_id')} AS u_own", f"{U('cdue:' + dom, 'person_id')} AS u_due")
             .selectExpr("*", f"u_close < 0.35 AND opened_at < {AS_OF_SQL} - INTERVAL 14 DAYS AS is_closed")
             .selectExpr(
                 "person_id", "client_ref", "client_ref_system", "data_domain", "agency_code", "service_type", "opened_at",
                 f"CASE WHEN is_closed THEN 'closed' ELSE {pick_sql(OPEN_STATUSES, 'u_stat')} END AS case_status",
                 "opened_at + make_interval(0, 0, 0, cast(floor(21 + u_due * 69) AS INT), 0, 0, 0) AS due_at",
                 f"CASE WHEN is_closed THEN opened_at + make_interval(0, 0, 0, cast(floor(u_close / 0.35 * "
                 f"greatest(datediff({AS_OF_SQL}, opened_at) - 1, 1)) AS INT), 0, 0, 0) END AS closed_at",
                 f"{pick_arr_sql(owners, 'u_own')} AS owner_principal",
                 f"'{prefix}' AS prefix"))
        parts.append(c)
    cases = parts[0]
    for c in parts[1:]:
        cases = cases.unionByName(c)
    w = Window.orderBy(F.xxhash64(F.lit(SEED), "person_id", "data_domain"))
    cases = (cases.withColumn("seq", F.row_number().over(w))
             .withColumn("case_id", F.expr("concat(prefix, '-', cast(year(opened_at) AS STRING), '-', lpad(cast(seq + 1200 AS STRING), 6, '0'))"))
             .withColumn("last_updated_at", F.expr(f"coalesce(closed_at, least({AS_OF_SQL}, opened_at + INTERVAL 3 DAYS))")))
    # persona cases (relative to the as-of time so the design's stories always hold)
    pr = refs.filter("person_id IN ('P-900001', 'P-900002', 'P-900003')").collect()
    pref = {r.person_id: r for r in pr}
    a = AS_OF
    persona_cases = [
        ("HSG-PERSONA-01", "P-900001", "housing", "HOUSING", pref["P-900001"].ref_housing_crm, "housing_crm", "Housing Support application",
         "awaiting_evidence", a - timedelta(days=20), a + timedelta(days=4), None, DEMO_OFFICER, a - timedelta(minutes=8)),
        ("HLT-PERSONA-01", "P-900001", "health", "HEALTH", pref["P-900001"].ref_community_health, "community_health", "Community care plan",
         "open", a - timedelta(days=60), a + timedelta(days=30), None, officer["HEALTH"][0], a - timedelta(days=30)),
        ("TRN-PERSONA-01", "P-900002", "transport_licensing", "TRANSPORT", pref["P-900002"].ref_transport_licence, "transport_licence",
         "Licence renewal", "pending_decision", a - timedelta(days=12), a + timedelta(days=9), None, None, a - timedelta(minutes=24)),
        ("COL-PERSONA-01", "P-900003", "cost_of_living", "REVENUE", pref["P-900003"].ref_revenue_concession, "revenue_concession",
         "Cost of living concession", "in_review", a - timedelta(days=9), a + timedelta(days=21), None, officer["REVENUE"][0], a - timedelta(hours=1)),
    ]
    pc = spark.createDataFrame(persona_cases, "case_id string, person_id string, data_domain string, agency_code string, client_ref string, "
                                              "client_ref_system string, service_type string, case_status string, opened_at timestamp, "
                                              "due_at timestamp, closed_at timestamp, owner_principal string, last_updated_at timestamp")
    return cases.select(*CASE_COLS).unionByName(pc.select(*CASE_COLS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Interactions: skeleton from dbldatagen, latent intent / sentiment / needs, then channel-native text

# COMMAND ----------

INT_COLS = ["interaction_id", "person_id", "channel", "direction", "agency_code", "data_domain", "event_ts", "intent",
            "sentiment_label", "needs", "is_repeat", "outcome", "subject", "text", "svc", "doc", "case_id", "agent_no",
            "centre", "duration_seconds", "u_id1", "u_id2"]


def interaction_skeleton(eligible: DataFrame, n_elig: int, salt: str) -> DataFrame:
    m = int(round(n_elig * IPP * WINDOW_DAYS / 180.0))
    if m <= 0:
        return None
    skel = (dg.DataGenerator(spark, name="interactions", rows=m, partitions=PARTS, randomSeedMethod="hash_fieldname",
                             randomSeed=(SEED * 7919 + int(WINDOW_START.timestamp())) % 2147483647)
            .withIdOutput()
            .withColumn("direction", "string", values=["inbound", "outbound"], weights=[88, 12], random=True)
            .withColumn("agent_no", "int", minValue=101, maxValue=180, random=True)
            .withColumn("centre", "string", values=CENTRES, random=True)
            .withColumn("duration_seconds", "int", minValue=90, maxValue=2100, random=True)
            .withColumn("when_phrase", "string", values=WHEN_PHRASES, random=True)
            .build()
            .selectExpr("*", f"concat('{salt}', ':', cast(id AS STRING)) AS k"))
    doms = ("filter(array(" + ", ".join(
        ["IF(in_housing, 'housing', CAST(NULL AS STRING))"] * 3 + ["IF(in_transport, 'transport_licensing', CAST(NULL AS STRING))"] * 2
        + ["IF(in_revenue, 'cost_of_living', CAST(NULL AS STRING))"] * 2 + ["IF(in_health, 'health', CAST(NULL AS STRING))"] * 2
        + ["'customer_service'"] * 2) + "), x -> x IS NOT NULL)")
    hour_expr = ("CASE WHEN channel IN ('phone', 'shopfront') THEN "
                 "  CASE pref_time WHEN 'mornings' THEN 8.5 + u_h * 3.5 WHEN 'afternoons' THEN 12.0 + u_h * 4.8 ELSE 14.5 + u_h * 2.4 END "
                 "ELSE CASE pref_time WHEN 'mornings' THEN 7.0 + u_h * 5.0 WHEN 'afternoons' THEN 12.0 + u_h * 5.0 ELSE 17.0 + u_h * 5.5 END END")
    df = (skel.selectExpr("*", f"cast(floor(pow({U('pp', 'k')}, 1.45) * {n_elig}) AS INT) AS rank")
          .join(eligible, "rank")
          .selectExpr(
              "*",
              f"CASE WHEN direction = 'outbound' THEN IF(has_email AND {U('och', 'k')} < 0.6, 'email', 'phone') "
              f"WHEN {U('ch', 'k')} < 0.65 THEN pref_channel ELSE {pick_sql(['phone', 'web', 'email', 'shopfront'], U('ch2', 'k'))} END AS ch0",
              f"{pick_arr_sql(doms, U('dom', 'k'))} AS data_domain",
              f"{U('h', 'k')} AS u_h",
              f"{WINDOW_START_SQL} + make_interval(0, 0, 0, 0, 0, 0, floor({U('ts', 'k')} * {WINDOW_SECONDS})) AS ts0")
          .selectExpr(
              "*",
              "CASE WHEN ch0 = 'web' AND NOT in_web THEN 'phone' WHEN ch0 = 'email' AND NOT has_email THEN 'phone' ELSE ch0 END AS channel",
              f"element_at({DOMAIN_AGENCY_MAP}, data_domain) AS agency_code",
              f"CASE WHEN direction = 'outbound' THEN 'general_information' "
              f"ELSE {pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_INTENTS)}, data_domain)', U('int', 'k'))} END AS intent")
          .selectExpr(
              "*", f"to_utc_timestamp(timestampadd(SECOND, cast(floor(({hour_expr}) * 3600) AS INT), "
                   f"cast(to_date(from_utc_timestamp(ts0, '{TZ}')) AS TIMESTAMP)), '{TZ}') AS event_ts",
              f"element_at({sql_map_num(INTENT_SENT_BASE)}, intent) + element_at({sql_map_num(DOMAIN_STRESS)}, data_domain) "
              f"+ ({U('sent', 'k')} - 0.5) * 0.9 AS sent_score",
              "false AS is_repeat"))
    # repeat contact: unresolved enquiries come back within a week, more negative
    fu = (df.filter(f"direction = 'inbound' AND intent IN ('status_enquiry', 'complaint', 'evidence_question') "
                    f"AND {U('res', 'k')} >= element_at({sql_map_num(RESOLVE_P)}, intent) AND {U('fu', 'k')} < 0.45")
          .withColumn("k", F.concat("k", F.lit(":fu")))
          .withColumn("event_ts", F.expr(f"event_ts + make_interval(0, 0, 0, cast(floor(1 + {U('fud', 'k')} * 6) AS INT), "
                                         f"cast(floor({U('fuh', 'k')} * 5) AS INT) - 2, 0, 0)"))
          .withColumn("intent", F.expr(f"IF({U('fui', 'k')} < 0.75, 'status_enquiry', 'complaint')"))
          .withColumn("channel", F.expr(f"IF({U('fuc', 'k')} < 0.6, 'phone', channel)"))
          .withColumn("sent_score", F.expr("sent_score - 0.45"))
          .withColumn("is_repeat", F.lit(True)))
    return df.unionByName(fu).filter(f"event_ts > {WINDOW_START_SQL} AND event_ts <= {AS_OF_SQL}")


def derive_text(df: DataFrame) -> DataFrame:
    """Latent labels -> outcome, needs and channel-native text (shared by generated and persona interactions)."""
    d = df.selectExpr(
        "*",
        "CASE WHEN direction = 'outbound' THEN 'neutral' WHEN sent_score < -0.3 THEN 'negative' WHEN sent_score > 0.3 THEN 'positive' ELSE 'neutral' END AS sentiment_label",
        f"{pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_SVC)}, data_domain)', U('svc', 'k'))} AS svc",
        f"{pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_DOC)}, data_domain)', U('doc', 'k'))} AS doc",
        f"{U('res', 'k')} < element_at({sql_map_num(RESOLVE_P)}, intent) AS resolved",
        f"CASE WHEN direction = 'inbound' AND {U('n1', 'k')} < 0.65 THEN try_element_at({sql_map(DOMAIN_NEED)}, data_domain) END AS need1",
        f"CASE WHEN direction = 'outbound' THEN NULL "
        f"WHEN intent = 'payment_or_debt' AND {U('n2', 'k')} < 0.8 THEN 'financial_pressure' "
        f"WHEN intent IN ('document_submission', 'evidence_question') AND {U('n2', 'k')} < 0.45 THEN 'document_burden' "
        f"WHEN (channel = 'web' OR intent = 'general_information') AND {U('n2', 'k')} < 0.25 THEN 'digital_access' "
        f"WHEN data_domain = 'housing' AND {U('n2', 'k')} < 0.3 THEN 'financial_pressure' END AS need2",
        f"{U('id1', 'k')} AS u_id1", f"{U('id2', 'k')} AS u_id2",
    ).selectExpr(
        "*",
        f"CASE WHEN direction = 'outbound' THEN 'sent' WHEN intent = 'document_submission' THEN 'received' WHEN resolved THEN 'resolved' "
        f"WHEN {U('ref', 'k')} < 0.3 THEN 'referred' ELSE 'follow_up' END AS outcome",
        "array_distinct(filter(array(need1, need2), x -> x IS NOT NULL)) AS needs",
        f"concat_ws(' ', IF(is_repeat, {pick_sql(REPEAT_TPL, U('rp', 'k'))}, NULL), "
        f"{pick_arr_sql(f'element_at({sql_map_arr(INTENT_TPL)}, intent)', U('ti', 'k'))}, "
        f"IF(need1 IS NULL, NULL, {pick_arr_sql(f'element_at({sql_map_arr(NEED_TPL)}, need1)', U('tn1', 'k'))}), "
        f"IF(need2 IS NULL OR need2 = need1, NULL, {pick_arr_sql(f'element_at({sql_map_arr(NEED_TPL)}, need2)', U('tn2', 'k'))}), "
        f"nullif({pick_arr_sql(f'element_at({sql_map_arr(SENT_TPL)}, sentiment_label)', U('tsn', 'k'))}, '')) AS body0",
        f"{pick_sql(OUTBOUND_TPL, U('ob', 'k'))} AS ob0",
    ).selectExpr(
        "*",
        "replace(replace(replace(body0, '{svc}', svc), '{doc}', doc), '{when}', when_phrase) AS body",
        "replace(replace(replace(ob0, '{svc}', svc), '{doc}', doc), '{when}', when_phrase) AS ob",
        f"{pick_arr_sql(f'element_at({sql_map_arr(AGENT_TPL)}, outcome)', U('ag', 'k'))} AS agent_resp",
        f"element_at({AGENCY_NAME_MAP}, agency_code) AS agency_name",
    ).selectExpr(
        "*",
        "CASE WHEN direction = 'outbound' AND channel = 'email' THEN concat('Dear ', given_name, ',\n\n', ob, '\n\nKind regards,\n', agency_name) "
        "WHEN direction = 'outbound' THEN concat('Outbound call: ', ob) "
        "WHEN channel = 'phone' THEN concat('Caller: ', body, ' Agent: ', agent_resp) "
        "WHEN channel = 'email' THEN concat('Hello,\n\n', body, '\n\nRegards,\n', given_name) "
        "WHEN channel = 'web' THEN body "
        "ELSE concat('Customer attended the ', centre, ' service centre. Customer said: \"', body, '\" Outcome: ', agent_resp) END AS text",
        f"CASE WHEN direction = 'outbound' THEN concat('Your ', svc) ELSE concat(element_at({INTENT_LABEL_MAP}, intent), ' - ', svc) END AS subject",
        "concat(CASE channel WHEN 'phone' THEN 'CALL-' WHEN 'web' THEN 'WF-' WHEN 'email' THEN 'EM-' ELSE 'SV-' END, "
        "upper(substr(sha2(k, 256), 1, 14))) AS interaction_id",
        "CAST(NULL AS STRING) AS case_id",
    )
    return d


def persona_interactions(persons: DataFrame) -> DataFrame:
    """Curated interactions for the design's personas, positioned relative to the as-of time."""
    m = lambda minutes: AS_OF - timedelta(minutes=minutes)  # noqa: E731
    rows = [
        # person, channel, direction, domain, intent, sentiment, needs, ts, outcome, repeat, text
        ("P-900001", "web", "inbound", "housing", "document_submission", "neutral", ["housing_stability", "document_burden"], m(8), "received", False,
         "I've uploaded my proof of income for the Housing Support application. I have to leave my rental by Friday and I "
         "don't have anywhere lined up. I've already sent other documents so I hope this is the last one."),
        ("P-900001", "phone", "inbound", "housing", "status_enquiry", "negative", ["housing_stability"], m(60 * 18 + 36), "follow_up", True,
         "Caller: I called earlier this week about the same thing. Does my existing Housing Support application cover emergency "
         "accommodation? I have to leave my rental by Friday and I'm really worried about this. "
         "Agent: Agent logged a follow-up for the case officer."),
        ("P-900001", "phone", "inbound", "housing", "status_enquiry", "negative", ["housing_stability", "financial_pressure"], m(60 * 24 * 3 + 200), "follow_up", False,
         "Caller: Can you tell me where my Housing Support application is up to? The rent has gone up again and I'm behind on payments. "
         "Agent: Agent advised a callback within two business days."),
        ("P-900001", "email", "outbound", "housing", "general_information", "neutral", [], m(60 * 24 * 8 + 120), "sent", False,
         "Dear Amara,\n\nEligibility checklist for your Housing Support application sent with plain-language guidance.\n\n"
         "Kind regards,\nHousing support"),
        ("P-900001", "web", "inbound", "customer_service", "change_of_details", "neutral", [], m(60 * 24 * 40), "resolved", False,
         "I've moved and need my details changed on my MyService account. My new address is in Parramatta."),
        ("P-900001", "phone", "inbound", "health", "appointment_booking", "neutral", ["health_wellbeing"], m(60 * 24 * 30), "resolved", False,
         "Caller: I need to book an appointment for my community care plan. I've been unwell lately. "
         "Agent: Agent confirmed the details and resolved the enquiry."),
        ("P-900002", "phone", "inbound", "transport_licensing", "status_enquiry", "negative", ["mobility_access"], m(24), "follow_up", True,
         "Caller: I called last week about the same thing. Can you tell me where my licence renewal is up to? I need my licence "
         "to get to work. I'm really worried about this. Agent: Agent logged a follow-up for the case officer."),
        ("P-900002", "phone", "inbound", "transport_licensing", "status_enquiry", "neutral", ["mobility_access"], m(60 * 24 * 5 + 90), "follow_up", False,
         "Caller: I wanted to know if my licence renewal has been approved yet. Just checking where things are at. "
         "Agent: Agent advised a callback within two business days."),
        ("P-900002", "web", "inbound", "transport_licensing", "new_application", "neutral", [], m(60 * 24 * 12), "resolved", False,
         "I want to lodge a licence renewal today. My medical assessment form is attached."),
        ("P-900003", "email", "inbound", "cost_of_living", "evidence_question", "neutral", ["document_burden"], m(60), "resolved", False,
         "Hello,\n\nDo I need to provide a Centrelink income statement again for the cost of living concession? I sent one last "
         "month.\n\nRegards,\nPriya"),
        ("P-900003", "email", "inbound", "cost_of_living", "document_submission", "positive", ["financial_pressure"], m(60 * 26), "received", False,
         "Hello,\n\nAttached is the electricity bill you asked for in relation to my cost of living concession. Money is very tight "
         "since my hours were cut. Thanks so much for the help last time.\n\nRegards,\nPriya"),
    ]
    sch = ("person_id string, channel string, direction string, data_domain string, intent string, sentiment_label string, "
           "needs array<string>, event_ts timestamp, outcome string, is_repeat boolean, text string")
    pdf = spark.createDataFrame(rows, sch).withColumn("k", F.concat(F.lit("persona:"), "person_id", F.lit(":"),
                                                                    F.col("event_ts").cast("string")))
    return (pdf.join(persons.select("person_id", "given_name"), "person_id")
            .selectExpr(
                "*", f"element_at({DOMAIN_AGENCY_MAP}, data_domain) AS agency_code",
                f"{pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_SVC)}, data_domain)', '0.0')} AS svc",
                f"{pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_DOC)}, data_domain)', '0.0')} AS doc",
                "CASE WHEN direction = 'outbound' THEN concat('Your ', 'Housing Support application') "
                f"ELSE concat(element_at({INTENT_LABEL_MAP}, intent), ' - ', "
                f"{pick_arr_sql(f'element_at({sql_map_arr(DOMAIN_SVC)}, data_domain)', '0.0')}) END AS subject",
                "concat(CASE channel WHEN 'phone' THEN 'CALL-' WHEN 'web' THEN 'WF-' WHEN 'email' THEN 'EM-' ELSE 'SV-' END, "
                "upper(substr(sha2(k, 256), 1, 14))) AS interaction_id",
                "CAST(NULL AS STRING) AS case_id", "117 AS agent_no", "'Parramatta' AS centre", "420 AS duration_seconds",
                "0.5 AS u_id1", "0.9 AS u_id2"))


def attach_cases(df: DataFrame, cases: DataFrame) -> DataFrame:
    c = cases.select("person_id", "data_domain", F.col("case_id").alias("cid"), "opened_at", "closed_at")
    j = (df.drop("case_id").join(c, ["person_id", "data_domain"], "left")
         .withColumn("ok", F.expr("cid IS NOT NULL AND event_ts >= opened_at AND (closed_at IS NULL OR event_ts <= closed_at + INTERVAL 7 DAYS)"))
         .withColumn("case_id", F.expr("CASE WHEN ok AND (persona OR u_id2 < CASE channel WHEN 'phone' THEN 0.4 ELSE 0.7 END) THEN cid END")))
    w = Window.partitionBy("interaction_id").orderBy(F.col("case_id").isNull(), F.col("opened_at").desc_nulls_last())
    return j.withColumn("_r", F.row_number().over(w)).filter("_r = 1").drop("_r", "cid", "opened_at", "closed_at", "ok")


MAILBOX = sql_map({a[0]: f"{a[0].lower()}.enquiries@example.gov.au" for a in AGENCIES})
DOMAIN_REF = {"customer_service": "ref_snsw_customer", "housing": "ref_housing_crm", "transport_licensing": "ref_transport_licence",
              "cost_of_living": "ref_revenue_concession", "health": "ref_community_health"}


def channel_extracts(it: DataFrame, persons: DataFrame, refs: DataFrame) -> dict:
    x = (it.join(persons.select("person_id", "mobile", "landline", "email", "alt_email", F.col("persona_key").isNotNull().alias("persona_p")), "person_id")
         .join(refs, "person_id", "left")
         .selectExpr("*", "CASE data_domain " + " ".join(f"WHEN '{d}' THEN {c}" for d, c in DOMAIN_REF.items()) + " END AS domain_ref"))
    ts = lambda c: f"date_format(event_ts, '{TS_FMT}') AS {c}"  # noqa: E731
    calls = (x.filter("channel = 'phone'").selectExpr(
        "interaction_id AS call_id", "direction", ts("started_at"), "duration_seconds",
        "CASE WHEN persona_p THEN mobile WHEN u_id1 < 0.06 THEN 'withheld' WHEN landline IS NOT NULL AND u_id1 < 0.16 THEN landline ELSE mobile END AS caller_number",
        "concat(agency_code, '_CONTACT') AS queue", "agency_code", "concat('AG', cast(agent_no AS STRING)) AS agent_id",
        "CASE WHEN persona_p OR u_id2 < 0.45 THEN domain_ref END AS account_ref", "case_id AS case_ref",
        "outcome AS wrap_outcome", "text AS transcript"))
    web = (x.filter("channel = 'web'").selectExpr(
        "interaction_id AS submission_id", "ref_web_account AS account_id", "agency_code",
        f"element_at({INTENT_LABEL_MAP}, intent) AS form_type", "case_id AS case_ref", ts("submitted_at"), "text AS message",
        "IF(intent = 'document_submission', concat(replace(lower(doc), ' ', '_'), '.pdf'), NULL) AS attachment_name",
        "outcome AS status"))
    email = (x.filter("channel = 'email'").selectExpr(
        "interaction_id AS message_id", "direction",
        f"CASE WHEN direction = 'outbound' THEN element_at({MAILBOX}, agency_code) WHEN u_id1 < 0.1 AND NOT persona_p THEN alt_email ELSE email END AS from_address",
        f"CASE WHEN direction = 'outbound' THEN email ELSE element_at({MAILBOX}, agency_code) END AS to_address",
        "agency_code", "subject", "text AS body", ts("received_at"), "case_id AS case_ref"))
    shop = (x.filter("channel = 'shopfront'").selectExpr(
        "interaction_id AS visit_id", "centre", "agency_code", "ref_snsw_customer AS customer_ref",
        "concat(substr(centre, 1, 1), cast(agent_no AS STRING), '-', substr(interaction_id, 4, 4)) AS ticket_no",
        "svc AS service", ts("visited_at"), "replace(text, '\n', ' ') AS officer_notes", "outcome", "case_id AS case_ref"))
    return {"contact_centre_calls": calls, "web_form_submissions": web, "email_messages": email, "shopfront_visits": shop}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Consent events
# MAGIC
# MAGIC Consent is captured by the agency that runs the case, against **its own** client reference, for a
# MAGIC specific purpose and data domain. Entity resolution later resolves it to the constituent. A constituent
# MAGIC who contacted one agency has not thereby consented to that contact being visible to another.

# COMMAND ----------

CONSENT_COLS = ["consent_event_id", "person_id", "captured_by_agency", "client_ref", "client_ref_system", "purpose_code",
                "data_domain", "decision", "captured_at", "expires_at", "capture_channel", "notice_version"]
CONSENT_DOMAINS = {}
for p_, d_, rule, *_ in PURPOSE_DOMAIN_POLICY:
    if rule == "consent":
        CONSENT_DOMAINS.setdefault(p_, []).append(d_)
DOMAIN_FLAG = {"customer_service": "(in_snsw OR in_web)", "housing": "in_housing", "transport_licensing": "in_transport",
               "cost_of_living": "in_revenue", "health": "in_health"}


def build_consent(cases: DataFrame, persons: DataFrame, refs: DataFrame) -> DataFrame:
    purpose_of = sql_map(DOMAIN_PURPOSE)
    cdom = sql_map_arr(CONSENT_DOMAINS)
    flags = "CASE d " + " ".join(f"WHEN '{d}' THEN {f}" for d, f in DOMAIN_FLAG.items()) + " END"
    base = (cases.filter("case_id NOT LIKE '%PERSONA%'")
            .join(persons.select("person_id", "in_snsw", "in_web", "in_housing", "in_transport", "in_revenue", "in_health"), "person_id")
            .selectExpr("*", f"element_at({purpose_of}, data_domain) AS purpose_code")
            .selectExpr("*", f"explode(element_at({cdom}, purpose_code)) AS d")
            .filter(flags)
            .selectExpr("*", "concat(case_id, ':', d) AS ck")
            .selectExpr("*", f"{U('cons', 'ck')} AS u_c", f"{U('consx', 'ck')} AS u_x", f"{U('consw', 'ck')} AS u_w")
            .filter("u_c < 0.77")
            .selectExpr(
                "person_id", "agency_code AS captured_by_agency", "client_ref", "client_ref_system", "purpose_code", "d AS data_domain",
                "IF(u_c < 0.62, 'granted', 'declined') AS decision",
                f"least(opened_at + make_interval(0, 0, 0, cast(floor(u_x * 3) AS INT), 2, 0, 0), {AS_OF_SQL}) AS captured_at",
                "u_x", "u_w", "ck", f"{pick_sql(['phone', 'web', 'shopfront', 'email'], 'u_w')} AS capture_channel"))
    base = base.withColumn("expires_at", F.expr("IF(decision = 'granted', captured_at + IF(u_x < 0.12, INTERVAL 90 DAYS, INTERVAL 365 DAYS), NULL)"))
    withdrawn = (base.filter("decision = 'granted' AND u_w < 0.06")
                 .withColumn("captured_at", F.expr(f"captured_at + make_interval(0, 0, 0, cast(floor(u_w / 0.06 * greatest(datediff({AS_OF_SQL}, captured_at), 1)) AS INT), 0, 0, 0)"))
                 .withColumn("decision", F.lit("withdrawn")).withColumn("expires_at", F.lit(None).cast("timestamp"))
                 .withColumn("ck", F.concat("ck", F.lit(":w"))))
    # front-door consents captured on the web account for general enquiries
    front = (persons.filter("persona_key IS NULL AND (in_snsw OR in_web)").join(refs, "person_id")
             .selectExpr("*", f"explode(element_at({cdom}, 'general_enquiry')) AS d").filter(flags)
             .selectExpr("*", "concat(person_id, ':ge:', d) AS ck")
             .filter(f"{U('gec', 'ck')} < 0.35")
             .selectExpr("person_id", "'SNSW' AS captured_by_agency",
                         "coalesce(ref_snsw_customer, ref_web_account) AS client_ref",
                         "IF(ref_snsw_customer IS NOT NULL, 'snsw_customer', 'web_account') AS client_ref_system",
                         "'general_enquiry' AS purpose_code", "d AS data_domain", "'granted' AS decision",
                         f"{AS_OF_SQL} - make_interval(0, 0, 0, cast(floor({U('gect', 'ck')} * 400) AS INT) + 1, 0, 0, 0) AS captured_at",
                         "0.5 AS u_x", "0.5 AS u_w", "ck", "'web' AS capture_channel")
             .withColumn("expires_at", F.expr("captured_at + INTERVAL 730 DAYS")))
    pr = {r.person_id: r for r in refs.filter("person_id LIKE 'P-9000%'").collect()}
    a = AS_OF
    persona = spark.createDataFrame([
        ("P-900001", "HOUSING", pr["P-900001"].ref_housing_crm, "housing_crm", "housing_case_support", "customer_service", "granted",
         a - timedelta(days=19), a + timedelta(days=19), "phone", "persona:amara:cs"),
        ("P-900002", "TRANSPORT", pr["P-900002"].ref_transport_licence, "transport_licence", "licence_renewal", "customer_service", "granted",
         a - timedelta(days=11), a + timedelta(days=35), "web", "persona:leo:cs"),
        ("P-900003", "REVENUE", pr["P-900003"].ref_revenue_concession, "revenue_concession", "cost_of_living_support", "customer_service",
         "granted", a - timedelta(days=8), a + timedelta(days=357), "email", "persona:priya:cs"),
        ("P-900003", "REVENUE", pr["P-900003"].ref_revenue_concession, "revenue_concession", "cost_of_living_support", "transport_licensing",
         "declined", a - timedelta(days=8), None, "email", "persona:priya:tl"),
    ], "person_id string, captured_by_agency string, client_ref string, client_ref_system string, purpose_code string, "
       "data_domain string, decision string, captured_at timestamp, expires_at timestamp, capture_channel string, ck string")
    out = base.drop("u_x", "u_w").unionByName(withdrawn.drop("u_x", "u_w")).unionByName(front.drop("u_x", "u_w")).unionByName(persona)
    return (out.withColumn("consent_event_id", F.expr("concat('CE-', upper(substr(sha2(ck, 256), 1, 12)))"))
            .withColumn("notice_version", F.lit("privacy-notice-v3.2"))
            .filter(f"captured_at <= {AS_OF_SQL}")
            .select(*CONSENT_COLS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build and land

# COMMAND ----------


def land(df: DataFrame, extract: str) -> int:
    fmt = EXTRACTS[extract][0]
    path = f"{LANDING_ROOT}/{extract}/delivery={DELIVERY}"
    df = df.select([F.col(c).cast("string").alias(c) if dict(df.dtypes)[c] in ("timestamp", "date") else F.col(c) for c in df.columns])
    n = df.count()
    if DRY_RUN or n == 0:
        print(f"{'[dry-run] ' if DRY_RUN else ''}{extract}: {n} rows")
        return n
    if fmt == "csv":
        (df.select([F.col(c).cast("string").alias(c) for c in df.columns]).coalesce(4).write.mode("overwrite")
         .option("header", True).option("quoteAll", True).option("escape", '"').csv(path))
    else:
        df.coalesce(4).write.mode("overwrite").json(path)
    print(f"landed {extract}: {n} rows -> {path}")
    return n


def save_truth(df: DataFrame, name: str, comment: str, mode_: str = "overwrite") -> DataFrame:
    """Persist generator state; returns the persisted table so later steps read materialised data
    (serverless has no DataFrame cache)."""
    if DRY_RUN:
        return df
    write_table(df, name, comment, mode=mode_, layer="evaluation", classification="synthetic_ground_truth")
    return spark.table(table_name(name))


if mode == "bootstrap":
    persons = save_truth(build_population(), "synthetic_truth_persons",
                         "Ground truth population (synthetic). Evaluation only - never served.")
    identity_extracts, truth_sources = build_identity_extracts(persons)
    truth_sources = save_truth(truth_sources, "synthetic_truth_source_records",
                               "Ground truth: which person each source identity record belongs to.")
    refs = refs_pivot(truth_sources)
    cases = save_truth(build_cases(persons, refs), "synthetic_truth_cases",
                       "Generator state: current case snapshot including the person behind each case.")
    consent = build_consent(cases, persons, refs)
    for extract, df in identity_extracts.items():
        land(df, extract)
else:
    persons = spark.table(table_name("synthetic_truth_persons"))
    refs = refs_pivot(spark.table(table_name("synthetic_truth_source_records")))
    cases = spark.table(table_name("synthetic_truth_cases")).select(*CASE_COLS)
    prior = spark.table(table_name("synthetic_truth_consent"))
    # a small share of current grants is withdrawn during the window
    latest = (prior.withColumn("_r", F.row_number().over(Window.partitionBy("person_id", "purpose_code", "data_domain")
                                                          .orderBy(F.desc("captured_at")))).filter("_r = 1 AND decision = 'granted'"))
    consent = (latest.filter(f"{U('wd:' + DELIVERY, 'consent_event_id')} < {0.003 * WINDOW_DAYS}")
               .withColumn("consent_event_id", F.concat("consent_event_id", F.lit("-W")))
               .withColumn("decision", F.lit("withdrawn")).withColumn("expires_at", F.lit(None).cast("timestamp"))
               .withColumn("captured_at", F.expr(f"{AS_OF_SQL} - make_interval(0, 0, 0, 0, 0, 0, floor({U('wdt', 'consent_event_id')} * {WINDOW_SECONDS}))"))
               .withColumn("capture_channel", F.lit("phone")).select(*CONSENT_COLS))

eligible = persons.filter("persona_key IS NULL").withColumn(
    "rank", F.row_number().over(Window.orderBy(F.desc("need_score"), "person_id")) - 1)
n_elig = eligible.count()
skeleton = interaction_skeleton(eligible, n_elig, f"w{int(WINDOW_START.timestamp())}")
generated = derive_text(skeleton).withColumn("persona", F.lit(False)) if skeleton is not None else None
parts = [generated] if generated is not None else []
if mode == "bootstrap":
    parts.append(persona_interactions(persons).withColumn("persona", F.lit(True)))
interactions = parts[0].select(*INT_COLS, "persona", "given_name") if parts else None
for extra in parts[1:]:
    interactions = interactions.unionByName(extra.select(*INT_COLS, "persona", "given_name"))

if interactions is not None:
    interactions = save_truth(attach_cases(interactions, cases), "synthetic_staging_interactions",
                              "Generator scratch: interactions generated for the current delivery window.")
    if mode == "incremental":
        # a document arriving moves an open case into review
        moved = (interactions.filter("intent = 'document_submission' AND case_id IS NOT NULL").select("case_id").distinct()
                 .withColumn("to_review", F.lit(True)))
        cases = (cases.join(moved, "case_id", "left")
                 .withColumn("case_status", F.expr("IF(to_review AND case_status IN ('open', 'awaiting_evidence'), 'in_review', case_status)"))
                 .withColumn("last_updated_at", F.expr(f"IF(to_review, {AS_OF_SQL}, last_updated_at)")).drop("to_review"))
        cases = save_truth(cases, "synthetic_truth_cases",
                           "Generator state: current case snapshot including the person behind each case.")
    for extract, df in channel_extracts(interactions, persons, refs).items():
        land(df, extract)
    save_truth(interactions.select("interaction_id", "person_id", "channel", "direction", "agency_code", "data_domain", "event_ts",
                                   "intent", "sentiment_label", "needs", "is_repeat", "outcome", "case_id"),
               "synthetic_truth_interactions", "Ground truth interaction labels (intent, sentiment, needs) for AI evaluation.",
               "overwrite" if mode == "bootstrap" else "append")

land(cases.selectExpr("case_id", "agency_code", "client_ref", "client_ref_system", "service_type", "case_status",
                      "opened_at", "due_at", "closed_at", "owner_principal", "last_updated_at"), "service_cases")
land(consent.drop("person_id"), "consent_events")
save_truth(consent, "synthetic_truth_consent", "Ground truth consent events with the person behind each.",
           "overwrite" if mode == "bootstrap" else "append")

if DRY_RUN:
    display(interactions.filter("persona").select("interaction_id", "person_id", "channel", "data_domain", "event_ts", "case_id", "text"))
else:
    if mode == "bootstrap":
        set_control("world_anchor_ts", AS_OF.isoformat())
        set_control("seed", SEED)
        set_control("population_size", N)
        set_control("history_days", HISTORY_DAYS)
        set_control("demo_officer_principal", DEMO_OFFICER or "")
    set_control("last_landed_ts", AS_OF.isoformat())
    set_control("last_delivery", DELIVERY)
print("delivery", DELIVERY, "complete")
