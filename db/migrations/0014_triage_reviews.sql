-- 0014: every triage decision with all its fields, and the later share-price outcome of each.
--
-- triage_shortlist_items keeps one decision per shortlisted company and week (the first one recorded).
-- Backtests re-triage the same packets under newer rules, with different models, and with a rules
-- engine screened by a model second opinion.  Each of those decisions is kept here, append-only,
-- with who or what made it and under which rules; is_final marks the decision that counts for the
-- company in that week.  Outcomes (excess return against the median NSE stock over the same window,
-- entry 14 days after the week starts) are stored separately so they can be refreshed as prices age.

CREATE TABLE triage_reviews (
    review_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start           date NOT NULL,
    issuer_id            uuid NOT NULL REFERENCES issuers (issuer_id),
    label                text NOT NULL,                -- folder label, e.g. symbol or ISIN
    packet_id            uuid REFERENCES triage_packets (packet_id),
    packet_hash          text,
    decided_by           text NOT NULL,                -- e.g. 'claude-haiku-5-5', 'local engine rules-3.3'
    rules_version        text,
    triage_action        text NOT NULL CHECK (triage_action IN
                             ('DEEP_RESEARCH', 'WATCH_MILESTONE', 'REJECT_WITH_REASON', 'DATA_REPAIR', 'DEFER_BUDGET')),
    size_pct_of_revenue  numeric,
    size_basis           text,
    firm                 boolean,
    routine              boolean,
    disqualifier         text,
    pass_through         boolean,
    confidence           text,
    rationale            text,
    result               jsonb NOT NULL,               -- the full decision as returned
    is_final             boolean NOT NULL DEFAULT true,
    source               text NOT NULL,                -- where it was loaded from
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX triage_reviews_week ON triage_reviews (week_start, triage_action) WHERE is_final;
CREATE INDEX triage_reviews_issuer ON triage_reviews (issuer_id, week_start);
CREATE UNIQUE INDEX triage_reviews_once ON triage_reviews (week_start, issuer_id, decided_by, md5(result::text));
CREATE TRIGGER triage_reviews_append_only BEFORE UPDATE OR DELETE ON triage_reviews
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE triage_review_outcomes (
    review_id      uuid NOT NULL REFERENCES triage_reviews (review_id),
    horizon_days   integer NOT NULL,
    entry_date     date NOT NULL,
    stock_return   numeric,
    market_median  numeric,                            -- median NSE stock over the same window
    excess_return  numeric,
    computed_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (review_id, horizon_days, computed_at)
);



-- One row per final decision with its latest 6/12/24-month outcome.  is_pick: a deep-research decision
-- made or confirmed by a model (the local engine's own deep-research calls are only a screen).
CREATE VIEW triage_review_results AS
SELECT r.week_start, r.label, i.legal_name, r.triage_action,
       (r.triage_action = 'DEEP_RESEARCH' AND r.decided_by NOT LIKE 'local engine%') AS is_pick, r.decided_by, r.rules_version, r.size_pct_of_revenue,
       r.size_basis, r.firm, r.routine, r.disqualifier, r.confidence, r.rationale,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 182) AS excess_6m,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 365) AS excess_12m,
       max(o.excess_return) FILTER (WHERE o.horizon_days = 730) AS excess_24m,
       max(o.stock_return)  FILTER (WHERE o.horizon_days = 365) AS return_12m,
       max(o.stock_return)  FILTER (WHERE o.horizon_days = 730) AS return_24m,
       r.issuer_id, r.review_id
  FROM triage_reviews r JOIN issuers i USING (issuer_id) LEFT JOIN triage_review_outcomes o USING (review_id)
 WHERE r.is_final
 GROUP BY r.review_id, i.legal_name;

INSERT INTO schema_migrations (version) VALUES ('0014_triage_reviews');
