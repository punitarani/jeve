-- WORLD-0003: space is load-bearing.
--
-- Where each staff member is, tile by tile. One row per person, overwritten
-- each tick: the *history* of movement is in `events` (agent.moved, on zone
-- change only), this is the current frame plus the route walked to reach it,
-- which is what a client needs to interpolate between coarse server ticks.
CREATE TABLE positions (
    person_id       text PRIMARY KEY REFERENCES persons(id),
    zone            text        NOT NULL
                    CHECK (zone IN ('software_office','law_office',
                                    'accounting_office','cafe','plaza','home')),
    -- NULL while at home: off the map.
    x               integer,
    y               integer,
    -- Tiles walked during `moved_tick`, inclusive of both ends. Empty if the
    -- person stayed put.
    path            jsonb       NOT NULL DEFAULT '[]'::jsonb,
    moved_tick      bigint      NOT NULL DEFAULT 0,
    mood            integer     NOT NULL DEFAULT 2,
    CHECK ((zone = 'home') = (x IS NULL)),
    CHECK ((x IS NULL) = (y IS NULL))
);
CREATE INDEX positions_zone ON positions (zone);

-- An encounter can escalate an outage, once. The event that did it is kept so
-- `incident.ended` can cite it: that citation is the link by which a
-- conversation in the cafe reaches an invoice.
ALTER TABLE incidents ADD COLUMN escalated_sim bigint;
ALTER TABLE incidents ADD COLUMN escalation_event_seq bigint REFERENCES events(seq);

-- SIM-0001: the daemon pauses itself when the day's model budget is spent.
ALTER TABLE sim_meta DROP CONSTRAINT sim_meta_status_check;
ALTER TABLE sim_meta ADD CONSTRAINT sim_meta_status_check
    CHECK (status IN ('running','paused','paused_budget','waiting_on_model','halted'));
