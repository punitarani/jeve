-- MEM-0002: four typed belief slots per person, and who knows whom.
--
-- A belief is a level, not a sentence: how reliable a vendor is, how strained
-- an employer, how trustworthy a counterparty, and whether a fact is known.
-- Revised by score questions inside requests that are already being made,
-- never by a call of their own. Relationships are a strength that grows when
-- two people talk and decays in SQL when they do not.
CREATE TABLE beliefs (
    person_id   text        NOT NULL REFERENCES persons(id),
    slot        text        NOT NULL CHECK (slot IN (
                                'vendor_reliability', 'employer_strain',
                                'counterparty_trust', 'knows_of')),
    entity_id   text        NOT NULL,
    level       smallint    NOT NULL CHECK (level BETWEEN 0 AND 3),
    updated_sim bigint      NOT NULL,
    PRIMARY KEY (person_id, slot, entity_id)
);
CREATE INDEX beliefs_entity ON beliefs (slot, entity_id);

CREATE TABLE relationships (
    a           text        NOT NULL REFERENCES persons(id),
    b           text        NOT NULL REFERENCES persons(id),
    strength    smallint    NOT NULL CHECK (strength BETWEEN 1 AND 3),
    last_sim    bigint      NOT NULL,
    PRIMARY KEY (a, b),
    CHECK (a < b)
);
