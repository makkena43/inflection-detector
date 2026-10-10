-- 0008: the financial discovery route (spec sections 18.1, 18.2).
--
-- Results figures are stored per issuer and period (financial_facts, one publication per filing).
-- This migration adds one table: ``financial_scans``, one row per results filing and rules version,
-- saying what the route made of it:
--
-- * EVALUATED       at least one spec 18.1 check fired, or its inputs failed the statement
--                   arithmetic; ``evaluation_id`` points to the candidate_evaluations row (route
--                   FINANCIAL), which uses the same priority classes as the commercial route.
-- * NOT_NOMINATED   the year-earlier comparison was made and nothing fired.
-- * NO_COMPARABLE   no year-earlier figures of the same scope and period length were public by then.
-- * NO_FIGURES      the filing has no company-level, non-cumulative period to compare.
-- * NO_ISSUER / NO_TIMESTAMP   data repair; read again once fixed.
-- * SKIPPED_STANDALONE  a standalone filing from an issuer that reports consolidated figures.
--
-- ``checks`` keeps every check with its inputs, so a NOT_NOMINATED filing still shows how close it came.

BEGIN;

CREATE TABLE financial_scans (
    publication_id      uuid NOT NULL REFERENCES document_publications,
    rules_version       text NOT NULL,
    issuer_id           uuid REFERENCES issuers,
    available_at        timestamptz,
    scope               text,
    period_type         text,
    period_end          date,
    comparable_period_end date,
    status              text NOT NULL CHECK (status IN ('EVALUATED','NOT_NOMINATED','NO_COMPARABLE','NO_FIGURES',
                                                        'NO_ISSUER','NO_TIMESTAMP','SKIPPED_STANDALONE')),
    fired               text[] NOT NULL DEFAULT '{}',
    checks              jsonb NOT NULL DEFAULT '[]',
    evaluation_id       uuid REFERENCES candidate_evaluations,
    scanned_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publication_id, rules_version)
);
CREATE INDEX financial_scans_issuer ON financial_scans (issuer_id, available_at);
CREATE INDEX financial_facts_publication ON financial_facts (publication_id);

INSERT INTO schema_migrations (version) VALUES ('0008_financial_route');

COMMIT;
