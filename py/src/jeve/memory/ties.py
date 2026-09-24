"""Who knows whom, and how they get on (MEM-0004).

Every meeting used to be between strangers: an encounter resolved and left
nothing behind but an event, so the tenth coffee two people had together was
decided exactly as the first. A tie is the typed residue of meetings — how
often a pair has met, and a warmth from -3 (they have fallen out) to +3 (good
friends) — moved by rules from what happened, never by prose:

* a friendly word over small talk warms a tie, and money or an outage
  discussed by someone already stressed cools it;
* in an episode, a refusal cools the tie between the one who refused and the
  one asking, a promise warms it, and pressing someone hard when tempers are up
  cools it;
* a promise kept warms the tie between promiser and creditor; a broken one
  cools it by two.

What a tie changes is read back by the decisions (WORLD-0013): whom somebody
approaches in a room, and what they are told about the people in a
conversation. Nothing here decides anything.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from psycopg import Connection
from psycopg.rows import DictRow

WARMTH_MIN, WARMTH_MAX = -3, 3


@dataclass(frozen=True, slots=True)
class Tie:
    met: int = 0
    warmth: int = 0

    @property
    def friend(self) -> bool:
        return self.warmth >= 2 or (self.met >= 4 and self.warmth >= 1)

    @property
    def fallen_out(self) -> bool:
        return self.warmth <= -1

    def as_facts(self) -> dict[str, int]:
        return {"met": self.met, "warmth": self.warmth}


def _pair(x: str, y: str) -> tuple[str, str]:
    return (x, y) if x < y else (y, x)


def ties_of(
    conn: Connection[DictRow], person: str, others: Iterable[str]
) -> dict[str, Tie]:
    """This person's tie to each of `others`; strangers are absent."""

    wanted = sorted({o for o in others if o != person})
    if not wanted:
        return {}
    rows = conn.execute(
        "SELECT a, b, met, warmth FROM ties WHERE (a = %s AND b = ANY(%s)) "
        "OR (b = %s AND a = ANY(%s))",
        (person, wanted, person, wanted),
    ).fetchall()
    return {
        str(r["b"] if r["a"] == person else r["a"]): Tie(
            int(r["met"]), int(r["warmth"])
        )
        for r in rows
    }


def meet(
    conn: Connection[DictRow],
    x: str,
    y: str,
    *,
    sim_time: int,
    warmth: int = 0,
    topic: str | None = None,
) -> Tie:
    """They met: once more, and `warmth` warmer or cooler. Returns the tie as
    it stood *before* this meeting, which is what the meeting was held under."""

    a, b = _pair(x, y)
    before = conn.execute(
        "SELECT met, warmth FROM ties WHERE a = %s AND b = %s", (a, b)
    ).fetchone()
    conn.execute(
        "INSERT INTO ties (a, b, met, warmth, first_met, last_met, last_topic) "
        "VALUES (%s, %s, 1, %s, %s, %s, %s) ON CONFLICT (a, b) DO UPDATE SET "
        "met = ties.met + 1, "
        "warmth = GREATEST(%s, LEAST(%s, ties.warmth + EXCLUDED.warmth)), "
        "last_met = EXCLUDED.last_met, "
        "last_topic = COALESCE(EXCLUDED.last_topic, ties.last_topic)",
        (
            a, b, max(WARMTH_MIN, min(WARMTH_MAX, warmth)), sim_time, sim_time,
            topic, WARMTH_MIN, WARMTH_MAX,
        ),
    )  # fmt: skip
    if before is None:
        return Tie()
    return Tie(int(before["met"]), int(before["warmth"]))


def warm(conn: Connection[DictRow], x: str, y: str, by: int, *, sim_time: int) -> None:
    """A change in how they get on that was not a meeting (a promise scored)."""

    if x == y or by == 0:
        return
    a, b = _pair(x, y)
    conn.execute(
        "INSERT INTO ties (a, b, met, warmth, first_met, last_met) "
        "VALUES (%s, %s, 0, %s, %s, %s) ON CONFLICT (a, b) DO UPDATE SET "
        "warmth = GREATEST(%s, LEAST(%s, ties.warmth + EXCLUDED.warmth))",
        (
            a, b, max(WARMTH_MIN, min(WARMTH_MAX, by)), sim_time, sim_time,
            WARMTH_MIN, WARMTH_MAX,
        ),
    )  # fmt: skip
