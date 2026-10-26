SELECT constituent_id, display_name, initials, birth_year, suburb, open_cases,
       priority_band, has_verified_source, source_record_count,
       last_interaction_ts, case_purposes
FROM au_pubsec_catalog.constituent_360_jared_champion.constituent_directory
ORDER BY open_cases DESC, last_interaction_ts DESC
LIMIT 200
