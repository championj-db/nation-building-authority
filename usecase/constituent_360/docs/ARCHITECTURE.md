# Constituent 360 - pipeline architecture

This document is the design contract between the data pipeline and the consumer experience in
`design/constituent-360-workspace.html` (staff workspace + case briefing assistant). Everything is
synthetic. Every catalog, schema, volume, endpoint and principal is a bundle variable.

## Stages (Lakeflow Job `c360_bootstrap` / `c360_refresh`, serverless)

```
00_setup                 schema, volume, control + reference tables, governance tables
01_generate_synthetic    dbldatagen population -> 6 agency identity extracts, 4 channel extracts,
                         case snapshots, consent events -> landing volume (CSV / JSON)
02_ingest_bronze         Auto Loader (availableNow) -> bronze_* (raw strings + file lineage)
03_standardise_silver    typed + normalised identities, contact points, unified interactions,
                         cases, consent events, quarantine + DQ results
04_entity_resolution     embeddings (ai_query) -> NEAREST BY semantic candidates -> Splink
                         (Fellegi-Sunter, EM) -> human decisions -> clusters -> stable constituent
                         IDs -> golden record, identity links, review queue, evaluation vs truth
05_sentiment_and_intent  ai_analyze_sentiment, ai_classify (intent), ai_query structured output
                         (summary, tone, urgency, need signals) - incremental, capped per run
06_gold_360              interactions resolved to constituents, journeys/cases, profile, need
                         signals, identity graph, KPIs (small-cell suppressed)
07_consent_and_serving   consent_current, UC row filters + column masks, serving tables (fail-closed
                         swap), purpose-aware views, SQL procedures for sessions / audit / changes
08_validate              data, ER, AI and policy assertions -> pipeline_quality_checks
```

## Layers and tables

| Layer | Tables | Who can read |
| --- | --- | --- |
| Landing | `/Volumes/<catalog>/<schema>/<volume>/extracts/<extract>/delivery=<ts>/` | pipeline only |
| Bronze | `bronze_<extract>` (12) | pipeline only |
| Silver | `silver_source_identities`, `silver_contact_points`, `silver_interactions`, `silver_cases`, `silver_consent_events`, `silver_quarantine` | pipeline only |
| Entity resolution | `er_identity_embeddings`, `er_semantic_candidates`, `er_pairwise_predictions`, `silver_identity_xref`, `silver_constituents`, `er_review_queue`, `er_evaluation`, `er_model_runs` | pipeline + identity stewards |
| AI signals | `ai_interaction_signals`, `ai_signal_evaluation` | pipeline only (inferred personal information) |
| Gold (unfiltered) | `gold_interactions`, `gold_cases`, `gold_constituent_profile`, `gold_need_signals`, `gold_identity_graph`, `gold_service_kpis`, `gold_repeat_contact_by_service`, `gold_operational_signals` | pipeline only |
| Governance | `ref_*`, `staff_directory`, `staff_purpose_authorisations`, `access_sessions`, `consent_current`, `access_audit_events`, `record_change_requests`, `identity_review_decisions` | pipeline; staff only via procedures / views |
| Serving (policy-protected) | `constituent_360`, `constituent_profile`, `constituent_need_signals`, `constituent_identity_graph`, `constituent_directory`, `priority_queue`, `consent_decisions` | staff group, row filters + column masks always applied |
| Serving (aggregate) | `service_kpis`, `repeat_contact_by_service`, `operational_signals` | staff group |
| Serving (views) | `v_my_session`, `v_my_access_scope`, `v_my_access_audit`, `v_lineage_edges` | staff group |

`synthetic_truth_*` tables hold the generator's ground truth and exist only to measure entity
resolution and AI accuracy. They are never exposed to serving.

## Design screen -> serving object

