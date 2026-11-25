# Use Case Catalogue

One selected use case per capability domain, across twelve domains grouped into three pillars:
reinventing public services, optimising operations, and strengthening security. Each domain had
several candidate functions; we selected the single highest-impact function and anchored it to a
publicly citable customer reference or published Databricks material.

Every source cited in this repository is public and linked. Where a selection has no public
reference behind it, the entry says so plainly rather than implying evidence that is not there.

## On the Nation Building Authority

The NBA is a fictional Australian Federal Government department whose remit is deliberately
unbounded — it is whatever the government of the day needs solved. This matters for the catalogue:
**use cases are not re-themed to fit a departmental persona.** Patient & Provider 360 is a pure
health insights play, not a workforce-health variant. Keeping each use case true to its own domain
makes it directly comparable to the real customer work it is modelled on, and reusable by anyone
working in that domain.

Coherence comes from the repository's structure — shared scaffold, shared conventions, one
self-contained folder per use case — rather than from a shared subject matter.

## Selection criteria

Functions were ranked within each category on:

1. **Reference fidelity** — is there a live, publicly citable customer, ideally in ANZ?
2. **Published outcome** — is there a real number behind it, not just a capability claim?
3. **Breadth of platform surface** — does it exercise ingest, governance, AI, and serving rather
   than one narrow feature?
4. **Reuse** — does the pattern serve other use cases in the repository?

## The catalogue

| # | Category | Selected function | Folder | Headline KPI |
| --- | --- | --- | --- | --- |
| 1 | Benefit Administration | AI-Enabled Eligibility Determination | `ai_enabled_eligibility_determination` | Record processing time |
| 2 | Health Insights | Patient & Provider 360 | `patient_and_provider_360` | Patient engagement and retention |
| 3 | Fraud Prevention | Fraud Detection (improper payments) | `improper_payments_detection` | Improper payments identified |
| 4 | Back Office Automation | Intelligent Document Processing | `intelligent_document_processing` | Document processing cost |
| 5 | Cybersecurity | Augment SIEM | `siem_augmentation` | SIEM retention and licensing cost |
| 6 | Physical Security | Geospatial Analysis | `geospatial_analysis` | Time to spatial insight |
| 7 | Personalized Engagement | Citizen & Constituent 360 | `constituent_360` | Time per constituent interaction |
| 8 | Smart Infrastructure | Critical Infrastructure Monitoring | `critical_infrastructure_monitoring` | Time from signal to decision |
| 9 | Open Data Sharing | Secure cross-agency sharing | `cross_agency_data_sharing` | Time to deliver cross-agency insight |
| 10 | Resource Allocation | Budget Planning & Financial Projections | `budget_planning_and_projections` | Planning cycle productivity |
| 11 | Autonomous Systems | IoT Sensor Data Management | `iot_sensor_data_management` | Time to insight from sensor data |
| 12 | Regulatory Compliance | Automated Compliance Reporting | `automated_compliance_reporting` | Review accuracy and coverage |

The KPI column names the measure each use case is built to move — not a result reproduced here. A
**figure** appears only where a public Databricks source supports that specific measure. No row
currently has one: published outcomes behind a selection (for example AusNet's platform savings
behind Critical Infrastructure Monitoring) are cited in the entry itself, not presented as the KPI
the use case is built to move.

## Build priority

| Priority | Use case | Why |
| --- | --- | --- |
| 1 | `critical_infrastructure_monitoring` | Anchored to published references in every sector it covers, three of them ANZ. Exercises the widest platform surface: multi-feed streaming ingest, medallion pipeline, explainable risk scoring, cross-sector dependency analysis, alerting, an operational app, AI/BI and Genie. |
| 2 | `intelligent_document_processing` | Broadest reuse across the other 11, and the most current product story (`ai_parse_document`, Agent Bricks IDP). |
| 3 | `improper_payments_detection` | Shares the entity resolution core with the two 360 use cases, so builds on work already done. |

---

## 1. Benefit Administration — AI-Enabled Eligibility Determination

**Folder:** `usecase/ai_enabled_eligibility_determination`

**Why this function.** Of the four candidates — eligibility determination, program performance
analysis, case management automation, demand forecasting — eligibility determination is where the
processing-time improvement actually originates, and it is the decision point that
determines citizen outcomes. The other three are reporting or scheduling layers around it.

