# Databricks notebook source
# MAGIC %md
# MAGIC # Generate synthetic data - Automated Compliance Reporting
# MAGIC
# MAGIC **Wholly synthetic.** Builds a seeded, reproducible world modelled on the Australian Government
# MAGIC [Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process):
# MAGIC
# MAGIC | Table | What it is |
# MAGIC | --- | --- |
# MAGIC | `review_gates` | Gateway gates 0-5 |
# MAGIC | `source_systems` | Seven evidence source systems and their connectors |
# MAGIC | `artefact_types` | Catalogue of evidence artefact types (what evidence *is*) |
# MAGIC | `obligation_register` | Versioned (SCD2) obligation register: effective dates, approvals, drafts, retirements |
# MAGIC | `obligation_requirements` | Evidence requirements per obligation version, with freshness thresholds |
# MAGIC | `evidence_labels` | **Labelled evaluation set**: true artefact type per evidence item (never used by mapping) |
# MAGIC | `synthetic_evidence_plan` | Connector deliveries over a past + future timeline (landed day by day by `02`) |
# MAGIC | `synthetic_collection_runs_plan` | Nightly connector runs incl. outages |
# MAGIC | `synthetic_review_plan` | Synthetic human mapping reviews (landed when due by `02`) |
# MAGIC
# MAGIC The timeline is anchored on `as_of_date` (default: today) and spans `history_days` back and
# MAGIC `future_days` forward. Only deliveries up to the run date are landed, so the daily job keeps
# MAGIC producing fresh evidence, evidence keeps expiring, and gaps open and close over time.
# MAGIC Scenarios are seeded per artefact type (current, expiring, expired, missing, unsigned draft),
# MAGIC and a few are pinned so the demo always shows the stories in the design wireframe.
# MAGIC
# MAGIC Idempotent: if a plan already exists it is left untouched (run `00_setup` with `reset=true` to rebuild).

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("history_days", "540")
dbutils.widgets.text("future_days", "365")
dbutils.widgets.text("seed", "42")
dbutils.widgets.text("history_retention_days", "2555")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
as_of_param = dbutils.widgets.get("as_of_date")
history_days = int(dbutils.widgets.get("history_days"))
future_days = int(dbutils.widgets.get("future_days"))
seed = int(dbutils.widgets.get("seed"))
retention_days = int(dbutils.widgets.get("history_retention_days"))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import random
import re

anchor = date.fromisoformat(resolve_as_of(as_of_param))
start = anchor - timedelta(days=history_days)
end = anchor + timedelta(days=future_days)
print(f"anchor={anchor} window={start}..{end} seed={seed}")

if table_exists("synthetic_generation_runs") and spark.table(fqn("synthetic_generation_runs")).count() > 0:
    prior = spark.table(fqn("synthetic_generation_runs")).orderBy(F.desc("generated_at")).first()
    msg = f"Synthetic plan already exists (anchor {prior['anchor_date']}, seed {prior['seed']}); leaving it untouched."
    print(msg)
    dbutils.notebook.exit(msg)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reference catalogues

# COMMAND ----------

FRAMEWORKS = {
    "Gateway Reviews Process": "https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process",
    "DTA Assurance Framework": "https://www.dta.gov.au/updates/updated-assurance-framework-strengthen-digital-investment-delivery",
    "DTA AI assurance framework": "https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework",
    "DTA AI transparency statement": "https://www.dta.gov.au/ai-transparency-statement",
    "Protective Security Policy Framework": "https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework",
}

GATES = [
    ("GATE-0", "Gate 0", "Business need", 0, "Confirms the business need, strategic fit and accountable leadership before options are developed."),
    ("GATE-1", "Gate 1", "Business case", 1, "Confirms the preferred option is robust, affordable and governed before investment approval."),
    ("GATE-2", "Gate 2", "Delivery strategy", 2, "Confirms the delivery, procurement, risk and benefits strategy before going to market."),
    ("GATE-3", "Gate 3", "Investment decision", 3, "Confirms the investment decision, contracts and controls before committing to delivery."),
    ("GATE-4", "Gate 4", "Readiness for service", 4, "Confirms the organisation is ready to transition the solution into service."),
    ("GATE-5", "Gate 5", "Benefits realisation", 5, "Confirms benefits are being realised and lessons are captured."),
]

# source_id, name, connector, provides_document_class, evidence form shown in the register
SOURCES = [
    ("SRC-DOC", "Document repository", "document.connector", False, "Approved document"),
    ("SRC-MTG", "Meeting records", "meeting.connector", False, "Most recent meeting"),
    ("SRC-RISK", "Risk system", "risk.connector", True, "Controlled register"),
    ("SRC-FIN", "Finance system", "finance.connector", True, "System extract"),
    ("SRC-PPM", "Project portfolio system", "ppm.connector", True, "Controlled register"),
    ("SRC-SEC", "Security register", "security.connector", True, "Controlled register"),
    ("SRC-HR", "HR system", "hr.connector", True, "System extract"),
]
SOURCE = {s[0]: s for s in SOURCES}

