-- WORLD-0005: the loops that close.

-- A ticket ends. `answered_sim`/`answered_seq` say when support replied;
-- `asked_day` is the last sim-day its reporter was asked to confirm.
ALTER TABLE tickets ADD COLUMN answered_sim bigint;
ALTER TABLE tickets ADD COLUMN answered_seq bigint;
ALTER TABLE tickets ADD COLUMN asked_day integer;
ALTER TABLE tickets ADD COLUMN reopened integer NOT NULL DEFAULT 0;

-- A bill is answered once a day. `asked_day` is the last sim-day its payer was
-- asked; `issued_seq` replaces a scan of the event log by JSON payload, which
-- ran once per bill per tick and grew with the log.
ALTER TABLE invoices ADD COLUMN issued_seq bigint;
ALTER TABLE invoices ADD COLUMN asked_day integer;
ALTER TABLE invoices ADD COLUMN deferrals integer NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN chase_asked_day integer;
ALTER TABLE invoices ADD COLUMN chased_sim bigint;
ALTER TABLE invoices ADD COLUMN written_off_sim bigint;
CREATE INDEX invoices_open ON invoices (due_sim) WHERE paid_sim IS NULL AND written_off_sim IS NULL;

-- Who has noticed an outage, and when they were last asked whether to report
-- it. `notice_sim` is drawn once per (person, incident) (CORE-0009): the same
-- person notices the same outage at the same moment in every arm of a
-- counterfactual.
CREATE TABLE outage_notices (
    incident_id     bigint      NOT NULL REFERENCES incidents(id),
    person_id       text        NOT NULL REFERENCES persons(id),
    notice_sim      bigint      NOT NULL,
    asked_day       integer,
    ticket_id       bigint      REFERENCES tickets(id),
    PRIMARY KEY (incident_id, person_id)
);
CREATE INDEX outage_notices_due ON outage_notices (incident_id, notice_sim) WHERE ticket_id IS NULL;
