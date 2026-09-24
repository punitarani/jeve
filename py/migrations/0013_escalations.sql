-- DECIDE-0005: tier-1 escalation, and what it said.
--
-- One row per decision whose uncertain questions were asked again of a flash
-- LLM (DECIDE-0002's first tier). In shadow both answers are kept and Jev's
-- decided; live, the escalated answer decided and `decisions.source` is 'llm'.
-- Measurement, not world state: nothing in the world reads this table, and a
-- replay that cannot find a shadow answer simply records nothing.
CREATE TABLE escalations (
    id              bigserial   PRIMARY KEY,
    decision_id     bigint      NOT NULL REFERENCES decisions(id),
    question_set    text        NOT NULL,
    sim_time        bigint      NOT NULL,
    mode            text        NOT NULL CHECK (mode IN ('shadow', 'live')),
    sampled         boolean     NOT NULL DEFAULT false,
    triggers        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    asks            text[]      NOT NULL,
    jev             jsonb       NOT NULL,
    llm             jsonb       NOT NULL,
    model           text        NOT NULL,
    call_hash       text        NOT NULL,
    agrees          boolean     NOT NULL,
    applied         boolean     NOT NULL DEFAULT false
);
CREATE INDEX escalations_time ON escalations (sim_time);
CREATE INDEX escalations_set ON escalations (question_set, mode);
