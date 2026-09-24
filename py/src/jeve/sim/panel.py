"""`make judge-panel`: does another model read a situation the way Jev does?
(DECIDE-0005; validation survey 02 §3.5.)

Two measurements, both from the call cache.

1. **Situation or temperament.** The golden field report found temperament
   outweighing situation in Jev's answers. Within a question set, two recorded
   contexts that differ *only* in the person's temperament measure a
   temperament effect; two that differ only in the situation measure a
   situation effect. Each effect is the mean total-variation distance between
   the two answers. Jev's are computed from what is already cached, for
   nothing.
2. **Agreement.** A sample of those contexts, chosen so that both kinds of
   pair exist, is put to three model families through tier 1's own request
   (`escalation.request_for`): the same state, the same typed questions.
   Agreement is how often a model puts most mass where Jev does, and each
   model's two effects are computed on the same contexts as Jev's.

A panel that reads situations much harder than Jev does is the evidence that
Jev under-reads them: a wording problem in `questions.py`, or a set to name in
`JEVE_ESCALATION_LIVE`. What this measures is agreement with other models, not
correctness (design/005).

    make judge-panel             # Jev's effects, and what a panel run would ask
    make judge-panel LIVE=1      # asks the panel; answers kept, a rerun is free
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import TypeAdapter

from jeve import db
from jeve.config import find_repo_root, load_settings
from jeve.decide import escalation
from jeve.decide.questions import QUESTION_SETS, TRAIT_PHRASES, Ask, Prepared
from jeve.decide.recorder import insert_call
from jeve.errors import JeveError
from jeve.llm import GENERATIVE_PREFERENCE, ChatRequest, Gateway
from jeve.llm.gateway import parse_decision
from jeve.llm.protocol import Answer, Question, Usage

REPORT = find_repo_root() / "ops" / "judge-panel.md"
PANEL: tuple[str, ...] = GENERATIVE_PREFERENCE[:3]
"""Three families, in LLM-0006's order of measured reliability."""
KIND = "panel"
PER_SET = 24
PAIRS_PER_GROUP = 30
"""A situation met by two hundred people would otherwise be most of the pairs."""

_QUESTION: TypeAdapter[Question] = TypeAdapter(Question)


@dataclass(frozen=True, slots=True)
class Context:
    """One recorded Jev call: what it was asked and what it said."""

    kind: str
    hash: str
    state: dict[str, object]
    asks: tuple[Ask, ...]
    jev: dict[str, Answer]

    @property
    def temperament(self) -> str:
        return _canonical({k: v for k, v in self.state.items() if _is_trait(v)})

    @property
    def situation(self) -> str:
        return _canonical({k: v for k, v in self.state.items() if not _is_trait(v)})

    @property
    def prepared(self) -> Prepared:
        return Prepared(self.kind, self.asks, self.state)


def _is_trait(value: object) -> bool:
    return isinstance(value, str) and value in TRAIT_PHRASES


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def load(
    conn: Connection[DictRow], kinds: Iterable[str] | None = None
) -> list[Context]:
    """Every recorded Jev call for these sets that can still be read."""

    wanted = sorted(set(kinds) if kinds else set(QUESTION_SETS))
    rows = conn.execute(
        "SELECT hash, kind, request, wire, response FROM model_calls "
        "WHERE kind = ANY(%s) ORDER BY kind, hash",
        (wanted,),
    ).fetchall()
    found: list[Context] = []
    for row in rows:
        # The wire, not the jsonb column: jsonb reorders keys, and the order of
        # a state and of a choice's options is part of the question
        # (DECIDE-0004). Rebuilt from it, the panel's request is byte for byte
        # tier 1's, so an answer tier 1 already paid for is read, not bought.
        request = (
            json.loads(str(row["wire"])) if row["wire"] else dict(row["request"] or {})
        )
        state, questions = request.get("state"), request.get("questions")
        if not isinstance(state, dict) or not isinstance(questions, dict):
            continue
        try:
            asks = tuple(
                Ask(key, "J", _QUESTION.validate_python(q))
                for key, q in questions.items()
            )
            jev = parse_decision(
                dict(row["response"]),
                expected={a.key for a in asks},
                fallback_model="jev",
                usage=Usage(),
            ).answers
        except ValueError, JeveError:
            continue  # a response from before a question changed shape
        found.append(Context(str(row["kind"]), str(row["hash"]), state, asks, jev))
    return found


type Answers = Callable[[Context], dict[str, Answer] | None]


