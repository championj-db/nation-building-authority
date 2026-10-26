SELECT snapshot_date, open_journeys, opened_today, closed_today,
       open_journeys_7d_ago, high_need_awaiting, high_need_consent_restricted,
       overdue_journeys, inbound_contacts_7d, repeat_contact_7d_rate,
       repeat_contact_prev_7d_rate, repeat_contact_target, identity_confidence,
       multi_source_constituents, suppressed
FROM au_pubsec_catalog.constituent_360_jared_champion.service_kpis
WHERE agency_code = 'ALL'
ORDER BY snapshot_date DESC
LIMIT 1
