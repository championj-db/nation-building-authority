"""Probabilistic linkage with Splink 4 (Fellegi-Sunter) for the party records.

Scores candidate pairs and returns them in the same (key_a, key_b, probability, method) shape that
er_rules.assign_entities() takes, so the clustering, stable ids and xref are identical whichever
scorer ran. Splink is imported inside the function: if it is not installed, the caller falls back
to er_rules.score_pairs().

Deliberately not compared: phone, email and bank account. Those are the signals the investigation
is about (shared contact details and shared accounts), so letting them pull records together would
merge the very entities the graph is meant to show as separate.

Runs on Splink's DuckDB backend on the driver, which handles the tens of thousands of party
records in this use case comfortably.
"""

from __future__ import annotations

import pandas as pd


def score_with_splink(parties: list[dict], threshold: float = 0.5, max_pairs_u: int = 1_000_000,
                      seed: int = 42) -> tuple[list[tuple[str, str, float, str]], dict]:
    """Return (scored links with probability >= threshold, diagnostics).

    Diagnostics report the number of records, the pairs predicted and the model's lambda, so the
    notebook can log them.
    """
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    df = pd.DataFrame(parties)
    df["unique_id"] = df["key"]
    df["name_block"] = df["name"].fillna("").str[:6]
    df["family_block"] = df["family"].fillna("").str[:4]
    df["postcode_block"] = df["postcode"].fillna("")
    df["address_block"] = df["address_key"].fillna("")
    for col in ("name", "given", "family", "dob", "abn", "address_key"):
        df[col] = df[col].where(df[col].notna() & (df[col] != ""), None)

    settings = SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="unique_id",
        blocking_rules_to_generate_predictions=[
            block_on("abn"),
            block_on("postcode_block", "name_block"),
            block_on("family_block", "dob"),
            block_on("address_block"),
        ],
        comparisons=[
            cl.JaroWinklerAtThresholds("name", [0.95, 0.9]),
            cl.JaroWinklerAtThresholds("given", [0.92, 0.85]),
            cl.JaroWinklerAtThresholds("family", [0.92]),
            cl.DateOfBirthComparison("dob", input_is_string=True),
            cl.ExactMatch("abn"),
            cl.ExactMatch("address_key"),
        ],
        additional_columns_to_retain=["kind"],
        retain_intermediate_calculation_columns=False,
        retain_matching_columns=True,
    )
    linker = Linker(df[["unique_id", "kind", "name", "given", "family", "dob", "abn", "address_key",
                        "postcode_block", "name_block", "family_block", "address_block"]],
                    settings, db_api=DuckDBAPI())
    linker.training.estimate_probability_two_random_records_match(
        [block_on("abn"), block_on("family_block", "dob")], recall=0.8)
    linker.training.estimate_u_using_random_sampling(max_pairs=max_pairs_u)
    # EM sessions each leave out the fields they block on, so together they train every comparison
    for rule in (block_on("abn"), block_on("family_block", "dob"), block_on("address_block"),
                 block_on("name_block")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)

    pred = linker.inference.predict(threshold_match_probability=threshold).as_pandas_dataframe()
    kind = dict(zip(df["unique_id"], df["kind"]))
    links = []
    for row in pred.itertuples(index=False):
        a, b = row.unique_id_l, row.unique_id_r
        if kind.get(a) != kind.get(b):
            continue  # a supplier and a claimant are never the same party
        links.append((a, b, float(row.match_probability), "splink"))
    diagnostics = {"records": int(len(df)), "pairs_above_threshold": int(len(links))}
    return links, diagnostics
