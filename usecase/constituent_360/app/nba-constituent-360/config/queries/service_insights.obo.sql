SELECT service_line, channel_label, sum(inbound_contacts) AS inbound_contacts,
       sum(repeat_contacts) AS repeat_contacts,
       round(sum(repeat_contacts) / nullif(sum(inbound_contacts), 0), 4) AS repeat_contact_rate,
       bool_or(suppressed) AS suppressed
FROM au_pubsec_catalog.constituent_360_jared_champion.repeat_contact_by_service
WHERE week_start >= current_date() - INTERVAL 8 WEEKS
GROUP BY service_line, channel_label
ORDER BY repeat_contact_rate DESC
LIMIT 30
