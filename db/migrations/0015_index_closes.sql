-- 0015: daily closing values of NSE indices (from NSE's ind_close_all archive files), to benchmark
-- picks against e.g. Nifty Smallcap 250 over the same holding window.

CREATE TABLE index_closes (
    index_name   text NOT NULL,
    trade_date   date NOT NULL,
    close        numeric NOT NULL,
    source_url   text NOT NULL,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (index_name, trade_date)
);

INSERT INTO schema_migrations (version) VALUES ('0015_index_closes');
