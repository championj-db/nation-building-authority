SELECT constituent_id, display_name, initials, birth_year, age, email, mobile,
       street, suburb, postcode, identity_confidence, source_record_count,
       open_cases, open_services, priority_score, priority_band,
       recommended_action, interactions_total, interactions_90d,
       last_interaction_ts, last_channel, repeat_contacts_30d, urgency_score,
       latest_tone, latest_sentiment
FROM au_pubsec_catalog.constituent_360_jared_champion.constituent_profile
LIMIT 1
