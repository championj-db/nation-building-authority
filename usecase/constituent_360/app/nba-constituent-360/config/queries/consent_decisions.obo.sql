SELECT constituent_id, purpose_code, data_domain, decision, decided_at,
       expires_at, is_active, captured_by_agency, capture_channel,
       consent_event_id, notice_version
FROM au_pubsec_catalog.constituent_360_jared_champion.consent_decisions
ORDER BY data_domain, decided_at DESC
