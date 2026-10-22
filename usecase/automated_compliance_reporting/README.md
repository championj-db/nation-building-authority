# Automated Compliance Reporting

| | |
| --- | --- |
| **Category** | Regulatory Compliance |
| **Selected function** | Automated Compliance Reporting |
| **Evidence anchor** | [Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process) |
| **Target KPI** | Review accuracy and evidence coverage |
| **Status** | **Implemented** - synthetic data, Lakeflow Jobs, AI mapping, reports, alerts, and a hybrid AppKit application using DBSQL analytics with Lakebase state. |

## Problem

Compliance reporting is assembled by hand, every cycle, from evidence scattered across systems and
mailboxes. The work is repetitive but not trivial: each obligation needs the right evidence, current
and complete. Most of the effort goes into finding and collating evidence rather than assessing
compliance, and gaps surface at the reporting deadline instead of when they open.

## What this use case demonstrates

Treating compliance as a data product: an obligation register, automated evidence collection,
explicit evidence-to-obligation mapping, scheduled report generation, and gap detection that fires
when evidence expires rather than when the report is due.

## Modelled on

The Australian Government's
[Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process),
which structures assurance around review gates, delivery confidence assessments, and
recommendations to the Senior Responsible Official. The
[DTA Assurance Framework](https://www.dta.gov.au/updates/updated-assurance-framework-strengthen-digital-investment-delivery)
covers digital investment assurance specifically.

Where AI is used in the reporting path, the
[DTA AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework)
and [AI transparency statement](https://www.dta.gov.au/ai-transparency-statement) obligations apply,
and the [Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework)
governs the underlying information.

A note on measuring review accuracy: it is only meaningful against a known answer. An
implementation should therefore include a labelled evaluation set, or report no accuracy figure at
all rather than an unverifiable one.

## Scope

**In scope**

* An obligation register as a governed, versioned table
* Automated evidence collection from source systems
* Explicit evidence-to-obligation mapping, with coverage reporting
* Scheduled report generation
* Gap and expiry detection with alerting
* An immutable audit trail

**Out of scope**

* Any real compliance, audit, or assurance data. Wholly synthetic.
* Legal or regulatory interpretation. The register models obligations; it does not interpret them.
* Submitting a report to any real regulator or oversight body.

## Functions

| Function | Description |
| --- | --- |
| Obligation register | Versioned register of obligations, owners, and evidence requirements |
| Evidence collection | Automated collection of evidence artefacts from source systems |
| Evidence mapping | Map evidence to obligations and report coverage |
| Report generation | Generate compliance reports on a schedule |
| Gap and expiry detection | Alert when evidence is missing, stale, or expiring |
| Audit trail | Immutable record of what was reported, from which evidence, when |

## Architecture

```
source systems -> evidence bronze -> obligation register (versioned)
               -> evidence-to-obligation mapping -> coverage gold
               -> scheduled reports + gap alerts
               -> immutable audit trail
```

Lakeflow for collection and transformation, Unity Catalog for governance, lineage and audit, Delta
time travel for the immutable trail, AI/BI for reporting, serverless throughout. Document-based
evidence reuses the parsed bronze layer from `intelligent_document_processing`.

## Data

Wholly synthetic and seeded (`synthetic_seed`). `src/01_generate_synthetic_data.py` builds a
timeline anchored on the run date: 540 days of history and 365 days of future connector deliveries.
The daily job lands each day's deliveries as they fall due, so evidence keeps arriving, expiring,
and gaps open and close over time. A few scenarios are pinned so the stories in
`design/compliance-reporting-wireframe.html` always appear (risk treatment register about to expire,
benefits baseline with only an unsigned draft, document repository connector offline).

| Synthetic input | Content |
| --- | --- |
| Obligation register | 35 obligations over Gateway gates 0-5 (Gateway, DTA Assurance, DTA AI assurance, AI transparency, PSPF), 82 SCD2 versions incl. 3 pending drafts and 1 retirement |
| Evidence requirements | 101 requirement rows over 47 artefact types with freshness thresholds |
| Source systems | 7 connectors (documents, meetings, risk, finance, portfolio, security, HR) with nightly runs and outages |
| Evidence | ~340 documents / ~650 versions, including noise documents, unsigned drafts, source mis-classifications and checksum mismatches |
| Labelled evaluation set | `evidence_labels`: true artefact type for every document (never read by mapping) |

## Pipeline

| Step | Notebook | Output |
| --- | --- | --- |
| Setup | `00_setup` | Schema, volume, append-only tables (`delta.appendOnly`, CDF, long retention) |
| Synthetic data | `01_generate_synthetic_data` | Reference data, versioned register, delivery / run / review plans, labels |
| Evidence collection | `02_collect_evidence` | Connector deliveries land as JSON in the volume; Auto Loader into `evidence_bronze`; versioned `evidence_artefacts` (valid_from/valid_to, integrity check) and `evidence_documents` |
| Evidence mapping | `03_map_evidence` | Rule mapping, `ai_query` suggestions, human reviews, `evidence_mappings`, `evidence_obligation_map`, accuracy in `mapping_evaluation` |
| Coverage and gaps | `04_coverage_and_gaps` | Gold tables for the app, `gap_alerts` lifecycle, `coverage_history` replayed point-in-time |
| Report generation | `05_generate_report` | `compliance_reports`, `report_findings`, `evidence_snapshots`, output package in the volume, reproduction check |
| Audit verification | `06_verify_audit_chain` | Hash-chain, append-only and table-history checks in `audit_chain_verifications` |

`_common` holds the shared point-in-time coverage logic, so the daily gold build and report
generation apply exactly the same rules.

Jobs (`resources/compliance_jobs.job.yml`, serverless): `compliance_bootstrap` (run once),
`compliance_daily` (scheduled), `compliance_report` (monthly, or on demand with `report_type`,
`gate_id`, `as_of_date`, `reproduce_report_id`). SQL alerts (`resources/compliance_alerts.alert.yml`)
notify on new high-severity gaps, evidence expiring within 7 days, and a failed chain verification.

## AI in the reporting path

| Use | How | Guardrail |
| --- | --- | --- |
| Evidence classification | `ai_query` with structured output; candidates limited to the source's artefact types; `NONE` allowed | Suggestions are shown as *Needs review* and never count as coverage until a person confirms |
| Report executive summary | `ai_query`, temperature 0, facts only, no ratings or recommendations | Marked `summary_ai_generated`, model and prompt version stored, excluded from the findings digest |

Mapping precedence is human review, then deterministic rule, then AI suggestion. This follows the
DTA AI assurance framework and AI transparency statement linked above: AI makes recommendations and
people make decisions.

### Review accuracy

Accuracy is measured only against the labelled evaluation set. Last run (seed 42):

| Method | Labelled items | Accuracy |
| --- | --- | --- |
| Rule (source document class) | 108 | 97.2% (seeded source mis-classifications) |
| AI suggestion | 106 | 100% |
| Human review (synthetic) | 102 | 99.0% (seeded reviewer error) |
| Resolved mapping | 210 | 98.1% |

The synthetic titles and excerpts are cleaner than real documents, so the AI figure is optimistic.
Re-measure on real labelled evidence before relying on it.

## Application data contract

Tables in `${catalog}.${schema}` that map to the screens in `design/`:

| Screen | Read | Write (app, on behalf of the user) |
| --- | --- | --- |
| Overview | `compliance_overview`, `obligation_coverage`, `gate_coverage`, `needs_attention` | - |
| Obligations | `obligation_register_current`, `obligation_register` (history), `obligation_requirements`, `requirement_coverage` | - |
| Evidence | `evidence_inbox`, `evidence_obligation_map`, `evidence_artefacts`, `source_health` | `mapping_reviews` (append: confirm or reject) |
| Reports | `compliance_reports`, `report_findings`, `evidence_snapshots`, status = latest `report_status_events`, `report_reproductions`; files under `/Volumes/<catalog>/<schema>/<volume>/reports/<report_id>/` | `report_status_events` (append); run the `compliance_report` job for Generate / Reproduce |
| Audit trail | `audit_events`, `audit_chain_verifications` | Run `06_verify_audit_chain` (Verify chain) |

App decisions land in append-only tables. The next pipeline run turns them into hash-chained
audit events.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG> --var warehouse_id=<YOUR_WAREHOUSE_ID>
databricks bundle deploy --target dev --var catalog=<YOUR_CATALOG> --var warehouse_id=<YOUR_WAREHOUSE_ID>
databricks bundle run compliance_bootstrap --target dev --var catalog=<YOUR_CATALOG> --var warehouse_id=<YOUR_WAREHOUSE_ID>
```

Replace `<YOUR_CATALOG>` and `<YOUR_WAREHOUSE_ID>` (angle brackets included) with a catalog you can
write to and a SQL warehouse ID, or put both in `.databricks/bundle/<target>/variable-overrides.json`
(git-ignored). The catalog must already exist. Development mode pauses the job and alert schedules.
To rebuild the synthetic world, run `compliance_bootstrap` with `reset=true`.

## Assurance notes

The audit trail must be genuinely immutable, not merely append-intended, because a compliance
report's value rests entirely on being able to show what was reported and on what basis. Report
generation should be reproducible: regenerating a past report must yield the same output from the
evidence as it stood at the time, which means the obligation register and evidence tables both need
point-in-time retrieval.

How the build meets these notes:

* **Immutable:** `audit_events` and every decision or report table use `delta.appendOnly = true`,
  so UPDATE and DELETE fail with `DELTA_CANNOT_MODIFY_APPEND_ONLY`. Events are also hash-chained
  (`event_hash = sha256(prev_hash || canonical)`) and checked on every run.
* **Reproducible:** the register is SCD2, evidence is versioned with `valid_from`/`valid_to`, and
  mappings and reviews are timestamped and append-only. Regenerating a report for its `as_of_date`
  reproduces the same `findings_digest`. All seeded reports pass this check. Delta table versions at
  generation are also stored in `compliance_reports.table_versions`.

## Application

`app/nba-compliance-reports` implements the design handoff as a responsive Databricks AppKit
application. DBSQL queries the governed compliance tables at request time; Lakebase stores user
preferences and saved views in the app-owned `compliance_app` schema. The app can trigger the
bundle-managed report job and surfaces overview, obligation, evidence, report, and audit views.

Deploy all assets together with the additional Lakebase bindings:

```bash
databricks bundle deploy --target dev \
  --var catalog=<YOUR_CATALOG> \
  --var warehouse_id=<YOUR_WAREHOUSE_ID> \
  --var postgres_branch=<YOUR_POSTGRES_BRANCH_RESOURCE> \
  --var postgres_database=<YOUR_POSTGRES_DATABASE_RESOURCE>
```

## Further integration

* Real source-system connectors. Set `simulate_connectors=false` and write to the landing path.
* PDF rendering. The package contains printable `report.html`, `findings.json` and `evidence_manifest.csv`.
* Integration with the `intelligent_document_processing` parsed bronze layer for document text.
