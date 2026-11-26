# Pipeline notes: improper payments detection

Everything here is synthetic and seeded (`seed` = 42 by default). Counts are for seed 42 with the
run date as the anchor; other seeds move the counts slightly. Scores are triage indicators, not
findings.

## Tables

| Layer | Table | Expected rows (seed 42) | Step |
| --- | --- | --- | --- |
| bronze | `bronze_supplier_master` | 2,000 (1,600 businesses plus 400 duplicates) | 01 |
| bronze | `bronze_business_registry` | 2,500 (incl. about 1,000 registry-only and 100 homonyms) | 01 |
| bronze | `bronze_claimant` | 8,000 (7,500 people plus 500 duplicates) | 01 |
| bronze | `bronze_claim` | 25,000 | 01 |
| bronze | `bronze_officer` | 400 | 01 |
| bronze | `bronze_payment` | about 60,400 (supplier and claims programmes, 18 months) | 01 |
| bronze | `bronze_ground_truth` | one row per payment (about 1,470 improper) | 01 |
| silver | `silver_party_record` | about 12,500 normalised source records | 02 |
| silver | `silver_entity_xref` | one row per source record | 02 |
| silver | `silver_entity` | about 10,150 (about 2,660 supplier, 7,500 claimant) | 02 |
| silver | `silver_graph_node` / `silver_graph_edge` | about 49,000 nodes, 116,000 edges | 03 |
| silver | `silver_payment_score` | one row per payment | 06 |
| silver | `silver_investigation_outcome` | live decisions from Lakebase (empty until the workbench writes) | 08 |
| gold | `gold_payment_features` | one row per payment | 04 |
| gold | `gold_case` | about 170 (range 120 to 200) | 06 |
| gold | `gold_case_factor` | up to 5 per case (about 380 total) | 06 |
| gold | `gold_case_graph_node` / `_edge` | 8 per case (about 1,370 nodes) | 06 |
| gold | `gold_case_payment` | up to 30 per case | 06 |
| gold | `gold_model_eval` | 7 metrics | 06 |
| gold | `gold_signal_eval` | one row per primary signal | 07 |
| gold | `gold_outcome_history` | about 400 (synthetic, prior six months) | 07 |
| gold | `gold_pipeline_summary` | one row | 07 |
| gold | `gold_precision` | by signal, risk band and week | 08 |
| ops | `pipeline_provenance` | one row per step | 00, 01 |

## Injected patterns (ground truth)

Improper (is_improper = true):

- shared_bank_account: 25 suppliers in groups of 2 to 4 paying one account (about 690 payments)
- new_vendor_early_invoice: 20 suppliers created 3 to 20 days before first invoice (160)
- duplicate_invoice: 60 near-identical repeat payments (amount within 0.4%, invoice reference variants)
- split_below_threshold: 12 suppliers with invoices between $9,000 and $10,000 (60)
- officer_supplier_link: 12 suppliers whose director address matches an approver's home (231)
- cancelled_registration_paid: 20 suppliers paid after registry cancellation (160)
- claimant_contact_reuse: 8 claimant clusters of 4 to 6 sharing a phone (74)
- claimant_assessor_address: 16 claimants living at the assessor's home address (32)

Benign look-alikes (is_improper = false, expected false positives):

- benign_franchise_branch: 15 branches sharing a parent account (462 payments)
- benign_new_vendor: 14 legitimate new suppliers (112)
- benign_family_address: 8 households of three sharing a phone (44)
- benign_cancelled_inactive: 13 cancelled suppliers never paid after cancellation (130)

## Method, briefly

- Entity resolution: Splink 4 (DuckDB) over ABN, name, address and claimant identity. Phone, email
  and account are not match keys, so shared contact details stay visible as graph signals. Falls
  back to `er_rules` if Splink cannot be imported. Stable ids: hash of the smallest member key.
- Model: LightGBM on payment-level features and rule flags. Time-based 75/25 split. Positive class
  weighted by the negative:positive ratio, capped at 10. Champion alias moves only if held-out
  PR-AUC does not fall.
- Calibration: training up-weights improper payments by `positive_weight`, so 05 and 06 undo that
  prior shift (`p / (p + (1 - p) * w)`) before scoring. Without it nearly every case saturated
  near 100 and the High / Medium bands meant nothing.
- Rule floor: any payment that fires a rule scores at least 60, so rule hits always reach the
  queue and the model ranks within them. Without the floor, rare patterns with few training
  examples scored near zero.
- Case = supplier entity or claimant cluster with a flagged payment (score >= 50) and case score
  >= case_threshold (55). Case score is the highest flagged payment score.

## Results on seed 42 (synthetic)

- First workspace run (LightGBM, serverless): holdout PR-AUC 0.92, precision 1.0 in the top 100
  payments, 0.81 precision and 0.80 recall at the flag threshold; 171 open cases (97 High, 74
  Medium, scores 60 to 99). Case-level precision against ground truth is about 0.75, with the
  benign look-alikes accounting for most false positives.
- Most precise signals: duplicate invoice, cancelled registration, assessor address, split
  invoices, officer link (all 1.0 on this data). Least precise: new vendor and contact reuse (0.5),
  where the benign look-alikes fire the same rule.

These figures describe the generator, not real-world performance. Injected patterns are clean by
construction; a real queue would be noisier.

## Risks not resolved

1. **Not run on a workspace.** Per instruction, nothing was deployed or executed on Databricks. The
   pure modules are tested locally (24 tests). The notebooks compile and their pandas logic was run
   locally, but the Spark I/O, `%pip` cells, MLflow registration and job wiring are untested.
2. **LightGBM path untested locally.** LightGBM would not load on the development machine (libomp
   missing). The local run used scikit-learn with a linear stand-in for SHAP. The `pred_contrib`
   path in 05 and 06 is unexercised.
3. **Lakebase SDK calls unverified.** `w.postgres.get_endpoint`, `generate_database_credential` and
   the endpoint `status.hosts.host` attribute were written from the eligibility app's usage and the
   SDK's shape, not against a live client. The job identity needs a Postgres role with access to
   `ipw.case_outcome`.
4. **Splink.** Validated locally on Splink 4.0.17 with DuckDB. Some Splink comparisons were not
   fully trained (warnings) and default values were used. Splink 5 was not tested; the version is
   pinned to 4.x. Over-merges: 6 of about 10,150 entities (rules path: 2). Two claimants with the same
   birth date and near-identical names are the typical failure.
5. **Driver-side pandas.** Features, scoring and case assembly run on the driver. Fine at 60,000
   payments; it will not scale to a national ledger without moving to Spark.
6. **Case identifiers.** `IP-nnnn` is a hash of the entity id with probing in sorted order, so it
   is stable while the set of open cases is stable. A new case that collides can shift a later
   one. Claimant cluster labels ("Claimant cluster 001") are numbered among open cases and can
   renumber between runs.
7. **Run date.** `as_of` defaults to each task's own date. A run that crosses midnight can disagree
   with itself. Pass `as_of` explicitly for reproducible runs.
8. **Assurance.** A score influences which people and businesses are investigated. The README's
   assurance requirements (DTA framework, transparency statement, access controls and audit on the
   graph and scores) are not implemented here and would be needed before any real use.
