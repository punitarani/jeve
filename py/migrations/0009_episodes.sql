-- WORLD-0006 and MEM-0002: an encounter can become an episode, and an episode
-- has somewhere to write.
--
-- Until now the only thing a meeting could change was the end of an outage
-- (WORLD-0003). One consequence rule meant a richer meeting had nowhere to put
-- its result, so adding rounds to a conversation would have been decoration.
-- These five tables are the somewhere: a fact that can travel, a record of who
-- holds it, a promise that raises the pressure on a bill, and the episode
-- itself with its participants.

-- ------------------------------------------------------------------- facts

-- A thing that can be known and passed on. Typed, and never generated: a row
-- names its topic and the entity it is about, and a question set renders that
-- into words. `id` is derived from what the fact is about, so the same outage
-- is the same fact in every arm of a counterfactual.
CREATE TABLE facts (
    id              text PRIMARY KEY,
    topic           text        NOT NULL CHECK (topic IN ('outage', 'price_rise')),
    about_org_id    text        REFERENCES orgs(id),
    about_module_id text        REFERENCES modules(id),
    incident_id     bigint      REFERENCES incidents(id),
    born_sim        bigint      NOT NULL,
    born_seq        bigint      REFERENCES events(seq),
    -- An outage fact stops travelling when the outage ends: yesterday's
    -- trouble is gossip, not news, and it must not keep minting notices.
    stale_sim       bigint
);
CREATE INDEX facts_live ON facts (topic, born_sim) WHERE stale_sim IS NULL;

-- Who knows what, and from whom. `hops` is 0 for first-hand knowledge and one
-- more than the teller's for anything passed on, which makes diffusion depth
-- a column rather than a walk over the event log.
CREATE TABLE knowledge (
    person_id       text        NOT NULL REFERENCES persons(id),
    fact_id         text        NOT NULL REFERENCES facts(id),
    learned_sim     bigint      NOT NULL,
    learned_seq     bigint      REFERENCES events(seq),
    from_person_id  text        REFERENCES persons(id),
    hops            integer     NOT NULL DEFAULT 0 CHECK (hops >= 0),
    PRIMARY KEY (person_id, fact_id),
    -- First-hand means nobody told them; being told means hops > 0. The two
    -- are the same statement and the database holds them together.
    CHECK ((from_person_id IS NULL) = (hops = 0))
);
CREATE INDEX knowledge_fact ON knowledge (fact_id, learned_sim);

-- --------------------------------------------------------------- episodes

-- A bounded, multi-round interaction among people who are together and have
-- something between them. The one-shot encounter of WORLD-0003 is still there
-- and is still what happens to everyone else; this is the higher-resolution
-- arm, and `stake` is why it was worth running.
CREATE TABLE episodes (
    id              bigserial PRIMARY KEY,
    zone            text        NOT NULL
                    CHECK (zone IN ('software_office', 'law_office',
                                    'accounting_office', 'cafe', 'plaza')),
    -- A side conversation carved out of a larger one. Depth is capped in the
    -- schema, not only in code: unbounded nesting is the failure mode the
    -- multi-resolution literature calls chain disaggregation.
    parent_id       bigint      REFERENCES episodes(id),
    depth           integer     NOT NULL DEFAULT 0 CHECK (depth BETWEEN 0 AND 1),
    stake           text        NOT NULL CHECK (stake IN ('outage', 'invoice', 'news')),
    stake_ref       text        NOT NULL,
    opened_sim      bigint      NOT NULL,
    opened_seq      bigint      NOT NULL REFERENCES events(seq),
    closed_sim      bigint,
    closed_seq      bigint      REFERENCES events(seq),
    rounds          integer     NOT NULL DEFAULT 0 CHECK (rounds >= 0),
    exit_reason     text        CHECK (exit_reason IN ('settled', 'emptied', 'rounds')),
    -- The typed result, written once at close. Everything downstream cites
    -- `closed_seq`, never this column: the outcome is evidence for a reader,
    -- the events are what the world ran on.
    outcome         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CHECK ((closed_sim IS NULL) = (exit_reason IS NULL)),
    CHECK ((closed_sim IS NULL) = (closed_seq IS NULL)),
    CHECK (closed_sim IS NULL OR closed_sim >= opened_sim),
    CHECK ((parent_id IS NULL) = (depth = 0))
);
CREATE INDEX episodes_open ON episodes (opened_sim) WHERE closed_sim IS NULL;
CREATE INDEX episodes_time ON episodes (opened_sim, id);

-- `seat` is a stable slot order within an episode, drawn once when it opens.
-- Rounds iterate seats, so a replayed episode speaks in the same order as the
-- live one; iterating a set would not.
CREATE TABLE episode_participants (
    episode_id      bigint      NOT NULL REFERENCES episodes(id),
    person_id       text        NOT NULL REFERENCES persons(id),
    seat            integer     NOT NULL CHECK (seat >= 0),
    left_round      integer,
    PRIMARY KEY (episode_id, person_id),
    UNIQUE (episode_id, seat)
);
CREATE INDEX episode_participants_person ON episode_participants (person_id, episode_id);

-- ------------------------------------------------------------ commitments

-- A promise made inside an episode. Money never moves because somebody said it
-- would — the referee is still code (WORLD-0005). What a promise changes is the
-- pressure on the promiser's next decision about that bill, and whether the
-- promise was kept is then a fact about them rather than a matter of opinion.
CREATE TABLE commitments (
    id              bigserial PRIMARY KEY,
    kind            text        NOT NULL CHECK (kind IN ('pay_invoice')),
    episode_id      bigint      NOT NULL REFERENCES episodes(id),
    from_person_id  text        NOT NULL REFERENCES persons(id),
    to_person_id    text        NOT NULL REFERENCES persons(id),
    invoice_id      bigint      NOT NULL REFERENCES invoices(id),
    made_sim        bigint      NOT NULL,
    made_seq        bigint      NOT NULL REFERENCES events(seq),
    due_sim         bigint      NOT NULL,
    settled_sim     bigint,
    kept            boolean,
    CHECK (due_sim >= made_sim),
    CHECK ((settled_sim IS NULL) = (kept IS NULL))
);
CREATE INDEX commitments_open ON commitments (invoice_id) WHERE settled_sim IS NULL;
CREATE INDEX commitments_due ON commitments (due_sim) WHERE settled_sim IS NULL;
