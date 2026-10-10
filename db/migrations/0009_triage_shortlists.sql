-- 0009: the weekly shortlist for AI triage (spec sections 1, 5.2, 5.3, 18.2, 18.3).
--
-- ``triage_shortlists`` is one row per week (Monday, IST): the cutoff the queue was read at and the
-- allocation policy used.  ``triage_shortlist_items`` is one row per company in the combined queue
-- at that cutoff, shortlisted or not, so nothing in the queue disappears from view:
--
-- * UPDATE        U0, a company with an open case; never capped
-- * RANKED        P1 then P2, in ranking order (milestone soon, stage, materiality band, waiting
--                 time, deterministic hash); optionally capped
-- * EXPLORATION   oldest waiting first among ranked companies over the cap and P3 companies the
--                 routes marked for exploration
-- * AUDIT         a rotating sample of the remaining P3 (watch) companies
-- * DEFERRED      P1/P2 over the cap and outside exploration; keeps its waiting time
-- * WATCH         P3 not sampled this week
-- * COOLDOWN      triaged within the cooldown with nothing that bypasses it
-- * DATA_REPAIR   D; its own queue, never a fundamental verdict
--
-- ``stale`` marks a company waiting longer than the policy's stale_days (STALE_UNRESEARCHED in
-- 18.3): it stays in the queue, and triage checks the catalyst still holds.  The triage result is
-- recorded on the item (``triage_action``, once); ``revision`` guards that write.

BEGIN;

CREATE TABLE triage_shortlists (
    shortlist_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start       date NOT NULL UNIQUE CHECK (extract(isodow FROM week_start) = 1),
    cutoff           timestamptz NOT NULL,
    mode             text NOT NULL DEFAULT 'LIVE'
                     CHECK (mode IN ('LIVE','PUBLIC_INFORMATION_RECONSTRUCTION','ACTUAL_SYSTEM_REPLAY')),
    policy_version   text NOT NULL,
    policy           jsonb NOT NULL,
    summary          jsonb NOT NULL DEFAULT '{}',
    created_by       text NOT NULL DEFAULT 'system',
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE triage_shortlist_items (
    shortlist_id     uuid NOT NULL REFERENCES triage_shortlists,
    issuer_id        uuid NOT NULL REFERENCES issuers,
    slot             text NOT NULL CHECK (slot IN ('UPDATE','RANKED','EXPLORATION','AUDIT',
                                                   'DEFERRED','WATCH','COOLDOWN','DATA_REPAIR')),
    position         integer,                       -- order within the shortlist; NULL when not shortlisted
    priority_class   text NOT NULL CHECK (priority_class IN ('U0','P1','P2','P3','D')),
    corroborated     boolean NOT NULL DEFAULT false,
    waiting_since    timestamptz NOT NULL,
    stale            boolean NOT NULL DEFAULT false,
    reason           text NOT NULL,
    note             text,                          -- why this slot (cap reached, cooldown until ...)
    ranking          jsonb NOT NULL,
    evaluation_ids   uuid[] NOT NULL,
    trigger_event_version_ids uuid[] NOT NULL DEFAULT '{}',
    triage_action    text CHECK (triage_action IN ('DEEP_RESEARCH','WATCH_MILESTONE','REJECT_WITH_REASON',
                                                   'DATA_REPAIR','DEFER_BUDGET')),
    triage_note      text,
    triaged_by       text,
    triaged_at       timestamptz,
    revision         integer NOT NULL DEFAULT 1,
    PRIMARY KEY (shortlist_id, issuer_id),
    CHECK ((position IS NOT NULL) = (slot IN ('UPDATE','RANKED','EXPLORATION','AUDIT'))),
    CHECK (triage_action IS NULL OR slot IN ('UPDATE','RANKED','EXPLORATION','AUDIT')),
    CHECK ((triage_action IS NULL) = (triaged_at IS NULL))
);
CREATE INDEX triage_shortlist_items_issuer ON triage_shortlist_items (issuer_id) WHERE triage_action IS NOT NULL;

INSERT INTO schema_migrations (version) VALUES ('0009_triage_shortlists');

COMMIT;