@dataclass(frozen=True, slots=True)
class Effects:
    situation: float | None
    temperament: float | None
    situation_pairs: int
    temperament_pairs: int

    @property
    def verdict(self) -> str:
        if self.situation is None or self.temperament is None:
            return "not enough pairs"
        if self.temperament > self.situation:
            return "temperament outweighs situation"
        return "situation outweighs temperament"


def _distance(ask: Ask, a: Answer, b: Answer) -> float:
    p, q = escalation.distribution(ask, a), escalation.distribution(ask, b)
    return 0.5 * sum(abs(p[o] - q[o]) for o in ask.options)


def _pairs(
    groups: Iterable[list[Context]], differ: Callable[[Context], str]
) -> Iterable[tuple[Context, Context]]:
    for group in groups:
        pairs = [(a, b) for a, b in combinations(group, 2) if differ(a) != differ(b)]
        yield from pairs[:PAIRS_PER_GROUP]


def _grouped(
    contexts: Sequence[Context], by: Callable[[Context], str]
) -> list[list[Context]]:
    groups: dict[str, list[Context]] = {}
    for context in contexts:
        groups.setdefault(by(context), []).append(context)
    return list(groups.values())


def effects(contexts: Sequence[Context], answers: Answers) -> Effects:
    """How far answers move when only the situation, or only the person, does."""

    def mean_distance(
        pairs: Iterable[tuple[Context, Context]],
    ) -> tuple[float | None, int]:
        distances: list[float] = []
        for a, b in pairs:
            first, second = answers(a), answers(b)
            if first is None or second is None:
                continue
            for ask in a.asks:
                if ask.key in first and ask.key in second:
                    distances.append(_distance(ask, first[ask.key], second[ask.key]))
        return (statistics.fmean(distances) if distances else None), len(distances)

    same_situation = _grouped(contexts, lambda c: c.situation)
    same_person = _grouped(contexts, lambda c: c.temperament)
    temperament, t_pairs = mean_distance(
        _pairs(same_situation, lambda c: c.temperament)
    )
    situation, s_pairs = mean_distance(_pairs(same_person, lambda c: c.situation))
    return Effects(situation, temperament, s_pairs, t_pairs)


def pick(contexts: Sequence[Context], per_set: int = PER_SET) -> list[Context]:
    """A sample that holds both kinds of pair: half from the situations met by
    the most different people, half from the people met in the most different
    situations. Deterministic: largest groups first, then by hash."""

    chosen: dict[str, Context] = {}

    def take(
        groups: list[list[Context]], differ: Callable[[Context], str], cap: int
    ) -> None:
        ranked = sorted(
            (g for g in groups if len({differ(c) for c in g}) > 1),
            key=lambda g: (-len({differ(c) for c in g}), g[0].hash),
        )
        for group in ranked:
            seen: set[str] = set()
            for context in group:
                if len(chosen) >= cap:
                    return
                if differ(context) not in seen:
                    seen.add(differ(context))
                    chosen.setdefault(context.hash, context)

    take(
        _grouped(contexts, lambda c: c.situation), lambda c: c.temperament, per_set // 2
    )
    take(_grouped(contexts, lambda c: c.temperament), lambda c: c.situation, per_set)
    return sorted(chosen.values(), key=lambda c: c.hash)


def request(context: Context, model: str) -> ChatRequest:
    return escalation.request_for(
        context.prepared, [ask.key for ask in context.asks], model
    )


def cached(
    conn: Connection[DictRow], contexts: Sequence[Context], models: Sequence[str]
) -> dict[tuple[str, str], dict[str, Answer]]:
    """Answers already paid for, by tier 1 or by an earlier panel: the same
    bytes, so the same answer (DECIDE-0004)."""

    keys = {
        escalation.request_key(request(c, m)): (c, m) for c in contexts for m in models
    }
    rows = conn.execute(
        "SELECT hash, response FROM model_calls WHERE hash = ANY(%s)", (list(keys),)
    ).fetchall()
    found: dict[tuple[str, str], dict[str, Answer]] = {}
    for row in rows:
        context, model = keys[str(row["hash"])]
        try:
            found[(context.hash, model)] = escalation.parse(
                str(dict(row["response"]).get("text", "")), context.asks
            )
        except ValueError:
            continue
    return found


