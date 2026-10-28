-- 0019: quarterly shareholding pattern and PLI scheme approvals.
-- shareholding_patterns: one row per company and quarter from NSE's shareholding filings.  Promoter and public
-- percentages come from the filing list; the category split (mutual funds, foreign and domestic institutions,
-- retail, promoter shares pledged) is read from the filing's XBRL where it has been fetched.  broadcast_at is when
-- NSE published it, the date it can be used from.
-- pli_beneficiaries: companies approved under the Production Linked Incentive schemes, from PIB and ministry
-- releases, dated by the release.  issuer_id is filled when the published name matches a listed company.

CREATE TABLE shareholding_patterns (
    issuer_id          uuid REFERENCES issuers (issuer_id),
    exchange           text NOT NULL,
    symbol             text NOT NULL,
    period_end         date NOT NULL,
    broadcast_at       timestamptz,
    promoter_pct       numeric,
    public_pct         numeric,
    mf_pct             numeric,                     -- mutual funds / UTI
    fii_pct            numeric,                     -- foreign institutions (FPIs)
    dii_pct            numeric,                     -- domestic institutions, mutual funds included
    retail_pct         numeric,                     -- resident individuals up to Rs 2 lakh
    promoter_pledged_pct numeric,                   -- promoter shares pledged, as % of promoter shares
    xbrl_url           text,
    detail_status      text,                        -- NULL = not fetched, OK, FAILED
    source             text NOT NULL,
    source_ref         text NOT NULL UNIQUE,
    recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX shareholding_patterns_issuer ON shareholding_patterns (issuer_id, period_end);

CREATE TABLE pli_beneficiaries (
    pli_id                  bigserial PRIMARY KEY,
    scheme                  text NOT NULL,
    tranche                 text,
    company_name            text NOT NULL,
    issuer_id               uuid REFERENCES issuers (issuer_id),
    approval_date           date,
    committed_investment_cr numeric,
    incentive_or_output_cr  numeric,
    product_segment         text,
    source_url              text NOT NULL,
    notes                   text,
    UNIQUE (scheme, tranche, company_name, source_url)
);
CREATE INDEX pli_beneficiaries_issuer ON pli_beneficiaries (issuer_id, approval_date);

INSERT INTO schema_migrations (version) VALUES ('0019_shareholding_and_pli');
