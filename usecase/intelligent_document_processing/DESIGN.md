---
name: Document Assurance Workbench
description: An accounts payable workbench where every extracted value sits beside the page region it came from, and the payment clock sets the order.
colors:
  lava: "#ff3621"
  lava-strong: "#c42a18"
  lava-hover: "#aa2313"
  lava-active: "#961e10"
  navy-ink: "#0b2026"
  ink-muted: "rgba(11, 32, 38, 0.66)"
  hairline: "rgba(11, 32, 38, 0.24)"
  hairline-soft: "rgba(11, 32, 38, 0.12)"
  oat: "#eeede9"
  warm-white: "#f9f7f4"
  row-hover: "#ebebe8"
  paper-white: "#ffffff"
  signal-ok: "#00875c"
  signal-warn: "#ffab00"
  signal-danger: "#bd2b26"
  warn-ink: "#796033"
  deep-teal: "#1b5162"
  slate-teal: "#618794"
  series-current: "#7fa3af"
  series-2027: "#1b5162"
  dark-ground: "#303f47"
  dark-surface: "#0b2026"
  dark-ink: "#e8ecf0"
  dark-lava: "#bd2b26"
  dark-ok: "#00a972"
  dark-danger: "#ff6b5e"
  dark-warn-ink: "#ffc94d"
  dark-series-current: "#4f7c8a"
  dark-series-2027: "#a9cbd6"
typography:
  display:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  subtitle:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  body:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  body-small:
    fontFamily: "DM Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
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
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  data-mono:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: "tnum"
  column-head:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.4
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
    padding: "0 16px"
    height: "44px"
  button-primary:
    backgroundColor: "{colors.lava-strong}"
    textColor: "{colors.warm-white}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.lava-hover}"
    textColor: "{colors.warm-white}"
  button-primary-active:
    backgroundColor: "{colors.lava-active}"
  button-ghost-hover:
    backgroundColor: "{colors.hairline-soft}"
    textColor: "{colors.navy-ink}"
  button-small:
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  nav-item:
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "44px"
  nav-item-active:
    backgroundColor: "{colors.navy-ink}"
    textColor: "{colors.warm-white}"
  filter-pill:
    textColor: "{colors.ink-muted}"
    typography: "{typography.body-small}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "36px"
  filter-pill-active:
    backgroundColor: "{colors.navy-ink}"
    textColor: "{colors.warm-white}"
  input:
    backgroundColor: "{colors.oat}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "40px"
  card:
    backgroundColor: "{colors.warm-white}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.lg}"
  summary-tile:
    backgroundColor: "{colors.warm-white}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.lg}"
    padding: "20px"
  tag-held:
    textColor: "{colors.warn-ink}"
    rounded: "{rounded.pill}"
    padding: "1px 7px"
  tag-confirmed:
    textColor: "{colors.signal-ok}"
    rounded: "{rounded.pill}"
    padding: "1px 7px"
  tag-fail:
    textColor: "{colors.signal-danger}"
    rounded: "{rounded.pill}"
    padding: "1px 7px"
  classification-pill:
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.pill}"
    padding: "4px 8px"
  toast:
    backgroundColor: "{colors.navy-ink}"
    textColor: "{colors.warm-white}"
    rounded: "{rounded.md}"
    padding: "16px 20px"
---

# Design System: Document Assurance Workbench

## Overview

**Creative North Star: "The Evidence Desk"**

A calm, warm operational workbench for officers who decide one invoice at a time. Oat ground, warm-white panels and navy ink carry nearly everything; colour is spent on meaning, not decoration. The one accent, lava, belongs to the primary action and to focus. Warn amber is the colour of evidence: it outlines the cited region on the rendered page and tints the field row it belongs to, so the eye travels between value and source by colour alone.

The world is pinned by the Genie Design export (`design/document-assurance-workbench.html`) and was carried into an AppKit React app with the deltas recorded in `design/DESIGN-HANDOFF.md`. It is a 248px sidebar plus 72px blurred top bar shell, panels on hairline borders with one soft raised shadow, DM Sans throughout and the system mono for every figure a reader compares down a column: money, ids, confidence, days left. Density is moderate: 44px controls, 20px panel gutters, row lists divided by soft hairlines rather than boxed.

Motion is state only, 150ms to 200ms on one standard ease, and collapses to nothing under reduced motion. The signature moment is the evidence box drawing in on the page when a field is selected.

