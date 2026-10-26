SELECT constituent_id, purpose_code, data_domain, domain_name, access_rule,
       visible, reason, consent_expires_at, signals_visible, session_expires_at
FROM au_pubsec_catalog.constituent_360_jared_champion.v_my_access_scope
ORDER BY visible DESC, domain_name
