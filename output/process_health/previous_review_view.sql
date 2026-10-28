CREATE OR REPLACE VIEW triage_review_results AS
 SELECT r.week_start,
    r.label,
    i.legal_name,
    r.triage_action,
    r.triage_action = 'DEEP_RESEARCH'::text AND r.decided_by !~~ 'local engine%'::text AS is_pick,
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
     LEFT JOIN triage_review_outcomes o USING (review_id)
  WHERE r.is_final AND NOT (EXISTS ( SELECT 1
           FROM triage_reviews s
          WHERE s.is_final AND s.week_start = r.week_start AND s.issuer_id = r.issuer_id AND COALESCE(s.result ->> 'supersedes_review_id'::text, (s.result -> 'staleness_filter'::text) ->> 'supersedes_review_id'::text, (s.result -> 'repeat_filter'::text) ->> 'supersedes_review_id'::text, (s.result -> 'freshness_filter'::text) ->> 'supersedes_review_id'::text) = r.review_id::text))
  GROUP BY r.review_id, i.legal_name;;
