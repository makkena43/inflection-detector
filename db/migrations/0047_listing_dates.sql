-- 0047 (first applied as 0046_listing_dates, renumbered after 0046_industry_classification): listing dates per exchange listing, with their basis.  NSE's listing file states a listing date; BSE's does
-- not, so BSE dates come from BSE's own notice ("effective from <date>, the equity shares of ... (Scrip Code: N) are
-- listed and admitted to dealings"), else from the first stored trading day when the scrip code is newer than every
-- code trading on the first stored day (codes are issued in order, so a stock resuming after a suspension is not
-- taken for a new listing).  Otherwise the listing is only known to be before the first stored day (CENSORED).
BEGIN;
CREATE TABLE IF NOT EXISTS listing_dates (
    exchange      text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    code          text NOT NULL,
    security_id   uuid REFERENCES securities,
    listing_date  date,
    listed_before date,
    basis         text NOT NULL CHECK (basis IN ('EXCHANGE_NOTICE','FIRST_TRADE','CENSORED')),
    migration     boolean NOT NULL DEFAULT false,      -- an SME listing moving to the main board, not a new listing
    evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, code),
    CHECK ((basis = 'CENSORED') = (listing_date IS NULL)),
    CHECK (basis <> 'CENSORED' OR listed_before IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS listing_dates_security ON listing_dates (security_id);
INSERT INTO schema_migrations(version) VALUES ('0047_listing_dates') ON CONFLICT DO NOTHING;
COMMIT;
