"""Facts, who knows them, and promises (MEM-0002).

Three things an episode can leave behind, each a typed row rather than a
sentence:

* a **fact** — a thing that can be known and passed on, identified by what it
  is about, so the same outage is the same fact in every arm of a
  counterfactual;
* **knowledge** — who holds a fact, from whom, and at what remove, which makes
  diffusion depth a column instead of a walk over the event log;
* a **commitment** — a promise to pay a particular bill, which raises the
  pressure on the promiser's next decision about it and is then kept or not.

Nothing in here moves money, ends an outage, or decides anything: it records
what is true so that a flow in `jeve.world` can act on it. Text never enters —
a fact's words are rendered from its topic by a question set, on the way to the
model, and are never read back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from psycopg import Connection
from psycopg.rows import DictRow

type Topic = Literal[
    "outage", "price_rise", "payroll_late", "insolvency", "churned", "promise_broken"
]
type CommitmentKind = Literal["pay_invoice"]


@dataclass(frozen=True, slots=True)
class Fact:
    """Something that can be known. `id` is derived from the subject, never
    minted from a counter, so two runs of the same world agree about it."""

    id: str
    topic: Topic
    about_org_id: str | None = None
    about_module_id: str | None = None
    incident_id: int | None = None
    about_person_id: str | None = None
    true_fact: bool = True
    """False for a rumour: it travels like a fact, and nothing in the world
    that computes money reads it (WORLD-0010)."""

    @staticmethod
    def outage(incident_id: int, module_id: str) -> Fact:
        """That a module is down right now. Travels while the outage lasts."""

        return Fact(
            id=f"outage:{incident_id}",
            topic="outage",
            about_module_id=module_id,
            incident_id=incident_id,
        )

    @staticmethod
    def price_rise(org_id: str) -> Fact:
        """That a firm plans to put its prices up. Seeded into one head, so
        that the share of the town holding it measures diffusion and nothing
        else (the scenario's behaviour #6)."""

        return Fact(id=f"price_rise:{org_id}", topic="price_rise", about_org_id=org_id)

    @staticmethod
    def payroll_late(org_id: str) -> Fact:
        """That a firm has not paid its staff. Its own staff know at once."""

        return Fact(
            id=f"payroll_late:{org_id}", topic="payroll_late", about_org_id=org_id
        )

    @staticmethod
    def insolvency(org_id: str) -> Fact:
        """That a firm is running out of money."""

        return Fact(id=f"insolvency:{org_id}", topic="insolvency", about_org_id=org_id)

    @staticmethod
    def rumour(org_id: str, week: int) -> Fact:
        """That a firm is running out of money, said about a firm that is not.
        One per firm per week at most, keyed by when it started."""

        return Fact(
            id=f"rumour:insolvency:{org_id}:{week}",
            topic="insolvency",
            about_org_id=org_id,
            true_fact=False,
        )

    @staticmethod
    def churned(org_id: str) -> Fact:
        """That a firm is losing customers."""

        return Fact(id=f"churned:{org_id}", topic="churned", about_org_id=org_id)

    @staticmethod
    def promise_broken(person_id: str) -> Fact:
        """That somebody gave their word to pay and did not."""

        return Fact(
            id=f"promise_broken:{person_id}",
            topic="promise_broken",
            about_person_id=person_id,
        )


@dataclass(frozen=True, slots=True)
class Tellable:
    """A fact one person holds and at least one person present does not."""

    fact: Fact
    hops: int
    """How far the teller is from first hand. The hearer lands one further."""
    missing: tuple[str, ...]
    """Who present does not hold it yet, in id order."""


@dataclass(frozen=True, slots=True)
class Commitment:
    id: int
    invoice_id: int
    from_person_id: str
    to_person_id: str
    made_sim: int
    due_sim: int


_FACT_COLUMNS = (
    "id, topic, about_org_id, about_module_id, incident_id, about_person_id, true_fact"
)


def _fact_of(row: DictRow) -> Fact:
    return Fact(
        id=str(row["id"]),
        topic=str(row["topic"]),  # type: ignore[arg-type]
        about_org_id=row["about_org_id"],
        about_module_id=row["about_module_id"],
        incident_id=int(row["incident_id"]) if row["incident_id"] is not None else None,
        about_person_id=row["about_person_id"],
        true_fact=bool(row["true_fact"]),
    )


# -- facts ------------------------------------------------------------------


def record_fact(
    conn: Connection[DictRow], fact: Fact, *, sim_time: int, seq: int | None = None
) -> None:
    """Bring a fact into being, idempotently.

    Idempotent because the id is derived: a flow that re-runs after a rolled
    back tick must not create a second copy of the same news.
    """

    conn.execute(
        "INSERT INTO facts (id, topic, about_org_id, about_module_id, incident_id, "
        "about_person_id, true_fact, born_sim, born_seq) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
        (
            fact.id,
            fact.topic,
            fact.about_org_id,
            fact.about_module_id,
            fact.incident_id,
            fact.about_person_id,
            fact.true_fact,
            sim_time,
            seq,
        ),
    )


def make_stale(conn: Connection[DictRow], fact_id: str, *, sim_time: int) -> None:
    """Retire a fact: it may still be remembered, but it no longer travels.

    An outage that has ended is gossip rather than news. Without this the fact
    would keep minting outage notices for an incident that is over, and the
    share of the town that "knows" would only ever rise.
    """

    conn.execute(
        "UPDATE facts SET stale_sim = %s WHERE id = %s AND stale_sim IS NULL",
        (sim_time, fact_id),
    )


def revive(conn: Connection[DictRow], fact_id: str) -> None:
    """News again. A firm short of money last month and short again now is the
    same fact (its id is what it is about), and it travels again."""

    conn.execute("UPDATE facts SET stale_sim = NULL WHERE id = %s", (fact_id,))


# -- who knows what ---------------------------------------------------------


def learn(
    conn: Connection[DictRow],
    person_id: str,
    fact_id: str,
    *,
    sim_time: int,
    seq: int | None = None,
    from_person_id: str | None = None,
    hops: int = 0,
) -> bool:
    """Write down that someone now knows something. True if it is news to them.

    First hand means nobody told them, and the database holds the two halves of
    that together (`hops = 0` exactly when there is no teller).
    """

    row = conn.execute(
        "INSERT INTO knowledge (person_id, fact_id, learned_sim, learned_seq, "
        "from_person_id, hops) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (person_id, fact_id) DO NOTHING RETURNING person_id",
        (person_id, fact_id, sim_time, seq, from_person_id, hops),
    ).fetchone()
    return row is not None


def facts_known_by(conn: Connection[DictRow], person_id: str) -> dict[str, int]:
    """Fact id to how far from first hand this person is."""

    rows = conn.execute(
        "SELECT fact_id, hops FROM knowledge WHERE person_id = %s ORDER BY fact_id",
        (person_id,),
    ).fetchall()
    return {str(row["fact_id"]): int(row["hops"]) for row in rows}


def holders_of(conn: Connection[DictRow], fact_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT person_id FROM knowledge WHERE fact_id = %s ORDER BY person_id",
        (fact_id,),
    ).fetchall()
    return [str(row["person_id"]) for row in rows]


def most_tellable(
    conn: Connection[DictRow], teller_id: str, listeners: list[str]
) -> Tellable | None:
    """The one piece of live news this person could pass on to someone here.

    One, not all of them: a round asks "does she bring it up?" about a single
    thing. Jev's accuracy falls as irrelevant state grows, and a hearer who
    learns four facts from one remark is not a conversation. Ties break on the
    newest fact, then on its id, so the choice is a function of the world and
    not of row order.
    """

    if not listeners:
        return None
    rows = conn.execute(
        f"SELECT f.{_FACT_COLUMNS}, k.hops FROM knowledge k JOIN facts f "
        "ON f.id = k.fact_id WHERE k.person_id = %s AND f.stale_sim IS NULL "
        "ORDER BY f.born_sim DESC, f.id",
        (teller_id,),
    ).fetchall()
    if not rows:
        return None

    known = conn.execute(
        "SELECT person_id, fact_id FROM knowledge WHERE person_id = ANY(%s) "
        "AND fact_id = ANY(%s)",
        (listeners, [str(row["id"]) for row in rows]),
    ).fetchall()
    already: dict[str, set[str]] = {}
    for row in known:
        already.setdefault(str(row["fact_id"]), set()).add(str(row["person_id"]))

    for row in rows:
        fact_id = str(row["id"])
        missing = tuple(
            sorted(p for p in listeners if p not in already.get(fact_id, set()))
        )
        if missing:
            return Tellable(_fact_of(row), int(row["hops"]), missing)
    return None


def reach_of(conn: Connection[DictRow], fact_id: str) -> dict[str, int]:
    """How far a fact has travelled: holders, and how many at each remove.

    The diffusion measure, computed in SQL so a report cannot disagree with the
    world. Smallville's own headline evidence was this number; here it involves
    no prose at all.
    """

    rows = conn.execute(
        "SELECT hops, count(*) AS n FROM knowledge WHERE fact_id = %s "
        "GROUP BY hops ORDER BY hops",
        (fact_id,),
    ).fetchall()
    by_hops = {f"hops_{int(row['hops'])}": int(row["n"]) for row in rows}
    return {"holders": sum(by_hops.values()), **by_hops}


# -- promises ---------------------------------------------------------------


def promise(
    conn: Connection[DictRow],
    *,
    episode_id: int,
    from_person_id: str,
    to_person_id: str,
    invoice_id: int,
    sim_time: int,
    seq: int,
    due_sim: int,
    kind: CommitmentKind = "pay_invoice",
) -> int:
    """Record that someone gave their word about a particular bill."""

    row = conn.execute(
        "INSERT INTO commitments (kind, episode_id, from_person_id, to_person_id, "
        "invoice_id, made_sim, made_seq, due_sim) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
        "RETURNING id",
        (
            kind,
            episode_id,
            from_person_id,
            to_person_id,
            invoice_id,
            sim_time,
            seq,
            due_sim,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def open_commitment(conn: Connection[DictRow], invoice_id: int) -> Commitment | None:
    """The promise still outstanding on this bill, if anyone made one.

    The newest wins: someone who has promised twice is held to what they said
    last, which is also the only reading under which promising again is not a
    way to escape the first promise.
    """

    row = conn.execute(
        "SELECT id, invoice_id, from_person_id, to_person_id, made_sim, due_sim "
        "FROM commitments WHERE invoice_id = %s AND settled_sim IS NULL "
        "ORDER BY made_sim DESC, id DESC LIMIT 1",
        (invoice_id,),
    ).fetchone()
    if row is None:
        return None
    return Commitment(
        id=int(row["id"]),
        invoice_id=int(row["invoice_id"]),
        from_person_id=str(row["from_person_id"]),
        to_person_id=str(row["to_person_id"]),
        made_sim=int(row["made_sim"]),
        due_sim=int(row["due_sim"]),
    )


def close_commitments_for(
    conn: Connection[DictRow], invoice_id: int, *, sim_time: int, kept: bool
) -> list[int]:
    """Settle every open promise about this bill. Returns the ids settled.

    Called when the bill is paid (kept) and when the promised day passes with
    it still unpaid (not kept). Both matter: a promise nobody ever scores is
    not an obligation, it is decoration.
    """

    rows = conn.execute(
        "UPDATE commitments SET settled_sim = %s, kept = %s WHERE invoice_id = %s "
        "AND settled_sim IS NULL RETURNING id",
        (sim_time, kept, invoice_id),
    ).fetchall()
    return [int(row["id"]) for row in rows]
