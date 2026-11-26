---
name: Improper Payments Workbench
description: A calm, dense investigator ledger where every risk score arrives with its reasons.
colors:
  lava: "#ff3621"
  lava-strong: "#c42a18"
  lava-hover: "#b02616"
  lava-active: "#a12214"
  meter-teal: "#1b5162"
  slate-teal: "#618794"
  navy-ink: "#0b2026"
  ink-muted: "rgba(11, 32, 38, 0.62)"
  hairline: "rgba(11, 32, 38, 0.24)"
  hairline-soft: "rgba(11, 32, 38, 0.12)"
  oat: "#eeede9"
  warm-white: "#f9f7f4"
  row-hover: "#edecea"
  signal-ok: "#00875c"
  signal-caution: "#ffab00"
  signal-alert: "#bd2b26"
  caution-ink: "#916c11"
  related-ink: "#c42a18"
  dark-ground: "#303f47"
  dark-surface: "#0b2026"
  dark-ink: "#e8ecf0"
typography:
  display:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 590
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 590
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 590
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  body:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
  lede:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.55
  figure:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "1.75rem"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  data-mono:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    fontFeature: "tnum"
  column-head:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    letterSpacing: "0.08em"
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  pill: "9999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "12": "48px"
components:
  button:
    backgroundColor: "{colors.warm-white}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "44px"
  button-hover:
    backgroundColor: "{colors.row-hover}"
  button-primary:
    backgroundColor: "{colors.lava-strong}"
    textColor: "{colors.warm-white}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.lava-hover}"
  button-primary-active:
    backgroundColor: "{colors.lava-active}"
  button-small:
    rounded: "{rounded.md}"
    padding: "6px 12px"
    height: "36px"
    typography: "{typography.label}"
  control:
    backgroundColor: "{colors.oat}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
    height: "44px"
  panel:
    backgroundColor: "{colors.warm-white}"
    rounded: "{rounded.lg}"
  metric-tile:
    backgroundColor: "{colors.warm-white}"
    rounded: "{rounded.lg}"
    padding: "20px"
    height: "132px"
  inset-card:
    backgroundColor: "{colors.oat}"
    rounded: "{rounded.md}"
    padding: "16px"
  risk-badge-high:
    backgroundColor: "rgba(189, 43, 38, 0.08)"
    textColor: "{colors.signal-alert}"
    rounded: "{rounded.pill}"
    padding: "4px 9px"
    typography: "{typography.data-mono}"
  risk-badge-medium:
    backgroundColor: "rgba(255, 171, 0, 0.10)"
    textColor: "{colors.caution-ink}"
    rounded: "{rounded.pill}"
    padding: "4px 9px"
    typography: "{typography.data-mono}"
  nav-link-active:
    backgroundColor: "#e8e8e6"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
  drawer:
    backgroundColor: "{colors.warm-white}"
    width: "620px"
  rule-signal-tag:
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 8px"
    typography: "{typography.label}"
  toast:
    backgroundColor: "{colors.navy-ink}"
    textColor: "{colors.warm-white}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
---

# Design System: Improper Payments Workbench

## Overview

**Creative North Star: "The Quiet Ledger"**

The workbench is an operational ledger, not a command centre. An oat ground carries warm-white panels drawn with hairline ink borders, and the case table is the dominant object on every screen. Density is high but unhurried: 14px body text at a generous 1.55 leading, 16px cell padding, and a single soft shadow under raised panels. Colour is almost entirely navy ink on oat; the one loud colour, lava, is spent on the primary action, the active-tab rule, focus, and data markers, so the investigator's eye always knows where the action is.

Every number is typeset in system mono with tabular figures (case ids, money, scores, counts, timestamps) and every score travels with its words: a risk pill reads "99 · High", a status reads "Unassigned" beside its dot. The signature interaction is a right-hand review drawer that slides over a dimmed queue and carries the evidence (ranked factors, each marked as a rule signal or measured as a share of the model, a data-drawn linked-entity graph, the payments) and the outcome form. Motion is state-only, 150 to 200ms, and collapses under reduced motion.

The system ships in light and dark. Dark mode swaps the ground to deep slate and the panels to navy, keeps every structural rule, and lowers lava to the alert red so it never glares.

**Key Characteristics:**
- Oat ground, warm-white panels, navy ink, hairline borders at 24% ink.
- Lava reserved for the primary action, the active-tab rule, focus rings and data markers.
- DM Sans for all prose and headings; system mono with tabular figures for every id, figure and score.
- 12 to 16px radii throughout, pills only for risk badges, rule-signal tags and meter ends.
- One soft raised shadow; one overlay shadow for the drawer and toasts.
- One focus ring: a 2px lava line, never doubled.
- Score plus word, status plus word: colour never carries meaning alone.