# artefact_type, source_id, period_days (None = one document, versioned), formats, purpose, title variants
ARTEFACT_TYPES = [
    ("Governance charter", "SRC-DOC", None, ["PDF"], "Sets out the program governance structure, decision rights, committee terms of reference and escalation paths.", ["Program Governance Charter", "Governance Framework and Terms of Reference", "Governance charter"]),
    ("Delegations schedule", "SRC-DOC", None, ["PDF", "XLSX"], "Records the financial and administrative delegations held by program officers and their limits.", ["Instrument of Delegation - Program", "Delegations schedule", "Financial and administrative delegations register"]),
    ("Strategic alignment statement", "SRC-DOC", None, ["DOCX", "PDF"], "Explains how the program aligns with government priorities and the agency corporate plan.", ["Strategic Alignment Statement", "Alignment with corporate plan priorities"]),
    ("Problem definition paper", "SRC-DOC", None, ["DOCX", "PDF"], "Describes the policy problem, its causes and the outcomes the investment seeks.", ["Problem Definition Paper", "Statement of the problem and intended outcomes"]),
    ("Options analysis", "SRC-DOC", None, ["PDF"], "Compares delivery options with costs, benefits and risks and recommends a preferred option.", ["Options Analysis", "Comparative assessment of delivery options", "Preferred option recommendation paper"]),
    ("Independent cost review", "SRC-DOC", None, ["PDF"], "Independent review of the program cost estimate, assumptions and contingency.", ["Independent Cost Estimate Review", "External cost assurance review"]),
    ("Funding approval letter", "SRC-DOC", None, ["PDF"], "Confirms the approved funding source, appropriation and amount.", ["Funding Approval Letter", "Confirmation of appropriation"]),
    ("SRO appointment letter", "SRC-DOC", None, ["PDF"], "Formally appoints the Senior Responsible Official and states their accountabilities.", ["Letter of Appointment - Senior Responsible Official", "SRO appointment"]),
    ("Integrated assurance plan", "SRC-DOC", None, ["DOCX", "PDF"], "Schedules assurance activities, reviews and reviewers across the program lifecycle.", ["Integrated Assurance Plan", "Program assurance schedule"]),
    ("Privacy impact assessment", "SRC-DOC", None, ["PDF"], "Assesses the privacy impacts of personal information handling and records mitigations.", ["Privacy Impact Assessment", "PIA - program data flows"]),
    ("Procurement strategy", "SRC-DOC", None, ["PDF", "DOCX"], "Sets out the approach to market, evaluation method and contract model.", ["Procurement Strategy", "Approach to market plan"]),
    ("Probity plan", "SRC-DOC", None, ["PDF"], "Describes probity arrangements, conflict-of-interest management and the probity adviser role.", ["Probity Plan", "Probity and conflict of interest arrangements"]),
    ("Resourcing plan", "SRC-DOC", None, ["DOCX", "XLSX"], "Identifies roles, capability needs and the staffing profile for delivery.", ["Resourcing Plan", "Workforce and capability plan"]),
    ("Change impact assessment", "SRC-DOC", None, ["DOCX", "PDF"], "Assesses the impacts of the change on business units, users and processes.", ["Change Impact Assessment", "Business change impact analysis"]),
    ("Benefits realisation plan", "SRC-DOC", None, ["DOCX", "PDF"], "Defines the benefits baseline, measures, targets and benefit owners.", ["Benefits baseline draft", "Benefits Realisation Plan", "Benefits baseline and measures"]),
    ("AI impact assessment", "SRC-DOC", None, ["PDF"], "Assesses the risks and impacts of the AI use case, including fairness, transparency and human oversight.", ["AI Impact Assessment", "Assessment of AI use case risks"]),
    ("AI transparency statement", "SRC-DOC", None, ["PDF"], "Public statement describing how the agency uses AI and the safeguards applied.", ["AI Transparency Statement", "Statement on agency use of artificial intelligence"]),
    ("Contract management plan", "SRC-DOC", None, ["DOCX", "PDF"], "Describes how supplier contracts are managed, monitored and reported.", ["Contract Management Plan", "Supplier management plan"]),
    ("Test strategy", "SRC-DOC", None, ["DOCX", "PDF"], "Defines test phases, entry and exit criteria and acceptance responsibilities.", ["Test Strategy", "Test and acceptance approach"]),
    ("Service transition plan", "SRC-DOC", None, ["DOCX", "PDF"], "Plans the transition of the solution into business-as-usual operations and support.", ["Service Transition Plan", "Transition to operations plan"]),
    ("Lessons learned register", "SRC-DOC", None, ["XLSX", "DOCX"], "Captures lessons identified during delivery and the actions taken to embed them.", ["Lessons Learned Register", "Lessons identified log"]),
    ("Post-implementation review plan", "SRC-DOC", None, ["DOCX"], "Schedules and scopes the post-implementation review.", ["Post-Implementation Review Plan", "PIR terms of reference"]),
    ("Steering committee minutes", "SRC-MTG", 30, ["PDF", "DOCX"], "Records decisions, actions and risks considered by the program steering committee.", ["Steering Committee Minutes - {period}", "SteerCo minutes {period}", "Program Board meeting record - {period}"]),
    ("Risk committee minutes", "SRC-MTG", 90, ["PDF"], "Records the risk committee's review of program risks, ratings and treatments.", ["Risk and Audit Committee minutes - {period}", "Risk committee meeting record {period}"]),
    ("Risk treatment register", "SRC-RISK", None, ["XLSX"], "Lists program risks, ratings, owners and treatment actions.", ["Risk treatment register"]),
    ("Cost estimate", "SRC-FIN", None, ["XLSX"], "Detailed program cost estimate by phase and cost category.", ["Cost estimate"]),
    ("Expenditure approvals extract", "SRC-FIN", 30, ["CSV"], "Extract of expenditure approvals with the approving delegate and amount.", ["Expenditure approvals extract - {period}"]),
    ("Budget variance report", "SRC-FIN", 30, ["XLSX"], "Reports actual expenditure against budget with variance commentary.", ["Budget variance report - {period}"]),
    ("Stakeholder register", "SRC-PPM", None, ["XLSX"], "Lists stakeholders, their interests and the engagement approach.", ["Stakeholder register"]),
    ("Tier assessment", "SRC-PPM", None, ["PDF"], "Assessment of the investment's risk and complexity tier.", ["Tier assessment"]),
    ("Issues log", "SRC-PPM", None, ["XLSX"], "Tracks open program issues, owners and resolution actions.", ["Issues log"]),
    ("Integrated master schedule", "SRC-PPM", None, ["XLSX"], "Baseline schedule of milestones, dependencies and the critical path.", ["Integrated master schedule"]),
    ("AI use case register entry", "SRC-PPM", None, ["JSON"], "Register entry describing an AI use case, its accountable owner and risk rating.", ["AI use case register entry"]),
    ("Data quality report", "SRC-PPM", 30, ["CSV"], "Reports data quality measures for program data assets.", ["Data quality report - {period}"]),
    ("Delivery plan", "SRC-PPM", None, ["XLSX"], "Plan of delivery phases, releases and dependencies.", ["Delivery plan"]),
    ("Change control register", "SRC-PPM", None, ["XLSX"], "Records change requests and their approval decisions.", ["Change control register"]),
    ("Status report", "SRC-PPM", 30, ["PDF"], "Monthly program status covering milestones, risks and issues.", ["Program status report - {period}"]),
    ("Operational readiness checklist", "SRC-PPM", None, ["XLSX"], "Checklist confirming operational readiness criteria are met.", ["Operational readiness checklist"]),
    ("Benefits tracking report", "SRC-PPM", 90, ["XLSX"], "Tracks benefit measures against baseline targets.", ["Benefits tracking report - {period}"]),
    ("Recommendation action tracker", "SRC-PPM", None, ["XLSX"], "Tracks actions taken in response to previous review recommendations.", ["Recommendation action tracker"]),
    ("Security risk assessment", "SRC-SEC", None, ["PDF"], "Assesses security threats, vulnerabilities and controls for the system.", ["Security risk assessment"]),
    ("System security plan", "SRC-SEC", None, ["PDF"], "Describes the system's security controls and their implementation.", ["System security plan"]),
    ("Information classification register", "SRC-SEC", None, ["XLSX"], "Records information holdings and their security classification.", ["Information classification register"]),
    ("Access review attestation", "SRC-SEC", 90, ["PDF"], "Attests that privileged and user access has been reviewed.", ["Access review attestation - {period}"]),
    ("Business continuity test report", "SRC-SEC", None, ["PDF"], "Reports the results of business continuity and disaster recovery testing.", ["Business continuity test report"]),
    ("Authority to operate", "SRC-SEC", None, ["PDF"], "Formal security authorisation for the system to operate.", ["Authority to operate"]),
    ("Training completion report", "SRC-HR", 30, ["CSV"], "Reports completion of mandatory and role-based training by users.", ["Training completion report - {period}"]),
]
ATYPE = {a[0]: a for a in ARTEFACT_TYPES}

