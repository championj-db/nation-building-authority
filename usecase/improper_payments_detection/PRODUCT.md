# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Investigators in an integrity-operations team inside an Australian public-sector agency. They work a
daily review queue of potentially improper supplier payments and claims. For each case they
inspect the linked evidence, decide whether the indicator holds up, and record an accountable
outcome. Team leads also watch how many flags survive investigation.

## Product Purpose

The Improper Payments Workbench turns relationships that row-by-row rule checking misses into a
ranked, explained investigator queue. Examples: the same bank account under two supplier names, a
claimant who shares an address with an assessor, a vendor created days before its first invoice.
Each investigation outcome is captured so that the team can measure precision, meaning how many
flags held up once investigated rather than how many the model raised. Success is a queue that
investigators trust and a precision figure the team can report.

## Positioning

Entity resolution across disconnected source systems, a relationship graph, and risk scores that
keep their contributing factors, all governed in Unity Catalog. The workbench closes the loop by
feeding investigation outcomes back into precision measurement.

## Operating Context

- Investigators work at desktop browsers during office hours, in long sessions on a shared queue.
- The terminology is Australian: ABN, AEST, procedural fairness.
- Any real deployment would need an assurance assessment and transparency statement under the
  DTA AI assurance framework.

## Capabilities and Constraints

- Payments, claims and counterparty registries are ingested, entities are resolved
  probabilistically, and a relationship graph is built.
- Payments are scored with rule signals plus an MLflow model. Contributing factors are retained
  with each score.
- The triage queue carries an explanation for every case. Investigators can assign cases, clear an
  indicator, or escalate a case for assessment, with notes required.
- Investigation outcomes and case state are stored in Lakebase Postgres and fed back into a
  precision view.
- Out of scope: automated payment blocking or recovery, and any real payment, claimant or supplier
  data.

## Brand Commitments

- The Databricks palette (navy, lava, oat) with DM Sans, as set by the Genie Design export at
  `design/improper-payments-workbench.html`.
- The voice is a plain, Australian Government register.

## Evidence on Hand

- All data is wholly synthetic and seeded, with known improper-payment patterns and benign
  look-alikes injected, so detection can be measured against ground truth.
- No claim may be made that synthetic detection rates say anything about real-world performance.
- No real agencies, people or businesses appear in the data.

## Product Principles

- Scores are indicators, not findings. Every surface that shows a score says so.
- Every flag carries its explanation. An investigator never sees a number without the reasons
  behind it.
- Measure what survives investigation. Precision is reported from outcomes, not from flag volume.
- Accountability is built in. Each outcome records who decided, when, what they saw, and why.
- Linking records creates privacy exposure, so show only what the decision needs.

## Accessibility & Inclusion

WCAG 2.2 AA. Status and risk are always conveyed by text as well as colour, and the whole queue
can be worked from the keyboard.
