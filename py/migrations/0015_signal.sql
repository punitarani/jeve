-- WORLD-0013: decisions, interactions and bills carry what they were about.

-- What each decision was asked from: the typed facts the question set rendered
-- into words (DecisionContext.facts). NULL on rows written before this, and on
-- none after. A decision row is then evidence on its own, without the cache.
ALTER TABLE decisions ADD COLUMN facts jsonb;

-- A bill raised in person — money talked over in the cafe, or pressed in an
-- episode — is a reminder the payer's next decision is told about. The words
-- for it existed (questions.chased_words) and nothing ever set it.
ALTER TABLE invoices ADD COLUMN reminded_sim bigint;
-- Why the payer last left it unpaid, typed (Atradius: liquidity, process
-- delays and disputes are most of the real reasons).
ALTER TABLE invoices ADD COLUMN late_reason text;
-- A bill is chased more than once: a dunning cadence, not a single call.
ALTER TABLE invoices ADD COLUMN chases integer NOT NULL DEFAULT 0;

-- Who knows whom, and how they get on (MEM-0004). One row per pair, a < b,
-- moved by every encounter and episode between them and by promises kept and
-- broken. Read back into whom somebody talks to and how a conversation goes.
CREATE TABLE ties (
    a           text    NOT NULL REFERENCES persons(id),
    b           text    NOT NULL REFERENCES persons(id),
    met         integer NOT NULL DEFAULT 0 CHECK (met >= 0),
    warmth      integer NOT NULL DEFAULT 0 CHECK (warmth BETWEEN -3 AND 3),
    first_met   bigint  NOT NULL,
    last_met    bigint  NOT NULL,
    last_topic  text,
    PRIMARY KEY (a, b),
    -- Byte order, as Python's sorted() orders the pair: under a locale
    -- collation '.' and '_' can compare the other way (macOS en_US put
    -- tallybird.support.6 after tallybird.support_lead.5), and the insert fails.
    CHECK ((a COLLATE "C") < (b COLLATE "C"))
);
CREATE INDEX ties_b ON ties (b);
