# Geospatial Analysis

| | |
| --- | --- |
| **Category** | Physical Security |
| **Selected function** | Geospatial Analysis |
| **Evidence anchor** | None public - pattern-based selection (see below) |
| **Target KPI** | Time to spatial insight (measure to instrument) |
| **Status** | **Stub** - README and DAB skeleton only |

## Problem

Most government questions have a "where" in them: which households are beyond reasonable reach of
a service, which assets sit inside a hazard zone, how an incident propagates across a network.
Spatial data is large, awkwardly formatted, and usually sits in a specialist tool disconnected from
everything else, so these questions take days and the answers cannot be joined to anything.

## What this use case demonstrates

Spatial analysis as a first-class part of the lakehouse rather than a separate stack: indexed
spatial data, proximity and containment analysis at scale, and spatial aggregates that join
directly to non-spatial data.

## Modelled on

Nothing publicly citable. Unlike the flagship, this selection rests on the architectural pattern
rather than on a published customer outcome, and it is worth strengthening if a citable reference
becomes available.

The pattern itself is well supported: Databricks SQL spatial functions and H3 indexing make
large-scale spatial joins tractable, and genuinely public Australian boundary data is available to
make the analysis realistic. The concrete pattern built here is proximity analysis for essential
services - household-to-hospital distance being the canonical example - because it is the spatial
question that most often has a policy consequence attached to it.

## Scope

**In scope**

* Ingest and indexing of spatial datasets
* Proximity analysis, including distance-to-nearest-service
* Containment analysis against zones and boundaries
* Spatial aggregation to standard geographies
* Map-ready serving

**Out of scope**

* Any real incident, crime, or operational location data. Wholly synthetic.
* Routing over a real road network graph.
* Replacing a GIS. This complements one by making spatial results joinable to everything else.

## Functions

| Function | Description |
| --- | --- |
| Spatial ingest | Ingest spatial datasets and conform geometries and projections |
| Spatial indexing | Index geometries so large-scale spatial joins are tractable |
| Proximity analysis | Distance-to-nearest and within-radius analysis at scale |
| Containment analysis | Point-in-polygon against zones and administrative boundaries |
| Spatial aggregation | Aggregate to standard geographies for comparison and reporting |
| Map-ready serving | Serve aggregates in a form a mapping client can consume |

## Architecture

```
spatial sources -> bronze (conformed geometries) -> spatial index (silver)
                -> proximity + containment analysis -> spatial aggregates (gold)
                -> map-ready serving
```

Lakeflow for ingest, Databricks SQL spatial functions and H3 indexing for analysis, Unity Catalog
for governance, AI/BI for mapping, serverless throughout.

## Data

Synthetic and seeded. Where genuinely public Australian boundary data would make the analysis more
realistic (ABS statistical areas, for example), fetch it at deploy time rather than committing a
copy - see CONTRIBUTING.md.

## Deploy

```bash
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a catalog you can write to. There is
nothing to deploy or run yet.

## Assurance notes

Location data is identifying even when nothing else in the record is: a sufficiently precise
home-location trace identifies a person regardless of how the other columns are masked. Spatial
aggregation is therefore a privacy control as much as an analytical step, and small-count
suppression matters when aggregating to fine geographies. Relevant: the
[Protective Security Policy Framework](https://www.protectivesecurity.gov.au/about/structure-protective-security-policy-framework).

## Not built yet

Everything. This is a stub: README plus a validating DAB skeleton. No synthetic generator, no
spatial ingest, no indexing, no analysis, no aggregates, no serving.
