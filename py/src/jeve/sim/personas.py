"""Staff written by a model, compiled to typed traits (an eval arm; EVAL-0002).

The seeded world draws every trait of every person independently and
uniformly (`seed_world.traits_for`), so a founder is as likely to be timid as a
barista is to be litigious. This asks a general-purpose model to describe each
firm's staff as real people — one request per firm, so a team is written as a
team — and keeps only what can be typed: each trait's *level* (low, middle,
high), in the words Jev itself reads for that trait.

A referee compiles the reply, with no model in it (workbench's grounded GM):

* every person must be named by id, once; every trait level must be one of the
  three; anything else is rejected and that trait keeps its seeded value;
* a level becomes a value inside the same tertile `trait_level` reads back,
  placed within it by a draw keyed by (person, trait) — so two people the model
  called "high" are not identical, and a replay places them the same way;
* the model also writes each person a one-line backstory. It is prose for a
  reader: kept in `model_calls` with the reply, and read by nothing.

Seed-time only: a world is described once, before its first tick, and the
reply is cached by the content hash of the request like every other call, so
a replay re-compiles the same traits without a key.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.hashing import content_hash
from jeve.core.seed import derive_rng
from jeve.decide.questions import (
    ORG_WORDS,
    TRAIT_LEVEL_WORDS,
    TRAIT_NAMES,
    role_words,
    trait_value,
)
from jeve.decide.recorder import insert_call
from jeve.llm import (
    GENERATIVE_PREFERENCE,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Gateway,
)

KIND = "persona"
LEVELS: tuple[str, ...] = ("low", "middle", "high")
MAX_TOKENS = 6000
SEED = 0
BACKSTORY_CHARS = 400

SYSTEM = (
    "You write the staff of a small business in a quiet town as real, specific "
    "people. For each person you are given their name and job; describe them "
    "as an individual would be, not as a stereotype of the job, since people "
    "in the same line of work differ a great deal. Then place them on each of "
    "the listed traits, choosing low, middle or high by which description fits "
    "the person you have imagined. Reply in the JSON shape required and "
    "nothing else."
)


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    name: str
    role: str


@dataclass(slots=True)
class Authored:
    """What the referee made of the replies."""

    traits: dict[str, dict[str, float]] = field(default_factory=dict)
    set_by_model: int = 0
    rejected: list[str] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)
    cost_usd: float = 0.0


def request_for(org: str, name: str, staff: list[Member], model: str) -> ChatRequest:
    traits = {
        t: dict(zip(LEVELS, TRAIT_LEVEL_WORDS[t], strict=True)) for t in TRAIT_NAMES
    }
    body = {
        "firm": {"name": name, "what_it_is": ORG_WORDS.get(org, "a local firm")},
        "staff": [
            {"id": m.id, "name": m.name, "job": role_words(m.role)} for m in staff
        ],
        "traits": traits,
    }
    person = {
        "type": "object",
        "properties": {
            "backstory": {"type": "string"},
            **{t: {"type": "string", "enum": list(LEVELS)} for t in TRAIT_NAMES},
        },
        "required": ["backstory", *TRAIT_NAMES],
        "additionalProperties": False,
    }
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=SYSTEM),
            ChatMessage(
                role="user",
                content=json.dumps(body, ensure_ascii=False)
                + "\n\nFor every staff id, give a backstory of one sentence and a "
                "level for every trait.",
            ),
        ],
        max_tokens=MAX_TOKENS,
        seed=SEED,
        temperature=0.0,
        response_schema={
            "type": "object",
            "properties": {m.id: person for m in staff},
            "required": [m.id for m in staff],
            "additionalProperties": False,
        },
    )


def request_key(req: ChatRequest) -> str:
    return content_hash({"kind": KIND, **req.model_dump(mode="json")})


def compile_reply(
    text: str, staff: list[Member], seeded: dict[str, dict[str, float]], root_seed: int
) -> tuple[dict[str, dict[str, float]], int, list[str]]:
    """The referee: typed traits from a reply, or the seeded ones where the
    reply cannot be read. Returns the traits, how many were set by the model,
    and what was rejected and why."""

    rejected: list[str] = []
    try:
        raw = json.loads(text.strip().removeprefix("```json").removesuffix("```"))
    except json.JSONDecodeError:
        return {m.id: dict(seeded[m.id]) for m in staff}, 0, ["reply: not JSON"]
    if not isinstance(raw, dict):
        return {m.id: dict(seeded[m.id]) for m in staff}, 0, ["reply: not an object"]
    rejected += [f"{key}: not on the staff" for key in raw if key not in seeded]
    out: dict[str, dict[str, float]] = {}
    set_by_model = 0
    for member in staff:
        traits = dict(seeded[member.id])
        said = raw.get(member.id)
        if not isinstance(said, dict):
            rejected.append(f"{member.id}: not described")
            out[member.id] = traits
            continue
        for trait in TRAIT_NAMES:
            level = said.get(trait)
            if level not in LEVELS:
                rejected.append(f"{member.id}.{trait}: {level!r} is not a level")
                continue
            within = (
                0.15 + 0.7 * derive_rng(root_seed, "persona", member.id, trait).random()
            )
            traits[trait] = trait_value(trait, LEVELS.index(str(level)), within)
            set_by_model += 1
        out[member.id] = traits
    return out, set_by_model, rejected


def _staff(conn: Connection[DictRow]) -> dict[str, tuple[str, list[Member]]]:
    firms: dict[str, tuple[str, list[Member]]] = {}
    rows = conn.execute("SELECT id, name FROM orgs").fetchall()
    names = {str(r["id"]): str(r["name"]) for r in rows}
    for row in conn.execute(
        "SELECT id, org_id, name, role FROM persons WHERE kind = 'staff' ORDER BY id"
    ).fetchall():
        org = str(row["org_id"])
        firms.setdefault(org, (names.get(org, org), []))[1].append(
            Member(str(row["id"]), str(row["name"]), str(row["role"]))
        )
    return firms


async def _ask(requests: list[ChatRequest]) -> list[object]:
    async with Gateway() as gateway:
        return await asyncio.gather(
            *(gateway.complete(r, purpose="gate") for r in requests),
            return_exceptions=True,
        )


def author(
    conn: Connection[DictRow],
    root_seed: int,
    *,
    live: bool,
    cassette: Path | None = None,
) -> Authored:
    """Describe every firm's staff and write the compiled traits.

    Walks LLM-0006's generative order per firm: a reply on record is used, a
    missing one is asked for when `live`, and a firm no model describes keeps
    its seeded traits (and says so in `rejected`).
    """

    result = Authored()
    seeded = {
        str(r["id"]): {k: float(v) for k, v in dict(r["traits"] or {}).items()}
        for r in conn.execute("SELECT id, traits FROM persons WHERE kind = 'staff'")
    }
    for org, (name, staff) in sorted(_staff(conn).items()):
        text: str | None = None
        for model in GENERATIVE_PREFERENCE:
            req = request_for(org, name, staff, model)
            key = request_key(req)
            row = conn.execute(
                "SELECT response FROM model_calls WHERE hash = %s", (key,)
            ).fetchone()
            if row is None and live:
                reply = asyncio.run(_ask([req]))[0]
                if not isinstance(reply, ChatResponse):
                    continue
                body = req.model_dump(mode="json")
                stored = {
                    "hash": key,
                    "kind": KIND,
                    "model": reply.model,
                    "provider": reply.provider,
                    "request": body,
                    "wire": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                    "response": {"text": reply.text, "model": reply.model},
                    "input_tokens": reply.usage.input_tokens,
                    "output_tokens": reply.usage.output_tokens,
                    "cost_usd": reply.usage.cost_usd,
                    "cost_estimated": reply.usage.cost_is_estimated,
                    "latency_s": round(reply.latency_s, 4),
                }
                insert_call(conn, stored)
                result.cost_usd += reply.usage.cost_usd
                if cassette is not None:
                    cassette.parent.mkdir(parents=True, exist_ok=True)
                    with open(cassette, "a") as handle:
                        handle.write(json.dumps(stored, sort_keys=True) + "\n")
                row = {"response": stored["response"]}
            if row is None:
                continue
            text = str((row["response"] or {}).get("text", ""))
            compiled, count, why = compile_reply(text, staff, seeded, root_seed)
            if count == 0:
                result.rejected += [f"{org} ({model}): {w}" for w in why]
                text = None
                continue
            result.traits.update(compiled)
            result.set_by_model += count
            result.rejected += [f"{org}: {w}" for w in why]
            result.models[org] = model
            break
        if text is None:
            result.rejected.append(f"{org}: no model described this firm")
    for person, traits in sorted(result.traits.items()):
        conn.execute(
            "UPDATE persons SET traits = %s WHERE id = %s", (json.dumps(traits), person)
        )
    return result
