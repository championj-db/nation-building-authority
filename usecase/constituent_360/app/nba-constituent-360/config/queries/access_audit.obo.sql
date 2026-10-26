SELECT event_ts, principal, officer_name, constituent_id, case_id,
       purpose_code, event_type, decision, detail
FROM au_pubsec_catalog.constituent_360_jared_champion.v_my_access_audit
ORDER BY event_ts DESC
LIMIT 100