**Anchor.** Databricks' [Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector)
page names "Citizen 360 and AI-enabled eligibility" as a core health and human services use case.
[Reinventing Government with the Databricks Data + AI Platform](https://www.databricks.com/blog/reinventing-government-databricks-data-intelligence-platform)
(31 October 2025) sets out the surrounding architecture: Unity Catalog governance, AI/BI for
self-service, and agency-specific AI agents.

**Scope.** Ingest applications and supporting evidence; assemble an applicant view; apply
rules-based eligibility criteria; use an agent to triage and explain borderline cases against
policy; route to a human for determination. The decision stays with the human — under the
[DTA's AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework)
an automated eligibility decision affecting an individual needs assurance and a transparency
statement, so the design target is decision support with a full audit trail, not automation of the
determination itself.

**Functions.** Application intake · applicant 360 assembly · deterministic rules engine · agentic
triage and policy citation · caseworker queue prioritisation · decision audit trail.

## 2. Health Insights — Patient & Provider 360

**Folder:** `usecase/patient_and_provider_360`

**Why this function.** Selected over Health Intervention Analysis and Intervention Efficacy, which
have strong methodology material but no published government outcome, and which overlap heavily
with Program Performance Analysis under Benefit Administration. Public Health Surveillance was
considered and rejected as narrower. Patient & Provider 360 also earns its place structurally: the
ingest → standardise → resolve identity → govern → activate spine is reused by Constituent 360 and
supplies the entity resolution core of improper payments detection.

**Anchor.** The [Healthcare Patient Personalization Reference Architecture](https://www.databricks.com/resources/architectures/healthcare-patient-personalization-reference-architecture)
describes the 360-degree patient view and provider matching pattern.
[Unlocking FHIR for Data and AI in a Meaningful Way](https://www.databricks.com/blog/unlocking-fhir-data-and-ai-meaningful-way)
(25 October 2024) covers standardisation via the open-source `dbignite` project;
[Building a FHIR-native health data platform on Databricks Lakebase](https://www.databricks.com/blog/building-fhir-native-health-data-platform-databricks-lakebase)
(27 May 2026) adds terminology normalisation and patient deduplication at ingestion. The
[Social Determinants of Health accelerator](https://community.databricks.com/t5/community-articles/solution-accelerator-series-social-determinants-of-health/m-p/163604)
covers enrichment. Patient 360 is named as a healthcare use case in the
[federal government solution sheet](https://www.databricks.com/sites/default/files/2024-03/federal-government-solution-sheet-2.pdf).
Databricks' [health and human services solutions](https://www.databricks.com/solutions/industries/nhs)
page covers the broader public health data platform pattern.

**Scope.** Ingest clinical, claims, provider directory and engagement data; standardise toward
FHIR; resolve patient and provider identity into longitudinal profiles; enrich with social
determinants; govern with Unity Catalog row and column controls; activate through next-best-action
and provider matching.

**Functions.** Multi-source ingest · FHIR standardisation · patient and provider identity
resolution · SDoH enrichment · longitudinal profile serving · next-best-action · attribute-based
access control over sensitive health attributes.

## 3. Fraud Prevention — Fraud Detection (improper payments)

**Folder:** `usecase/improper_payments_detection`

**Why this function.** Improper payments detection is where the published public sector numbers
sit, and avoided fraud and waste is the measure the domain is judged on. Smart claims triage is a
subset of it; procurement and acquisition analytics are narrower.

**Anchor.** Databricks' [A smarter state: AI outlook in the public sector](https://www.databricks.com/sites/default/files/2025-02/public-sector-report-jan-30.pdf)
reports the US Department of Defense processing more than 10 million records and identifying over
US$12.7 billion in true improper payments since 2020. The
[Entity Resolution for Public Sector accelerator](https://community.databricks.com/t5/announcements/solution-accelerator-series-entity-resolution-for-public-sector/m-p/169611/highlight/true)
and the [Smart Claims accelerator](https://www.databricks.com/solutions/accelerators/smart-claims-for-insurance)
provide the reference implementations.

**Scope.** Ingest payments, claims, and counterparty registries; resolve entities across sources
to expose duplicates and undisclosed relationships; build a relationship graph; score payments for
improper-payment risk; triage to investigators with explanations.

**Functions.** Payment and claim ingest · probabilistic entity resolution · relationship graph
construction · anomaly and risk scoring · investigator triage queue · feedback loop from
investigation outcomes.

## 4. Back Office Automation — Intelligent Document Processing

**Folder:** `usecase/intelligent_document_processing`

**Why this function.** The highest-reuse selection in the catalogue: eligibility determination,
compliance reporting, and procurement analysis all need documents turned into structured data.
It also has the most current product story. Workforce analytics and agentic content summary are
downstream of it.

**Anchor.** [PDFs to Production: announcing state-of-the-art document intelligence on Databricks](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks)
(11 November 2025) introduces `ai_parse_document`, which parses PDFs directly in SQL, emits layout,
tables, bounding boxes and figure captions into Unity Catalog, and is reported to deliver
competitive quality at 3–5x lower cost than competing offerings. The
[Intelligent document processing guide](https://docs.databricks.com/aws/en/agents/agent-bricks/intelligent-document-processing)
sets out the bronze-layer pattern; [Information Extraction](https://docs.databricks.com/aws/en/agents/agent-bricks/info-extraction)
covers the Agent Bricks extraction agent.

**Scope.** Land documents in a UC volume; parse to a standardised structured bronze layer; classify
by document type; extract typed fields against a schema; validate and flag low-confidence
extractions for human review; serve structured output and make the corpus queryable.

**Functions.** Volume landing and change detection · `ai_parse_document` bronze layer · document
classification · schema-driven field extraction · confidence scoring and human-in-the-loop review ·
structured publication · corpus Q&A.

## 5. Cybersecurity — Augment SIEM

**Folder:** `usecase/siem_augmentation`

**Why this function.** SIEM cost is driven by ingest volume and retention, which is exactly what
SIEM augmentation addresses — moving high-volume retention and hunting onto the lakehouse while
leaving detection and response in the SIEM. Threat hunting and user behaviour analysis are
capabilities built on top of that foundation.

**Anchor.** None public. This is the weakest-anchored selection in the catalogue: we have no
published public sector customer outcome to cite for it, and the use case README states that
plainly. The architecture itself is well established — long-retention log storage in Delta, Unity
Catalog governance over security telemetry, and detection logic as version-controlled code — but
the pattern is the evidence here, not a customer result. Worth strengthening if a citable
reference becomes available.

**Scope.** Ingest high-volume security telemetry; retain cheaply at full fidelity; run scheduled
and ad hoc hunting queries over a retention window the SIEM cannot afford; surface detections back
to the SIEM.

**Functions.** Telemetry ingest · long-retention storage · detection-as-code · hunting queries ·
entity risk scoring · detection forwarding.

## 6. Physical Security — Geospatial Analysis

**Folder:** `usecase/geospatial_analysis`

**Why this function.** Geospatial analysis is the shared foundation beneath the rest of the domain:
law enforcement analytics, trafficking targeting and weather prediction all sit on top of indexed
spatial data, proximity analysis and containment testing.

**Anchor.** None public. Like SIEM augmentation, this selection rests on the pattern rather than on
a published customer outcome. The pattern is well supported by the platform — Databricks SQL spatial
functions and H3 indexing — and genuinely public Australian boundary data (ABS statistical areas)
is available to make the analysis realistic.

**Scope.** Ingest and index spatial datasets; run proximity, containment and routing analysis at
scale; publish spatial aggregates for mapping; support ad hoc spatial questions.

**Functions.** Spatial ingest · spatial indexing · proximity and containment analysis · spatial
aggregation · map-ready serving.

## 7. Personalized Engagement — Citizen & Constituent 360

**Folder:** `usecase/constituent_360`

**Why this function.** The foundation the rest of the category depends on — an AI call centre,
chatbot, or accessibility improvement without a resolved constituent view is just a generic
assistant. Shares its spine with Patient & Provider 360.

**Anchor.** [GovTech Singapore](https://www.databricks.com/customers/govtech), unifying government
data to improve nationwide services, is the publicly citable reference.

**Scope.** Unify interaction history across channels and agencies; resolve constituent identity;
derive engagement and sentiment signals; serve a consented 360 view to service staff and
assistants.

**Functions.** Cross-channel interaction ingest · identity resolution · sentiment and intent
derivation · consent and purpose-of-use enforcement · 360 view serving.

## 8. Smart Infrastructure — Critical Infrastructure Monitoring

**Folder:** `usecase/critical_infrastructure_monitoring`

**Why this function — and why it is the flagship.** Critical infrastructure is run by many
operators across many sectors, and the failures that hurt most cross between them: a heatwave that
loads the grid, heats rail and draws down reservoirs at once, or a substation fault that takes out
the signalling and pumping it powers. Each operator monitors its own assets; nobody sees the
operating picture across them. A national, cross-sector **Infrastructure Operations Centre** is
the function that closes that gap, and it exercises the full platform surface end to end, which
makes it the best first build.

**Anchors.** Every sector modelled has a published Databricks reference:

* **Energy** — [AusNet Services](https://www.databricks.com/customers/ausnet-services), an
  Australian electricity and gas network, assesses the condition, criticality and risk of its
  assets to predict failures and schedule maintenance, starting with three asset classes and
  extending across its fleet. Published outcomes: **50% cost savings on the data platform**, **3×
  faster data processing** and a **20–30% reduction in platform operational overhead**.
* **Water** — [Sydney Water](https://www.databricks.com/blog/social-impact-using-data-and-ai-revealing-2024-finalists-data-good-award)
  (2024 Data for Good finalist) manages 22,600 km of pipes and 247 reservoirs, and uses Databricks
  for AI pipe-inspection to cut maintenance backlogs and for real-time water-quality monitoring.
  No outcome figures are published.
* **Rail** — [Dutch Railways (NS)](https://www.databricks.com/customers/dutch-railways) runs real-time
  operational intelligence and predictive maintenance on train telemetry, flagging risks such as
  ice on overhead lines. Published outcomes: **100B+ telemetry points processed daily** across about
  420 trains and a **70% reduction in analytical compute costs**. International; no ANZ rail
  reference is public.
* **Roads and transport telemetry** — the
  [National Heavy Vehicle Regulator](https://www.databricks.com/customers/national-heavy-vehicle-regulator)
  shows real-time telemetry, alerting and targetable risk engines at national ANZ scale (4.5 million
  monthly sightings, a 4% uplift in high-risk fatigue infringements). The use case borrows the
  pattern, not the heavy-vehicle domain.

**Learnings to carry across.** From the anchors: the value is in *asset risk that drives
maintenance and intervention* (AusNet, NS), it starts with a few asset classes and extends (AusNet),
real-time and analytical workloads belong on one platform (NS), and a risk score only matters once
it resolves to a specific asset and a specific action (NHVR). The repository models all four:
per-asset likelihood × consequence scoring with a recommended first action, fourteen asset classes
on one platform, streaming ingest feeding the same governed tables the analysts query, and every
incident resolved to an asset, an operator and a decision.

**Scope.** Ingest operator telemetry and weather warnings; conform and quarantine readings; model
cross-sector supply dependencies; score every asset for likelihood of failure and consequence,
including downstream cascades; raise incidents with a recommended action; serve an operations app
with a network map, human-in-the-loop decisions and an audit trail; dashboards and natural-language
analysis over the same gold tables.

**Functions.** Multi-feed streaming ingest · telemetry conformance and quarantine · dependency
graph · hazard exposure · risk engine · incident queue and network map · decision audit ·
dashboard · Genie space.

## 9. Open Data Sharing — Secure cross-agency sharing

**Folder:** `usecase/cross_agency_data_sharing`

**Why this function.** The category is structured by sharing relationship — intra-agency,
industry/government, state/federal, agency/constituent — rather than by function, so the use case
is the governed sharing capability itself, demonstrated across those relationships.

**Anchor.** [Best Practices for Government Data Sharing](https://www.databricks.com/blog/2023/02/21/best-practices-cross-government-data-sharing.html).
The key architectural move is that Clean Rooms shift the approval point from data outputs to
approved code and permitted use cases, so an agency can collaborate without exposing its underlying
protected data. Delta Sharing avoids maintaining a separate copy per recipient.

**Scope.** Publish governed shares from a provider catalog; mount a share as a consumer; run a
Clean Room collaboration where neither party sees the other's raw data; audit every access.

**Functions.** Share definition and governance · recipient management · consumer mount · Clean Room
collaboration · access audit · lineage across the sharing boundary.

## 10. Resource Allocation — Budget Planning & Financial Projections

**Folder:** `usecase/budget_planning_and_projections`

**Why this function.** Budget planning and financial projections are the decision-making core of
the category; revenue optimisation is less applicable to a department, and performance reporting
is a presentation layer over the same data.

**Anchor.** Infrastructure Australia's [2025 Infrastructure Market Capacity Report](https://www.infrastructureaustralia.gov.au/reports/2025-infrastructure-market-capacity-report)
establishes the Major Public Infrastructure Pipeline as the central dataset for sector planning and
market capacity analysis. The [Australian Government Grants Framework](https://www.finance.gov.au/government/commonwealth-grants/australian-government-grants-framework)
defines the funding administration obligations around it.

**Scope.** Model a project and program portfolio with cost, schedule and benefit profiles; forecast
expenditure; test allocation scenarios against capacity constraints; report projections and
variance.

**Functions.** Portfolio and pipeline modelling · expenditure forecasting · scenario comparison ·
capacity constraint analysis · variance reporting.

## 11. Autonomous Systems — IoT Sensor Data Management

**Folder:** `usecase/iot_sensor_data_management`

**Why this function.** The foundational layer of the category — threat detection and classification,
decision support, and mission planning all require managed sensor data first. The defence-specific
candidates were set aside as less broadly applicable.

**Anchor.** The telemetry ingest pattern proven at
[NHVR](https://www.databricks.com/customers/national-heavy-vehicle-regulator) scale (4.5 million
monthly vehicle sightings with sub-second serving), applied to a general sensor estate rather than
to vehicles specifically.

**Scope.** Register a sensor estate; ingest high-frequency readings; handle late and out-of-order
data; detect sensor health problems; serve aggregates at multiple time grains.

**Functions.** Sensor registry · high-frequency streaming ingest · late and out-of-order handling ·
sensor health monitoring · multi-grain aggregate serving.

## 12. Regulatory Compliance — Automated Compliance Reporting

**Folder:** `usecase/automated_compliance_reporting`

**Why this function.** Reporting and review accuracy is the measure that matters in this domain,
and automated compliance reporting is what moves it. Auditing is the assurance layer over the top;
investment risk and supply chain analysis are narrower.

**Anchor.** The Australian Government's [Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process)
defines the assurance regime, with delivery confidence assessments and recommendations to the
Senior Responsible Official. The [DTA AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework)
and [AI transparency statement](https://www.dta.gov.au/ai-transparency-statement) requirements
apply to any AI used in the process, and the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework)
governs handling of the underlying information.

**Scope.** Collect obligation evidence from source systems; map evidence to obligations; generate
reports on a schedule; detect gaps and expiring evidence; keep an immutable audit trail.

**Functions.** Obligation register · evidence collection · evidence-to-obligation mapping ·
scheduled report generation · gap and expiry detection · immutable audit trail.

---

## Sources

Every source below is public. This repository cites nothing internal, and no customer is named
unless a published Databricks page names them.

**Published Databricks customer stories and material.**
[National Heavy Vehicle Regulator](https://www.databricks.com/customers/national-heavy-vehicle-regulator) ·
[AusNet Services](https://www.databricks.com/customers/ausnet-services) ·
[Dutch Railways](https://www.databricks.com/customers/dutch-railways) ·
[2024 Data for Good finalists (Sydney Water)](https://www.databricks.com/blog/social-impact-using-data-and-ai-revealing-2024-finalists-data-good-award) ·
[GovTech Singapore](https://www.databricks.com/customers/govtech) ·
[Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector) ·
[A smarter state: AI outlook in the public sector](https://www.databricks.com/sites/default/files/2025-02/public-sector-report-jan-30.pdf) ·
[Federal government solution sheet](https://www.databricks.com/sites/default/files/2024-03/federal-government-solution-sheet-2.pdf) ·
[Reinventing Government with the Databricks Data + AI Platform](https://www.databricks.com/blog/reinventing-government-databricks-data-intelligence-platform) ·
[Best Practices for Government Data Sharing](https://www.databricks.com/blog/2023/02/21/best-practices-cross-government-data-sharing.html) ·
[PDFs to Production](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks) ·
[Unlocking FHIR for Data and AI](https://www.databricks.com/blog/unlocking-fhir-data-and-ai-meaningful-way) ·
[FHIR-native health data platform on Lakebase](https://www.databricks.com/blog/building-fhir-native-health-data-platform-databricks-lakebase) ·
[Healthcare Patient Personalization Reference Architecture](https://www.databricks.com/resources/architectures/healthcare-patient-personalization-reference-architecture) ·
[Entity Resolution for Public Sector accelerator](https://community.databricks.com/t5/announcements/solution-accelerator-series-entity-resolution-for-public-sector/m-p/169611/highlight/true) ·
[Social Determinants of Health accelerator](https://community.databricks.com/t5/community-articles/solution-accelerator-series-social-determinants-of-health/m-p/163604) ·
[Intelligent document processing](https://docs.databricks.com/aws/en/agents/agent-bricks/intelligent-document-processing)

**Australian Government policy.**
[Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process) ·
[Australian Government Grants Framework](https://www.finance.gov.au/government/commonwealth-grants/australian-government-grants-framework) ·
[DTA AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework) ·
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework) ·
[2025 Infrastructure Market Capacity Report](https://www.infrastructureaustralia.gov.au/reports/2025-infrastructure-market-capacity-report)
