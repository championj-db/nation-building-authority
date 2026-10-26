SELECT constituent_id, data_domain, need_code, need_label, evidence_count,
       last_seen_ts, avg_urgency, strength, evidence_interaction_ids
FROM au_pubsec_catalog.constituent_360_jared_champion.constituent_need_signals
ORDER BY CASE strength WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
         last_seen_ts DESC
