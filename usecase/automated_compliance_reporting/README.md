# Automated Compliance Reporting

| | |
| --- | --- |
| **Category** | Regulatory Compliance |
| **Selected function** | Automated Compliance Reporting |
| **Evidence anchor** | [Gateway Reviews Process](https://www.finance.gov.au/government/assurance-reviews-and-risk-assessment/gateway-reviews-process) |
| **Target KPI** | Review accuracy and evidence coverage |
| **Status** | **Stub** - README and DAB skeleton only |

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

Synthetic and seeded, including a synthetic obligation register and evidence artefacts.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

The audit trail must be genuinely immutable, not merely append-intended, because a compliance
report's value rests entirely on being able to show what was reported and on what basis. Report
generation should be reproducible: regenerating a past report must yield the same output from the
evidence as it stood at the time, which means the obligation register and evidence tables both need
point-in-time retrieval.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
obligation register, no evidence collection, no mapping, no reports, no gap detection, no audit
trail.