## Colors

A warm-neutral ledger palette (Databricks navy, lava, oat) with three muted signal colours used only for status.

### Primary
- **Lava** (#ff3621): the accent wherever no text sits on it. The 3px active-tab rule, the 2px focus outline, caret and selection tint, the spinner arc, flagged-payment dots, the ground-truth tick on precision meters.
- **Deep Lava** (#c42a18): the fill of the primary button, under warm-white text (5.3:1). Hover deepens to #b02616, press to #a12214.
- **Related Ink** (deep lava in light): the icon colour of related-party nodes in the graph, kept as its own role so dark mode can lift it to a legible coral.

### Secondary
- **Meter Teal** (#1b5162): the fill of every quantitative bar (factor weight meters, precision meters, legend key). Dark mode lightens the meter to #8fb0bc.
- **Slate Teal** (#618794): the status dot for unassigned cases.

### Neutral
- **Navy Ink** (#0b2026): all primary text, strong borders on hover and on the graph's subject node, and the fill of toasts. The 62% wash (ink-muted) is secondary text: labels, ledes, sub-lines, column headers.
- **Hairline** (24% ink): every border on panels, controls, tabs and table headers. **Hairline Soft** (12% ink) separates table rows and list items.
- **Oat** (#eeede9): the page ground, and the inset ground of inputs, mini summary cards, the graph well and notices, so wells read as recessed into warm-white panels.
- **Warm White** (#f9f7f4): panels, metric tiles, the drawer, the top bar (at 96%). Also the text colour on deep lava.
- **Row Hover** (warm white with 5% ink): hover and selected rows, ghost-button and icon-button hover, meter-row hover.

### Status
- **Signal Alert** (#bd2b26): high-risk badges (text, 45% border, 8% fill), escalated decisions, field errors, error notices and error toasts.
- **Signal Caution** (#ffab00): the in-review status dot and the medium-risk badge tint and border. Never used as text.
- **Caution Ink** (caution mixed 45% with ink): the text of the medium-risk badge, so the band word holds contrast on its pale tint.
- **Signal OK** (#00875c): closed status dot, cleared decisions, the cleared outcome tag.

### Dark theme
- **Dark Ground** (#303f47) for the page, **Dark Surface** (#0b2026) for panels, **Dark Ink** (#e8ecf0) for text. Lava and deep lava both become #bd2b26; alert lightens to #ff6b5e; OK lightens to #00a972; caution ink becomes #ffc94d; related ink becomes #ff8a7a. Hairlines and washes are mixes of the ink, so they follow automatically.

### Named Rules
**The One Hot Colour Rule.** Lava appears only on the primary action, the active-tab rule, focus, and small data markers (ticks, flag dots, spinner). It never fills a tile, a header, or a large area, and risk is never shown in lava: high risk uses the alert red in a pale pill.

**The Lava Under Text Rule.** Wherever text sits on a lava fill, use deep lava (#c42a18), never #ff3621.

## Typography

**Display Font:** DM Sans (variable, self-hosted; ui-sans-serif, system-ui fallback)
**Body Font:** DM Sans
**Label/Mono Font:** system mono stack (ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas)

**Character:** One humanist grotesque for every word, set at the in-between weight 590 for headings and 550 for emphasis, paired with the platform's own monospace for every figure so columns of money and scores align like a ledger.

### Hierarchy
- **Display** (590, 2.25rem, 1.15, -0.02em): the one page H1 ("Payment review queue", "Precision monitoring"). Steps down to 1.75rem under 680px.
- **Headline** (590, 1.375rem, 1.15): drawer title (the entity name).
- **Title** (590, 1rem, 1.15): section headings in the drawer and panel heads.
- **Body** (400, 0.875rem, 1.55): table cells, factor descriptions, all running text.
- **Lede** (400, 1rem, 1.55, muted, max 64ch): the single sentence under each H1.
- **Label** (400, 0.75rem, muted): field labels, metric labels and footers, sub-lines under entities, table foot.
- **Figure** (mono 400, 1.75rem, 1.2, -0.03em, tabular): metric tile values; 1.375rem on mobile. Drawer summary figures use mono at 1rem, weight 550.
- **Data Mono** (mono 400, 0.75rem, tabular): case ids, risk pills, tab counts, history timestamps, the brand mark.
- **Column Head** (mono 500, 0.6875rem, uppercase, 0.08em): table column headers only.

### Named Rules
**The Figures Are Mono Rule.** Every id, amount, score, count and timestamp is set in the mono stack with tabular figures; prose is never set in mono.

**The Heading Stands Alone Rule.** A heading carries its own weight. Context (team, case reference) goes in the top-bar identity line or beside the title as a mono id, never as a small label stacked above the heading.

## Layout

A single centred workspace, max 1440px, with 32px padding (16px under 680px). The page head runs H1 and lede left with the synthetic-data note card right, aligned to the baseline. Below it: four equal metric tiles in a row (two columns under 1000px), the status tabs on a hairline, then one panel holding the filter bar (search at 1.5fr, three selects, clear button) and the case table with its footer.

Spacing is a 4px-based scale (4, 8, 12, 16, 20, 24, 32, 48). Sections inside the drawer are separated by 24px gaps and hairline top borders with 20px padding; panel heads pad 16px by 20px. Every interactive control is at least 44px tall (36px for small buttons).

The precision view uses a 1.6fr / 1fr two-panel grid that stacks under 1000px. Wide content (the status tabs, the 940px case table) scrolls inside its own box; the shell's children are allowed to shrink so nothing pushes the page wider than the viewport.

Under 680px: the top bar becomes a two-row grid (brand and theme toggle on the first row, the view switch on the second) with the brand name truncating; the H1 steps down to 1.75rem and the page head stacks; the metric tiles stay two by two (12px gap, 112px tall, 16px padding); filters stack to one column; the case table drops its header row and each case becomes a stacked block padded 16px over a soft hairline (reference and risk badge on line one, then entity, signal in muted label size, then status and value; the programme column is hidden); meter rows put the track on its own line; the drawer goes full width with 16px side padding.

**The Queue Is The Page Rule.** The case table is the largest object on the queue screen and the top-ranked case stays above the fold at 1440 by 900; nothing (charts, banners, hero art) is placed between the metric tiles and the table.

## Elevation & Depth

Depth is mostly tonal: warm-white panels sit on an oat ground, and oat wells sit inside warm-white panels. Two shadows exist and both are soft, ink-tinted and offset straight down.

### Shadow Vocabulary
- **Raised** (`box-shadow: 0 2px 8px` ink at 8%): metric tiles and the main panels. The only resting shadow.
- **Overlay** (`box-shadow: 0 16px 48px` ink at 22%): the review drawer and toasts, things above the page.

The drawer's backdrop dims the queue with navy at 30%; the drawer's sticky head is warm white at 97% with a 10px backdrop blur.

Focus is drawn by line, not by shadow: the 2px lava outline, offset 3px outside most elements and pulled 2px inside on queue rows. The component library's two-ring focus shadow on tabbable elements is suppressed so only the lava ring ever shows.

### Named Rules
**The One Soft Shadow Rule.** Resting surfaces get the raised shadow or none; nothing hovers, glows or lifts on hover. Hover is shown by border and tone, never by elevation.

**The One Ring Rule.** Focus is a single 2px lava line. Where an outset would clip or collide (table rows), pull the same outline inside with a negative offset; never stack it with a library focus shadow, a per-cell inset shadow, or a glow.

## Shapes

Gently rounded throughout: 12px on controls, buttons, nav links, notices and inset cards; 16px on panels, metric tiles and the graph well; 8px on small squares (brand mark, evidence index chips, skeletons, meter-row hover). Full pills are reserved for risk badges, rule-signal tags, the active-tab rule and meter track ends. Status is a 7px dot; flagged payments a 6px lava dot. Every container is drawn with a 1px hairline; the strong ink border appears only on hover, on the selected outcome choice, and on the graph's subject node.

## Components

### Buttons
Quiet and outlined; only the commit action is filled.
- **Shape:** gently rounded (12px), 44px tall, 10px by 16px padding, weight 550, 0.02em tracking.
- **Default:** warm white with a hairline border. Hover: ink border and row-hover tone, 150ms standard ease.
- **Primary:** deep lava fill and border, warm-white text; hover and press deepen. One per view (the outcome submit, "Assign to me").
- **Small:** 36px, 6px by 12px, label size (pager, retry). **Ghost:** transparent border and fill.
- **Icon button:** 44px square, hairline border, lucide icon at 18px, 1.75 stroke (theme toggle, drawer close).
- **Disabled:** 55% opacity, not-allowed cursor.

### Risk badge (signature)
- **Style:** mono pill, minimum 96px wide, 4px by 9px, showing the score and the band word ("99 · High"). High: alert text, alert 45% border, alert 8% fill. Medium: caution tint with ink-mixed text (dark mode #ffc94d).

### Status label
- **Style:** muted label text preceded by a 7px dot (slate teal unassigned, caution in review, OK closed); the holder's name sits on a second line indented to the text.

### Cards / Containers
- **Panel:** warm white, 16px radius, hairline border, raised shadow, clipped. Panel head 16px by 20px with a hairline below.
- **Metric tile:** warm white, 16px radius, raised shadow, 20px padding, 132px minimum; label top, mono figure, muted foot.
- **Inset card** (mini summary, assurance note, holder strip, decision, notice): oat ground, 12px radius, hairline, 16px padding. Decisions and error notices tint the ground and border with OK or alert.

### Inputs / Fields
- **Style:** oat ground, hairline border, 12px radius, 9px by 12px, 44px tall; muted label above at label size with 4px gap.
- **Focus:** 2px lava outline at 3px offset (shared by every focusable element); no second ring or glow. Hover: ink border.
- **Error:** alert border via `aria-invalid`, alert label-size message below. Textareas start at 112px and resize vertically.
- **Outcome choice:** 44px radio tiles on oat in a two-column row; checked turns warm white with an ink border and weight 550; focus draws the lava ring on the tile.

### Navigation
- **Top bar:** 64px, warm white at 96% over a hairline. Brand mark (28px mono square, ink border, 8px radius) plus name at 590; nav links 40px tall, 12px radius, muted until hover; the current page is ink at 590 on warm white with 7% ink. Identity block right-aligned at label size, hidden under 1000px.
- **Status tabs:** text tabs 24px apart on a hairline, muted with a mono count; the selected tab is ink at 590 with a 3px lava pill rule overlapping the hairline.

### Case table
- **Style:** mono uppercase column heads at 0.6875rem, 16px cells divided by soft hairlines, money right-aligned in mono. Rows are keyboard-focusable buttons into the drawer; hover and selected rows take the row-hover tone. A focused row takes the same 2px lava outline on the row itself at a -2px offset, so the ring sits inside the table edge; no box-shadow.

### Review drawer (signature)
- A native modal dialog, 620px wide (full width on mobile), sliding in from the right in 200ms with the out-ease over a navy 30% backdrop; overlay shadow, sticky blurred head with the entity name, mono case id and meta line (three segments, each held on one line, separated only by a 16px column gap with no dot or rule between them; the line wraps between segments). Body sections: three mini summary cards, the holder strip, ranked factors, the linked-entity graph, payments, assurance note, and the outcome form.

### Contributing factor
- A 28px mono index chip beside the factor title and its muted description, then one evidence line at label size. Rules and the model are in different units and are never drawn on one scale: a **rule factor** carries a "Rule signal" tag (hairline pill, 1px by 8px, ink text, never shrinks or wraps) and a sentence saying a defined pattern matched; a **model factor** carries a 96px by 4px meter-teal bar showing its share of the model's own contribution, with the percentage written beside it.

### Linked-entity graph
- An SVG in an oat well (16px radius), laid out in three columns: the subject, the shared attributes (accounts, addresses, officers), and the entities they lead to. Warm-white node rectangles with hairline strokes and a lucide icon per node type; the subject in a 1.5px ink stroke; related parties (including an officer or assessor who shares the subject's address) in a 7% lava-tinted fill with a 50% lava stroke and a related-ink icon; edges at 38% ink, 1.25 stroke. The same links are listed as text beneath.

### Precision meters
- Rows of name, 12px track (4px radius, 10% ink) with a meter-teal fill and a 2px lava ground-truth tick, and a right-aligned mono value. Hover or focus tints the row and swaps its own muted sub-line (the decision count) for the breakdown in ink; nothing floats over a neighbouring row and there is no tooltip.

### Feedback
- **Toast:** navy with warm-white text, 12px radius, overlay shadow, bottom right; rises 12px on show. Error toasts use alert red.
- **Skeleton:** soft-hairline shimmer bars, 8px radius. **Empty state:** centred, 48px padding, ink title at 590, muted explanation at most 52ch.

## Do's and Don'ts

### Do:
- **Do** put every score next to its band word and every status dot next to its label.
- **Do** set ids, money, scores, counts and times in the mono stack with tabular figures.
- **Do** use deep lava (#c42a18) for any filled control that carries text, and limit it to one primary action per view.
- **Do** draw containers with a 1px hairline at 24% ink and round them at 12 or 16px.
- **Do** keep motion to state changes at 150 to 200ms with the standard or out ease, and honour reduced motion.
- **Do** label synthetic data on every surface with the status-note card beside the page head.
- **Do** reveal detail in place (swap a row's own sub-line) rather than in a floating tooltip.

### Don't:
- **Don't** build a chart-heavy "command centre": no red alarm tiles, no hero charts above the queue, no large lava fills.
- **Don't** colour risk in lava; high risk is the alert red in a pale pill.
- **Don't** place a small label or kicker above a heading; context belongs in the top bar or beside the title.
- **Don't** use Unicode glyphs as icons; use the lucide set at 18px and 1.75 stroke.
- **Don't** add hover lift, glows, or hard offset shadows; the raised and overlay shadows are the whole vocabulary.
