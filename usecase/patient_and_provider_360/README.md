# Patient & Provider 360

| | |
| --- | --- |
| **Category** | Health Insights |
| **Selected function** | Patient & Provider 360 |
| **Evidence anchor** | [Healthcare Patient Personalization Reference Architecture](https://www.databricks.com/resources/architectures/healthcare-patient-personalization-reference-architecture) |
| **Target KPI** | Patient engagement and retention (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

A person's health information is scattered across clinical systems, claims, provider directories,
and engagement channels, each holding a partial record under a different identifier. Nobody can see
the whole picture, so care is duplicated, gaps go unnoticed, and people are matched to providers
who are not the right fit. The same fragmentation applies to providers themselves.

This is a pure health insights use case. It is not re-themed to fit the Nation Building Authority's
remit, because a health use case is most useful when it stays recognisable to the people who work
in health.

## What this use case demonstrates

Building a governed longitudinal view of patients and providers from fragmented sources:
standardise toward FHIR, resolve identity, enrich with social determinants, govern sensitive
attributes, and activate through next-best-action and provider matching.

## Modelled on

The [Healthcare Patient Personalization Reference Architecture](https://www.databricks.com/resources/architectures/healthcare-patient-personalization-reference-architecture),
which describes pairing a patient with the correct provider and presenting a holistic 360-degree
view of their health, integrating clinical, CRM, provider, pharmacy and regulatory data.

Supporting material:

* [Unlocking FHIR for Data and AI in a Meaningful Way](https://www.databricks.com/blog/unlocking-fhir-data-and-ai-meaningful-way)
  (25 October 2024) - using HL7 v2 and FHIR to build a complete patient view, and `dbignite`, the
  open-source project that makes FHIR easier to work with on Databricks.
* [Building a FHIR-native health data platform on Databricks Lakebase](https://www.databricks.com/blog/building-fhir-native-health-data-platform-databricks-lakebase)
  (27 May 2026) - standardising HL7v2, C-CDA and X12 into FHIR at ingestion, with terminology
  normalisation and patient deduplication built in.
* [Social Determinants of Health accelerator](https://community.databricks.com/t5/community-articles/solution-accelerator-series-social-determinants-of-health/m-p/163604)
  for enrichment.
* Patient 360 is named as a healthcare use case in the Databricks
  [federal government solution sheet](https://www.databricks.com/sites/default/files/2024-03/federal-government-solution-sheet-2.pdf).

Databricks' [health and human services solutions](https://www.databricks.com/solutions/industries/nhs)
page covers the broader pattern of delivering personalised, secure online patient care.

This use case also carries the repository's shared 360 spine - ingest, standardise, resolve
identity, govern, activate - which `constituent_360` reuses directly and
`improper_payments_detection` reuses for its entity resolution core.

## Scope

**In scope**

* Ingest of clinical, claims, provider directory and engagement data
* Standardisation toward FHIR resources
* Patient and provider identity resolution into longitudinal profiles
* Social determinants enrichment
* Unity Catalog row, column and attribute-based controls over sensitive health attributes
* Next-best-action and provider matching

**Out of scope**

* Any real clinical, claims, or provider data. Wholly synthetic.
* Write-back into an EHR or any clinical system of record.
* Clinical decision-making of any kind. Nothing here is a clinical tool, and no output should be
  read as clinical advice.
* Full FHIR conformance. We model the standardisation pattern, not a certified implementation.

## Functions

| Function | Description |
| --- | --- |
| Multi-source ingest | Clinical, claims, provider directory and engagement data into bronze |
| FHIR standardisation | Conform sources toward FHIR resources with terminology normalisation |
| Identity resolution | Resolve and deduplicate patient and provider identity across sources |
| SDoH enrichment | Join normalised social determinants to the longitudinal profile |
| Governed profile serving | Serve the 360 view under row, column and attribute-based controls |
| Next-best-action | Derive recommended engagement actions and provider matches |

## Architecture

```
clinical + claims + provider directory + engagement
  -> bronze -> FHIR-conformed silver -> resolved longitudinal profiles
  -> SDoH enrichment -> gold 360 view -> next-best-action + provider matching
```

Lakeflow for ingest and transformation, Unity Catalog for governance of sensitive health
attributes, MLflow for next-best-action, serverless throughout.

## Data

Synthetic and seeded. No real, de-identified, or re-identifiable health data — synthetic records
only, generated for this use case.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Health information is among the most sensitive data government holds, and this use case
deliberately assembles it into one place, which concentrates the risk. Attribute-based access
control over sensitive attributes and purpose-of-use enforcement are core requirements, not
extensions. Identity resolution also creates linkage that does not exist in the source systems, so
the resolved profile warrants a higher classification than its inputs under the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework).
Even with synthetic data, the access model should be built as though the data were real — a demo
that skips the controls teaches the wrong pattern.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no FHIR
standardisation, no identity resolution, no SDoH enrichment, no access controls, no
next-best-action.
