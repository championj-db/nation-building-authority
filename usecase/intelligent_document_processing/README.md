# Intelligent Document Processing

| | |
| --- | --- |
| **Category** | Back Office Automation |
| **Selected function** | Intelligent Document Processing |
| **Evidence anchor** | [PDFs to Production](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks) |
| **Target KPI** | Document processing cost (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |
| **Build priority** | 2 |

## Problem

Government runs on documents: applications, business cases, invoices, correspondence, assurance
reports. The information inside them is locked in formats that analytics cannot reach, so staff
re-key it by hand. That is slow, expensive, and error-prone, and it means the richest evidence an
agency holds is invisible to every downstream system.

## What this use case demonstrates

Turning a corpus of unstructured documents into governed, queryable structured data: parse,
classify, extract typed fields against a schema, score confidence, route the uncertain cases to a
human, and publish the result.

## Modelled on

[PDFs to Production: announcing state-of-the-art document intelligence on Databricks](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks)
(11 November 2025), which introduces `ai_parse_document`. The function parses PDFs directly in SQL
and emits layout information, parsed tables, bounding boxes, and figures with captions into Unity
Catalog. Databricks reports it delivering competitive quality at 3-5x lower cost than competing
offerings.

Supporting material: the
[intelligent document processing guide](https://docs.databricks.com/aws/en/agents/agent-bricks/intelligent-document-processing),
which sets out applying `ai_parse_document` to create a standardised bronze layer that serves every
downstream use case, and
[Information Extraction](https://docs.databricks.com/aws/en/agents/agent-bricks/info-extraction)
for the Agent Bricks extraction agent.

This is the highest-reuse use case in the catalogue. Eligibility determination, compliance
reporting, and procurement analysis all need documents turned into structured data first, so the
bronze layer built here is intended to be lifted into those use cases rather than rebuilt.

## Scope

**In scope**

* Landing documents in a Unity Catalog volume with change detection
* A standardised parsed bronze layer via `ai_parse_document`
* Document type classification
* Schema-driven field extraction
* Confidence scoring and a human review queue for low-confidence extractions
* Structured publication and corpus Q&A

**Out of scope**

* Any real document. The corpus is synthetic, generated for this use case.
* Handwriting-heavy or poor-quality scans. The synthetic corpus is clean, so results here are not
  evidence of robustness on degraded inputs.
* Writing extracted data back into a source system of record.

## Functions

| Function | Description |
| --- | --- |
| Volume landing | Documents land in a UC volume; new arrivals detected incrementally |
| Parsed bronze layer | `ai_parse_document` produces text, tables, and layout into a standard schema |
| Classification | Route each document to a type, so the right extraction schema is applied |
| Field extraction | Extract typed fields against a declared schema per document type |
| Confidence and review | Score extractions; queue low-confidence cases for a human |
| Structured publication | Publish validated structured output as governed tables |
| Corpus Q&A | Natural-language question answering over the parsed corpus |

## Architecture

```
UC volume (documents) -> ai_parse_document bronze -> classified silver
                      -> extracted fields (schema per type) -> validated gold
                      -> review queue (low confidence)
                      -> corpus Q&A
```

Unity Catalog volumes for landing and governance, Lakeflow for incremental processing,
`ai_parse_document` and Agent Bricks for parsing and extraction, serverless throughout.

## Data

Synthetic document corpus, generated with a fixed seed. No real documents of any kind.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Documents are the most likely place for unexpected personal or sensitive information to appear, and
parsing makes it newly searchable at scale. The landing volume and parsed bronze layer should be
treated at the highest classification of anything in the corpus under the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework),
not at the average. Note also the PSPF
[policy advisory on OFFICIAL information and generative AI](https://www.protectivesecurity.gov.au/news/policy-advisory-official-information-use-generative-artificial-intelligence).
The human review step is a control, not a nicety: extraction confidence is the mechanism that keeps
a wrong field from silently becoming a fact.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic corpus generator,
no parse pipeline, no classifier, no extraction schemas, no review queue, no Q&A.
