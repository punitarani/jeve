-- WORLD-0010: archetype flows — rent, supplies and stock, credit lines.
--
-- A retailer with a supplier keeps stock, and a sale takes a unit of it; a
-- supplier can put its prices up; a firm short of runway can draw a line of
-- credit from the bank, and the bank keeps the book of loans.
ALTER TABLE orgs ADD COLUMN stock_units integer NOT NULL DEFAULT 0 CHECK (stock_units >= 0);
ALTER TABLE orgs ADD COLUMN price_multiplier numeric(6,3) NOT NULL DEFAULT 1.0 CHECK (price_multiplier > 0);
ALTER TABLE orgs ADD COLUMN credit_asked_day integer;

CREATE TABLE loans (
    id              bigserial PRIMARY KEY,
    lender_org_id   text        NOT NULL REFERENCES orgs(id),
    borrower_org_id text        NOT NULL REFERENCES orgs(id),
    principal_cents bigint      NOT NULL CHECK (principal_cents > 0),
    balance_cents   bigint      NOT NULL CHECK (balance_cents >= 0),
    rate_bp         integer     NOT NULL CHECK (rate_bp >= 0),
    opened_sim      bigint      NOT NULL,
    closed_sim      bigint,
    opened_seq      bigint      REFERENCES events(seq),
    CHECK (closed_sim IS NULL OR closed_sim >= opened_sim)
);
CREATE INDEX loans_open ON loans (borrower_org_id) WHERE closed_sim IS NULL;

-- A till is any retailer's, and what can be down is whatever runs it.
ALTER TABLE retail_sales RENAME COLUMN pos_down TO till_down;
