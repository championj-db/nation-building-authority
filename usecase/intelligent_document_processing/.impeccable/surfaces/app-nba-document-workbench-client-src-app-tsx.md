---
version: 1
slug: "app-nba-document-workbench-client-src-app-tsx"
primary_target: "app/nba-document-workbench/client/src/App.tsx"
related_targets: []
---

Scope: Document Assurance Workbench app (app/nba-document-workbench): Overview, Review queue, Review workspace (document + evidence), Intake, Ask (Genie), Document register, Performance & readiness, Decision log. Visitor mode: Operate.

Audience/job: AP officers decide, per supplier invoice, "correctly rendered: start the clock and accept" or "return to the supplier with the failed criterion"; AP team leads watch the RMG 417 clock and 1 January 2027 readiness.
Constraints: visual world pinned by the Genie Design export (design/document-assurance-workbench.html): tokens, sidebar + top bar shell, screens, copy and interactions preserved; deltas recorded in design/DESIGN-HANDOFF.md. Synthetic documents, labelled on every surface. Confidence routes work; it never certifies it.

## Direction contract

THESIS: Evidence beside the decision. The source page and its cited regions sit next to every extracted value, and the payment clock, not model confidence alone, sets the order. Refuses the category default of an OCR "accuracy dashboard" with a confidence leaderboard and a bulk-approve button.

OWN-WORLD: Oat ground (#EEEDE9), warm-white panels (#F9F7F4), navy ink (#0B2026) for the active nav pill and text; lava only for the primary action and focus; warn amber as the evidence highlight on the page and on low-confidence fields; DM Sans throughout, system mono for money, ids, confidence and days left; 12-16px radii, hairline borders, one soft raised shadow; numbered pipeline stages; OFFICIAL pill in the sidebar foot.

STORY: The officer sees what is due and what is held, opens the most urgent invoice, clicks each held field to see where it sits on the page, confirms or corrects it, reads the correctly rendered checks, and either accepts (the clock was already running) or returns it with the specific criterion; the lead sees readiness for 10 business days.

FIRST VIEWPORT: 248px sidebar (brand, Workspace nav with counts, Governance nav, OFFICIAL foot), 72px top bar (crumb left; theme, Decision log, Ingest documents right); H1 greeting with lede and date; four clickable summary tiles (due within 5 business days, overdue, needs review, exceptions); review queue panel (filters, rows ordered by days left) beside the numbered document pipeline with live counts and the assurance note. Primary action: open a queue row into the review workspace.

FORM: Pinned operational workbench from the approved export (seed: none (pinned) - "Preserve the current visual design, layout, interactions, and assets."). Signature interaction: selecting an extracted field draws its cited bounding box on the rendered page and scrolls it into view; Accept stays locked until every held field is confirmed or corrected. Motion 150-200ms standard ease, state only.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
