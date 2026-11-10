-- 0046: sector / industry labels per listing (NSE and BSE), loaded from a file.
-- Labels are as of the load date (labels_as_of), NOT point in time: using them for past months is a known
-- look-ahead caveat (labels rarely change; delisted companies are missing). Every load keeps its source file,
-- file hash and load time, so a later file is added beside the old one instead of overwriting it.
BEGIN;
CREATE TABLE IF NOT EXISTS industry_classification (
    classification_id      bigserial PRIMARY KEY,
    issuer_id              uuid REFERENCES issuers,
    security_id            uuid REFERENCES securities,
    exchange               text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    symbol                 text NOT NULL,
    isin                   text,
    company_name           text,
    sector                 text,
    industry_group         text,
    industry               text,
    classification_status  text,
    source                 text NOT NULL,
    source_url             text,
    source_file            text NOT NULL,
    source_file_sha256     text NOT NULL,
    labels_as_of           date NOT NULL,
    loaded_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_file_sha256, exchange, symbol)
);
CREATE INDEX IF NOT EXISTS industry_classification_issuer_idx ON industry_classification (issuer_id);
CREATE INDEX IF NOT EXISTS industry_classification_industry_idx ON industry_classification (industry);
-- One row per issuer from the newest load; NSE row preferred over BSE.
CREATE OR REPLACE VIEW industry_classification_latest AS
SELECT DISTINCT ON (issuer_id) issuer_id, security_id, exchange, symbol, isin, company_name,
       sector, industry_group, industry, source, source_file, labels_as_of, loaded_at
FROM industry_classification
WHERE issuer_id IS NOT NULL AND coalesce(industry, '') <> ''
ORDER BY issuer_id, labels_as_of DESC, loaded_at DESC, (exchange = 'NSE') DESC;
INSERT INTO schema_migrations(version) VALUES ('0046_industry_classification') ON CONFLICT DO NOTHING;
COMMIT;
