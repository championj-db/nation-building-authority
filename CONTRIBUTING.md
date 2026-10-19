# Contributing

## Adding a use case

1. Pick the category and function from [docs/usecase-catalogue.md](docs/usecase-catalogue.md). If
   you are adding something not in the catalogue, add the catalogue row first — including its
   evidence anchor — so the selection rationale is recorded alongside the code.
2. Copy the template:

   ```bash
   cp -r template/usecase usecase/<usecase_name>
   ```

3. Replace every `{{usecase_name}}` placeholder with your snake_case use case name.
4. Fill in the README front matter: category, selected function, evidence anchor, target KPI.
5. Build inside your folder only. Never reach into another use case.

### Naming

* Folder names are `snake_case` and name the **function**, not the category —
  `intelligent_document_processing`, not `back_office_automation`.
* Bundle names are `nba-<usecase-name>` with hyphens.
* Table names carry no environment prefix. The environment lives in the catalog or schema, which
  is supplied per target.

## The no-hard-coding rule

This is the rule that is easiest to break and most damaging when broken, because a hard-coded
catalog name turns a portable asset into one that only runs in the workspace it was written in.

Everything environment-specific is a bundle variable:

| Variable | Purpose |
| --- | --- |
| `catalog` | Unity Catalog catalog owning the use case's schemas, volumes and models |
| `schema` | Schema holding the use case's tables |
| `volume` | UC volume for landing raw or unstructured source files |
| `warehouse_id` | SQL warehouse backing dashboards and SQL tasks |
| `notifications_email` | Address notified on job failure |
| `environment` | Logical environment label, applied as a tag to every resource |

Reference them as `${var.catalog}`, never as a literal. In notebook and Python code, read them as
parameters passed from the DAB rather than hard-coding or inferring them:

```python
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
```

Things that are **not** hard-coded values, and are fine as literals: the bundle name, the use case
folder name, table and column names, and resource keys. These are structural identifiers that
travel with the code.

## Data

This repository is public. Therefore:

* No real data, no customer data, no personally identifiable information, not even de-identified
  extracts of either.
* Each use case ships a deterministic, seeded synthetic data generator so anyone can reproduce the
  same dataset. Seed it explicitly — an unseeded generator makes results irreproducible and
  dashboards unreviewable.
* Where a use case benefits from genuinely public reference data, fetch Australian open data
  (`data.gov.au`, ABS, BITRE) at deploy time rather than committing a copy.

## Evidence standard

**Public sources only.** This repository is public, so every cited source must be public too. Do not
cite internal decks, partner packs, field material, Salesforce or Glean records, internal wikis, or
anything behind a corporate login — not even with a "check before quoting externally" caveat. If
the only source for a claim is internal, the claim does not belong here.

The same applies to customer names: **do not name a customer unless a published Databricks page
names them**, and link that page. An unpublished reference is a reference you cannot use, however
well known the engagement is internally.

Outcome claims must be traceable. Cite the published customer story, blog, or report they came
from, with a URL. Where we are modelling a pattern rather than reproducing a published result, say
so plainly — write "modelled on" rather than implying the number was reproduced here. Do not
attribute numbers to a named customer unless that customer has published them.

Where a use case has no public reference behind it, write "None public - pattern-based selection"
in its evidence anchor and explain the reasoning. `siem_augmentation` and `geospatial_analysis` are
both examples. A stated gap is more useful than a borrowed number, and far safer than an internal
citation that should never have left the building.

A figure with no public source is worse than no figure at all: it cannot be checked, and in a
public repository it will be read as a Databricks claim. Prefer naming the *measure* the use case
moves — "document processing cost" — over quoting an unverifiable improvement against it.

## Before you open a pull request

```bash
cd usecase/<usecase_name>
databricks bundle validate --target dev --var catalog=<YOUR_CATALOG>
```

Replace `<YOUR_CATALOG>` (angle brackets included) with your own catalog. Then check:

* No literal catalog, schema, warehouse ID, workspace URL, or email address anywhere in the use
  case.
* **No internal references.** Every cited source resolves to a public URL, and every named customer
  appears on a published Databricks page. Grep your diff before pushing:

  ```bash
  git diff --cached | grep -niE "internal|partner pack|confidential|do not share"
  ```

* The use case deploys and runs end to end from a clean catalog.
* The README states current status honestly, including what is not built yet.

If an internal reference does reach a commit, removing it in a later commit is not enough — it
stays in the history and remains reachable on the remote. It has to be removed from the history
itself, which is disruptive for everyone who has cloned the repository. Checking the diff before
pushing is considerably cheaper.