**Key Characteristics:**
- Oat ground, warm-white panels, navy ink; the active nav item and active filter invert to navy.
- Lava (deepened to #C42A18 under text) only for the primary action, checked controls in the decision form, caret and focus ring.
- Warn amber is the evidence colour: page highlight, held field tint, held tag.
- Mono with tabular figures for money, ids, confidence, days left and summary values.
- 12px controls, 16px panels, pills for filters, tags and the OFFICIAL classification.
- One raised shadow at rest; the overlay shadow only on things that float above scrolling content.

## Colors

A warm neutral field of oat and warm white under navy ink, with one hot accent and three signal hues used strictly for status.

### Primary
- **Lava** (#ff3621): the Databricks accent at full strength, used only where no text sits on it: the 2px focus outline, the focused chart bar stroke, and the soft input focus halo.
- **Deep Lava** (#c42a18): the primary action's fill wherever text sits on lava (5.3:1 against warm white). Also checked checkboxes in the return form, the text caret and the native `accent-color`. Hover deepens to #aa2313, press to #961e10.

### Secondary
- **Deep Teal** (#1b5162): the data hue. Meter fills (order value used), the corrected-field tag, and the stronger step of the readiness chart.
- **Slate Teal** (#618794): the quiet data hue. Processing and not-an-invoice status dots, and the dashed outline of cited fields that are not selected.
- **Readiness pair** (#7fa3af current terms, #1b5162 2027 terms; dark #4f7c8a and #a9cbd6): an ordinal one-hue pair for the same measure under two regimes, the stricter 2027 terms carrying the stronger step. Validated with the dataviz validator (`--ordinal`) on both surfaces. Scoped to the chart.

### Tertiary (signals)
- **Signal OK** (#00875c): ready status dot, passed checks, confirmed tag, recorded decision.
- **Signal Warn** (#ffab00): the evidence highlight on the page, the needs-review dot and the selection colour. Never used as text.
- **Warn Ink** (#796033): warn as legible text: held tag, due-soon clock, unknown checks.
- **Signal Danger** (#bd2b26): overdue clocks, low confidence scores, failed checks, alert summary values, payment-redirection risk, form errors.
- Each signal has a translucent tint (ok 12%, warn 16%, danger 11% opacity) for tag and row backgrounds.

### Neutral
- **Navy Ink** (#0b2026): all text, the brand mark, the active nav and filter fill, the toast.
- **Muted Ink** (navy at 66%): secondary copy, metadata, labels, inactive nav.
- **Hairline** (navy at 24%): panel borders, control borders, axes.
- **Soft Hairline** (navy at 12%): row dividers inside panels, ghost hover fill, chart grid.
- **Oat** (#eeede9): the page ground, input fields, the page viewer well.
- **Warm White** (#f9f7f4): panels, sidebar, default buttons.
- **Row Hover** (#ebebe8): warm white mixed 5% toward ink, the hover on every clickable row and tile.
- **Paper White** (#ffffff): only the rendered invoice page, so the document reads as paper against the oat well.

### Dark theme
Ground #303f47, panels #0b2026, ink #e8ecf0. Lava and deep lava both become #bd2b26; ok lifts to #00a972, danger to #ff6b5e, warn ink to #ffc94d. Hairlines, tints and hover are derived from ink and surface by the same mixes, so they follow automatically. The theme is a user toggle on `data-theme`, persisted, not the OS preference.

### AppKit mapping
AppKit UI's shadcn variables are pointed at the palette so its components (Genie chat, toasts) follow the app's own theme: background to oat, foreground and primary to navy ink, card and popover to warm white, secondary, accent and border to the soft hairline, input to the hairline, muted foreground to muted ink, ring to lava, destructive to danger. App tokens are named `--lava`, `--fg-muted` and `--line` so they never collide with shadcn's `--accent`, `--muted` and `--border`.

### Named Rules
**The One Accent Rule.** Lava marks the action that moves the decision forward and the element that has focus. A second lava element on a screen is a defect unless it is a checked control inside that same decision.

**The Amber Is Evidence Rule.** Warn amber means "look here on the page": the cited region, the held field, the held tag. It is not a generic warning colour and never carries text at full strength; use warn ink.

**The Deepened Lava Rule.** Text never sits on #FF3621. Where lava is a fill under text, use #C42A18.

## Typography

**Display Font:** DM Sans (variable, self-hosted, with ui-sans-serif and system-ui fallback)
**Body Font:** DM Sans
**Label/Mono Font:** the system mono stack (ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas) with tabular figures

**Character:** One humanist grotesk at slightly tightened tracking for headings, set against the platform mono for numbers. The mono is functional, not stylistic: it appears where a figure is compared.

### Hierarchy
- **Display** (600, 2.25rem, 1.15, -0.02em): the page H1 greeting; drops to 1.75rem below 820px.
- **Headline** (600, 1.75rem, 1.15): the review workspace H1 (supplier name).
- **Title** (600, 1.375rem, 1.15): panel headings (H2).
- **Subtitle** (600, 1rem, 1.15): H3 and stage names; verdict titles step up to 1.125rem.
- **Body** (400, 1rem, 1.55): default text; intros capped at 68ch, prose facts at 62ch.
- **Body small** (400, 0.875rem): panel copy, crumb, buttons (600), filters, check labels (600).
- **Label** (400, 0.75rem): metadata lines, field names, tile footers, sidebar foot.
- **Figure** (mono 600, 1.75rem, -0.03em, tabular): summary tile values.
- **Data mono** (mono 600, 0.875rem, tabular): confidence scores, field scores, money, ids.
- **Column head** (mono 500, 0.6875rem, 0.08em, uppercase): table column headers, queue head, sidebar nav group labels, list group labels within a panel. Nav group labels use 0.75rem 600.

### Named Rules
**The Figures In Mono Rule.** Money, document ids, confidence and day counts are always set in the mono with tabular numerals. Prose numbers stay in DM Sans.

**The Label Is Not A Kicker Rule.** Uppercase mono is reserved for column heads and group labels inside a list or the nav. It never sits above a page or panel heading; context above an H1 belongs in the crumb.

## Layout

A fixed two-column shell: a 248px sticky sidebar and a main column with a 72px sticky top bar (oat at 92% with a 12px backdrop blur). Content is capped at 1500px with 32px padding.

- **Spacing:** a 4px-based scale (4, 8, 12, 16, 20, 24, 32, 48). Panels use 20px horizontal gutters; rows use 16px vertical padding in queues and 12px in field and check lists; page sections stack at 24px; page head sits 32px above content.
- **Overview:** four summary tiles in a row (2 columns at 1180px and below), then a 1.65 : 0.75 work grid: review queue beside the numbered pipeline and assurance note.
- **Queue rows:** a fixed column grid (title, 128px status, 80px confidence, 158px clock, 20px chevron); below 820px the confidence column drops and status wraps under the title.
- **Review workspace:** document view and field column at 1 : 1, the document view sticky under the top bar; the decision dock is sticky to the viewport foot.
- **Responsive:** at 1180px all two-column grids stack and the viewer becomes static at 70vh. At 820px the sidebar becomes a top strip with horizontally scrolling nav, nav labels and foot hide, crumb hides, page heads stack. At 520px tiles compress and lose their icons.
- **Targets:** buttons and selects have a 44px minimum height; small buttons and filters 36px.

## Elevation & Depth

Flat tonal layering with one soft lift. Panels separate from the oat ground by colour and a hairline, plus a barely-there raised shadow. Rows inside panels never lift; they divide with soft hairlines and tint on hover.

### Shadow Vocabulary
- **Raised** (`box-shadow: 0 2px 8px` navy at 8%): every card and panel at rest, and the rendered page inside the viewer.
- **Overlay** (`box-shadow: 0 16px 48px` navy at 22%): only things floating above scrolling content: the sticky decision dock, the dialog, the toast. When the decision dock expands into the page flow it drops back to raised.

### Named Rules
**The Float Earns Overlay Rule.** The overlay shadow is for elements that sit above content scrolling beneath them. Anything in the flow of the page uses raised or nothing.

## Shapes

Gently rounded, never sharp, never soft-blob. Controls, nav items, notices and toasts use 12px; panels, cards, tiles, the dialog and the document view use 16px; skeletons, small hit areas, the page well and the printed-value box use 8px. Filters, tags, meters and the OFFICIAL classification are full pills. Stage numbers and status dots are circles. Borders are 1px hairlines; the one dashed border is the "printed on the page" box under a held field, and the dashed outline marks cited fields that are not selected. Evidence boxes on the page have 4px corners and a 3px warn stroke.

## Components

### Buttons
Quiet and solid: outlined warm white by default, filled only for the one primary action.
- **Shape:** 12px radius, 44px tall, 16px horizontal padding, 600 weight at 0.875rem with 0.01em tracking; 16px lucide icon at an 8px gap.
- **Default:** warm white with a hairline border; hover darkens the border to ink.
- **Primary:** deep lava fill and border with warm-white text; hover and press deepen.
- **Ghost:** transparent; hover fills with the soft hairline.
- **Small:** 36px tall, 12px padding. **Icon:** 44px square (theme toggle).
- **Disabled:** 55% opacity and a not-allowed cursor. Accept stays disabled until every held field is confirmed or corrected.
- **Link button:** underlined text, 1px underline at 3px offset.

### Filter pills
- **Style:** 36px pill with a hairline border, muted text at 0.875rem, a mono count.
- **State:** hover darkens text and border to ink; pressed (`aria-pressed`) inverts to a navy fill with warm-white text.

### Cards / Panels
- **Corner Style:** 16px.
- **Background:** warm white on oat.
- **Shadow Strategy:** raised at rest (see Elevation).
- **Border:** 1px hairline.
- **Internal Padding:** panel head 20px with a soft hairline beneath; heading plus muted 0.875rem copy; panel foot 12px x 20px in 0.75rem muted text.

### Summary tiles
Buttons shaped as cards: muted label with a small lucide icon at 70% opacity, mono figure value (danger for the overdue count), muted foot with a chevron. Hover tints to row hover, darkens the border to ink and nudges the chevron 3px right; press drops 1px. Each tile opens the queue filtered to what it counts.

### Inputs / Fields
- **Style:** oat fill on warm-white panels, 1px hairline, 12px radius, 40px tall; search carries a 15px muted lucide icon at 12px from the left.
- **Focus:** border turns deep lava with a 2px lava halo at 45%.
- **Checkbox (decision form):** custom 18px box, 5px corners, hairline stroke; checked fills deep lava with a warm-white tick.
- **Error:** danger text at 0.875rem under the field.

### Navigation
Sidebar nav of full-width 44px rows, 12px radius, muted text at 520 weight with a 17px lucide icon and an optional mono count at the right. Hover fills the soft hairline and darkens text; the current page inverts to a navy pill with warm-white text. Groups (Workspace, Governance) are labelled in uppercase mono. Below 820px the nav becomes a horizontal scrolling strip. The top bar carries the crumb (muted, current page in ink at 560) and the actions: theme toggle, Decision log, and the primary Ingest documents.

### Tags and status
- **Tags:** pills at 0.6875rem 600, 1px x 7px, optional 12px icon. Held (warn tint, warn ink), confirmed (ok tint, ok), corrected (deep teal tint and text), fail (danger tint, danger), neutral (hairline outline, muted).
- **Status text:** 0.75rem muted label led by an 8px dot: warn for needs review, ok for ready, danger for exception, slate teal for processing and not-an-invoice, and a hollow muted ring for awaiting delivery.
- **Clock:** 650 weight at 0.875rem, tabular; danger when overdue, warn ink when due soon, muted when not started.

### Evidence field row (signature)
Each extracted field is a row: muted field name with tags, value at 600, and a right-aligned mono score with its reason underneath ("confident", "low", "not on page"). Held rows carry a faint warn tint; the selected row a full warn tint. Selecting a row draws its cited box on the page in warn (fill at 22%, 3px stroke) with a 200ms draw-in, scrolls it into view, and shows a warn-tinted caption under the viewer. Held rows open a dashed "printed on the page" box in mono and the confirm and correct actions.

### Decision dock
A card stuck to the viewport foot with the overlay shadow while fields are reviewed: a muted hint naming what still blocks acceptance, then Return to supplier and Accept as correctly rendered. When its form opens it drops into the page flow with the raised shadow; the return form pre-ticks the failed criteria and shows the supplier notice in an oat box.

### Pipeline stages
Numbered stages: a 30px circle with a hairline and a mono number, filled navy when complete, beside the stage name and a 0.75rem muted line with a live mono count. Stages divide with soft hairlines.

### Data tables and chart
Tables: uppercase mono column heads, 12px x 20px cells on soft hairline rules, numeric columns right-aligned tabular, clickable rows tint on hover. The readiness chart uses the ordinal teal pair, 11px muted axis text, hairline axes, soft grid, mono value labels, a faint ink crosshair band, keyboard-focusable bars outlined in lava on focus, a square-swatch legend and a table view.

### States
Shimmering skeleton bars in the soft hairline (8px corners, 1.4s), error notices with a danger tint and a Try again small button, centered empty states with an ink title over muted copy, the navy toast at the bottom right, and the dialog on warm white with a navy scrim at 38%.

## Do's and Don'ts

### Do:
- **Do** keep lava to the primary action, the checked control in the decision form, and focus; use #C42A18 wherever text sits on it.
- **Do** use warn amber for evidence: the page highlight, the held tint, the held tag; use warn ink (#796033 light, #ffc94d dark) when it must be read as text.
- **Do** set money, ids, confidence and days left in the mono with tabular figures.
- **Do** give every score its reason, and show confidence beside the clock rather than in place of it; queues order by days left.
- **Do** use raised for cards at rest and overlay only for the floating dock, dialog and toast.
- **Do** use one drawn icon system (lucide) at one stroke weight, sized 12 to 22px per context.
- **Do** keep motion to state changes at 150ms or 200ms on `cubic-bezier(0.2, 0, 0, 1)` (or the 0.16, 1, 0.3, 1 ease-out for entrances), and honour reduced motion.

### Don't:
- **Don't** put an uppercase label above a page or panel heading; the crumb carries context.
- **Don't** set text on #FF3621.
- **Don't** use warn amber at full strength as a text colour, or as a general-purpose warning fill.
- **Don't** add a second accent or a bulk-approve action; acceptance is per invoice and locked behind held fields.
- **Don't** let AppKit components fall back to their shadcn defaults or the OS colour scheme; map them to the palette.
- **Don't** use Unicode glyphs as icons.
