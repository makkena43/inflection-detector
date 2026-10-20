-- 0017: company-reported order book and order inflow figures, extracted from results presentations, results
-- press releases and con-call transcripts (inflection.orderbook).  One row per (publication, kind): the figure
-- closest to the "order book" / "order inflow" wording, the largest per document (normally the company total).

CREATE TABLE order_book_figures (
    figure_id         bigserial PRIMARY KEY,
    issuer_id         uuid NOT NULL REFERENCES issuers (issuer_id),
    publication_id    uuid NOT NULL REFERENCES document_publications (publication_id),
    published_at      timestamptz NOT NULL,
    quarter_end       date NOT NULL,                -- quarter the document reports on (Jan-Mar filing -> December)
    kind              text NOT NULL CHECK (kind IN ('BOOK', 'INFLOW')),
    amount_cr         numeric NOT NULL,
    sentence          text NOT NULL,
    extractor_version text NOT NULL,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (publication_id, kind, extractor_version)
);
CREATE INDEX order_book_figures_issuer ON order_book_figures (issuer_id, quarter_end);

INSERT INTO schema_migrations (version) VALUES ('0017_order_book_figures');
