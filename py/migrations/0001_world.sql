-- The world: control, the record, and current state.
--
-- CORE-0007. Two things are load-bearing here and neither is negotiable:
-- events carry the ids of the events that caused them, and money is
-- double-entry with balance enforced by the database rather than by code.

-- ---------------------------------------------------------------- control

-- Singleton. `only_row` is the trick that makes it one: a primary key over a
-- column constrained to a single value.
CREATE TABLE sim_meta (
    only_row        boolean PRIMARY KEY DEFAULT true CHECK (only_row),
    run_id          text        NOT NULL,
    root_seed       bigint      NOT NULL,
    sim_time        bigint      NOT NULL DEFAULT 0,  -- sim-seconds from epoch
    tick_seq        bigint      NOT NULL DEFAULT 0,
    status          text        NOT NULL DEFAULT 'paused'
                    CHECK (status IN ('running','paused','waiting_on_model','halted')),
    engine_sha      text        NOT NULL DEFAULT 'unknown',
    speed           double precision NOT NULL DEFAULT 1.0,
    started_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- The discrete-event queue, durable so a restart resumes mid-schedule.
CREATE TABLE scheduled (
    id              bigserial PRIMARY KEY,
    due_sim_time    bigint      NOT NULL,
    ord             integer     NOT NULL DEFAULT 0,  -- tie-break, for determinism
    kind            text        NOT NULL,
    subject_id      text,
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX scheduled_due ON scheduled (due_sim_time, ord, id);

-- ----------------------------------------------------------------- record

CREATE TABLE events (
    seq             bigserial PRIMARY KEY,
    sim_time        bigint      NOT NULL,
    tick_seq        bigint      NOT NULL,
    kind            text        NOT NULL,
    actor_id        text,
    org_id          text,
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- The most important column in the schema: a cascade is a recursive query
    -- over this, not something a reader has to infer.
    causes          bigint[]    NOT NULL DEFAULT '{}',
    decision_id     bigint
);
CREATE INDEX events_sim_time ON events (sim_time, seq);
CREATE INDEX events_kind     ON events (kind, seq);
CREATE INDEX events_org      ON events (org_id, seq);
CREATE INDEX events_causes   ON events USING gin (causes);

-- ------------------------------------------------------------------ orgs

CREATE TABLE orgs (
    id              text PRIMARY KEY,
    name            text        NOT NULL,
    kind            text        NOT NULL
                    CHECK (kind IN ('software','law','accounting','cafe')),
    -- An org's rules are data, so one org changes without touching another.
    policy          jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE persons (
    id              text PRIMARY KEY,
    org_id          text        REFERENCES orgs(id),
    name            text        NOT NULL,
    role            text        NOT NULL,
    -- 'staff' get a full decision surface; 'counterparty' make a few typed
    -- decisions a day (customers, clients, subscribers).
    kind            text        NOT NULL CHECK (kind IN ('staff','counterparty')),
    traits          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    decision_seq    bigint      NOT NULL DEFAULT 0,
    beliefs         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status          text        NOT NULL DEFAULT 'idle'
);
CREATE INDEX persons_org ON persons (org_id, kind);

-- ----------------------------------------------------------------- money

CREATE TABLE accounts (
    id              text PRIMARY KEY,
    org_id          text        REFERENCES orgs(id),
    name            text        NOT NULL,
    -- 'external' is the outside world: wages to households, rent, suppliers,
    -- walk-in customers. Having it as a real account is what lets total cash
    -- be checked for stock-flow consistency.
    kind            text        NOT NULL
                    CHECK (kind IN ('cash','receivable','payable','revenue','expense','external'))
);
CREATE INDEX accounts_org ON accounts (org_id);

CREATE TABLE ledger_txns (
    id              bigserial PRIMARY KEY,
    sim_time        bigint      NOT NULL,
    memo            text        NOT NULL,
    event_seq       bigint      REFERENCES events(seq)
);

CREATE TABLE ledger_entries (
    id              bigserial PRIMARY KEY,
    txn_id          bigint      NOT NULL REFERENCES ledger_txns(id) ON DELETE CASCADE,
    account_id      text        NOT NULL REFERENCES accounts(id),
    -- Integer cents. Floating-point money in a simulation that runs for
    -- sim-years would drift until the invariant check became meaningless.
    amount_cents    bigint      NOT NULL CHECK (amount_cents <> 0)
);
CREATE INDEX ledger_entries_txn     ON ledger_entries (txn_id);
CREATE INDEX ledger_entries_account ON ledger_entries (account_id, id);

-- Double entry, enforced here rather than in code.
--
-- The constraint is DEFERRED: entries arrive one INSERT at a time, so the sum
-- is only meaningful once the transaction is complete. An unbalanced set of
-- entries therefore fails at COMMIT, which is exactly when the writer can
-- still be told about it.
CREATE FUNCTION assert_txn_balances() RETURNS trigger AS $$
DECLARE
    total bigint;
    txn   bigint := COALESCE(NEW.txn_id, OLD.txn_id);
BEGIN
    SELECT COALESCE(sum(amount_cents), 0) INTO total
      FROM ledger_entries WHERE txn_id = txn;
    IF total <> 0 THEN
        RAISE EXCEPTION
            'ledger transaction % does not balance: % cents unaccounted for',
            txn, total
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_entries_balance
    AFTER INSERT OR UPDATE OR DELETE ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_txn_balances();

-- ------------------------------------------------------------ the product

CREATE TABLE modules (
    id              text PRIMARY KEY,      -- timetrack | invoicing | pos
    name            text        NOT NULL,
    status          text        NOT NULL DEFAULT 'up' CHECK (status IN ('up','down'))
);

CREATE TABLE incidents (
    id              bigserial PRIMARY KEY,
    module_id       text        NOT NULL REFERENCES modules(id),
    started_sim     bigint      NOT NULL,
    ended_sim       bigint,
    severity        integer     NOT NULL DEFAULT 1,
    cause_event_seq bigint      REFERENCES events(seq),
    CHECK (ended_sim IS NULL OR ended_sim >= started_sim)
);
CREATE INDEX incidents_open ON incidents (module_id) WHERE ended_sim IS NULL;

CREATE TABLE subscriptions (
    id              bigserial PRIMARY KEY,
    org_id          text        REFERENCES orgs(id),
    person_id       text        REFERENCES persons(id),
    module_id       text        NOT NULL REFERENCES modules(id),
    monthly_cents   bigint      NOT NULL CHECK (monthly_cents > 0),
    active          boolean     NOT NULL DEFAULT true,
    -- A subscriber is an org or an outside person, never both and never neither.
    CHECK ((org_id IS NULL) <> (person_id IS NULL))
);

-- ------------------------------------------------------------------ work

CREATE TABLE tickets (
    id              bigserial PRIMARY KEY,
    opened_sim      bigint      NOT NULL,
    closed_sim      bigint,
    reporter_id     text        NOT NULL REFERENCES persons(id),
    assignee_id     text        REFERENCES persons(id),
    module_id       text        REFERENCES modules(id),
    incident_id     bigint      REFERENCES incidents(id),
    queue           text        NOT NULL DEFAULT 'unsorted',
    severity        double precision NOT NULL DEFAULT 1.0,
    status          text        NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','triaged','answered','closed')),
    subject         text        NOT NULL,
    decided_by      text        NOT NULL DEFAULT 'rules'
                    CHECK (decided_by IN ('rules','jev','llm')),
    CHECK (closed_sim IS NULL OR closed_sim >= opened_sim)
);
CREATE INDEX tickets_open ON tickets (status, opened_sim) WHERE status <> 'closed';

CREATE TABLE invoices (
    id              bigserial PRIMARY KEY,
    from_org_id     text        NOT NULL REFERENCES orgs(id),
    to_org_id       text        REFERENCES orgs(id),
    to_person_id    text        REFERENCES persons(id),
    issued_sim      bigint      NOT NULL,
    due_sim         bigint      NOT NULL,
    paid_sim        bigint,
    amount_cents    bigint      NOT NULL CHECK (amount_cents > 0),
    kind            text        NOT NULL,   -- subscription | services | supplies
    -- Set when the issue was delayed by an outage; this is the observable for
    -- the headline cascade.
    blocked_ticks   integer     NOT NULL DEFAULT 0,
    CHECK ((to_org_id IS NULL) <> (to_person_id IS NULL)),
    CHECK (due_sim >= issued_sim),
    CHECK (paid_sim IS NULL OR paid_sim >= issued_sim)
);
CREATE INDEX invoices_unpaid ON invoices (due_sim) WHERE paid_sim IS NULL;

CREATE TABLE payments (
    id              bigserial PRIMARY KEY,
    invoice_id      bigint      NOT NULL REFERENCES invoices(id),
    paid_sim        bigint      NOT NULL,
    amount_cents    bigint      NOT NULL CHECK (amount_cents > 0),
    txn_id          bigint      REFERENCES ledger_txns(id),
    days_late       integer     NOT NULL DEFAULT 0,
    decided_by      text        NOT NULL DEFAULT 'rules'
                    CHECK (decided_by IN ('rules','jev','llm'))
);
CREATE INDEX payments_invoice ON payments (invoice_id);

CREATE TABLE cafe_sales (
    id              bigserial PRIMARY KEY,
    sim_time        bigint      NOT NULL,
    person_id       text        REFERENCES persons(id),
    amount_cents    bigint      NOT NULL CHECK (amount_cents > 0),
    txn_id          bigint      REFERENCES ledger_txns(id),
    pos_down        boolean     NOT NULL DEFAULT false
);
CREATE INDEX cafe_sales_time ON cafe_sales (sim_time);

-- ------------------------------------------------------------- decisions

CREATE TABLE decisions (
    id              bigserial PRIMARY KEY,
    person_id       text        NOT NULL REFERENCES persons(id),
    decision_seq    bigint      NOT NULL,
    sim_time        bigint      NOT NULL,
    tick_seq        bigint      NOT NULL,
    question_set    text        NOT NULL,
    -- Content hash of the model call, or NULL when rules decided.
    model_call      text,
    source          text        NOT NULL DEFAULT 'rules'
                    CHECK (source IN ('rules','jev','llm')),
    -- Everything the model returned, so a run can be explained without it.
    distributions   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    prng_path       text        NOT NULL DEFAULT '',
    draws           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    chosen          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (person_id, decision_seq)
);
CREATE INDEX decisions_person ON decisions (person_id, decision_seq DESC);

ALTER TABLE events
    ADD CONSTRAINT events_decision_fk
    FOREIGN KEY (decision_id) REFERENCES decisions(id);

-- Answers kept by content hash, so a re-executed tick after a crash finds
-- them instead of paying twice, and a replay run needs no network at all.
CREATE TABLE model_calls (
    hash            text PRIMARY KEY,
    model           text        NOT NULL,
    provider        text,
    request         jsonb,
    response        jsonb       NOT NULL,
    input_tokens    integer     NOT NULL DEFAULT 0,
    output_tokens   integer     NOT NULL DEFAULT 0,
    cost_usd        double precision NOT NULL DEFAULT 0,
    cost_estimated  boolean     NOT NULL DEFAULT false,
    latency_s       double precision NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