| Design element | Object | Notes |
| --- | --- | --- |
| KPI: Open service journeys / delta today | `service_kpis.open_journeys`, `opened_today`, `closed_today` | |
| KPI: Repeat contact within 7 days + target marker | `service_kpis.repeat_contact_7d_rate`, `repeat_contact_target` | target is a bundle variable |
| KPI: High-need cases awaiting action / consent-restricted | `service_kpis.high_need_awaiting`, `high_need_consent_restricted` | |
| KPI: Resolved identity confidence | `service_kpis.identity_confidence` | from `er_evaluation` / clusters |
| Priority queue | `priority_queue` | caseload row filter: own + unassigned cases in agencies the officer is authorised for |
| Profile header, facts, identity badge | `constituent_profile` | requires an active purpose session for that constituent |
| Recommended follow-up | `priority_queue.recommended_action`, `constituent_profile.recommended_action` | rules over case state + signals |
| Journey timeline | `constituent_360` | one row per interaction; row filter per data domain + consent |
| Needs & signals card / tab | `constituent_need_signals`, `constituent_profile.urgency_score` | masked unless the purpose allows derived signals |
| Current access scope | `v_my_access_scope` | per domain decision, reason and expiry |
| Identity graph tab + merge / split / review | `constituent_identity_graph`; `record_identity_decision` procedure | decisions feed the next ER run |
| Access audit tab | `v_my_access_audit`; `log_access_event` procedure | plus `system.access.audit` |
| Case briefing assistant | `constituent_360` (the design's generated SQL) + `constituent_need_signals` | assistant runs as the officer, so policies apply |
| Record update dialog | `request_record_change` procedure -> `record_change_requests` | staged for review, audit event |
| Constituents page | `constituent_directory` | minimum fields only |
| Interactions page | `constituent_360` | |
| Service insights page | `repeat_contact_by_service`, `operational_signals` | small cells suppressed |
| Consent & access page | `consent_decisions`, `record_consent_change` via `request_record_change` | |
| Data lineage page | `v_lineage_edges` (UC lineage system table) | |
| View access policy toast | `v_my_session` | purpose + masked field count |

## Entity resolution

No common identifier exists across the six identity sources (Service NSW verified customer, web
account, housing CRM, transport licensing, cost-of-living concessions, community health). Noise is
modelled on real failure modes: nicknames, transliteration and typing errors, surname change, stale
addresses after a move, day/month swaps, missing fields, shared household phones and addresses,
and within-source duplicate registrations.

1. **Normalise** (silver): canonical given name (nickname map), punctuation-free names, E.164-style
   phone digits, Gmail-aware email normalisation, expanded street types and unit forms, suburb and
   postcode parsing, plus a compact natural-language `identity_text`.
2. **Semantic candidates**: `identity_text` is embedded with `ai_query(<embedding endpoint>)`
   (cached by text hash) and every record finds its nearest neighbours with
   `JOIN ... APPROX NEAREST k BY SIMILARITY vector_cosine_similarity(...)`. Pairs above
   `semantic_lo` become extra candidates and a comparison feature.
3. **Probabilistic linkage**: Splink 4 (DuckDB backend on the driver; switch to the Spark backend
   on classic compute at larger scale) with blocking on DOB, email, phone, address, postcode +
   initial, name, and the exploded semantic pair keys. Comparisons: name (Jaro-Winkler with term
   frequency adjustment), DOB, email, phone, postcode, address, and semantic neighbour tier.
   m/u estimated with random sampling + EM; lambda from deterministic rules.
4. **Decisions**: pairs >= `auto_match_threshold` link automatically; pairs in
   [`review_threshold`, `auto_match_threshold`) go to `er_review_queue` and appear as dashed review
   links in the identity graph. Steward decisions in `identity_review_decisions` override the model
   (must-link / cannot-link).
5. **Clusters and stable IDs**: union-find over accepted edges; a cluster inherits the most common
   prior `constituent_id` of its records, otherwise a new `C-<n>` is minted from the control table.
6. **Golden record**: survivorship by source assurance rank then recency per attribute.
7. **Evaluation**: pairwise precision / recall / F1 against `synthetic_truth_source_records` every
   run; `08_validate` fails the run below `min_er_f1`.

## Consent and purpose-of-use model

Enforced in Unity Catalog, never in application code:

* `ref_purposes` - why an officer is accessing a record (e.g. `housing_case_support`), the owning
  agency, and whether the purpose must be anchored to a case.
* `ref_purpose_domain_policy` - for each purpose x data domain: `allow` (statutory basis), `consent`
  (visible only with a current constituent consent for that purpose and domain) or `deny`; the
  identity attribute level (`full` / `minimum`) and whether AI-derived signals may be shown.
* `staff_purpose_authorisations` - which principals may act under which purposes, with validity.
* `access_sessions` - an officer declares a purpose for one subject (a case in their caseload, or a
  verified constituent for non-case purposes) by calling `start_access_session`. The procedure is
  `SQL SECURITY DEFINER`, checks the authorisation and caseload, and writes an audit event.
  Officers cannot write to the session table directly.
* `consent_current` - latest consent decision per constituent x purpose x domain, resolved from
  agency-local client references through entity resolution.

Row filter `c360_rf_person_domain(constituent_id, data_domain)` returns true only when the current
user has an active, authorised session for that constituent and the purpose permits the domain
(statutory, or consent granted and unexpired). Column masks hide date of birth, full address,
email and phone below `full` identity level, and hide sentiment / intent / need signals unless the
purpose allows derived signals for that domain. The priority queue uses
`c360_rf_caseload(case_purpose, owner_principal)` and the directory uses
`c360_rf_directory(case_purposes, has_verified_source)`. All policy functions resolve the caller
with `session_user()` against the internal view `c360_v_active_grants`.

Serving tables are rebuilt each run as `<name>__build`, policies are attached, then the old table is
dropped and the build renamed. Table-level grants are re-applied afterwards, so a failure leaves the
table missing or ungranted (fail closed), never unprotected. Grant the staff group table-level
privileges only - never schema-level `SELECT`, which would expose the build table and every
unfiltered gold table.

## Object ownership

The catalog must already exist; the pipeline never creates or alters catalogs. Inside its schema it
only modifies objects it created: tables and views carry the table property
`nba.managed_by = nba-constituent-360`, and every table, view, function, procedure and the volume is
recorded in `pipeline_object_registry`. `write_table`, `owned_sql`, `drop_owned` and `rename_owned`
(in `_common`) refuse to touch an existing object without the marker, and `reset=true` drops only
registered objects. `08_validate` reports any other objects in the schema without touching them.
The staff group gets `USE SCHEMA` plus table-level grants; `USE CATALOG` is left to the catalog owner.

## Assurance notes carried into the build

* AI-derived sentiment, intent and need signals are personal information; they are masked by
  purpose, tagged `nba_classification=protected_inferred`, and evaluated against ground truth.
* Aggregates suppress cells below `small_cell_threshold`.
* The unified record inherits the highest classification of its inputs (health): every serving
  table is tagged accordingly.
* Human identity decisions and record change requests are staged and audited, not applied directly
  to source systems.
