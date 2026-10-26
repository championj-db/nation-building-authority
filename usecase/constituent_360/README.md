# Citizen & Constituent 360

![](docs/ui.png) 

| | |
| --- | --- |
| **Category** | Personalized Engagement |
| **Selected function** | Citizen & Constituent 360 |
| **Evidence anchor** | [GovTech Singapore](https://www.databricks.com/customers/govtech) |
| **Target KPI** | Time per constituent interaction (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

A constituent contacts government through whichever channel is at hand - phone, web, email,
shopfront, a different agency entirely - and each contact lands in a different system. Staff
cannot see what has already been said, so the constituent repeats themselves, and nobody can tell
whether an issue was ever resolved.

## What this use case demonstrates

Unifying interaction history across channels and agencies into a consented, resolved 360 view,
with sentiment and intent derived from the interactions themselves, served to the staff and
assistants who need it.

## Modelled on

[GovTech Singapore](https://www.databricks.com/customers/govtech), which unified data across
government to improve nationwide services. A hub-and-spoke or data mesh arrangement is the usual
shape for this: each agency keeps ownership of its own data while a shared layer makes the
resolved constituent view available to the services that need it.

This use case shares its ingest, identity resolution and governance spine with
`patient_and_provider_360`. The notable difference is that consent and purpose-of-use are harder
here: a constituent who contacted one agency has not thereby consented to that contact being
visible to another.

## Scope

**In scope**

* Ingest of interaction history across channels and agencies
* Constituent identity resolution
* Sentiment and intent derivation from interaction text
* Consent and purpose-of-use enforcement
* Serving the 360 view to service staff and assistants

**Out of scope**

* Any real constituent, contact, or correspondence data. Wholly synthetic.
* A deployed chatbot or call-centre integration. This builds the view those would consume.
* Cross-agency data sharing mechanics, which are covered by `cross_agency_data_sharing`.

## Functions

| Function | Description |
| --- | --- |
| Cross-channel ingest | Land interaction records from multiple channels and agencies |
| Identity resolution | Resolve constituents across channels without a common identifier |
| Sentiment and intent | Derive sentiment and intent signals from interaction text |
| Consent enforcement | Enforce consent and purpose-of-use at query time, not in application code |
| 360 view serving | Serve the resolved view to staff tooling and assistants |

## Architecture

```
channel interactions (multi-agency) -> bronze -> resolved constituents (silver)
                                    -> sentiment + intent -> gold 360 view
                                    -> consent-filtered serving
```

Lakeflow for ingest, Unity Catalog with row filters and column masks for consent enforcement, AI
functions for sentiment and intent, serverless throughout.

## Data

Synthetic and seeded, including synthetic interaction transcripts.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

The consent model is the hard part and should not be glossed over in the implementation. Joining
interaction history across agencies can exceed the purpose for which each contact was originally
collected, so purpose-of-use needs to be enforced in Unity Catalog where it cannot be bypassed,
rather than in an application layer. Sentiment inferred about an identifiable person is itself
personal information, and the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework)
applies to the unified record at the highest classification of its inputs.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
identity resolution, no sentiment derivation, no consent enforcement, no serving layer.
