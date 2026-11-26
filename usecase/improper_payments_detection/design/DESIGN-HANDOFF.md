# Improper Payments Workbench - design handoff

`improper-payments-workbench.html` is the source design (Genie Design export). The production app
is `app/nba-payments-workbench` (AppKit: Node + React). The prototype is one static page with five
hard-coded cases; the app keeps its layout, tokens, copy and interactions and replaces every
placeholder with governed data and real, recorded decisions.

## Kept as designed

- Tokens (colour, type scale, spacing, radii, elevation, motion) copied over, including the dark
  theme and its persisted toggle. Token names change only where AppKit UI's shadcn variables would
  collide (`--accent` → `--lava`, `--muted` → `--fg-muted`, `--border` → `--line`).
- Top bar (brand mark, name, identity, theme toggle). Page head with the "Synthetic demonstration
  data / Scores are indicators, not findings" note. Four metric tiles, status tabs, the filter bar
  (search, risk band, program, sort, clear), the case table and its footer with the model refresh
  time.
- The right-hand review drawer over a dimmed queue: case summary (risk score, payment value, queue
  age), "Why this case was prioritised" with ranked factors, "Linked entity view", the assurance
  note verbatim, and "Record investigation outcome" with required notes and `aria-invalid`.
- Interactions: filter and sort, keyboard-openable rows (Enter / Space), selected-row highlight,
  Esc and backdrop close, notes required before a decision, confirmation then close.

## Changed, and why

| Prototype | App | Reason |
| --- | --- | --- |
| Kicker "Integrity operations · Daily review" above the H1, and "Case IP-2048" above the drawer title | The context moved into the top bar identity line; the case reference sits beside the title as a mono id | The heading carries its own weight; an eyebrow above a heading is a ban in the project's design rules. |
| Unicode "◐" and "×" icons | lucide Moon / Sun and X | One drawn icon system at one stroke weight. |
| Lava `#FF3621` fill under Oat text on the primary button | `--lava-strong` `#C42A18` | Oat on `#FF3621` is 3.4:1; the deepened lava is 5.3:1 (WCAG AA). `#FF3621` stays the accent where no text sits on it. |
| Four CSS-rotated lines between four fixed boxes | An SVG drawn from `gold_case_graph_node/edge`: subject, shared attributes, related entities, with kind icons and the same links listed as text | The graph has to show each case's real links, and must not depend on reading the drawing. |
| Two outcome buttons ("Clear indicator", "Escalate for assessment") with notes | Outcome choice, a reason for that outcome, required notes, and one submit button whose label follows the choice | Precision feedback needs the reason (for example "Records were linked in error" tells entity resolution it was wrong). |
| Tabs All / Unassigned / In review / Closed today | The same, plus "Assigned to me" | Investigators work their own holdings first. |
| Outcome increments a counter | Assignment and outcome are written to Lakebase, checked against Unity Catalog as the investigator, one final outcome per case | Accountable, auditable decisions; a score is never a finding. |
| Under 680px: metric tiles in one column; the case table scrolls sideways | Tiles in a 2×2 grid; each case row becomes a stacked card (reference and risk, entity, signal, status and value) | One column pushed the queue a full screen below the fold on a phone; a 940px table that scrolls sideways hides the risk and value an investigator scans for. |
| Factor list with no weighting | Model factors show their share of the model's contribution; rule factors are tagged "Rule signal" | Rule matches and SHAP values are different units and are never drawn on one scale. |
| "Showing 5 illustrative cases" | "Showing N of M cases" with paging (25 per page) | A real queue holds 100–200 cases. |

## Added

- The linked entity view is evidence-first: an officer or assessor registered at one of the
  subject's own addresses is drawn as a related party through that shared address, ahead of
  incidental approvers.
- **Precision view** (top-bar navigation): outcomes recorded, share that held up at triage, share
  cleared, model precision against seeded ground truth; precision by primary signal and by risk
  band as single-series meters (bar = held up, tick = ground truth), with hover detail; model
  evaluation; and the most recent decisions read live from the case store.
- In the drawer: an assignment strip ("Assign to me", "Return to queue", "In review with …"), the
  relative weight and source (rule signal or model pattern) of each factor, the payments in the
  case with flagged ones marked, the recorded decision on closed cases, and the case record.
- Loading skeletons, error notices with retry, and empty states that say what to do next, for
  every panel and every tab; a read-only mode when Lakebase is not connected.
- Deep links: `?case=IP-2048`, `?tab=review`, `?view=precision`; browser back closes a case.
- The drawer is a native modal dialog (focus trap, inert background), animates in and out, returns
  focus to its row, and respects reduced motion.
