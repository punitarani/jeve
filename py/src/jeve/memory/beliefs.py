"""Typed beliefs and relationships (MEM-0003).

A belief is a slot with four described levels, held by a person about an
entity: how reliable a vendor's software is, how strained their employer is,
how trustworthy a counterparty is, and whether they know of a fact at all. It
is revised by a `score` question asked inside a request that is being made
anyway — nobody is called to reflect — and read back as words into the state
of the next question it bears on. A relationship is a strength that grows when
two people talk and decays, in SQL, when they do not.

Levels are the whole vocabulary. "Klaus is dedicated to his research" has no
slot here, and that is the typed thesis's limit (MEM-0001), measured rather
than hidden.
"""

from __future__ import annotations

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.clock import DAY

SLOTS: dict[str, tuple[str, str, str, str]] = {
    "vendor_reliability": (
        "Their software is unreliable; it is down all the time.",
        "Their software is shaky; it goes down more than it should.",
        "Their software is mostly reliable.",
        "Their software is rock solid; they cannot remember it failing.",
    ),
    "employer_strain": (
        "The firm is doing well.",
        "The firm is tightening its belt.",
        "The firm is under real strain; payroll has been held.",
        "The firm may not survive the season.",
    ),
    "counterparty_trust": (
        "They do not pay.",
        "They pay late, and only when chased.",
        "They pay, eventually.",
        "They pay on time.",
    ),
    "knows_of": (
        "They have not heard of it.",
        "They have heard of it.",
        "They have heard of it.",
        "They have heard of it.",
    ),
}
"""Each slot's four levels, in the words a question shows."""

KNOWN = 1
"""The one level `knows_of` uses: a fact is known or it is not."""
RELATIONSHIP_DECAY_AFTER = 14 * DAY
"""Two weeks without a word and a relationship weakens by one."""


def words(slot: str, level: object) -> str:
    """The sentence a level stands for, clamped to the slot's range."""

    described = SLOTS[slot]
    index = max(0, min(len(described) - 1, int(str(level)) if level is not None else 0))
    return described[index]


def get(
    conn: Connection[DictRow], person_id: str, slot: str, entity_id: str
) -> int | None:
    row = conn.execute(
        "SELECT level FROM beliefs "
        "WHERE person_id = %s AND slot = %s AND entity_id = %s",
        (person_id, slot, entity_id),
    ).fetchone()
    return int(row["level"]) if row else None


def set_level(
    conn: Connection[DictRow],
    person_id: str,
    slot: str,
    entity_id: str,
    level: int,
    sim_time: int,
) -> None:
    """Write a belief, replacing what was held. A belief is the latest
    revision, not a history: the event log is the history."""

    conn.execute(
        "INSERT INTO beliefs (person_id, slot, entity_id, level, updated_sim) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (person_id, slot, entity_id) DO UPDATE "
        "SET level = EXCLUDED.level, updated_sim = EXCLUDED.updated_sim",
        (person_id, slot, entity_id, max(0, min(3, int(level))), sim_time),
    )


def learn(conn: Connection[DictRow], person_id: str, fact: str, sim_time: int) -> bool:
    """A fact is known once and for good. Returns whether it was news."""

    row = conn.execute(
        "INSERT INTO beliefs (person_id, slot, entity_id, level, updated_sim) "
        "VALUES (%s, 'knows_of', %s, %s, %s) "
        "ON CONFLICT (person_id, slot, entity_id) DO NOTHING RETURNING 1",
        (person_id, fact, KNOWN, sim_time),
    ).fetchone()
    return row is not None


def knows(conn: Connection[DictRow], person_id: str, fact: str) -> bool:
    return get(conn, person_id, "knows_of", fact) is not None


def known_by(conn: Connection[DictRow], fact: str) -> list[str]:
    return [
        str(row["person_id"])
        for row in conn.execute(
            "SELECT person_id FROM beliefs WHERE slot = 'knows_of' AND entity_id = %s "
            "ORDER BY person_id",
            (fact,),
        ).fetchall()
    ]


def firm_view(
    conn: Connection[DictRow], org_id: str, slot: str, entity_id: str
) -> int | None:
    """What a firm's people think, as the loudest of them: the lowest level
    anybody on its staff holds. A vendor is as reliable as the person who
    lost a day to it says it is."""

    row = conn.execute(
        "SELECT min(b.level) AS level FROM beliefs b "
        "JOIN persons p ON p.id = b.person_id "
        "WHERE p.org_id = %s AND p.kind = 'staff' AND b.slot = %s AND b.entity_id = %s",
        (org_id, slot, entity_id),
    ).fetchone()
    return int(row["level"]) if row and row["level"] is not None else None


def bump_relationship(conn: Connection[DictRow], a: str, b: str, sim_time: int) -> None:
    """Two people talked: one step closer, to a ceiling of three."""

    if a == b:
        return
    low, high = sorted((a, b))
    conn.execute(
        "INSERT INTO relationships (a, b, strength, last_sim) VALUES (%s, %s, 1, %s) "
        "ON CONFLICT (a, b) DO UPDATE "
        "SET strength = least(3, relationships.strength + 1), "
        "last_sim = EXCLUDED.last_sim",
        (low, high, sim_time),
    )


def strengths(conn: Connection[DictRow], person_id: str) -> dict[str, int]:
    """How well this person knows everybody they know at all."""

    return {
        str(row["other"]): int(row["strength"])
        for row in conn.execute(
            "SELECT CASE WHEN a = %s THEN b ELSE a END AS other, strength "
            "FROM relationships WHERE a = %s OR b = %s",
            (person_id, person_id, person_id),
        ).fetchall()
    }


def decay(conn: Connection[DictRow], sim_time: int) -> int:
    """Nightly: every relationship idle for two weeks loses a step, and one
    that reaches nothing is forgotten. Aggregation, not generation (MEM-0001).
    Returns how many were touched."""

    cutoff = sim_time - RELATIONSHIP_DECAY_AFTER
    gone = conn.execute(
        "DELETE FROM relationships WHERE strength <= 1 AND last_sim < %s", (cutoff,)
    ).rowcount
    weakened = conn.execute(
        "UPDATE relationships SET strength = strength - 1, last_sim = %s "
        "WHERE strength > 1 AND last_sim < %s",
        (sim_time, cutoff),
    ).rowcount
    return int(gone) + int(weakened)
