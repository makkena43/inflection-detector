-- 0011: historical shadow replay of the discovery queue (spec sections 5, 12, 14 phase 2, 18.3).
--
-- A replay walks week by week over a past interval.  Each week it reads the candidate evaluations
-- public by the week's cutoff (Sunday midnight IST), allocates the triage shortlist with the live
-- rules, and records what the shortlist would have been.  It takes no actions: it never writes
-- triage_shortlists, packets, cases or decisions.  A shortlisted company is assumed triaged that
-- week, so the cooldown and waiting-time rules play out as they would have.
--
-- Outcomes are measured afterwards from prices and kept in the ``outcomes`` schema, apart from
-- anything an analyst or a packet reads (spec 12; docs/spec_open_issues.md #9).
--
-- * shadow_replays          one row per replay run: interval, mode, frozen policies, coverage, summary
-- * shadow_replay_weeks     one row per replayed week: slot counts and the sources it could see
-- * shadow_replay_items     shortlisted companies, plus companies with new evidence that week that
--                           were not shortlisted (the comparison group)
-- * outcomes.shadow_replay_outcomes  per item and horizon: entry and exit at the frozen execution rule,
--                           split/bonus-adjusted price return, universe median, drawdown, status
-- * outcomes.shadow_replay_winners   large later price moves, and whether the replay had shortlisted the
--                           company in time (missed winners, spec 12)
--
-- Rows are append-only; a new replay is a new run.

BEGIN;

CREATE TABLE shadow_replays (
    replay_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mode             text NOT NULL
                     CHECK (mode IN ('LIVE','PUBLIC_INFORMATION_RECONSTRUCTION','ACTUAL_SYSTEM_REPLAY')),
    first_week       date NOT NULL CHECK (extract(isodow FROM first_week) = 1),
    last_week        date NOT NULL CHECK (extract(isodow FROM last_week) = 1),
    holdout_from     date,
    policy_version   text NOT NULL,
    policy           jsonb NOT NULL,
    triage_policy    jsonb NOT NULL,
    coverage         jsonb NOT NULL,
    summary          jsonb NOT NULL,
    created_by       text NOT NULL DEFAULT 'system',
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (last_week >= first_week)
);

CREATE TABLE shadow_replay_weeks (
    replay_id        uuid NOT NULL REFERENCES shadow_replays,
    week_start       date NOT NULL CHECK (extract(isodow FROM week_start) = 1),
    cutoff           timestamptz NOT NULL,
    period           text NOT NULL CHECK (period IN ('DEVELOPMENT','HOLDOUT')),
    queue            jsonb NOT NULL,                -- the triage summary: slots, inflow, waiting time
    coverage         jsonb NOT NULL,                -- filings, results, evaluations and price days that week
    PRIMARY KEY (replay_id, week_start)
);

CREATE TABLE shadow_replay_items (
    replay_id        uuid NOT NULL,
    week_start       date NOT NULL,
    issuer_id        uuid NOT NULL REFERENCES issuers,
    slot             text NOT NULL CHECK (slot IN ('UPDATE','RANKED','EXPLORATION','AUDIT',
                                                   'DEFERRED','WATCH','COOLDOWN','DATA_REPAIR')),
    position         integer,
    shortlisted      boolean NOT NULL,
    priority_class   text NOT NULL CHECK (priority_class IN ('U0','P1','P2','P3','D')),
    routes           text[] NOT NULL,
    corroborated     boolean NOT NULL,
    waiting_since    timestamptz NOT NULL,
    reason           text NOT NULL,
    evaluation_ids   uuid[] NOT NULL,
    PRIMARY KEY (replay_id, week_start, issuer_id),
    FOREIGN KEY (replay_id, week_start) REFERENCES shadow_replay_weeks,
    CHECK ((position IS NOT NULL) = shortlisted)
);
CREATE INDEX shadow_replay_items_issuer ON shadow_replay_items (replay_id, issuer_id, week_start);

CREATE TABLE outcomes.shadow_replay_outcomes (
    replay_id        uuid NOT NULL,
    week_start       date NOT NULL,
    issuer_id        uuid NOT NULL,
    horizon          text NOT NULL,
    status           text NOT NULL CHECK (status IN ('VERIFIED','UNVERIFIED','INCOMPLETE','NO_PRICE',
                                                     'STOPPED_TRADING')),
    security_id      uuid REFERENCES securities,
    provider         text,
    entry_date       date,
    entry_close      numeric,
    exit_date        date,
    exit_close       numeric,
    price_multiplier numeric,                       -- splits and bonuses between entry and exit
    price_return     numeric,                       -- price return, dividends excluded
    benchmark_return numeric,                       -- median price return of the exchange's universe
    benchmark_count  integer,
    excess_return    numeric,
    max_drawdown     numeric,
    notes            text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (replay_id, week_start, issuer_id, horizon),
    FOREIGN KEY (replay_id, week_start, issuer_id) REFERENCES shadow_replay_items
);

CREATE TABLE outcomes.shadow_replay_winners (
    replay_id        uuid NOT NULL REFERENCES shadow_replays,
    window_start     date NOT NULL,
    security_id      uuid NOT NULL REFERENCES securities,
    issuer_id        uuid NOT NULL REFERENCES issuers,
    provider         text NOT NULL,
    entry_date       date NOT NULL,
    exit_date        date NOT NULL,
    price_return     numeric NOT NULL,
    status           text NOT NULL CHECK (status IN ('SHORTLISTED','QUEUED_NOT_SHORTLISTED',
                                                     'FIGURES_NO_NOMINATION','NO_COVERAGE')),
    first_shortlisted date,
    detail           jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (replay_id, window_start, security_id)
);

CREATE TRIGGER shadow_replays_append_only BEFORE UPDATE OR DELETE ON shadow_replays
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER shadow_replay_weeks_append_only BEFORE UPDATE OR DELETE ON shadow_replay_weeks
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER shadow_replay_items_append_only BEFORE UPDATE OR DELETE ON shadow_replay_items
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER shadow_replay_outcomes_append_only BEFORE UPDATE OR DELETE ON outcomes.shadow_replay_outcomes
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER shadow_replay_winners_append_only BEFORE UPDATE OR DELETE ON outcomes.shadow_replay_winners
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- The universe benchmark and the winner scan read every security's close on one day.
CREATE INDEX IF NOT EXISTS prices_day ON prices (trade_date, provider) WHERE adjustment = 'UNADJUSTED';

INSERT INTO schema_migrations (version) VALUES ('0011_shadow_replay');

COMMIT;
