---
version: 1
slug: "app-nba-payments-workbench-client-src-app-tsx"
primary_target: "app/nba-payments-workbench/client/src/App.tsx"
related_targets: []
---

Scope: Improper Payments Workbench app (app/nba-payments-workbench) — Review queue + case drawer, plus Precision view. Visitor mode: Operate.

Audience/job: integrity-operations investigators triage a ranked queue of potentially improper supplier payments and claims, inspect the evidence behind each score, and record an accountable outcome. Team leads read precision.
Constraints: visual world pinned by the Genie Design export (design/improper-payments-workbench.html): tokens, layout, copy and interactions preserved. Synthetic data, labelled on every surface. Scores are indicators, not findings.

## Direction contract

THESIS: The queue is the tool: a calm, dense ledger where every score arrives with its reasons. Refuses the category default of a chart-heavy fraud "command centre" with red alarm tiles.

OWN-WORLD: Oat ground (#EEEDE9) with warm-white panels (#F9F7F4), navy ink (#0B2026), lava (#FF3621) only for the primary action, the active-tab rule, and focus; DM Sans for everything, system mono for ids, money and scores; 12–16px radii, hairline borders at 24% ink, a single soft raised shadow; pill risk badges in danger/warn tints with the number and the word.

STORY: The investigator sees how much is waiting, filters to the highest-risk unassigned work, opens a case, reads why it was prioritised and how the entities link, assigns it, and clears or escalates it with notes, then sees precision move.

FIRST VIEWPORT: Top bar (brand mark + name and the Review queue / Precision switch left, signed-in identity with "Integrity operations · Daily review" + theme toggle right); H1 "Payment review queue", lede left with the synthetic-data note card right; four metric tiles in one row; status tabs; the filter bar and first rows of the case table, with the top-ranked case visible above the fold at 1440×900. Primary action: open a case row → drawer.

FORM: Pinned operational ledger from the approved export (seed: none (pinned) — "Preserve the current visual design, layout, interactions, and assets."). Signature interaction: the right-hand review drawer sliding over a dimmed queue, carrying factors, a data-drawn linked-entity graph, and outcome capture; motion 150–200ms standard ease, state-only.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