# Documents that look like evidence but are not (tests mapping precision).
NOISE = [
    ("Team offsite agenda", "Agenda and logistics for the team planning offsite."),
    ("Office relocation FAQ", "Frequently asked questions about the floor move."),
    ("Social club newsletter", "Social club events and member news."),
    ("Stationery order form", "Form for ordering office stationery."),
    ("Parking permit procedure", "How to apply for a staff parking permit."),
    ("All-staff town hall slides", "Slides presented at the all-staff town hall."),
    ("Vendor marketing brochure", "Marketing material received from a prospective vendor."),
    ("Conference travel itinerary", "Travel bookings for conference attendance."),
    ("Media release (unrelated program)", "Draft media release for another agency program."),
    ("IT service desk outage notice", "Notice of a planned service desk outage."),
    ("Flexible work guidelines", "Guidance on flexible working arrangements."),
    ("Weekly team stand-up notes", "Informal notes from the weekly team stand-up."),
]

# obligation_id, title, gate, owner_role, framework, description, [(artefact_type, max_age_days)]
GW, DTA, DTAAI, DTATS, PSPF = ("Gateway Reviews Process", "DTA Assurance Framework", "DTA AI assurance framework",
                               "DTA AI transparency statement", "Protective Security Policy Framework")
OBLIGATIONS = [
    ("OBL-001", "Governance model approved", "GATE-1", "Program office", GW, "The program governance model is approved by the accountable authority and identifies decision rights.", [("Governance charter", 365), ("Delegations schedule", 180), ("Steering committee minutes", 45)]),
    ("OBL-002", "Business need articulated", "GATE-0", "Senior Responsible Official", GW, "The policy problem, intended outcomes and strategic alignment are documented and endorsed.", [("Strategic alignment statement", 365), ("Problem definition paper", 365)]),
    ("OBL-003", "Stakeholders identified and engaged", "GATE-0", "Change lead", GW, "Stakeholders are identified with an engagement approach that is kept current.", [("Stakeholder register", 90)]),
    ("OBL-004", "Options analysis completed", "GATE-1", "Program office", GW, "Delivery options have been compared and a preferred option recommended.", [("Options analysis", 365)]),
    ("OBL-005", "Cost estimate independently reviewed", "GATE-1", "Finance lead", GW, "The cost estimate is current and has been independently reviewed.", [("Cost estimate", 180), ("Independent cost review", 365)]),
    ("OBL-006", "Funding source confirmed", "GATE-1", "Finance lead", GW, "The funding source and amount are confirmed in writing.", [("Funding approval letter", 365)]),
    ("OBL-007", "Senior Responsible Official appointed", "GATE-0", "Senior Responsible Official", GW, "An SRO is formally appointed with documented accountabilities.", [("SRO appointment letter", 730)]),
    ("OBL-008", "Integrated assurance plan agreed", "GATE-1", "Program office", DTA, "Assurance activities are planned and agreed for the program lifecycle.", [("Integrated assurance plan", 180)]),
    ("OBL-009", "Digital investment tier assessed", "GATE-1", "Program office", DTA, "The investment's risk and complexity tier has been assessed.", [("Tier assessment", 365)]),
    ("OBL-010", "Security risk assessment current", "GATE-2", "Chief information security officer", PSPF, "Security risks are assessed and the system security plan is current.", [("Security risk assessment", 365), ("System security plan", 365)]),
    ("OBL-011", "Information classification applied", "GATE-2", "Chief information security officer", PSPF, "Program information holdings are classified and the register is maintained.", [("Information classification register", 180)]),
    ("OBL-012", "Privacy impact assessment completed", "GATE-2", "Data governance lead", "Agency policy", "Privacy impacts of the program are assessed and mitigations recorded.", [("Privacy impact assessment", 365)]),
    ("OBL-013", "Procurement strategy approved", "GATE-2", "Procurement lead", GW, "The procurement approach and probity arrangements are approved.", [("Procurement strategy", 365), ("Probity plan", 365)]),
    ("OBL-014", "Risk treatment current", "GATE-2", "Risk lead", GW, "Program risks have current treatments that are reviewed by the risk committee.", [("Risk treatment register", 60), ("Risk committee minutes", 120)]),
    ("OBL-015", "Issues actively managed", "GATE-2", "Delivery lead", GW, "Program issues are logged, owned and actively resolved.", [("Issues log", 30)]),
    ("OBL-016", "Schedule baseline approved", "GATE-2", "Delivery lead", GW, "An integrated schedule baseline is approved and maintained.", [("Integrated master schedule", 60)]),
    ("OBL-017", "Resourcing plan endorsed", "GATE-2", "Program office", GW, "Delivery roles and capability needs are planned and endorsed.", [("Resourcing plan", 180)]),
    ("OBL-018", "Change impacts assessed", "GATE-2", "Change lead", GW, "Impacts of the change on people and processes are assessed.", [("Change impact assessment", 180)]),
    ("OBL-019", "Benefits baseline endorsed", "GATE-2", "Benefits lead", GW, "A benefits baseline with measures, targets and owners is endorsed.", [("Benefits realisation plan", 180)]),
    ("OBL-020", "AI use case registered and assessed", "GATE-2", "AI accountable officer", DTAAI, "Each AI use case is registered and its impacts assessed before deployment.", [("AI use case register entry", 365), ("AI impact assessment", 365)]),
    ("OBL-021", "AI transparency statement published", "GATE-3", "AI accountable officer", DTATS, "The agency AI transparency statement is published and current.", [("AI transparency statement", 365)]),
    ("OBL-022", "Contract management plan in place", "GATE-3", "Procurement lead", GW, "Supplier contracts have a management plan in place.", [("Contract management plan", 365)]),
    ("OBL-023", "Financial delegations observed", "GATE-3", "Finance lead", GW, "Expenditure is approved within delegation and tracked against budget.", [("Expenditure approvals extract", 45), ("Budget variance report", 45)]),
    ("OBL-024", "Test strategy approved", "GATE-3", "Delivery lead", GW, "The test and acceptance approach is approved.", [("Test strategy", 365)]),
    ("OBL-025", "Data governance controls operating", "GATE-3", "Data governance lead", "Agency policy", "Data quality is measured and access is reviewed.", [("Data quality report", 45), ("Access review attestation", 120)]),
    ("OBL-026", "Business continuity arrangements tested", "GATE-4", "Chief information security officer", PSPF, "Business continuity and recovery arrangements are tested.", [("Business continuity test report", 365)]),
    ("OBL-027", "Delivery plan controlled", "GATE-3", "Delivery lead", GW, "The delivery plan is baselined, changes are controlled and status is reported to governance.", [("Delivery plan", 90), ("Change control register", 60), ("Status report", 45), ("Steering committee minutes", 45)]),
    ("OBL-028", "Operational readiness confirmed", "GATE-4", "Delivery lead", GW, "Operational readiness criteria are met and transition is planned.", [("Operational readiness checklist", 60), ("Service transition plan", 180)]),
    ("OBL-029", "Security authorisation granted", "GATE-4", "Chief information security officer", PSPF, "The system holds a current authority to operate.", [("Authority to operate", 365)]),
    ("OBL-030", "Users trained for go-live", "GATE-4", "Change lead", GW, "Users have completed the training required for go-live.", [("Training completion report", 45)]),
    ("OBL-031", "Benefits tracked against baseline", "GATE-5", "Benefits lead", GW, "Benefit measures are tracked against the endorsed baseline.", [("Benefits tracking report", 120)]),
    ("OBL-032", "Lessons learned captured", "GATE-5", "Program office", GW, "Lessons are captured and actions taken to embed them.", [("Lessons learned register", 180)]),
    ("OBL-033", "Post-implementation review scheduled", "GATE-5", "Senior Responsible Official", GW, "A post-implementation review is scheduled and scoped.", [("Post-implementation review plan", 365)]),
    ("OBL-034", "Previous review recommendations actioned", "GATE-3", "Program office", GW, "Recommendations from previous assurance reviews are tracked to closure.", [("Recommendation action tracker", 30)]),
    ("OBL-035", "Quarterly paper status return lodged", "GATE-3", "Program office", GW, "A quarterly paper status return is lodged with the portfolio office (superseded by monthly digital status reporting).", [("Status report", 120)]),
]

