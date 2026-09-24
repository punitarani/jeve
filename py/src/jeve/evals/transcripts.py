"""An episode, told in plain words from its typed record — and told wrong, on
purpose, to test whoever reads it.

A judge compares *behaviour*, so every account it reads comes from one
template: who was there and what they are like, what was between them, what
each did in each round, how it ended, and what it changed. No model writes a
word of it. Two worlds' episodes then differ only in what their people did,
and a judge that prefers one is preferring behaviour, not prose (an LLM judge
shown generated prose prefers the fluent side, whatever happened in it).

`plant` breaks a record in one of a few ways a careful reader must notice:
somebody acting on a matter that is not theirs to act on, a conversation going
round in circles and then called settled, a consequence nothing caused, a
meeting at an hour the place is shut. The defects are made on the record,
before rendering, so the clean and broken accounts share every word the
defect does not touch. A judge that cannot pick the clean one reliably is not
evidence of anything (workbench L14: a check that cannot fail is not a check).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.clock import DAY, HOUR, SimTime
from jeve.decide.questions import MOODS, person_words, tellable_words, trait_words

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
PLACES: dict[str, str] = {
    "software_office": "the software company's office",
    "law_office": "the law firm's office",
    "accounting_office": "the accounting firm's office",
    "cafe": "the neighbourhood cafe",
    "plaza": "the plaza outside, by the fountain",
}
ENDINGS: dict[str, str] = {
    "settled": "Everyone still there had said what they wanted to say.",
    "stalled": "It went round in circles: everyone repeated what they had just done.",
    "emptied": "People drifted off until nobody was left talking.",
    "rounds": "It was still going when they had to get back to work.",
}
DEFECTS: tuple[str, ...] = ("wrong_actor", "loop", "phantom_effect", "closed_hours")


@dataclass(frozen=True, slots=True)
class Person:
    id: str
    name: str
    role: str
    org: str
    traits: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Act:
    person: str
    act: str
    mood: int | None
    mention: bool


@dataclass(frozen=True, slots=True)
class Record:
    """Everything an account is written from."""

    episode_id: int
    zone: str
    when: int
    stake: str
    matter: str
    """The stake, already in words: which bill, which outage, which news."""
    holder_orgs: frozenset[str]
    """The firms whose people may answer for the matter: the vendor for an
    outage, the debtor for a bill. For news, whoever already holds it."""
    holders: frozenset[str]
    """For news: the people who knew it before the meeting."""
    people: tuple[Person, ...]
    rounds: tuple[tuple[Act, ...], ...]
    ending: str
    effects: tuple[str, ...]


# -- reading a record ---------------------------------------------------------


def _org_names(conn: Connection[DictRow]) -> dict[str, str]:
    rows = conn.execute("SELECT id, name FROM orgs").fetchall()
    return {str(r["id"]): str(r["name"]) for r in rows}


def _matter(
    conn: Connection[DictRow], stake: str, ref: str, orgs: dict[str, str], when: int
) -> tuple[str, frozenset[str]]:
    kind, _, key = ref.partition(":")
    if stake == "outage" and kind == "incident":
        row = conn.execute(
            "SELECT module_id, started_sim FROM incidents WHERE id = %s", (int(key),)
        ).fetchone()
        if row is not None:
            minutes = max(0, (when - int(row["started_sim"])) // 60)
            return (
                f"{orgs.get('tallybird', 'The software company')}'s "
                f"{row['module_id']} feature has been down for {minutes} minutes. "
                "The other firms use it for their own work.",
                frozenset({"tallybird"}),
            )
    if stake == "invoice" and kind == "invoice":
        row = conn.execute(
            "SELECT from_org_id, to_org_id, amount_cents, due_sim FROM invoices "
            "WHERE id = %s",
            (int(key),),
        ).fetchone()
        if row is not None:
            late = max(0, (when - int(row["due_sim"])) // DAY)
            debtor = str(row["to_org_id"] or "")
            return (
                f"{orgs.get(str(row['from_org_id']), 'A firm')} billed "
                f"{orgs.get(debtor, 'a client')} "
                f"${int(row['amount_cents']) / 100:,.0f}; "
                + (f"it is {late} days overdue" if late else "it falls due about now")
                + ", and it has not been paid.",
                frozenset({debtor}),
            )
    topic, _, about = ref.partition(":")
    return (
        f"Some of them have heard {tellable_words(topic, about or None)}; "
        "the others have not.",
        frozenset(),
    )


def load(conn: Connection[DictRow], episode_id: int) -> Record | None:
    """The record of one closed episode, or None if it never closed."""

    ep = conn.execute(
        "SELECT id, zone, stake, stake_ref, opened_sim, exit_reason, closed_seq, "
        "outcome FROM episodes WHERE id = %s AND closed_sim IS NOT NULL",
        (episode_id,),
    ).fetchone()
    if ep is None:
        return None
    orgs = _org_names(conn)
    when = int(ep["opened_sim"])
    people = tuple(
        Person(
            str(r["id"]), str(r["name"]), str(r["role"]), str(r["org_id"]),
            dict(r["traits"] or {}),
        )
        for r in conn.execute(
            "SELECT p.id, p.name, p.role, p.org_id, p.traits "
            "FROM episode_participants e JOIN persons p ON p.id = e.person_id "
            "WHERE e.episode_id = %s ORDER BY e.seat",
            (episode_id,),
        ).fetchall()
    )  # fmt: skip
    ids = {p.id for p in people}
    rounds: list[tuple[Act, ...]] = []
    for event in conn.execute(
        "SELECT sim_time, decision_id, payload FROM events "
        "WHERE kind = 'episode.round' "
        "AND (payload->>'episode_id')::bigint = %s ORDER BY seq",
        (episode_id,),
    ).fetchall():
        # Every round of an episode happens inside one tick, so the rounds'
        # decisions share a sim time. The round's event names its first
        # decision; each person's answer in that round is their first
        # `episode.round` decision from there on.
        chosen: dict[str, dict[str, Any]] = {}
        for r in conn.execute(
            "SELECT person_id, chosen FROM decisions WHERE question_set = "
            "'episode.round' AND sim_time = %s AND id >= %s AND person_id = ANY(%s) "
            "ORDER BY id",
            (int(event["sim_time"]), int(event["decision_id"] or 0), sorted(ids)),
        ).fetchall():
            chosen.setdefault(str(r["person_id"]), dict(r["chosen"] or {}))
        acts = []
        for a in event["payload"].get("acts", []):
            said = chosen.get(str(a["person_id"]), {})
            mood = said.get("mood")
            acts.append(
                Act(
                    str(a["person_id"]),
                    str(a["act"]),
                    int(mood) if isinstance(mood, int) else None,
                    bool(said.get("mention")),
                )
            )
        rounds.append(tuple(acts))
    matter, holder_orgs = _matter(
        conn, str(ep["stake"]), str(ep["stake_ref"]), orgs, when
    )
    holders: frozenset[str] = frozenset()
    if ep["stake"] == "news":
        holders = frozenset(
            str(r["person_id"])
            for r in conn.execute(
                "SELECT person_id FROM knowledge WHERE fact_id = %s "
                "AND person_id = ANY(%s) AND learned_sim < %s",
                (str(ep["stake_ref"]), sorted(ids), when),
            ).fetchall()
        )
    return Record(
        episode_id=int(ep["id"]),
        zone=str(ep["zone"]),
        when=when,
        stake=str(ep["stake"]),
        matter=matter,
        holder_orgs=holder_orgs,
        holders=holders,
        people=people,
        rounds=tuple(rounds),
        ending=str(ep["exit_reason"]),
        effects=_effects(conn, ep, orgs),
    )


def _effects(
    conn: Connection[DictRow], ep: dict[str, Any], orgs: dict[str, str]
) -> tuple[str, ...]:
    """What the world recorded because of this meeting, in words."""

    out: list[str] = []
    outcome = ep["outcome"] or {}
    passed = int(outcome.get("facts_passed") or 0)
    if passed:
        whom = "person" if passed == 1 else "people"
        out.append(f"The news reached {passed} more {whom}.")
    kinds = [
        str(r["kind"])
        for r in conn.execute(
            "SELECT kind FROM events WHERE %s = ANY(causes) ORDER BY seq",
            (int(ep["closed_seq"]),),
        ).fetchall()
    ]
    if "ticket.escalated" in kinds:
        out.append("The outage was escalated to the software company's engineers.")
    if "escalation.handoff" in kinds or any(k.startswith("escalation.") for k in kinds):
        out.append("The complaint was passed on to be relayed to engineering.")
    for row in conn.execute(
        "SELECT c.from_person_id, p.name FROM commitments c "
        "JOIN persons p ON p.id = c.from_person_id WHERE c.episode_id = %s",
        (int(ep["id"]),),
    ).fetchall():
        out.append(f"{row['name']} gave their word to pay the bill by a set day.")
    return tuple(out)


# -- telling it ---------------------------------------------------------------


_DID: dict[str, dict[str, str]] = {
    "outage": {
        "press": "pushes the software company to fix it now",
        "promise": "gives their word that it will be fixed",
        "explain": "explains their side of it",
        "decline": "says plainly that nothing more can be done today",
        "ask": "asks what the others know about it",
    },
    "invoice": {
        "press": "presses for the bill to be paid now",
        "promise": "promises to pay the bill by a set day",
        "explain": "explains their firm's side of it",
        "decline": "says plainly that the bill will not be paid yet",
        "ask": "asks when it will be settled",
    },
    "news": {
        "press": "presses the others about it",
        "promise": "promises to look into it",
        "explain": "explains what they make of it",
        "decline": "says they will not discuss it",
        "ask": "asks what the others have heard",
    },
}
_ANY: dict[str, str] = {
    "small_talk": "lets the matter drop and chats about something else",
    "leave": "breaks off and heads back to work",
    "other": "does something else",
}


def _clock(seconds: int) -> str:
    t = SimTime(seconds)
    minutes = (t.time_of_day % HOUR) // 60
    return f"{WEEKDAYS[t.weekday]} {t.time_of_day // HOUR:02d}:{minutes:02d}"


def render(record: Record) -> str:
    names = {p.id: p.name for p in record.people}
    lines = [
        f"Place and time: {PLACES.get(record.zone, record.zone)}, "
        f"{_clock(record.when)}.",
        "Who is there:",
    ]
    for p in record.people:
        lines.append(
            f"- {p.name}, {person_words(p.role, p.org)}. "
            f"{trait_words('sociability', p.traits.get('sociability')).capitalize()}; "
            f"{trait_words('vocality', p.traits.get('vocality'))}."
        )
    lines.append(f"What is between them: {record.matter}")
    if record.stake == "news" and record.holders:
        knew = ", ".join(sorted(names.get(h, h) for h in record.holders))
        lines.append(f"Who already knew: {knew}.")
    for index, acts in enumerate(record.rounds, start=1):
        lines.append(f"Round {index}:")
        for act in acts:
            did = _DID.get(record.stake, {}).get(act.act) or _ANY.get(act.act, act.act)
            told = " and tells the others the news" if act.mention else ""
            mood = (
                f" ({MOODS[act.mood].rstrip('.').lower()})"
                if act.mood is not None and 0 <= act.mood < len(MOODS)
                else ""
            )
            lines.append(f"- {names.get(act.person, act.person)} {did}{told}{mood}.")
    lines.append(f"How it ended: {ENDINGS.get(record.ending, record.ending)}")
    after = " ".join(record.effects) if record.effects else "Nothing changed."
    lines.append(f"Afterwards: {after}")
    return "\n".join(lines)


# -- breaking it --------------------------------------------------------------


def _set_act(record: Record, person: str, act: str, *, mention: bool = False) -> Record:
    first = tuple(
        Act(a.person, act, a.mood, mention) if a.person == person else a
        for a in record.rounds[0]
    )
    return replace(record, rounds=(first, *record.rounds[1:]))


def plant(record: Record, defect: str, rng: Any) -> Record | None:
    """The same record with one thing wrong, or None if this record cannot
    carry that defect (a one-person episode has nobody to act out of turn)."""

    if not record.rounds or not record.rounds[0]:
        return None
    if defect == "wrong_actor":
        # Somebody answers for a matter that is not theirs: a customer promises
        # the vendor's fix, the creditor promises to pay their own bill, or a
        # person who had not heard the news is the one who tells it.
        if record.stake == "news":
            outsiders = [p.id for p in record.people if p.id not in record.holders]
            if not outsiders or not record.holders:
                return None
            quiet = replace(
                record,
                rounds=tuple(
                    tuple(Act(a.person, a.act, a.mood, False) for a in acts)
                    for acts in record.rounds
                ),
            )
            return _set_act(quiet, rng.choice(outsiders), "small_talk", mention=True)
        outsiders = [p.id for p in record.people if p.org not in record.holder_orgs]
        if not outsiders:
            return None
        return _set_act(record, rng.choice(outsiders), "promise")
    if defect == "loop":
        once = record.rounds[0]
        return replace(record, rounds=(once,) * 5, ending="settled")
    if defect == "phantom_effect":
        # A consequence nothing in the conversation caused.
        calm = tuple(
            tuple(Act(a.person, "small_talk", a.mood, False) for a in acts)
            for acts in record.rounds
        )
        phantom = {
            "outage": "The outage was escalated to the software company's engineers.",
            "invoice": f"{record.people[0].name} gave their word to pay the bill "
            "by a set day.",
            "news": "The news reached 3 more people.",
        }[record.stake]
        kept = tuple(e for e in record.effects if e != phantom)
        return replace(record, rounds=calm, effects=(*kept, phantom))
    if defect == "closed_hours":
        # Sunday, before dawn: every place in town is shut.
        day = SimTime(record.when).day
        sunday = day + (6 - day % 7)
        return replace(record, when=sunday * DAY + 3 * HOUR + 40 * 60)
    raise ValueError(f"unknown defect {defect!r}")
