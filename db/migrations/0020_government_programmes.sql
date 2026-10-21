-- 0020: large government programmes (Rs 10,000 crore+ outlay, from PIB Cabinet releases and Budget speeches, dated
-- by the first announcement) and each company's exposure to them, dated from the company's own filings.
-- programme_exposure keeps every dated mention as its own row, so any cutoff can ask "what was public by then".

CREATE TABLE govt_programmes (
    programme_id   bigserial PRIMARY KEY,
    name           text NOT NULL,
    announced_date date NOT NULL,
    outlay_cr      numeric,
    ministry       text,
    keywords       text NOT NULL,                  -- | separated, lowercase; phrases matched as phrases
    sectors        text,
    source_url     text NOT NULL,
    notes          text,
    UNIQUE (name, announced_date)
);

CREATE TABLE programme_mentions (
    programme_id   bigint NOT NULL REFERENCES govt_programmes (programme_id),
    issuer_id      uuid NOT NULL REFERENCES issuers (issuer_id),
    publication_id uuid NOT NULL,
    published_at   timestamptz NOT NULL,
    is_order       boolean NOT NULL,               -- the mention is about an order / award / contract / supply
    snippet        text,
    PRIMARY KEY (programme_id, publication_id)
);
CREATE INDEX programme_mentions_issuer ON programme_mentions (issuer_id, published_at);

INSERT INTO schema_migrations (version) VALUES ('0020_government_programmes');
