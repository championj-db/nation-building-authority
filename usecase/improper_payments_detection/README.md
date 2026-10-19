# Improper Payments Detection

| | |
| --- | --- |
| **Category** | Fraud Prevention |
| **Selected function** | Fraud Detection (improper payments) |
| **Evidence anchor** | [A smarter state: AI outlook in the public sector](https://www.databricks.com/sites/default/files/2025-02/public-sector-report-jan-30.pdf) |
| **Target KPI** | Improper payments identified and recovered |
| **Status** | **Stub** - README and DAB skeleton only |
| **Build priority** | 3 |

## Problem

Payments go out at volume and at speed, and the signals that a payment was improper are rarely in
the payment record itself. They are in the relationships between entities: the same bank account
under two supplier names, a claimant and an assessor sharing an address, a vendor created days
before its first invoice. Those relationships are invisible to row-by-row rule checking, so
improper payments are usually found long after the money has left.

## What this use case demonstrates

Resolving entities across disconnected sources to expose hidden relationships, building a
relationship graph, scoring payments for improper-payment risk, and triaging to investigators with
an explanation they can act on.

## Modelled on

Databricks' [A smarter state: AI outlook in the public sector](https://www.databricks.com/sites/default/files/2025-02/public-sector-report-jan-30.pdf)
reports the US Department of Defense using AI-driven tools to process more than 10 million records
and identify over US$12.7 billion in true improper payments since 2020.

Reference implementations: the
[Entity Resolution for Public Sector accelerator](https://community.databricks.com/t5/announcements/solution-accelerator-series-entity-resolution-for-public-sector/m-p/169611/highlight/true)
and the [Smart Claims accelerator](https://www.databricks.com/solutions/accelerators/smart-claims-for-insurance),
whose stated goals are lowering cost, reducing fraud, and accelerating settlement. Databricks'
[Public Sector Solutions](https://www.databricks.com/solutions/industries/public-sector) page
covers the surrounding fraud, waste and abuse detection pattern.

Note on the "true improper payments" phrasing in the DoD figure: it matters. The useful measure is
not how many payments a model flagged but how many flags survived investigation. A detection use
case that cannot report its own precision is not finished, which is why the feedback loop from
investigation outcomes is in scope here rather than deferred.

## Scope

**In scope**

* Ingest of payments, claims, and counterparty registries
* Probabilistic entity resolution across sources
* Relationship graph construction
* Risk and anomaly scoring at payment and counterparty level
* Investigator triage queue with contributing-factor explanations
* Feedback loop capturing investigation outcomes to measure precision

**Out of scope**

* Any real payment, claimant, or supplier data. Wholly synthetic.
* Automated payment blocking or recovery action.
* A claim that the synthetic detection rates mean anything about real-world performance.

## Functions

| Function | Description |
| --- | --- |
| Payment and claim ingest | Land payments, claims, and counterparty registries into bronze |
| Entity resolution | Probabilistic matching to resolve duplicate and related entities across sources |
| Relationship graph | Build and traverse the entity relationship graph to surface indirect links |
| Risk scoring | Score payments and counterparties, with contributing factors retained |
| Investigator triage | Rank and route cases, with the explanation attached |
| Outcome feedback | Capture investigation results to measure and improve precision |

## Architecture

```
payments + claims + registries -> bronze -> resolved entities (silver)
                               -> relationship graph -> risk scores (gold)
                               -> investigator queue -> outcome feedback
```

Lakeflow for ingest and transformation, Unity Catalog for governance and lineage over sensitive
financial data, graph analysis for relationships, MLflow for the scoring model, serverless
throughout.

## Data

Synthetic and seeded, with known improper-payment patterns deliberately injected so that detection
can be measured against ground truth.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Fraud risk scores are among the most consequential outputs in this catalogue: a false positive
puts a person or business under investigation. Scores must never be treated as findings. Access to
the graph and scores needs tight Unity Catalog controls and full audit, and because a score
influences a decision about an identifiable person, an assurance assessment and transparency
statement under the
[DTA AI assurance framework](https://www.dta.gov.au/articles/dta-pilots-new-ai-assurance-framework)
would apply in a real deployment. Entity resolution also creates a privacy exposure that does not
exist in the source systems, by linking records that were previously separate.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
entity resolution, no graph, no scoring model, no triage queue, no feedback loop.
