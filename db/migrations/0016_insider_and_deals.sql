-- 0016: promoter / insider trades and bulk / block deals, for "money behind the story" signals on picks.
-- Loaded from the NSE insider-trading (PIT) and bulk/block-deal APIs, and copied once from the MakroGraph
-- database (NSE and BSE history from 2023).  source_ref identifies the source row, so loads are idempotent.

CREATE TABLE insider_trades (
    trade_id         bigserial PRIMARY KEY,
    exchange         text NOT NULL,                 -- NSE / BSE
    symbol           text NOT NULL,                 -- NSE symbol or BSE scrip code / symbol as the source gives it
    company          text,
    person_name      text,
    person_category  text,                          -- e.g. Promoters, Promoter Group, Director, Employees
    transaction_type text,                          -- Buy / Sell / Pledge ... as filed
    mode             text,                          -- Market Purchase, Off Market, Pledge Creation ...
    quantity         numeric,
    value_inr        numeric,
    trade_from       date,
    trade_to         date,
    disclosed_at     timestamptz,
    post_holding_pct numeric,
    source           text NOT NULL,
    source_ref       text NOT NULL UNIQUE,
    recorded_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX insider_trades_symbol ON insider_trades (symbol, trade_to);

CREATE TABLE bulk_block_deals (
    deal_id       bigserial PRIMARY KEY,
    exchange      text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('BULK', 'BLOCK')),
    trade_date    date NOT NULL,
    symbol        text NOT NULL,
    security_name text,
    client_name   text,
    side          text,                             -- BUY / SELL
    quantity      numeric,
    price         numeric,
    remarks       text,
    source        text NOT NULL,
    source_ref    text NOT NULL UNIQUE,
    recorded_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bulk_block_deals_symbol ON bulk_block_deals (symbol, trade_date);

INSERT INTO schema_migrations (version) VALUES ('0016_insider_and_deals');
