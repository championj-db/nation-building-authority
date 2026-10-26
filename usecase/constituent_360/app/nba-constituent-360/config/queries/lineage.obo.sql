SELECT source_table_full_name, target_table_full_name, last_seen, events
FROM au_pubsec_catalog.constituent_360_jared_champion.v_lineage_edges
ORDER BY last_seen DESC
LIMIT 100