# Pinned to reproduce the stories in design/compliance-reporting-wireframe.html.
FORCED_VERSIONS = {"OBL-001": 3, "OBL-014": 2, "OBL-019": 1, "OBL-027": 4, "OBL-035": 1}
FORCED_LAST_EFFECTIVE_AGE = {"OBL-001": 8}
DRAFT_REVISIONS = {
    "OBL-019": "Proposed: require an endorsement minute alongside the benefits baseline",
    "OBL-012": "Proposed: shorten the review cycle for the privacy impact assessment",
    "OBL-023": "Proposed: align the variance report threshold with the monthly finance cycle",
}
RETIRED = {"OBL-035": 120}  # retired N days before anchor
FORCED_SCENARIO = {
    "Risk treatment register": ("expiring", 2),
    "Benefits realisation plan": ("unsigned", None),
    "Governance charter": ("current", None),
    "Steering committee minutes": ("current", None),
    "Delivery plan": ("current", None),
    "Status report": ("current", None),
    "Post-implementation review plan": ("missing", None),
    "Lessons learned register": ("expired", None),
    "Access review attestation": ("expired", None),
}
OTHER_REASONS = [
    "Owner and wording clarified",
    "Aligned to the updated DTA Assurance Framework",
    "Freshness threshold tightened following Gateway review recommendation",
]
REVIEWERS = [f"Assurance analyst {i:02d} (synthetic)" for i in range(1, 5)]


