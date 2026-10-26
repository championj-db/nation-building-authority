SELECT case_id, constituent_id, display_name, initials, agency_code, data_domain,
       service_type, case_status, sla_status, opened_at, due_at, days_open,
       priority_score, priority_band, recommended_action, high_need_awaiting,
       awaiting_agency, last_contact_ts, contacts_7d, repeat_contacts_7d,
       case_purpose, owner_display_name
FROM au_pubsec_catalog.constituent_360_jared_champion.priority_queue
ORDER BY priority_score DESC, due_at ASC
LIMIT 100