async def ask_panel(
    conn: Connection[DictRow], contexts: Sequence[Context], models: Sequence[str]
) -> int:
    """Put every uncached (context, model) to the panel; keep every reply."""

    have = cached(conn, contexts, models)
    missing = [(c, m) for c in contexts for m in models if (c.hash, m) not in have]
    if not missing:
        return 0
    async with Gateway(settings=load_settings()) as gateway:
        replies = await asyncio.gather(
            *(gateway.complete(request(c, m), purpose="explore") for c, m in missing),
            return_exceptions=True,
        )
    kept = 0
    for (context, model), reply in zip(missing, replies, strict=True):
        if isinstance(reply, BaseException):
            print(
                f"  {model} on {context.kind}: {type(reply).__name__}", file=sys.stderr
            )
            continue
        sent = request(context, model)
        body = sent.model_dump(mode="json")
        insert_call(
            conn,
            {
                "hash": escalation.request_key(sent),
                "kind": KIND,
                "model": model,
                "provider": reply.provider,
                "request": body,
                "wire": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                "response": {"text": reply.text, "model": reply.model},
                "input_tokens": reply.usage.input_tokens,
                "output_tokens": reply.usage.output_tokens,
                "cost_usd": reply.usage.cost_usd,
                "cost_estimated": reply.usage.cost_is_estimated,
                "latency_s": reply.latency_s,
            },
        )
        kept += 1
    return kept


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def render(
    contexts: Sequence[Context],
    sample: Sequence[Context],
    panel: dict[tuple[str, str], dict[str, Answer]],
    models: Sequence[str],
) -> str:
    kinds = sorted({c.kind for c in contexts})
    lines = [
        "# Judge panel",
        "",
        "Written by `make judge-panel` from the call cache. An effect is the "
        "mean total-variation distance between two answers that differ only in "
        "the situation, or only in the person's temperament. Agreement is with "
        "other models, not with the truth (design/005).",
        "",
        "## Jev, over everything it has been asked",
        "",
        "| set | contexts | situation pairs | situation effect "
        "| temperament pairs | temperament effect | reading |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for kind in kinds:
        mine = [c for c in contexts if c.kind == kind]
        e = effects(mine, lambda c: c.jev)
        lines.append(
            f"| {kind} | {len(mine)} | {e.situation_pairs} | {_fmt(e.situation)} "
            f"| {e.temperament_pairs} | {_fmt(e.temperament)} | {e.verdict} |"
        )

    lines += [
        "",
        "## The panel, on the same sample",
        "",
        f"{len(sample)} contexts, each put to {len(models)} models: "
        + ", ".join(f"`{m}`" for m in models)
        + ".",
        "",
        "| set | who | answered | agrees with Jev | situation effect "
        "| temperament effect |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for kind in sorted({c.kind for c in sample}):
        mine = [c for c in sample if c.kind == kind]
        e = effects(mine, lambda c: c.jev)
        lines.append(
            f"| {kind} | Jev | {len(mine)} | — | {_fmt(e.situation)} "
            f"| {_fmt(e.temperament)} |"
        )
        for model in models:

            def said(c: Context, model: str = model) -> dict[str, Answer] | None:
                return panel.get((c.hash, model))

            answered = [c for c in mine if said(c) is not None]
            agree = [escalation.agrees(c.asks, c.jev, said(c) or {}) for c in answered]
            e = effects(mine, said)
            share = f"{sum(agree) / len(agree):.0%}" if agree else "—"
            lines.append(
                f"| {kind} | {model} | {len(answered)} | {share} "
                f"| {_fmt(e.situation)} | {_fmt(e.temperament)} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make judge-panel", description=__doc__)
    parser.add_argument("--live", action="store_true", help="ask the panel (spends)")
    parser.add_argument("--per-set", type=int, default=PER_SET)
    parser.add_argument("--sets", default="", help="comma-separated; default all")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    kinds = [k.strip() for k in args.sets.split(",") if k.strip()] or None

    with db.connect(autocommit=True) as conn:
        contexts = load(conn, kinds)
        by_kind: dict[str, list[Context]] = {}
        for context in contexts:
            by_kind.setdefault(context.kind, []).append(context)
        sample = [c for mine in by_kind.values() for c in pick(mine, args.per_set)]
        have = cached(conn, sample, PANEL)
        asking = len(sample) * len(PANEL) - len(have)
        print(
            f"{len(contexts)} recorded Jev contexts; a sample of {len(sample)} "
            f"for {len(PANEL)} models; {asking} answers not yet had"
        )
        if args.live and asking:
            kept = asyncio.run(ask_panel(conn, sample, PANEL))
            print(f"kept {kept} new answers")
            have = cached(conn, sample, PANEL)
        elif asking:
            print("dry run: pass --live (make judge-panel LIVE=1) to ask them")
        args.out.write_text(render(contexts, sample, have, PANEL))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
