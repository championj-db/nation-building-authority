# Nation Building Authority

A reference repository of Databricks public sector use cases, built for the **Nation Building
Authority (NBA)** — a fictional Australian Federal Government department.

The NBA's remit is deliberately unbounded: it is whatever the government of the day needs solved.
That makes it a useful vehicle for demonstrating the full breadth of public sector data and AI work
without contorting any individual use case to fit a departmental persona. A health use case stays a
health use case; an infrastructure use case stays an infrastructure use case.

> **This repository is public.** It contains no real, customer, or personally identifiable data.
> Every use case generates its own synthetic data.

## Repository layout

```
README.md                     This file
CONTRIBUTING.md               How to add or implement a use case
docs/
  usecase-catalogue.md        The 12 selected use cases, with evidence anchors and KPIs
template/
  usecase/                    Copy this to start a new use case
    README.md
    databricks.yml
    resources/
usecase/
  {usecase_name}/             One self-contained use case per folder
    README.md
    databricks.yml
```

## How use cases are selected

One use case per capability domain, across twelve domains grouped into three pillars — reinventing
public services, optimising operations, and strengthening security. For each domain we selected the
single highest-impact function and anchored it to a publicly citable customer reference or
published Databricks material.

**Every source in this repository is public and linked.** Nothing internal is cited, no customer is
named unless a published Databricks page names them, and an outcome figure appears only where a
public source supports it. Where a selection has no public reference behind it — `siem_augmentation`
and `geospatial_analysis` — its README says so rather than implying evidence that is not there.

See [docs/usecase-catalogue.md](docs/usecase-catalogue.md) for the full catalogue, the rationale
behind each selection, and the evidence behind every claimed outcome.

## Conventions

These are non-negotiable, because they are what makes the repository reusable:

1. **Everything is templated. No hard-coded values.** Catalogs, schemas, volumes, warehouse IDs,
   paths, and email addresses are all bundle variables resolved per target. If you can find a
   literal catalog or schema name in a resource definition, that is a bug.
2. **All work lives under `usecase/{usecase_name}/`.** Nothing use-case-specific belongs at the
   repository root.
3. **Each use case is self-contained.** Its own `databricks.yml`, its own resources, its own
   synthetic data generator, its own README. No cross-imports between use cases. A use case can be
   deleted or lifted into another repository without breaking anything else.
4. **Deployments are reusable via DABs.** Every use case deploys with
   [Declarative Automation Bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/).

## Deploying a use case

Each use case is its own bundle, so commands run from inside the use case folder:

```bash
cd usecase/{usecase_name}

# Validate the bundle resolves
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>

# Deploy to your personal dev target
databricks bundle deploy --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with a Unity Catalog catalog you can write to.

To avoid passing variables on every command, create
`.databricks/bundle/dev/variable-overrides.json` inside the use case folder:

```json
{
  "catalog": "<YOUR_CATALOG>",
  "warehouse_id": "<YOUR_WAREHOUSE_ID>"
}
```

That file is git-ignored, so your local values never reach the public repository.

## Status

The catalogue is complete and all 12 use case folders are scaffolded. The folders are **stubs** —
README plus a validating DAB skeleton, with no pipelines, models, or dashboards implemented yet.
Each use case README carries its own status line.
