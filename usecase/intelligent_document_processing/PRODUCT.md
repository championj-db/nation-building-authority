# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Accounts payable (AP) officers in the shared finance team of an Australian Government
non-corporate Commonwealth entity (the fictional Nation Building Authority). Each working day they
clear a mixed supplier inbox. It holds tax invoices, adjustment notes, supplier statements, and
correspondence that was routed there by mistake. For each invoice they decide one of two things:
it is a **correctly rendered invoice**, so the payment clock starts and it goes to approval, or it
is not, so it goes back to the supplier with a reason. AP team leads watch the queue against the
payment deadline and report on whether the entity is ready for the new payment terms.

## Product Purpose

The Document Assurance Workbench turns inbound supplier documents into governed, structured
records. It parses each document, works out what kind of document it is, and extracts typed
fields. It then checks every invoice against the contract and purchase order it claims to relate
to, and against the rules for a valid tax invoice. Clean invoices go straight to approval. Only
the uncertain or non-compliant ones reach a person, and that person sees the evidence behind every
field. Success means invoices are paid within the policy term without re-keying, and fewer of them
go back to suppliers for avoidable reasons.

The deadline is real. Under the Supplier Pay On-Time or Pay Interest Policy (RMG 417), the clock
starts the day after both satisfactory delivery is acknowledged and a correctly rendered invoice
is received. The maximum term is currently 20 calendar days, or 5 calendar days for Peppol
e-invoices. From 1 January 2027 it becomes 10 business days for all invoice types. Late payment
accrues interest at the ATO General Interest Charge rate, which is payable when the accrued
interest exceeds A$100.

## Positioning

`ai_parse_document` produces a governed parsed layer with layout and bounding boxes. Per-field
evidence is located on the page, so a reviewer checks the source passage rather than trusting a
value. Contract-aware "correctly rendered" checks run against the procurement record. All of it is
governed in Unity Catalog and reusable by other use cases that need documents turned into data.

## Operating Context

- AP officers work at desktop browsers during office hours, in long sessions on a shared queue.
- Australian terminology throughout: ABN, GST, tax invoice, adjustment note, purchase order (PO),
  AusTender contract notice, AEST, business days.
- The "correctly rendered" criteria follow RMG 417 and the Commonwealth Contracting Suite's model
  definition. The invoice is correctly addressed and quotes the required PO or contract reference.
  It relates to accepted goods, services or milestones and is correctly calculated. It is within
  the contract price, and it is a valid GST tax invoice. Under ATO rules, a tax invoice must show
  the supplier's identity and ABN, the issue date, what was supplied, and the GST. For a taxable
  sale of A$1,000 or more, it must also show the recipient's identity or ABN.
- The workbench does not write back to the financial management information system (FMIS).
  Approval for payment happens downstream.
- Any real deployment would need an assurance assessment under the DTA AI assurance framework and
  handling at the highest classification of anything in the corpus (PSPF).

## Capabilities and Constraints

- Documents land in a Unity Catalog volume, and new arrivals are picked up incrementally.
- `ai_parse_document` produces text, tables, layout elements and bounding boxes into a standard
  bronze schema.
- Each document is classified by type, and typed fields are extracted against a declared schema
  per type.
- Field confidence is a routing score built from grounding (the value is found in the source
  text), type validity and arithmetic consistency. It is not a probability, and the UI never
  presents it as one.
- Deterministic checks decide whether an invoice is correctly rendered: valid ABN checksum, GST
  arithmetic, recipient identity at A$1,000 or more, PO and contract match, remaining contract
  value, duplicate invoice number, and delivery acknowledged.
- A pay-by date and the number of days left are computed under both the current terms and the
  1 January 2027 terms.
- Reviewer decisions (field corrections, accept as correctly rendered, return to supplier with
  reasons, reclassify) are stored in Lakebase Postgres. They are read back into Unity Catalog to
  measure extraction accuracy and straight-through rate.
- Out of scope: approving or making payments, writing to an FMIS, and any real invoice, supplier
  or person.

## Brand Commitments

- The Databricks palette (navy, lava, oat) with DM Sans, as set by the Genie Design export
  "Document Assurance Workbench" at `design/document-assurance-workbench.html`.
- The voice is a plain, Australian Government register.

## Evidence on Hand

- Contract notices are drawn from real public AusTender data (data.gov.au), fetched at deploy
  time. Supplier identities and contract notice IDs are pseudonymised, and the buying entity is
  the fictional Nation Building Authority, so no real company appears next to a synthetic invoice
  or exception.
- Invoices, adjustment notes, statements, correspondence, purchase orders and goods receipts are
  synthetic and seeded. Known defects are injected and labelled as ground truth.
- No claim may be made that extraction accuracy on this clean synthetic corpus says anything about
  real, degraded or handwritten documents.
- No processing-cost figure is claimed. Cost is a measure to instrument, not a result.

## Product Principles

- Confirm the evidence, not just the value. Every extracted field links to where it sits on the
  page.
- The deadline sets the order. The queue is ordered by days left on the payment clock, not by
  model confidence alone.
- Confidence routes work. It does not certify it. A low score sends a field to a person, and a
  high score is never presented as proof.
- Returning an invoice is a decision with consequences. It pauses the clock and costs the
  supplier time, so every return states the specific failed criterion.
- Measure what reviewers changed. Extraction accuracy is reported from reviewer corrections, not
  from model self-assessment.

## Accessibility & Inclusion

WCAG 2.2 AA. Status, confidence and deadline risk are always conveyed by text as well as colour.
The queue and the review workspace can be worked fully from the keyboard.
