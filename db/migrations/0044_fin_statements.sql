-- 0044: structured balance-sheet and cash-flow lines from NSE half-year / annual results XBRL (Ind AS
-- "Statement of Assets and Liabilities" and "Cash Flow Statement" elements, Sep and Mar period ends).
-- One row per filing, scope and XBRL element, for company-level facts only (no segment members). Values are exact
-- rupees as filed. available_at is the filing's publication time, so readers can apply the point-in-time rule.
-- Balance-sheet rows carry the instant (as_of); cash-flow rows carry the duration (period_start..period_end).
-- New tables only: nothing existing is changed.
BEGIN;
CREATE TABLE fin_balance_sheet (
    publication_id uuid NOT NULL REFERENCES document_publications (publication_id),
    issuer_id      uuid NOT NULL,
    available_at   timestamptz NOT NULL,
    report_period  date NOT NULL,           -- the filing's period end
    scope          text NOT NULL CHECK (scope IN ('STANDALONE', 'CONSOLIDATED')),
    as_of          date NOT NULL,           -- instant of the figure (report period end, or a prior comparative)
    element        text NOT NULL,           -- XBRL element name, e.g. Assets, BorrowingsCurrent
    value          numeric NOT NULL,
    source_url     text NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publication_id, scope, as_of, element)
);
CREATE INDEX fin_balance_sheet_issuer ON fin_balance_sheet (issuer_id, report_period, available_at);
CREATE TABLE fin_cash_flow (
    publication_id uuid NOT NULL REFERENCES document_publications (publication_id),
    issuer_id      uuid NOT NULL,
    available_at   timestamptz NOT NULL,
    report_period  date NOT NULL,
    scope          text NOT NULL CHECK (scope IN ('STANDALONE', 'CONSOLIDATED')),
    period_start   date NOT NULL,
    period_end     date NOT NULL,
    element        text NOT NULL,           -- e.g. CashFlowsFromUsedInOperatingActivities, ProfitBeforeTax
    value          numeric NOT NULL,
    source_url     text NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publication_id, scope, period_start, period_end, element)
);
CREATE INDEX fin_cash_flow_issuer ON fin_cash_flow (issuer_id, report_period, available_at);
CREATE TRIGGER fin_balance_sheet_append_only BEFORE UPDATE OR DELETE ON fin_balance_sheet
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER fin_cash_flow_append_only BEFORE UPDATE OR DELETE ON fin_cash_flow
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
INSERT INTO schema_migrations (version) VALUES ('0044_fin_statements');
COMMIT;
