# Infrastructure Operations Centre - product and design specification (v2)

Supersedes the v1 heavy-vehicle console in `critical-infrastructure-operations.html` (kept for
history; see `DESIGN-HANDOFF.md`). v2 keeps v1's layout grammar, copy voice and interaction
patterns, re-pointed at a national cross-sector operating picture, and adopts the Databricks brand
(`../app/nba-critical-infra/.databricks-impeccable.md`). The built app is the reference
implementation.

## Purpose

One operating picture across roads, rail, water and energy, run by many operators. The centre
answers three questions, in this order:

1. **What needs action now?** Incidents ranked by risk.
2. **Why, and what else fails if it fails?** Evidence, hazard context and downstream dependants.
3. **What did we decide?** Dispatch a crew, notify the operator, or keep monitoring, on the record.

## Persona and context

A duty officer in a national coordination centre (Canberra time), reviewing data shared by state
road and rail agencies, water utilities and energy networks. Primary device: a desktop or laptop
monitor, often mirrored to a wall screen or projector. Secondary: a tablet during handover.
Light theme only.

## Information architecture

A single scrolling screen with a sticky primary nav (scroll-spy highlights the section in view):

| Nav | Section | Purpose |
| --- | --- | --- |
| Overview | Hero + feed status + sector health | The headline, the health of the feeds, and one tile per sector |
| Incidents | Incident queue | The work list, filterable by sector, rating, status and text |
| Network map | Map + active warnings | Where risk sits, hazard footprints, and cascades for a selected incident |
| Assets | Asset risk register | Highest-risk assets across sectors and the factor driving each |
| Shift handover | Checks + decision record | What the next watch inherits, and the audit trail |

The review dialog opens from the queue, the map or the register.

## Modules

### Hero and feed status
* Eyebrow: "National operating picture · {weekday date · time zone}".
* Headline: "{Greeting}, {first name}. {N} incidents need action across {k} sectors." Number
  words up to ten; "No incidents need action." when clear.
* Feed status card: latest reading, sensors reporting (of total), processing lag, risk engine run.
  Pill: "All feeds current" or "Data as of HH:MM" once the run is more than 90 minutes old.

### Sector health tiles (4)
* One tile per sector with its icon, colour rule (top border) and name; extreme count or "No
  extreme".
* Big number: open incidents (after officer decisions). Facts: assets, in alarm, not reporting,
  dependants at risk (distinct downstream assets).
* People are **never** summed at sector level (supply chains nest, so totals double-count).
* The whole tile is a button: it filters the incident queue to that sector and scrolls to it.
* Under the tiles: readings today, sensors reporting, median detection time (each with the previous
  run), quarantine rate, late readings.

### Incident queue
* Row: score and rating label · sector badge, asset name, operator · incident title and evidence
  summary (metric value against its alarm, hazard, overdue inspection) · place, age, downstream
  impact · action.
* One primary button: the first open incident. Decided incidents dim and show their disposition.
* Filters: text (asset, operator, place), sector, rating, status. Eight rows, then "Show all".
* States: skeleton rows; teaching empty state; "No incidents match" with "Clear filters"; error
  with "Try again".

### Network map
* Equirectangular SVG of the states (Natural Earth, public domain); the same projection places
  assets.
* Layers, bottom to top: state outlines; warning footprints (warning amber, dashed); all assets as
  small sector-coloured dots; open incidents as larger markers sized and ringed by rating (extreme:
  Lava ring; high: Navy ring; medium: white ring); decided incidents at 40% opacity.
* Region focus: National, NSW & ACT, VIC & TAS, QLD, SA, WA, NT. Sector toggles hide or show
  layers.
* Selecting an incident frames it and its direct dependants, draws supply links (solid for direct,
  dashed for second hop), and opens a side card: rating, title, dependants (top five, then "+N
  more"), "Review incident".
* Active warnings list beside the map: icon, title, type · severity · time remaining, assets inside
  by sector, linked incidents. Selecting a warning zooms to its footprint.
* Markers are keyboard-focusable buttons with descriptive labels; the queue remains the accessible
  primary path.

### Review dialog
* Head: "Incident review · {sector badge}", asset name (receives focus), title · operator · place ·
  age.
* Score: risk number, "Likelihood × consequence" line, rating or decision pill.
* Why this was flagged: four factor bars (value, weight, contribution), largest first; consequence
  sentence.
* Evidence: 24-hour line of the triggering metric with warning and alarm limits.
* Hazard context (when inside a warning).
* If this fails: dependants grouped as "Directly supplied" and "Then, through those", each with
  sector badge, dependency type and people served.
* Recommended first action and responsible operator; decision record explanation; optional notes.
* Actions: Continue monitoring · Notify operator · **Dispatch crew** (primary). Recorded under
  the officer's Unity Catalog identity with the evidence panels viewed.

### Asset register
* Table: asset (code, place), sector, operator, driving factor (and metric), people relying, risk
  and rating. Rows with an incident open its review; rows below the threshold are not interactive.

### Shift handover
* Checks: incidents awaiting a decision (with extreme count and oldest age), crews dispatched and
  operators notified, active warnings ending this watch, telemetry currency.
* Decision record: the latest six decisions with disposition, sector, asset, title, officer and
  time.

## Visual system

Databricks brand tokens (namespaced `--ioc-*` in `client/src/index.css`): Oat Light surfaces,
Navy 900 text, `#4A5568` secondary text, `#C4CCD6` card borders, `#618794` control borders (3:1),
Lava 600 as a scarce accent, with a `#CC2B1A` button fill for AA contrast. DM Sans and DM Mono are
self-hosted.

| Role | Colour | Notes |
| --- | --- | --- |
| Roads | `#FBB300` | brand categorical palette |
| Rail | `#4462C9` | brand info blue |
| Water | `#1B5162` | brand teal |
| Energy | `#FF7033` | brand secondary orange |
| Warning areas | `#FBB300` tint, dashed | never Lava: footprints are large areas |
| Extreme | Lava ring / label | always paired with the word "extreme" |

Sector and severity are never conveyed by colour alone: every use carries an icon (Lucide) or a
label.

## Responsive behaviour

The handoff's viewport matrix still applies (360 to 1920 px, no horizontal scroll). Sector tiles go
4 → 2 → 2 columns; the map and warnings stack under 1024 px; queue rows collapse to score plus
content; the dialog's actions go full width on phones.

## Copy

Plain, declarative, sentence case. Actions are imperative verbs ("Dispatch crew", "Notify
operator", "Review incident"). Numbers carry units and provenance. Synthetic data is disclosed in
the map caption and the footer.