def rng(*key) -> random.Random:
    return random.Random(":".join([str(seed), *map(str, key)]))


def at(d: date, r: random.Random, lo: int = 8, hi: int = 18) -> datetime:
    return datetime(d.year, d.month, d.day, r.randint(lo, hi), r.randint(0, 59), r.randint(0, 59))


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Obligation register (SCD2)

# COMMAND ----------

register_rows, requirement_rows = [], []
for obl_id, title, gate, owner, framework, desc, reqs in OBLIGATIONS:
    r = rng("obl", obl_id)
    n_versions = FORCED_VERSIONS.get(obl_id) or r.choice([1, 1, 2, 2, 3, 4])
    first_eff = anchor - timedelta(days=r.randint(420, 600))
    last_eff = anchor - timedelta(days=FORCED_LAST_EFFECTIVE_AGE.get(obl_id, r.randint(5, 150)))
    if obl_id in RETIRED:
        last_eff = first_eff
    step = (last_eff - first_eff).days / max(1, n_versions - 1)
    effs = [first_eff + timedelta(days=round(step * k)) for k in range(n_versions)] if n_versions > 1 else [first_eff]
    prev_n, prev_tightened = 0, False
    for k, eff in enumerate(effs, start=1):
        n_req = max(1, len(reqs) - (n_versions - k)) if len(reqs) > 1 else 1
        tightened = k < n_versions and r.random() < 0.5
        if k == 1:
            reason = "Initial register entry"
        elif n_req > prev_n:
            reason = "Additional evidence requirement added"
        elif prev_tightened:
            reason = "Freshness threshold tightened following Gateway review recommendation"
        else:
            reason = r.choice(OTHER_REASONS)
        approved_at = at(eff - timedelta(days=r.randint(1, 10)), r)
        register_rows.append(dict(
            obligation_id=obl_id, version=k, title=title, description=desc, gate_id=gate, owner_role=owner,
            framework=framework, framework_url=FRAMEWORKS.get(framework), approval_state="Approved",
            effective_from=eff, effective_to=effs[k] if k < n_versions else None,
            retired_on=(anchor - timedelta(days=RETIRED[obl_id])) if obl_id in RETIRED else None,
            proposed_at=approved_at - timedelta(days=r.randint(3, 20)), approved_at=approved_at, approved_by=owner,
            change_reason=reason, requirement_count=n_req,
        ))
        for i, (atype, max_age) in enumerate(reqs[:n_req], start=1):
            requirement_rows.append(dict(
                obligation_id=obl_id, version=k, requirement_id=f"{obl_id}-R{i}", artefact_type=atype,
                requirement_description=SOURCE[ATYPE[atype][1]][4], expected_source_id=ATYPE[atype][1],
                max_age_days=round(max_age * 1.5) if tightened else max_age, mandatory=True,
            ))
        prev_n, prev_tightened = n_req, tightened
    if obl_id in DRAFT_REVISIONS:
        k = n_versions + 1
        proposed = at(anchor - timedelta(days=r.randint(1, 10)), r)
        register_rows.append(dict(
            obligation_id=obl_id, version=k, title=title, description=desc, gate_id=gate, owner_role=owner,
            framework=framework, framework_url=FRAMEWORKS.get(framework), approval_state="Draft",
            effective_from=None, effective_to=None, retired_on=None, proposed_at=proposed, approved_at=None,
            approved_by=None, change_reason=DRAFT_REVISIONS[obl_id], requirement_count=len(reqs),
        ))
        for i, (atype, max_age) in enumerate(reqs, start=1):
            requirement_rows.append(dict(
                obligation_id=obl_id, version=k, requirement_id=f"{obl_id}-R{i}", artefact_type=atype,
                requirement_description=SOURCE[ATYPE[atype][1]][4], expected_source_id=ATYPE[atype][1],
                max_age_days=max(30, round(max_age * 0.75)), mandatory=True,
            ))

print(f"register versions: {len(register_rows)}  requirements: {len(requirement_rows)}")

# Binding freshness per artefact type = tightest threshold among requirements in force at the anchor.
in_force = {(x["obligation_id"], x["version"]) for x in register_rows
            if x["approval_state"] == "Approved" and x["effective_from"] <= anchor
            and (x["effective_to"] is None or x["effective_to"] > anchor) and x["retired_on"] is None}
binding = {}
for q in requirement_rows:
    if (q["obligation_id"], q["version"]) in in_force:
        binding[q["artefact_type"]] = min(binding.get(q["artefact_type"], 10**6), q["max_age_days"])
for q in requirement_rows:  # types only used by non-current versions
    binding.setdefault(q["artefact_type"], q["max_age_days"])
approver = {}
for o in OBLIGATIONS:
    for atype, _ in o[6]:
        approver.setdefault(atype, o[3])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence timeline per artefact type

# COMMAND ----------

VERSIONED_WEIGHTS = [("current", 66), ("expiring", 12), ("expired", 8), ("missing", 6), ("unsigned", 8)]
PERIODIC_WEIGHTS = [("current", 75), ("expiring", 12), ("expired", 8), ("missing", 5)]


def pick(r, weights):
    return r.choices([w[0] for w in weights], weights=[w[1] for w in weights])[0]


def jitter(r, days, lo=0.85, hi=1.15):
    return timedelta(days=max(1, round(days * r.uniform(lo, hi))))


