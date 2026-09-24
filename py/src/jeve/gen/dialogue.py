"""What two people might have said: a projection of a typed encounter.

An encounter in the simulation is five typed fields — who, whom, where, about
what, in what mood — and everything that follows from it follows from those.
This module renders them as two to four lines of dialogue when somebody clicks
on the encounter. It is the escape hatch in its proper place: prose for a human
reader, generated on demand, cached by the content hash of the request, and
never an input to anything.

The prompt contains only typed fields and the names of the two people. It is
told not to invent facts, but nothing depends on its obeying: whatever it says,
the world does not hear it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.hashing import content_hash
from jeve.decide.questions import MOODS, ORG_WORDS, role_words
from jeve.llm.protocol import ChatMessage

KIND = "dialogue"
MAX_TOKENS = 700

TOPIC_WORDS: dict[str, str] = {
    "the_outage": "the software outage that is disrupting work",
    "work": "their own work and clients",
    "money": "bills and invoices; who owes whom",
    "small_talk": "nothing in particular: the weather, the weekend",
    "other": "something unremarkable",
}
PLACE_WORDS: dict[str, str] = {
    "software_office": "the software company's office",
    "law_office": "the law firm's office",
    "accounting_office": "the accounting firm's office",
    "cafe": "the neighbourhood cafe",
    "plaza": "the plaza, by the fountain",
}

SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Encounter:
    """The typed record. This, not the prose, is what happened."""

    seq: int
    a_name: str
    a_role: str
    a_org: str
    b_name: str
    b_role: str
    b_org: str
    zone: str
    topic: str
    mood: int
    escalated: bool

    def typed(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "between": [self.a_name, self.b_name],
            "zone": self.zone,
            "topic": self.topic,
            "mood": MOODS[self.mood] if 0 <= self.mood < len(MOODS) else "",
            "escalated": self.escalated,
        }


def load_encounter(conn: Connection[DictRow], seq: int) -> Encounter | None:
    row = conn.execute(
        "SELECT e.seq, e.payload, "
        "  a.name AS a_name, a.role AS a_role, a.org_id AS a_org, "
        "  b.name AS b_name, b.role AS b_role, b.org_id AS b_org, "
        "  EXISTS (SELECT 1 FROM events x WHERE x.kind = 'ticket.escalated' "
        "          AND e.seq = ANY(x.causes)) AS escalated "
        "FROM events e "
        "JOIN persons a ON a.id = e.payload->>'a' "
        "JOIN persons b ON b.id = e.payload->>'b' "
        "WHERE e.seq = %s AND e.kind = 'encounter'",
        (seq,),
    ).fetchone()
    if row is None:
        return None
    payload = row["payload"]
    return Encounter(
        seq=int(row["seq"]),
        a_name=str(row["a_name"]),
        a_role=str(row["a_role"]),
        a_org=str(row["a_org"]),
        b_name=str(row["b_name"]),
        b_role=str(row["b_role"]),
        b_org=str(row["b_org"]),
        zone=str(payload.get("zone", "")),
        topic=str(payload.get("topic", "other")),
        mood=int(payload.get("mood", 2)),
        escalated=bool(row["escalated"]),
    )


def _who(name: str, role: str, org: str) -> str:
    return f"{name}, {role_words(role)} at {ORG_WORDS.get(org, 'a local firm')}"


def messages_for(encounter: Encounter) -> list[ChatMessage]:
    mood = MOODS[encounter.mood] if 0 <= encounter.mood < len(MOODS) else ""
    first = _who(encounter.a_name, encounter.a_role, encounter.a_org)
    second = _who(encounter.b_name, encounter.b_role, encounter.b_org)
    facts = [
        f"{first} starts a conversation with {second}.",
        f"They are in {PLACE_WORDS.get(encounter.zone, 'town')}.",
        f"They talk about {TOPIC_WORDS.get(encounter.topic, encounter.topic)}.",
        f"{encounter.a_name.split()[0]}'s mood: {mood}",
    ]
    if encounter.escalated:
        facts.append(
            f"{encounter.a_name.split()[0]} presses for the outage to be fixed, and "
            f"{encounter.b_name.split()[0]} agrees to treat it as urgent."
        )
    return [
        ChatMessage(
            role="system",
            content=(
                "You write very short, natural dialogue for a simulation of a small "
                "town's businesses. Given the facts of one brief encounter, write "
                "two to four lines, alternating speakers, plain and understated. "
                "Use only the facts given: invent no names, numbers, dates, amounts "
                "or events. Use each speaker's first name as `speaker`."
            ),
        ),
        ChatMessage(role="user", content="\n".join(facts)),
    ]


def request_key(model: str, encounter: Encounter) -> str:
    """The cache key. Built from the typed fields, not the event's `seq`: two
    encounters that are the same in every typed respect share their prose."""

    return content_hash(
        {
            "kind": KIND,
            "model": model,
            "messages": [m.model_dump(mode="json") for m in messages_for(encounter)],
            "schema": SCHEMA,
        }
    )


def parse_lines(text: str) -> list[dict[str, str]]:
    """Lines from a model's reply, or nothing. Never raises on bad prose."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return []
    lines = raw.get("lines") if isinstance(raw, dict) else None
    if not isinstance(lines, list):
        return []
    clean: list[dict[str, str]] = []
    for line in lines[:4]:
        if isinstance(line, dict) and line.get("speaker") and line.get("text"):
            clean.append(
                {"speaker": str(line["speaker"])[:40], "text": str(line["text"])[:400]}
            )
    return clean


def cached(
    conn: Connection[DictRow], encounter: Encounter, models: tuple[str, ...]
) -> dict[str, Any] | None:
    """Prose already paid for, under any of the models we would have tried."""

    keys = {request_key(model, encounter): model for model in models}
    row = conn.execute(
        "SELECT hash, model, response, cost_usd FROM model_calls "
        "WHERE kind = %s AND hash = ANY(%s) ORDER BY created_at LIMIT 1",
        (KIND, list(keys)),
    ).fetchone()
    if row is None:
        return None
    lines = parse_lines(str(dict(row["response"]).get("text", "")))
    if not lines:
        return None
    return {
        "lines": lines,
        "model": str(row["model"]),
        "cost_usd": float(row["cost_usd"]),
        "cached": True,
    }
