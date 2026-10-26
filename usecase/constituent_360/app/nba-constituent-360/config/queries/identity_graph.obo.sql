SELECT constituent_id, source_record_id, source_system, source_display_name,
       agency_code, data_domain, link_state, link_probability,
       linked_constituent_id, identity_assurance, record_updated_at
FROM au_pubsec_catalog.constituent_360_jared_champion.constituent_identity_graph
ORDER BY link_probability DESC, source_system
