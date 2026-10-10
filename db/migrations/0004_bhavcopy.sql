-- 0004: daily exchange bhavcopy rows, as published.
--
-- One row per exchange, trade date, instrument code and series.  ``code`` is the NSE symbol or the
-- BSE scrip code.  Rows are the raw daily record that the company list (issuers, securities,
-- identifier_history) and later the ``prices`` table are built from.  ISIN is present only in the
-- UDiFF files (NSE and BSE, from July 2024); older rows, including those imported from MakroGraph,
-- carry no ISIN and stay unlinked until an ISIN-bearing row covers them.
--
-- ``turnover`` is in rupees for every format (NSE's sec_bhavdata_full reports lakhs and is
-- converted on load).

BEGIN;

CREATE TABLE bhavcopy_rows (
    exchange          text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    trade_date        date NOT NULL,
    code              text NOT NULL CHECK (code <> ''),   -- NSE symbol / BSE scrip code
    series            text NOT NULL DEFAULT '',           -- NSE series / BSE group
    ticker            text,                               -- BSE ticker symbol (UDiFF TckrSymb)
    isin              text CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
    instrument_name   text,
    instrument_type   text,                               -- UDiFF FinInstrmTp (STK ...)
    prev_close        numeric,
    open              numeric,
    high              numeric,
    low               numeric,
    last              numeric,
    close             numeric,
    avg_price         numeric,
    volume            numeric,
    turnover          numeric,
    trades            bigint,
    delivery_qty      numeric,
    delivery_pct      numeric,
    source_formats    text[] NOT NULL,                    -- NSE_UDIFF, NSE_FULL, BSE_UDIFF, BSE_LEGACY, MAKROGRAPH_*
    ingestion_run_id  uuid REFERENCES ingestion_runs,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, trade_date, code, series)
);
CREATE INDEX bhavcopy_rows_isin ON bhavcopy_rows (isin, exchange, trade_date) WHERE isin IS NOT NULL;
CREATE INDEX bhavcopy_rows_code ON bhavcopy_rows (exchange, code, trade_date);

INSERT INTO schema_migrations (version) VALUES ('0004_bhavcopy');

COMMIT;
