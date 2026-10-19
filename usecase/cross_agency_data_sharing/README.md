# Secure Cross-Agency Data Sharing

| | |
| --- | --- |
| **Category** | Open Data Sharing |
| **Selected function** | Secure cross-agency sharing (intra-agency, industry/government, state/federal, agency/constituent) |
| **Evidence anchor** | [Best Practices for Government Data Sharing](https://www.databricks.com/blog/2023/02/21/best-practices-cross-government-data-sharing.html) |
| **Target KPI** | Time to deliver cross-agency insight (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

Agencies need each other's data and the approval path to get it is slow, so people work around it.
The consequence is predictable: when compliance complexity makes the approved path harder than the
unapproved one, people resort to workarounds such as screen-scraping, which produces data that is
neither reliable nor governed. The workaround is a symptom - the real problem is the asymmetry
between the two paths.

## What this use case demonstrates

Governed sharing that is easier than the workaround: publishing live shares without copying data,
mounting a share as a consumer, and running a Clean Room collaboration where neither party sees the
other's raw data - with every access audited.

## Modelled on

[Best Practices for Government Data Sharing](https://www.databricks.com/blog/2023/02/21/best-practices-cross-government-data-sharing.html).

The key architectural move is that Clean Rooms shift the approval point from data *outputs* to
approved *code*, permitted use cases, and controlled outputs, so an agency can participate in a
collaboration without exposing its underlying protected data to the other participant. That is a
materially different governance conversation from "may I have a copy of your data", and it is the
heart of this use case.

Delta Sharing's relevance here is avoiding a maintained copy per recipient - the
[Kythera Labs story](https://www.databricks.com/blog/how-kythera-labs-databricks-built-partner-saves-year-using-delta-sharing)
quantifies that saving in a commercial setting, and the same arithmetic applies to an agency
publishing to many consumers.

## Scope

**In scope**

* Publishing governed shares from a provider catalog
* Recipient management across the four sharing relationships in the category
* Mounting a share as a consumer
* A Clean Room collaboration over approved code
* Access audit and lineage across the sharing boundary

**Out of scope**

* Any real agency data. Wholly synthetic on both sides.
* Cross-metastore or cross-cloud setup that cannot be reproduced in a single workspace. Where the
  demo simulates two agencies inside one workspace, the README will say so rather than imply a
  genuine cross-organisation deployment.
* Legal instruments. Data sharing agreements are the real-world gate and are out of scope here.

## Functions

| Function | Description |
| --- | --- |
| Share definition | Define and govern shares from the provider side |
| Recipient management | Create and manage recipients, including token-based open sharing |
| Consumer mount | Mount a share and query it as a consumer |
| Clean Room collaboration | Run approved code across two parties without either seeing raw data |
| Access audit | Report who accessed what, across the sharing boundary |
| Cross-boundary lineage | Trace lineage from shared object back to source |

## Architecture

```
provider catalog -> Delta Sharing share -> recipient -> consumer mount
                 -> Clean Room (approved code only) -> controlled outputs
                 -> audit + lineage
```

Delta Sharing for live sharing without copies, Unity Catalog for governance and audit, Clean Rooms
for privacy-preserving collaboration, Lakehouse Federation where data stays in place.

## Data

Synthetic and seeded, generated as two independent synthetic agency datasets so the sharing
boundary is meaningful.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Sharing is where governance either holds or fails, so the audit trail is the deliverable rather
than a by-product. Note that the sovereignty and residency questions are usually the blocker in
Australian federal practice, not the sharing mechanics - see Databricks'
[data residency documentation](https://docs.databricks.com/aws/en/resources/databricks-geos) and
the [Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework).
This use case demonstrates the mechanics; it does not resolve the policy question.

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic agency datasets, no
shares, no recipients, no Clean Room, no audit reporting.
