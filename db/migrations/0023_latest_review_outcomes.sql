-- Select the latest recomputation per horizon; never select the highest past return.
CREATE OR REPLACE VIEW triage_review_results AS
SELECT r.week_start,
       r.label,
       i.legal_name,
       r.triage_action,
       r.triage_action = 'DEEP_RESEARCH' AND r.decided_by NOT LIKE 'local engine%' AS is_pick,
       r.decided_by,
       r.rules_version,
       r.size_pct_of_revenue,
       r.size_basis,
       r.firm,
       r.routine,
       r.disqualifier,
       r.confidence,
       r.rationale,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 182) AS excess_6m,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 365) AS excess_12m,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 730) AS excess_24m,
       max(o.stock_return) FILTER (WHERE o.horizon_days = 365) AS return_12m,
       max(o.stock_return) FILTER (WHERE o.horizon_days = 730) AS return_24m,
       r.issuer_id,
       r.review_id
  FROM triage_reviews r
  JOIN issuers i USING (issuer_id)
  LEFT JOIN (
       SELECT DISTINCT ON (review_id, horizon_days) * FROM triage_review_outcomes
       ORDER BY review_id, horizon_days, computed_at DESC
  ) o USING (review_id)
 WHERE r.is_final
   AND NOT EXISTS (SELECT 1 FROM triage_reviews s
                    WHERE s.is_final AND s.week_start = r.week_start AND s.issuer_id = r.issuer_id
                      AND coalesce(s.result ->> 'supersedes_review_id',
                                   s.result -> 'staleness_filter' ->> 'supersedes_review_id',
                                   s.result -> 'repeat_filter' ->> 'supersedes_review_id',
                                   s.result -> 'freshness_filter' ->> 'supersedes_review_id') = r.review_id::text)
 GROUP BY r.review_id, i.legal_name;

INSERT INTO schema_migrations (version) VALUES ('0023_latest_review_outcomes') ON CONFLICT DO NOTHING;
