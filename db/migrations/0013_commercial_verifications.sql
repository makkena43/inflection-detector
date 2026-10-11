-- 0013: a model's verdict on each commercial passage the rules found.
--
-- The rules (inflection.commercial.vocabulary) find candidate passages; a language model then reads
-- each one in its surrounding text and says whether it discloses a new, company-specific event of
-- that kind.  A REJECTED passage is not placed onto the company's events.  Verdicts are kept per
-- verifier version, so a new prompt or model re-reads passages instead of overwriting history.

CREATE TABLE commercial_verifications (
    mention_id        uuid NOT NULL REFERENCES commercial_mentions (mention_id),
    verifier_version  text NOT NULL,
    verdict           text NOT NULL CHECK (verdict IN ('CONFIRMED', 'REJECTED', 'UNCERTAIN')),
    family            text,                      -- the family the model reads, when it differs or is NONE
    reason            text NOT NULL,
    model             text NOT NULL,
    input_tokens      integer,
    output_tokens     integer,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mention_id, verifier_version)
);

INSERT INTO schema_migrations (version) VALUES ('0013_commercial_verifications');
