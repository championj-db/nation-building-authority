# Document Assurance Workbench - design handoff

`document-assurance-workbench.html` is the source design (Genie Design export, kept unmodified as
the reference). The production app is `app/nba-document-workbench` (AppKit: Node + React). The
prototype is one static page with four hard-coded documents; the app keeps its shell, tokens,
screens and interactions and gives them a specific job: deciding, per supplier invoice, whether it
is a correctly rendered invoice under RMG 417, before the payment clock runs out.

## Kept as designed

- Tokens (colour, type scale, spacing, radii, elevation, motion) and the dark theme with its
  toggle (now persisted). Token names change only where AppKit UI's shadcn variables would
  collide (`--accent` to `--lava`, `--muted` to `--fg-muted`, `--border` to `--line`); AppKit's own
  components are pointed at the same palette so they follow the app's theme, not the OS.
- The 248px sidebar (brand mark, Workspace and Governance nav groups with counts, OFFICIAL pill
  and "Synthetic demonstration corpus" foot), the 72px blurred top bar with crumb, theme toggle,
  Audit log (now "Decision log") and the primary "Ingest documents".
- Overview: greeting H1 with intro and date, four summary tiles, the review queue panel with
  filter pills and rows (title, meta, status dot, lowest-field confidence, chevron), the numbered
  "Document pipeline" stages and the assurance note (copy kept, extended).
- Review: document view on the left, extracted fields with scores on the right, "Confirm the
  evidence, not just the value", the warn-amber evidence highlight, review actions at the foot.
- Corpus Q&A screen layout: question, example chips, answer.
- The ingest dialog, the toast.

## Changed, and why

| Prototype | App | Reason |
| --- | --- | --- |
| Eyebrows above every H1 ("Operations snapshot", "Human review control") | Removed; context lives in the crumb | An eyebrow above a heading is a ban in the project's design rules; the heading carries its own weight. |
| Tiles: Awaiting review / Ready to publish / Processing / Active control | Due within 5 business days / Past the pay-by date / Needs review / To return to supplier, each opening the filtered queue | The job is driven by the RMG 417 clock, not by pipeline stage. "Active control" was a statement, not a number. |
| Queue "prioritised by confidence and age" | Ordered by days left on the payment clock; a clock column replaces nothing, the confidence column stays | Confidence routes work; the deadline sets the order. A correctly rendered invoice's clock runs from receipt whether or not anyone has looked at it. |
| A static "paper" with one highlighted phrase | The page image `ai_parse_document` rendered, with every cited field outlined and the selected one highlighted from `ai_extract` v2.1 citations | The evidence has to be the real page, located by the model's own citations. |
| "Validate record" / "Return for correction" | "Accept as correctly rendered" (locked until each held field is confirmed or corrected; an override note is needed past a failed check) and "Return to supplier" (criteria pre-ticked from the failed checks, with the notice the supplier receives) | Returning pauses nothing (the clock never started) but costs the supplier time, so it must name the criterion. Confirming a misread is the failure the control exists to stop. |
| Field score shown alone | Score plus why: confident / low / not on page / missing; malformed values can be corrected but not confirmed | A number without its reason is not reviewable. |
| Lava #FF3621 primary button with Oat text | `--lava-strong` #C42A18 | Oat on #FF3621 is 3.4:1; the deepened lava is 5.3:1 (WCAG AA). |
| Unicode "◐" theme glyph | lucide Moon / Sun | One drawn icon system. |
| Text-only nav items and tiles | A lucide icon on each nav item and a small one in each tile label, at one stroke weight | Eight destinations scan faster with a shape beside each word; the icons are drawn, never glyphs. |
| Brand sub-line "Operations workbench" | "Accounts payable workbench" | The product has a specific job; the sub-line says which. |
| Review actions in a footer under the fields | A decision dock that stays at the bottom of the viewport while fields are reviewed, lifted with the export's overlay elevation; it drops back into the page when its form opens | The field list is long; the decision and what is blocking it must stay in view while the officer works down it. The overlay shadow separates the floating dock from the content scrolling beneath it, the one place the build uses more than the raised shadow. |
| Money in the body face | Money, ids, confidence and days left in the system mono with tabular figures | Figures line up for comparison down a column, as in the export's summary values. |
| Tiles as static figures | Tiles as buttons with a chevron that moves on hover | Each tile opens the queue filtered to what it counts. |
| Nav: Document register, Publications | Document register, Performance, Decision log | Publications had no content to stand on; readiness for the 2027 terms and an accountable decision record do. |

## Added

- Correctly rendered checks per invoice (eleven criteria from RMG 417, the Commonwealth
  Contracting Suite and ATO tax-invoice rules), with source links; the field-local ones re-run in
  the browser and on the server when a field is corrected.
- Order, delivery and clock panel: three-way match, remaining order value, receipt, clock start,
  pay-by under today's terms and under the 1 January 2027 terms.
- Intake: statements, letters and quotes, with bank-detail-change letters flagged as possible
  payment redirection and linked invoices.
- Performance: straight-through rate, wrong-but-not-held fields, a weekly late-payment chart under
  both regimes (ordinal teal pair validated with the dataviz validator, keyboard-focusable, with a
  table view), per-field accuracy by born-digital and scanned, and check detection per injected
  defect.
- Ask: Genie over the gold tables, SQL shown with every answer.
- Loading skeletons, error notices with retry, empty states, read-only mode without Lakebase,
  deep links (`?doc=DOC-000123`, `?view=queue&filter=needs_review`), focus moved to main on
  navigation, a skip link, and reduced motion.

## Removed in the distill pass

Removed because each one repeated something said elsewhere or decorated rather than informed. No function was lost.

| Removed | Why | Where the information still is |
| --- | --- | --- |
| Top-bar "Decision log" button | Duplicated the Governance nav entry, and was hidden on phones anyway | Sidebar, Governance, Decision log |
| Icons in the summary tile labels | Decoration beside a label that already names the tile; the chevron is the affordance | Tile label and chevron |
| "See all N" link under the overview queue | Second route to the same place as "Open queue" | "Open queue" button; the footer still says how many are shown |
| Second assurance-note paragraph (the clock rule) | Restated the page intro and the review screen's clock panel | Overview intro; Order, delivery and clock panel; RMG 417 link |
| "Tax invoice schema" tag on the fields panel | System detail an officer does not act on | Document type in the review header |
| "confident" under every confident score; "lowest field" under every queue percentage | Said on every row what a column head can say once | Column head "Confidence"; reasons (low, missing, not on page, N held) still shown where they apply |
| Dashed outlines of every other cited field on the page | Visual noise competing with the one region that matters | The selected field's amber highlight |
| Idle caption under the page, and the cited-text excerpt in the caption | Repeated the fields panel's instruction, and later the "Printed on the page" excerpt in the field row | Fields panel copy; the excerpt inside the selected row |
| Separate "All eleven criteria passed" row above the passed-checks disclosure | Same fact twice | The disclosure summary reads "All 11 criteria passed" |
| Repeated "check each held field..." in the verdict | Said in the verdict, the fields panel and the dock | Dock hint and field rows; the verdict keeps only the clock consequence |