documents = []  # each: dict(key, atype, source_id, title, file_format, document_class, versions=[(modified_date, approval)])
scenario_by_type = {}
for atype, source_id, period, formats, purpose, titles in ARTEFACT_TYPES:
    if atype not in binding:
        continue
    r = rng("ev", atype)
    b = binding[atype]
    scen, pinned_days_left = FORCED_SCENARIO.get(atype, (pick(r, PERIODIC_WEIGHTS if period else VERSIONED_WEIGHTS), None))
    scenario_by_type[atype] = scen
    provides_class = SOURCE[source_id][3]

    def doc_meta(i):
        dr = rng("doc", atype, i)
        cls = atype
        if provides_class:
            x = dr.random()
            if x < 0.06:
                cls = None  # source system did not classify the record
            elif x < 0.09:
                others = [a[0] for a in ARTEFACT_TYPES if a[1] == source_id and a[0] != atype and a[0] in binding]
                cls = dr.choice(others) if others else atype  # mis-classified at source
        return dict(file_format=dr.choice(formats), document_class=cls if provides_class else None, title_variant=dr.choice(titles))

    if period is None:
        refresh = max(14, round(b * r.uniform(0.5, 0.8)))
        latest_age = {
            "current": max(1, round(b * r.uniform(0.05, 0.7))),
            "expiring": b - (pinned_days_left or r.randint(1, 13)),
            "expired": b + r.randint(5, 60),
            "unsigned": r.randint(5, 15),
            "missing": None,
        }[scen]
        versions = []
        if latest_age is not None:
            d = anchor - timedelta(days=latest_age)
            if scen == "unsigned":
                versions = [(d, "Draft")]
                if r.random() < 0.6:
                    versions.insert(0, (d - timedelta(days=r.randint(15, 40)), "Draft"))
            else:
                while d >= start:
                    versions.insert(0, (d, "Approved"))
                    d -= jitter(r, refresh)
        nxt = {
            "current": (versions[-1][0] + jitter(r, refresh)) if versions else anchor,
            "expiring": anchor - timedelta(days=latest_age or 0) + timedelta(days=b + r.randint(3, 20)),
            "expired": anchor + timedelta(days=r.randint(7, 45)),
            "unsigned": anchor + timedelta(days=r.randint(10, 40)),
            "missing": anchor + timedelta(days=r.randint(20, 90)),
        }[scen]
        nxt = max(nxt, anchor + timedelta(days=1))
        while nxt <= end:
            versions.append((nxt, "Approved"))
            nxt += jitter(r, refresh)
        meta = doc_meta(0)
        documents.append(dict(key=f"{atype}", atype=atype, source_id=source_id, title=meta["title_variant"],
                              file_format=meta["file_format"], document_class=meta["document_class"],
                              versions=versions, periodic=False, purpose=purpose))
    else:
        latest_age = {
            "current": r.randint(1, max(2, min(period, b) - 2)),
            "expiring": b - r.randint(1, min(13, b - 1)),
            "expired": b + r.randint(5, 60),
            "missing": None,
        }[scen]
        dates = []
        if latest_age is not None:
            d = anchor - timedelta(days=latest_age)
            while d >= start:
                dates.insert(0, d)
                d -= jitter(r, period, 0.9, 1.1)
        nxt = {
            "current": (dates[-1] + jitter(r, period, 0.9, 1.1)) if dates else anchor,
            "expiring": anchor - timedelta(days=latest_age or 0) + timedelta(days=b + r.randint(3, 15)),
            "expired": anchor + timedelta(days=r.randint(7, 40)),
            "missing": anchor + timedelta(days=r.randint(20, 90)),
        }[scen]
        nxt = max(nxt, anchor + timedelta(days=1))
        while nxt <= end:
            dates.append(nxt)
            nxt += jitter(r, period, 0.9, 1.1)
        for i, d in enumerate(dates):
            meta = doc_meta(i)
            documents.append(dict(key=f"{atype}|{d.isoformat()}", atype=atype, source_id=source_id,
                                  title=meta["title_variant"].replace("{period}", d.strftime("%b %Y")),
                                  file_format=meta["file_format"], document_class=meta["document_class"],
                                  versions=[(d, "Approved")], periodic=True, purpose=purpose))

# Non-evidence documents arriving through the unstructured connectors.
r = rng("noise")
d = start + timedelta(days=r.randint(2, 8))
while d <= end:
    title, purpose = r.choice(NOISE)
    documents.append(dict(key=f"noise|{d.isoformat()}", atype=None, source_id=r.choice(["SRC-DOC", "SRC-DOC", "SRC-MTG"]),
                          title=title, file_format=r.choice(["PDF", "DOCX", "PPTX"]), document_class=None,
                          versions=[(d, "Approved")], periodic=True, purpose=purpose))
    d += timedelta(days=r.randint(6, 14))

print(f"documents: {len(documents)}")
print({s: sum(1 for v in scenario_by_type.values() if v == s) for s in set(scenario_by_type.values())})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Connector runs, deliveries and outages

# COMMAND ----------

ERRORS = ["Connection timed out", "Authentication token expired", "Source API returned HTTP 503"]
failed = set()
n_days = (end - start).days + 1
for source_id, *_ in SOURCES:
    for i in range(n_days):
        d = start + timedelta(days=i)
        if rng("run", source_id, d).random() < 0.03:
            failed.add((source_id, d))
# Pinned: the document repository connector is offline for the last two days before the anchor.
failed |= {("SRC-DOC", anchor - timedelta(days=1)), ("SRC-DOC", anchor)}


def next_ok(source_id, d):
    while (source_id, d) in failed:
        d += timedelta(days=1)
    return d


