-- WORLD-0011 and WORLD-0012: the loops the scenario names and the field report
-- found missing, and somewhere for each of them to write.

-- ------------------------------------------------------------------- facts

-- More things can be known and passed on: that a firm's wages are late, that
-- it is short of money, that the vendor is losing customers, that somebody
-- broke a promise. A rumour is a fact that is not true; it travels exactly
-- like one that is, which is the point of it (the scenario's shock deck).
ALTER TABLE facts DROP CONSTRAINT facts_topic_check;
ALTER TABLE facts ADD CONSTRAINT facts_topic_check
    CHECK (topic IN ('outage', 'price_rise', 'payroll_late', 'insolvency',
                     'churned', 'promise_broken'));
ALTER TABLE facts ADD COLUMN true_fact boolean NOT NULL DEFAULT true;
ALTER TABLE facts ADD COLUMN about_person_id text REFERENCES persons(id);

-- ------------------------------------------------------- outages and customers

-- How somebody got their work done while a feature was down (the scenario's
-- behaviour #5, "workaround divergence"): the latest answer they gave.
ALTER TABLE outage_notices ADD COLUMN workaround text;

-- A subscription can end, and start again.
ALTER TABLE subscriptions ADD COLUMN cancelled_sim bigint;

-- ------------------------------------------------------------------ invoices

-- A bill can be queried, and sent by hand while the invoicing feature is down.
ALTER TABLE invoices ADD COLUMN dispute_asked boolean NOT NULL DEFAULT false;
ALTER TABLE invoices ADD COLUMN disputed_sim bigint;
ALTER TABLE invoices ADD COLUMN dispute_resolution text
    CHECK (dispute_resolution IN ('stand_firm', 'discount', 'write_off'));
ALTER TABLE invoices ADD COLUMN manual boolean NOT NULL DEFAULT false;
ALTER TABLE invoices ADD COLUMN reconciled boolean;

-- Bills already in a running world are past the moment anyone would query them.
UPDATE invoices SET dispute_asked = true;

-- ---------------------------------------------------------------- timesheets

-- The law firm bills the hours it logs (the scenario's Halloran & Pike row).
-- A day's billable minutes exist whether or not anybody logs them; logged
-- late, some are forgotten; never logged, all of them are.
CREATE TABLE timesheets (
    person_id       text        NOT NULL REFERENCES persons(id),
    day             integer     NOT NULL,
    minutes         integer     NOT NULL CHECK (minutes >= 0),
    rate_cents      integer     NOT NULL CHECK (rate_cents >= 0),
    logged_day      integer,
    logged_minutes  integer,
    on_paper        boolean     NOT NULL DEFAULT false,
    lost            boolean     NOT NULL DEFAULT false,
    billed_month    integer,
    PRIMARY KEY (person_id, day),
    CHECK ((logged_day IS NULL) = (logged_minutes IS NULL))
);
CREATE INDEX timesheets_unbilled ON timesheets (billed_month)
    WHERE logged_day IS NOT NULL AND billed_month IS NULL;

-- ---------------------------------------------------------------------- rota

-- Departures from somebody's usual hours: off sick, or called in to cover.
CREATE TABLE rota (
    id              bigserial   PRIMARY KEY,
    person_id       text        NOT NULL REFERENCES persons(id),
    starts_sim      bigint      NOT NULL,
    ends_sim        bigint      NOT NULL,
    kind            text        NOT NULL CHECK (kind IN ('absent', 'extra')),
    reason          text        NOT NULL,
    CHECK (ends_sim > starts_sim)
);
CREATE INDEX rota_person ON rota (person_id, starts_sim);
