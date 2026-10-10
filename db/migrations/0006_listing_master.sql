-- 0006: exchange listing files, NSE symbol changes, and split/bonus-adjusted prices.
--
-- ``listing_master`` keeps each listing file as published on the day it was read: NSE EQUITY_L
-- and SME_EQUITY_L, BSE's scrip list by status (Active, Suspended, Delisted) or its Equity.csv
-- download.  The company list (issuers, securities, identifier_history) is built from it, so
-- suspended and delisted companies are present as well as the ones trading today.
--
-- ``symbol_changes`` is NSE's symbol change file: it dates when an old symbol stopped and a new
-- one started.
--
-- ``prices_split_bonus_adjusted`` scales UNADJUSTED prices by every split and bonus with a later
-- ex-date.  ``unverified`` is true when any of those actions is not reconciled against the
-- exchange's own price adjustment (spec: unreconciled actions make returns UNVERIFIED).

BEGIN;

CREATE TABLE listing_master (
    exchange          text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    list_name         text NOT NULL,                      -- NSE_EQUITY_L, NSE_SME_EQUITY_L, BSE_ACTIVE ...
    code              text NOT NULL CHECK (code <> ''),   -- NSE symbol / BSE scrip code
    snapshot_date     date NOT NULL,                      -- the day the file was read
    ticker            text,                               -- BSE security id
    isin              text CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
    name              text,
    status            text NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','DELISTED','UNKNOWN')),
    board             text NOT NULL DEFAULT 'UNKNOWN' CHECK (board IN ('MAINBOARD','SME','UNKNOWN')),
    series            text,                               -- NSE series / BSE group
    listing_date      date,
    face_value        numeric,
    industry          text,
    raw               jsonb NOT NULL,
    ingestion_run_id  uuid REFERENCES ingestion_runs,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, list_name, code, snapshot_date)
);
CREATE INDEX listing_master_isin ON listing_master (isin) WHERE isin IS NOT NULL;
CREATE INDEX listing_master_code ON listing_master (exchange, code, snapshot_date);

CREATE TABLE symbol_changes (
    exchange          text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    old_symbol        text NOT NULL,
    new_symbol        text NOT NULL,
    effective_date    date NOT NULL,
    name              text,
    ingestion_run_id  uuid REFERENCES ingestion_runs,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, old_symbol, new_symbol, effective_date)
);

-- One row per action as the provider published it; reruns update instead of duplicating.
CREATE UNIQUE INDEX corporate_actions_provider_key
    ON corporate_actions (provider, security_id, kind, ex_date, md5(details->>'subject'));
CREATE INDEX corporate_actions_security ON corporate_actions (security_id, ex_date);

CREATE VIEW prices_split_bonus_adjusted AS
SELECT p.security_id, p.trade_date, p.provider, p.provider_version,
       p.open * f.multiplier AS open, p.high * f.multiplier AS high, p.low * f.multiplier AS low,
       p.close * f.multiplier AS close, p.volume / f.multiplier AS volume,
       f.multiplier, f.unverified
  FROM prices p
 CROSS JOIN LATERAL (
       SELECT coalesce(round(exp(sum(ln((a.details->>'price_multiplier')::numeric))), 10), 1) AS multiplier,
              coalesce(bool_or(NOT a.reconciled), false) AS unverified
         FROM corporate_actions a
        WHERE a.security_id = p.security_id AND a.kind IN ('SPLIT','BONUS')
          AND a.ex_date > p.trade_date AND a.details ? 'price_multiplier') f
 WHERE p.adjustment = 'UNADJUSTED';

INSERT INTO schema_migrations (version) VALUES ('0006_listing_master');

COMMIT;