documents.sort(key=lambda x: (x["versions"][0][0] if x["versions"] else end, x["key"]))
plan_rows, label_rows = [], []
ev_seq = 1000
for doc in documents:
    if not doc["versions"]:
        continue
    ev_seq += 1
    evidence_id = f"EV-{ev_seq}"
    doc["evidence_id"] = evidence_id
    src = SOURCE[doc["source_id"]]
    label_rows.append(dict(evidence_id=evidence_id, true_artefact_type=doc["atype"], is_noise=doc["atype"] is None,
                           source_document_class=doc["document_class"], label_source="synthetic generator ground truth"))
    r = rng("versions", doc["key"])
    generic_excerpt = doc["source_id"] == "SRC-DOC" and doc["atype"] is not None and r.random() < 0.25
    for n, (modified, approval) in enumerate(doc["versions"], start=1):
        collected_day = next_ok(doc["source_id"], modified + timedelta(days=r.randint(0, 2)))
        if modified <= anchor < collected_day and (doc["source_id"], anchor) not in failed:
            collected_day = anchor
        collected_at = datetime(collected_day.year, collected_day.month, collected_day.day, 2, r.randint(0, 59), r.randint(0, 59))
        modified_at = at(modified, r)
        if modified_at > collected_at:
            modified_at = collected_at - timedelta(hours=r.randint(1, 12))
        title = doc["title"]
        if doc["source_id"] in ("SRC-DOC", "SRC-MTG") and doc["atype"] is not None:
            if approval == "Draft":
                excerpt = f"{title} (DRAFT). {doc['purpose']} Version {n}, last revised {modified:%d %b %Y}. DRAFT - not yet endorsed; not for distribution."
            elif doc["periodic"]:
                excerpt = f"{title}. {doc['purpose']} Meeting held {modified:%d %b %Y}. Minutes confirmed by the chair."
            elif generic_excerpt:
                excerpt = f"{title}. Version {n}, prepared for the program steering committee on {modified:%d %b %Y}."
            else:
                excerpt = f"{title}. {doc['purpose']} Version {n}, last revised {modified:%d %b %Y}. Approved by the {approver.get(doc['atype'], 'Program office')} on {modified:%d %b %Y}."
        elif doc["atype"] is None:
            excerpt = f"{title}. {doc['purpose']}"
        else:
            excerpt = f"{title} exported from the {src[1]} on {collected_day:%d %b %Y}. {doc['purpose']} Records: {r.randint(12, 480)}."
        checksum = sha(f"{evidence_id}|{n}|{excerpt}")
        source_checksum = checksum if r.random() > 0.01 else sha(f"{evidence_id}|{n}|corrupted-in-transit")
        file_name = f"{slug(title)}{'' if doc['periodic'] else f'_v{n}'}.{doc['file_format'].lower()}"
        plan_rows.append(dict(
            record_id=f"{doc['source_id']}-{collected_day:%Y%m%d}-{sha(evidence_id + str(n))[:8]}",
            source_id=doc["source_id"], connector=src[2], evidence_id=evidence_id, artefact_version=n,
            title=title, file_name=file_name, file_format=doc["file_format"], document_class=doc["document_class"],
            approval_status=approval, signed=(approval == "Approved" and doc["source_id"] in ("SRC-DOC", "SRC-MTG") and doc["file_format"] == "PDF"),
            source_modified_at=modified_at, collected_at=collected_at, source_checksum=source_checksum,
            content_excerpt=excerpt, size_bytes=r.randint(20_000, 4_000_000),
            source_uri=f"synthetic://{doc['source_id'].lower()}/{evidence_id}/v{n}", collection_date=collected_day,
        ))

run_rows = []
counts = {}
for p in plan_rows:
    counts[(p["source_id"], p["collection_date"])] = counts.get((p["source_id"], p["collection_date"]), 0) + 1
for source_id, _, connector, *_ in SOURCES:
    for i in range(n_days):
        d = start + timedelta(days=i)
        rr = rng("runrow", source_id, d)
        is_failed = (source_id, d) in failed
        run_rows.append(dict(
            run_id=f"RUN-{source_id}-{d:%Y%m%d}", source_id=source_id, connector=connector, run_date=d,
            started_at=datetime(d.year, d.month, d.day, 2, 0, rr.randint(0, 59)),
            status="Failed" if is_failed else "Succeeded", records_collected=0 if is_failed else counts.get((source_id, d), 0),
            error_message=rr.choice(ERRORS) if is_failed else None,
        ))

# Synthetic human reviewers confirm or reject evidence the deterministic rules cannot map.
review_rows = []
by_id = {d_["evidence_id"]: d_ for d_ in documents if "evidence_id" in d_}
first_collected = {}
for p in plan_rows:
    first_collected[p["evidence_id"]] = min(first_collected.get(p["evidence_id"], p["collected_at"]), p["collected_at"])
for evidence_id, doc in by_id.items():
    if doc["document_class"] is not None:
        continue  # rule-mapped
    r = rng("review", evidence_id)
    if r.random() < 0.06:
        continue  # never reviewed: remains in the backlog
    reviewed_at = first_collected[evidence_id] + timedelta(days=r.randint(1, 10), hours=r.randint(6, 14))
    if doc["atype"] is None:
        decision, atype, comment = "reject", None, "Not compliance evidence"
    elif r.random() < 0.97:
        decision, atype, comment = "confirm", doc["atype"], "Confirmed against evidence requirement"
    else:
        others = [a[0] for a in ARTEFACT_TYPES if a[1] == doc["source_id"] and a[0] != doc["atype"] and a[0] in binding]
        decision, atype, comment = "confirm", (r.choice(others) if others else doc["atype"]), "Confirmed against evidence requirement"
    review_rows.append(dict(review_id=f"REV-{sha(evidence_id)[:10].upper()}", evidence_id=evidence_id, decision=decision,
                            artefact_type=atype, reviewer=r.choice(REVIEWERS), reviewed_at=reviewed_at,
                            comment=comment, channel="synthetic"))

print(f"deliveries={len(plan_rows)} runs={len(run_rows)} failed_runs={len(failed)} reviews={len(review_rows)} labels={len(label_rows)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write tables

# COMMAND ----------

def write(name: str, rows, ddl: str, comment: str, history: bool = False):
    df = spark.createDataFrame(rows, ddl)
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn(name))
    spark.sql(f"COMMENT ON TABLE {fqn(name)} IS '{comment}'")
    if history:
        spark.sql(f"""ALTER TABLE {fqn(name)} SET TBLPROPERTIES (
            'delta.enableChangeDataFeed' = 'true',
            'delta.logRetentionDuration' = 'interval {retention_days} days',
            'delta.deletedFileRetentionDuration' = 'interval {retention_days} days')""")
    print(f"{name}: {df.count()} rows")


