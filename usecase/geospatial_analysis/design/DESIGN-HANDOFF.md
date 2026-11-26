# Spatial Service Planner - design handoff

`spatial-service-planner.html` is the source design (Genie Design export). The production app is
`app/nba-spatial-planner` (AppKit: Node + React). The prototype is a single static HTML page with
hard-coded figures; the app keeps its layout, tokens, copy and interactions and replaces every
placeholder with governed data.

## Kept as designed

- Tokens (colour, type scale, spacing, radii, elevation, motion) copied verbatim, including the
  dark theme and its toggle.
- Three-column analysis grid (policy settings · map · decision signals), evidence queue below,
  tabs for Analysis, Data pipeline and Assurance, banner, footer and toast.
- Copy: headings, helper text, metric labels ("Regions beyond threshold", "Threshold tested",
  "Straight-line proximity, not road travel"), process steps and assurance checklist.
- Interactions: Run analysis, threshold slider, suppression and boundary toggles, reset map view,
  saved views, export brief, add review note.

## Changed, and why

| Prototype | App | Reason |
| --- | --- | --- |
| Services: hospitals, community health centres, emergency relief hubs | Public hospitals, Medicare Urgent Care Clinics, residential aged care, ambulance stations | These have national, public, CC BY 4.0 location data. The prototype's last two have no national open register. |
| Geography: "sample planning regions / local service areas / statistical areas" | SA4, SA3, SA2, LGA, Remoteness Area, state (+ an Area scope selector) | Real ABS ASGS 2021 geographies. "Planning regions" maps to SA4. |
| Six stylised polygons | Real boundaries with pan/zoom, region search, H3 hexagon layer, site markers and threshold radius rings | The map has to answer the question for real places. |
| "Run analysis" recomputes a hard-coded count | Draft → apply: policy settings stay a draft until Run analysis; display options apply at once | Keeps the explicit commit the design asked for without re-querying on every slider tick. |
| "Test a relief-hub scenario" as text | New-site scenario: click the map to propose up to five sites and see who they would bring within the threshold | The prototype's recommended next step, made into a tool. |
| Assurance checkboxes are static | Purpose recorded and officer sign-off are real, append-only records; briefs cannot be prepared with suppression off | Governance the design describes, enforced. |
| Export brief shows a toast | Printable decision brief (PDF via the browser) with a findings snapshot, purpose, sign-off status and a draft watermark | A brief that can actually circulate. |

## Added

Loading, refreshing, error and empty states for every panel; selected-region card with a distance
distribution; remoteness breakdown; priority cohorts (65+, households without a car); evidence
queue filters, CSV export (suppression preserved) and per-region note history; shareable URLs.
