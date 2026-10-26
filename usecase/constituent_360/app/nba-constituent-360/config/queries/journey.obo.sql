SELECT interaction_id, constituent_id, display_name, case_id, service_type,
       channel, channel_label, direction, agency_code, data_domain, event_ts,
       subject, outcome, attachment_name, sentiment, intent, tone,
       urgency_score, needs, summary, follow_up_required, is_repeat_contact,
       resolution_method
FROM au_pubsec_catalog.constituent_360_jared_champion.constituent_360
ORDER BY event_ts DESC
LIMIT 100