write("review_gates", [dict(gate_id=g[0], gate_label=g[1], gate_name=g[2], gate_order=g[3], purpose=g[4]) for g in GATES],
      "gate_id STRING, gate_label STRING, gate_name STRING, gate_order INT, purpose STRING",
      "Gateway review gates (synthetic, modelled on the Gateway Reviews Process).")
write("source_systems", [dict(source_id=s[0], source_name=s[1], connector=s[2], provides_document_class=s[3], evidence_form=s[4]) for s in SOURCES],
      "source_id STRING, source_name STRING, connector STRING, provides_document_class BOOLEAN, evidence_form STRING",
      "Evidence source systems and connectors (synthetic).")
write("artefact_types", [dict(artefact_type=a[0], source_id=a[1], cadence="periodic" if a[2] else "versioned", period_days=a[2],
                              formats=a[3], purpose=a[4]) for a in ARTEFACT_TYPES if a[0] in binding],
      "artefact_type STRING, source_id STRING, cadence STRING, period_days INT, formats ARRAY<STRING>, purpose STRING",
      "Catalogue of evidence artefact types. Mapping classifies each collected document into one of these.")
write("obligation_register", register_rows,
      """obligation_id STRING, version INT, title STRING, description STRING, gate_id STRING, owner_role STRING,
         framework STRING, framework_url STRING, approval_state STRING, effective_from DATE, effective_to DATE,
         retired_on DATE, proposed_at TIMESTAMP, approved_at TIMESTAMP, approved_by STRING, change_reason STRING,
         requirement_count INT""",
      "Versioned obligation register (SCD2). A version is in force when approved and effective_from <= d < effective_to.", history=True)
write("obligation_requirements", requirement_rows,
      """obligation_id STRING, version INT, requirement_id STRING, artefact_type STRING, requirement_description STRING,
         expected_source_id STRING, max_age_days INT, mandatory BOOLEAN""",
      "Evidence requirements per obligation version, with freshness thresholds.", history=True)
write("evidence_labels", label_rows,
      "evidence_id STRING, true_artefact_type STRING, is_noise BOOLEAN, source_document_class STRING, label_source STRING",
      "Labelled evaluation set: true artefact type per evidence item. Evaluation only - never read by mapping.")
write("synthetic_evidence_plan", plan_rows,
      """record_id STRING, source_id STRING, connector STRING, evidence_id STRING, artefact_version INT, title STRING,
         file_name STRING, file_format STRING, document_class STRING, approval_status STRING, signed BOOLEAN,
         source_modified_at TIMESTAMP, collected_at TIMESTAMP, source_checksum STRING, content_excerpt STRING,
         size_bytes BIGINT, source_uri STRING, collection_date DATE""",
      "Synthetic connector deliveries (past and future). Landed into the volume day by day by 02_collect_evidence.")
write("synthetic_collection_runs_plan", run_rows,
      """run_id STRING, source_id STRING, connector STRING, run_date DATE, started_at TIMESTAMP, status STRING,
         records_collected INT, error_message STRING""",
      "Synthetic nightly connector runs including outages.")
write("synthetic_review_plan", review_rows,
      """review_id STRING, evidence_id STRING, decision STRING, artefact_type STRING, reviewer STRING,
         reviewed_at TIMESTAMP, comment STRING, channel STRING""",
      "Synthetic human mapping reviews, landed into mapping_reviews when due.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register events into the audit trail

# COMMAND ----------

reg = spark.table(fqn("obligation_register"))
activated = audit_events_df(
    reg.filter(F.col("approval_state") == "Approved").filter(F.col("effective_from") <= F.lit(anchor)),
    event_type="register.version_activated", entity_type="obligation", entity_id=F.col("obligation_id"),
    related_id=F.concat(F.lit("v"), F.col("version")),
    summary=F.format_string("%s v%d became effective after approval by the %s", "obligation_id", "version", "approved_by"),
    actor=F.lit("register.service"), occurred_at=F.col("effective_from").cast("timestamp"),
    payload=F.to_json(F.struct("title", "change_reason", "requirement_count", "approved_at")),
    dedup_key=F.format_string("register.version_activated|%s|%d", "obligation_id", "version"),
)
proposed = audit_events_df(
    reg.filter("approval_state = 'Draft'"),
    event_type="register.revision_proposed", entity_type="obligation", entity_id=F.col("obligation_id"),
    related_id=F.concat(F.lit("v"), F.col("version")),
    summary=F.format_string("%s v%d proposed: awaiting approval", "obligation_id", "version"),
    actor=F.col("owner_role"), occurred_at=F.col("proposed_at"),
    payload=F.to_json(F.struct("change_reason")),
    dedup_key=F.format_string("register.revision_proposed|%s|%d", "obligation_id", "version"),
)
retired = audit_events_df(
    reg.filter(F.col("retired_on") <= F.lit(anchor)).dropDuplicates(["obligation_id"]),
    event_type="register.obligation_retired", entity_type="obligation", entity_id=F.col("obligation_id"),
    summary=F.format_string("%s retired from the register", "obligation_id"),
    actor=F.lit("register.service"), occurred_at=F.col("retired_on").cast("timestamp"),
    dedup_key=F.format_string("register.obligation_retired|%s", "obligation_id"),
)
print(f"audit events appended: {append_audit_events(activated.unionByName(proposed).unionByName(retired))}")

spark.createDataFrame(
    [dict(anchor_date=anchor, seed=seed, history_days=history_days, future_days=future_days,
          generated_at=datetime.now(timezone.utc).replace(tzinfo=None))],
    "anchor_date DATE, seed INT, history_days INT, future_days INT, generated_at TIMESTAMP",
).write.mode("append").saveAsTable(fqn("synthetic_generation_runs"))

# COMMAND ----------

display(spark.sql(f"""
  SELECT r.gate_id, count(DISTINCT r.obligation_id) AS obligations, count(*) AS versions,
         sum(CASE WHEN approval_state = 'Draft' THEN 1 ELSE 0 END) AS drafts
  FROM {fqn('obligation_register')} r GROUP BY r.gate_id ORDER BY r.gate_id"""))
