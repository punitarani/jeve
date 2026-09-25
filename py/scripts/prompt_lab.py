"""The prompt lab: how the typed questions and tier 1's prompt are answered,
measured on real states, and searched over the way DSPy searches instructions.

jeve's model calls are typed questions about a state (DECIDE-0003). What a
wording is *for* can be measured without any ground-truth label:

* **fit** — the mass a model puts on "something else" (`other`): the options
  do not cover what it thinks happens (design/005's ontology gap).
* **persona** — the same state with one trait set low and then high: the act
  that trait is about should move (vocality → press, sociability → small
  talk). A model that answers alike for a loud and a quiet person has
  flattened the cast (DECIDE-0006 measured the LLM doing it).
* **situation** — the same state with one fact moved: a conversation that has
  gone on for a while should be likelier to end.
* **stability** — the same state with an irrelevant reference field changed:
  the answer should not move (TypeSafe's probe method).
* **validity** — replies that parse into the typed shape.

`tier1` searches tier 1's system prompt (`decide/escalation.py`) for the
routed conversation set: hand-written seeds and candidates proposed by a
strong model from the scores so far (DSPy's propose-evaluate-select, on
jeve's own gateway: DSPy's calls would bypass `jeve.llm`). Selection is on a
dev split; the winner and the incumbent are then scored on a held-out split
nobody looked at. `models` compares tier-1 models on one prompt. `audit`
scores Jev on every modelled set. Every figure is written to
`ops/evals/prompt-lab/`.

    uv run --env-file ../.env python scripts/prompt_lab.py tier1 --from-db NAME
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from jeve.config import find_repo_root, load_settings
from jeve.decide import escalation
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS, Ask, Prepared, average_traits
from jeve.errors import ResponseShapeError, TransportError
from jeve.evals.runner import decision_contexts
from jeve.llm import DECISION_PREFERENCE, DecisionRequest, Gateway
from jeve.llm.protocol import (
    Answer,
    ChatMessage,
    ChatRequest,
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    ScoreAnswer,
)
from jeve.llm.protocol import Score as ScoreQuestion

OUT = find_repo_root() / "ops" / "evals" / "prompt-lab"
LOW, HIGH = 0.1, 0.9
PARALLEL = 12
PROPOSER = "anthropic/claude-opus-5.5"
CAP = 0.5

type Dist = dict[str, dict[str, float]]
"""Per ask key, a probability for every option."""


# -- states ----------------------------------------------------------------------


def contexts(db: str, kind: str, n: int, *, offset: int = 0) -> list[DecisionContext]:
    return decision_contexts(db, kind, n, offset=offset)


def with_trait(ctx: DecisionContext, trait: str, value: float) -> DecisionContext:
    return replace(ctx, traits={**ctx.traits, trait: value})


def with_fact(ctx: DecisionContext, key: str, value: object) -> DecisionContext:
    return replace(ctx, facts={**ctx.facts, key: value})


# -- answering -------------------------------------------------------------------


def _as_dist(answers: dict[str, Answer], asks: Sequence[Ask]) -> Dist:
    out: Dist = {}
    for ask in asks:
        answer = answers.get(ask.key)
        if isinstance(answer, NoulAnswer):
            out[ask.key] = {"yes": answer.noul, "no": 1.0 - answer.noul}
        elif isinstance(answer, ChoiceAnswer | ScoreAnswer):
            probs = answer.probabilities or {}
            out[ask.key] = {o: float(probs.get(o, 0.0)) for o in ask.options}
    return out


@dataclass
class Ledger:
    calls: int = 0
    failed: int = 0
    seconds: float = 0.0
    usd: float = 0.0


def tier1_request(prepared: Prepared, system: str, model: str) -> ChatRequest:
    """Tier 1's request with another system prompt: everything else — the
    situation, the questions, the strict schema — exactly as production sends
    it (`escalation.request_for`)."""

    base = escalation.request_for(prepared, [a.key for a in prepared.asks], model)
    return base.model_copy(
        update={
            "messages": [
                ChatMessage(role="system", content=system),
                *base.messages[1:],
            ]
        }
    )


async def ask_llm(
    gw: Gateway, prepared: Prepared, system: str, model: str, ledger: Ledger
) -> Dist | None:
    request = tier1_request(prepared, system, model)
    started = time.monotonic()
    try:
        reply = await gw.complete(request, purpose="gate")
        answers = escalation.parse(reply.text, prepared.asks)
    except ValueError, ResponseShapeError, TransportError:
        # An unusable reply, or a provider that would not give one, is the
        # measurement. A spend ceiling or a missing key is not: it propagates.
        ledger.failed += 1
        return None
    finally:
        ledger.calls += 1
        ledger.seconds += time.monotonic() - started
    ledger.usd += float(getattr(reply.usage, "cost_usd", 0.0) or 0.0)
    return _as_dist(answers, prepared.asks)


async def ask_jev(
    gw: Gateway,
    prepared: Prepared,
    ledger: Ledger,
    *,
    questions: dict[str, Noul | Choice | ScoreQuestion] | None = None,
    reference: str | None = None,
    keep_all: bool = False,
) -> Dist | None:
    state = dict(prepared.state or {})
    if reference is not None:
        state["reference"] = reference
    qs = {a.key: a.question for a in prepared.asks}
    qs.update(questions or {})
    started = time.monotonic()
    try:
        reply = await gw.decide(
            DecisionRequest(model=DECISION_PREFERENCE[0], state=state, questions=qs),
            purpose="gate",
        )
    except ValueError, ResponseShapeError, TransportError:
        ledger.failed += 1
        return None
    finally:
        ledger.calls += 1
        ledger.seconds += time.monotonic() - started
    if keep_all:
        return {
            k: dict(v.probabilities or {v.choice: 1.0})
            for k, v in reply.answers.items()
            if isinstance(v, ChoiceAnswer)
        }
    return _as_dist(dict(reply.answers), prepared.asks)


def jev_answerer(
    gw: Gateway, ledger: Ledger
) -> Callable[[Prepared], Awaitable[Dist | None]]:
    async def answer(prepared: Prepared) -> Dist | None:
        return await ask_jev(gw, prepared, ledger)

    return answer


def llm_answerer(
    gw: Gateway, prompt: str, model: str, ledger: Ledger
) -> Callable[[Prepared], Awaitable[Dist | None]]:
    async def answer(prepared: Prepared) -> Dist | None:
        return await ask_llm(gw, prepared, prompt, model, ledger)

    return answer


async def gather(
    jobs: Sequence[Callable[[], Awaitable[Dist | None]]],
) -> list[Dist | None]:
    gate = asyncio.Semaphore(PARALLEL)

    async def one(job: Callable[[], Awaitable[Dist | None]]) -> Dist | None:
        async with gate:
            return await job()

    return list(await asyncio.gather(*(one(j) for j in jobs)))


# -- scoring ---------------------------------------------------------------------


def entropy(dist: dict[str, float]) -> float:
    ps = [p for p in dist.values() if p > 0]
    total = sum(ps) or 1.0
    h = -sum((p / total) * math.log2(p / total) for p in ps)
    return h / math.log2(len(dist)) if len(dist) > 1 else 0.0


@dataclass
class Probe:
    """One state and its counterfactuals, as a model answered them."""

    base: Dist | None
    vocality: tuple[Dist | None, Dist | None]
    sociability: tuple[Dist | None, Dist | None]
    rounds: tuple[Dist | None, Dist | None]


@dataclass
class Score:
    valid: float
    p_done: float | None
    act_entropy: float | None
    other: float | None
    press_by_vocality: float | None
    small_talk_by_sociability: float | None
    done_by_rounds: float | None
    n: int
    objective: float = 0.0
    notes: list[str] = field(default_factory=list)


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _gap(pair: tuple[Dist | None, Dist | None], key: str, option: str) -> float | None:
    low, high = pair
    if low is None or high is None or option not in low.get(key, {}):
        return None
    return high[key][option] - low[key][option]


def score(probes: Sequence[Probe]) -> Score:
    answered = [
        d for p in probes for d in (p.base, *p.vocality, *p.sociability, *p.rounds)
    ]
    valid = sum(d is not None for d in answered) / max(1, len(answered))
    bases = [p.base for p in probes if p.base is not None]
    press = [g for p in probes if (g := _gap(p.vocality, "act", "press")) is not None]
    small = [
        g for p in probes if (g := _gap(p.sociability, "act", "small_talk")) is not None
    ]
    done = [g for p in probes if (g := _gap(p.rounds, "done", "yes")) is not None]
    s = Score(
        valid=valid,
        p_done=_mean([b["done"]["yes"] for b in bases if "done" in b]),
        act_entropy=_mean([entropy(b["act"]) for b in bases if "act" in b]),
        other=_mean([b["act"].get("other", 0.0) for b in bases if "act" in b]),
        press_by_vocality=_mean(press),
        small_talk_by_sociability=_mean(small),
        done_by_rounds=_mean(done),
        n=len(probes),
    )
    # What the search maximises: the persona and situation gradients, held to
    # a valid reply every time, conversations that still end, acts that are
    # not collapsed and options that fit. Constraints are penalties, not
    # filters, so a near-miss is still ranked.
    # Each gradient earns credit up to CAP: a caricature is not a better
    # person than one who is merely distinct (Jev's own press-by-vocality on
    # production data was +0.40).
    objective = (
        min(CAP, s.press_by_vocality or 0.0)
        + min(CAP, s.small_talk_by_sociability or 0.0)
        + 0.5 * min(CAP, s.done_by_rounds or 0.0)
    )
    if valid < 0.99:
        objective -= 5 * (0.99 - valid)
        s.notes.append("invalid replies")
    if s.p_done is not None and s.p_done < 0.35:
        objective -= 2 * (0.35 - s.p_done)
        s.notes.append("conversations would not end")
    if s.act_entropy is not None and s.act_entropy < 0.6:
        objective -= 2 * (0.6 - s.act_entropy)
        s.notes.append("acts collapsed")
    if s.other is not None and s.other > 0.1:
        objective -= 2 * (s.other - 0.1)
        s.notes.append("reaches for other")
    s.objective = objective
    return s


async def probe_all(
    ctxs: Sequence[DecisionContext],
    answer: Callable[[Prepared], Awaitable[Dist | None]],
) -> list[Probe]:
    kind = ctxs[0].kind
    return await probe_contexts(ctxs, lambda c: answer(QUESTION_SETS[kind].prepare(c)))


async def probe_contexts(
    ctxs: Sequence[DecisionContext],
    answer: Callable[[DecisionContext], Awaitable[Dist | None]],
) -> list[Probe]:
    variants: list[DecisionContext] = []
    for c in ctxs:
        variants += [
            c,
            with_trait(c, "vocality", LOW),
            with_trait(c, "vocality", HIGH),
            with_trait(c, "sociability", LOW),
            with_trait(c, "sociability", HIGH),
            with_fact(c, "rounds_done", 0),
            with_fact(c, "rounds_done", 3),
        ]
    got = await gather([lambda v=v: answer(v) for v in variants])
    return [
        Probe(
            got[i],
            (got[i + 1], got[i + 2]),
            (got[i + 3], got[i + 4]),
            (got[i + 5], got[i + 6]),
        )
        for i in range(0, len(got), 7)
    ]


# -- the search ------------------------------------------------------------------

SEEDS: dict[str, str] = {
    "incumbent": escalation.SYSTEM,
    "persona_first": (
        "You are deciding for one particular person in a simulation of a small "
        "town's businesses. Read who they are before anything else: their "
        "temperament and how readily they speak up are the strongest evidence "
        "you have, and two people in the same situation with different "
        "temperaments often do different things. For each question, give a "
        "probability for every option: how likely this person is to choose it, "
        "or how likely it is to be the right answer, judging only by what you "
        "are told. A question's probabilities sum to one. Answer in the JSON "
        "shape required, and nothing else."
    ),
    "hundred_people": (
        "You are estimating behaviour for a simulation of a small town's "
        "businesses. Picture a hundred different people who each fit this "
        "description exactly — the same temperament, the same situation. For "
        "each question, give the share of them who would choose each option, "
        "or, where the question has a right answer, how likely each option is "
        "to be it. Let everything you are told matter, the person as much as "
        "the situation. A question's shares sum to one. Answer in the JSON "
        "shape required, and nothing else."
    ),
    "differentiate": (
        "You are deciding for one person in a simulation of a small town's "
        "businesses. You are given their situation and one or more questions. "
        "The description of the person is there because it changes what they "
        "do: a quiet person seldom pushes, a sociable one chats, an impatient "
        "one wants to be done. Do not give the answer an average person would "
        "give. For each question, give a probability for every option, judging "
        "only by what you are told; a question's probabilities sum to one. "
        "Answer in the JSON shape required, and nothing else."
    ),
}


def _proposal_brief(results: dict[str, tuple[str, Score]], jev: Score) -> str:
    table = "\n".join(
        f"- {name}: objective {s.objective:+.3f}; press-by-vocality "
        f"{s.press_by_vocality}; small-talk-by-sociability "
        f"{s.small_talk_by_sociability}; done-by-rounds {s.done_by_rounds}; "
        f"P(done) {s.p_done}; act entropy {s.act_entropy}; other {s.other}; "
        f"valid {s.valid:.2f}\n  PROMPT: {prompt}"
        for name, (prompt, s) in sorted(
            results.items(), key=lambda kv: -kv[1][1].objective
        )
    )
    return (
        "You are optimising the system prompt of a small, cheap language model "
        "that answers typed questions for one person in an agent-based "
        "simulation of a town's businesses. The user message is JSON: a "
        "'situation' (words describing the person — their temperament, how "
        "readily they speak up — and the conversation they are in) and "
        "'questions', each with options. The model must reply with a "
        "probability for every option, in a strict JSON schema; the "
        "simulation samples from those probabilities, so they must be honest "
        "propensities, not a single guess.\n\n"
        "The failure to fix: the model gives nearly the same answer for a loud "
        "person and a quiet one, so the simulated people lose their "
        "personalities. We measure, on real states, how much the probability "
        "of 'press' rises when the person is described as outspoken instead of "
        "quiet, how much 'small_talk' rises when they are sociable instead of "
        "reserved, and how much 'had their say' (done) rises when the "
        "conversation has gone on a while. The objective adds those three "
        "(the last at half weight), each capped at 0.5 because caricature is "
        "no better than flatness, and penalises invalid replies, mean "
        "P(done) under 0.35, act entropy under 0.6, and mass on 'other' over "
        "0.1.\n\n"
        f"For reference, the specialised decision model the simulation uses "
        f"otherwise scores: press-by-vocality {jev.press_by_vocality}, "
        f"small-talk-by-sociability {jev.small_talk_by_sociability}, "
        f"done-by-rounds {jev.done_by_rounds}, P(done) {jev.p_done}.\n\n"
        f"Prompts tried so far, best first:\n{table}\n\n"
        "Propose four new system prompts that you expect to score higher. "
        "Each must keep the contract: probabilities for every option, summing "
        "to one per question, JSON only. Do not mention the metrics, the "
        "words 'press' or 'small_talk', or any particular option. Do not tell "
        "the model what probabilities to give. Vary the strategy between the "
        'four. Reply as JSON: {"prompts": ["...", "...", "...", "..."]}.'
    )


async def propose(gw: Gateway, brief: str) -> list[str]:
    reply = await gw.complete(
        ChatRequest(
            model=PROPOSER,
            messages=[ChatMessage(role="user", content=brief)],
            max_tokens=4000,
            seed=20261210,
            temperature=0.7,
            response_schema={
                "type": "object",
                "properties": {
                    "prompts": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["prompts"],
                "additionalProperties": False,
            },
        ),
        purpose="gate",
    )
    raw = json.loads(reply.text)
    return [str(p) for p in raw["prompts"]][:4]


def _row(name: str, s: Score, ledger: Ledger | None = None) -> dict[str, Any]:
    out = {"name": name, **{k: v for k, v in s.__dict__.items()}}
    if ledger is not None:
        out |= {
            "calls": ledger.calls,
            "failed": ledger.failed,
            "seconds_per_call": ledger.seconds / max(1, ledger.calls),
        }
    return out


async def tier1(args: argparse.Namespace) -> int:
    dev = contexts(args.from_db, "episode.round", args.dev)
    held = contexts(args.from_db, "episode.round", args.held_out, offset=args.dev)
    model = args.model
    results: dict[str, tuple[str, Score]] = {}
    log: list[dict[str, Any]] = []
    async with Gateway(settings=load_settings()) as gw:
        jev_ledger = Ledger()
        jev_dev = score(await probe_all(dev, lambda p: ask_jev(gw, p, jev_ledger)))
        log.append(_row("jev (reference)", jev_dev, jev_ledger))
        print("jev dev", _row("jev", jev_dev))

        async def evaluate(name: str, prompt: str) -> None:
            ledger = Ledger()
            s = score(await probe_all(dev, llm_answerer(gw, prompt, model, ledger)))
            results[name] = (prompt, s)
            log.append({**_row(name, s, ledger), "prompt": prompt})
            print(f"{name}: objective {s.objective:+.3f} {s.notes}")

        for name, prompt in SEEDS.items():
            await evaluate(name, prompt)
        for generation in range(args.rounds):
            for i, prompt in enumerate(
                await propose(gw, _proposal_brief(results, jev_dev))
            ):
                await evaluate(f"proposed_{generation + 1}_{i + 1}", prompt)

        best = max(results, key=lambda k: results[k][1].objective)
        finals: dict[str, Any] = {}
        for name in dict.fromkeys(["incumbent", best]):
            ledger = Ledger()
            prompt = results[name][0]
            s = score(await probe_all(held, llm_answerer(gw, prompt, model, ledger)))
            finals[name] = {**_row(name, s, ledger), "prompt": prompt}
        jl = Ledger()
        finals["jev (reference)"] = _row(
            "jev", score(await probe_all(held, lambda p: ask_jev(gw, p, jl))), jl
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"tier1-{model.replace('/', '_')}.json").write_text(
        json.dumps({"model": model, "dev": log, "held_out": finals, "best": best},
                   indent=1, default=str) + "\n"
    )  # fmt: skip
    print(json.dumps(finals, indent=1, default=str))
    return 0


async def models(args: argparse.Namespace) -> int:
    held = contexts(args.from_db, "episode.round", args.held_out, offset=args.dev)
    prompt = SEEDS["incumbent"] if args.prompt == "incumbent" else args.prompt
    rows = []
    async with Gateway(settings=load_settings()) as gw:
        for model in args.models.split(","):
            ledger = Ledger()
            s = score(await probe_all(held, llm_answerer(gw, prompt, model, ledger)))
            rows.append({"model": model, **_row(model, s, ledger)})
            print(
                model,
                f"{s.objective:+.3f}",
                s.valid,
                ledger.seconds / max(1, ledger.calls),
            )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "models.json").write_text(
        json.dumps({"prompt": prompt, "rows": rows}, indent=1, default=str) + "\n"
    )
    return 0


# -- the persona transplant (DECIDE-0008) -----------------------------------------


def _answer_of(ask: Ask, dist: dict[str, float]) -> Answer:
    best = max(ask.options, key=lambda o: dist.get(o, 0.0))
    if isinstance(ask.question, Noul):
        return NoulAnswer(noul=dist["yes"])
    if isinstance(ask.question, Choice):
        return ChoiceAnswer(choice=best, probabilities=dist)
    return ScoreAnswer(score=float(best), probabilities=dist)


class Once:
    """Each distinct request asked once, however many variants share it."""

    def __init__(self) -> None:
        self._jobs: dict[str, asyncio.Task[Dist | None]] = {}

    async def __call__(
        self, key: str, job: Callable[[], Awaitable[Dist | None]]
    ) -> Dist | None:
        if key not in self._jobs:
            self._jobs[key] = asyncio.ensure_future(job())
        return await self._jobs[key]


def transplanted(
    gw: Gateway, model: str, llm: Ledger, jev: Ledger, once: Once
) -> Callable[[DecisionContext], Awaitable[Dist | None]]:
    """The LLM asked about the average person in this situation, moved by
    Jev's own answer for this person over its answer for the average one."""

    async def answer(ctx: DecisionContext) -> Dist | None:
        qs = QUESTION_SETS[ctx.kind]
        person = qs.prepare(ctx)
        average = qs.prepare(replace(ctx, traits=average_traits(ctx.traits)))
        key = json.dumps(average.state, sort_keys=True)
        situation = await once(
            f"{model}|{key}",
            lambda: ask_llm(gw, average, escalation.SYSTEM, model, llm),
        )
        p = await once(
            "jev|" + json.dumps(person.state, sort_keys=True),
            lambda: ask_jev(gw, person, jev),
        )
        a = await once("jev|" + key, lambda: ask_jev(gw, average, jev))
        if situation is None or p is None or a is None:
            return None
        out: Dist = {}
        for ask in person.asks:
            if ask.key in situation and ask.key in p and ask.key in a:
                moved = escalation.transplant(
                    ask,
                    _answer_of(ask, situation[ask.key]),
                    _answer_of(ask, p[ask.key]),
                    _answer_of(ask, a[ask.key]),
                )
                out[ask.key] = escalation.distribution(ask, moved)
        return out

    return answer


async def transplant(args: argparse.Namespace) -> int:
    """Each model plain and transplanted, against Jev, on dev and held-out
    states: persona should come out at Jev's strength, and the situation
    (conversations ending as they go on) at the LLM's."""

    splits = {
        "dev": contexts(args.from_db, "episode.round", args.dev),
        "held_out": contexts(
            args.from_db, "episode.round", args.held_out, offset=args.dev
        ),
    }
    out: dict[str, list[dict[str, Any]]] = {}
    async with Gateway(settings=load_settings()) as gw:
        for split, ctxs in splits.items():
            rows: list[dict[str, Any]] = []
            once = Once()
            jl = Ledger()
            rows.append(
                _row(
                    "jev",
                    score(await probe_all(ctxs, jev_answerer(gw, jl))),
                    jl,
                )
            )
            for model in args.models.split(","):
                plain = Ledger()
                s = score(
                    await probe_all(
                        ctxs, llm_answerer(gw, escalation.SYSTEM, model, plain)
                    )
                )
                rows.append(_row(model, s, plain))
                llm, jev = Ledger(), Ledger()
                s = score(
                    await probe_contexts(ctxs, transplanted(gw, model, llm, jev, once))
                )
                rows.append(
                    _row(f"{model} + Jev's persona", s, llm)
                    | {"jev_calls": jev.calls, "jev_failed": jev.failed}
                )
            for row in rows:
                print(split, json.dumps({k: row[k] for k in (
                    "name", "press_by_vocality", "small_talk_by_sociability",
                    "done_by_rounds", "p_done", "act_entropy", "other", "valid",
                )}, default=str))  # fmt: skip
            out[split] = rows
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "transplant.json").write_text(
        json.dumps({"from": args.from_db, **out}, indent=1, default=str) + "\n"
    )
    return 0


# -- the persona judge on arms (EVAL-0004) ----------------------------------------


def _sampled(dist: dict[str, float], options: Sequence[str], u: float) -> str:
    """The option a uniform `u` lands on, in declared order: every arm reads
    the same `u` for the same moment and cast (common random numbers)."""

    total = 0.0
    for option in options:
        total += dist.get(option, 0.0)
        if u < total:
            return option
    return options[-1]


type Acts = dict[str, dict[tuple[int, int], dict[str, str]]]


async def cast_acts(
    args: argparse.Namespace, states: Sequence[DecisionContext]
) -> tuple[Acts, dict[str, Ledger]]:
    """What each arm's person did in each moment under each cast, drawn from
    the arm's answer with the same uniform for every arm."""

    from jeve.core.seed import derive_rng
    from jeve.evals import casts

    arms: dict[str, Callable[[DecisionContext], Awaitable[Dist | None]]] = {}
    once = Once()
    ledgers: dict[str, Ledger] = {}
    async with Gateway(settings=load_settings()) as gw:
        for arm in args.arms.split(","):
            ledgers[arm] = ledger = Ledger()
            if arm == "jev":
                answer = jev_answerer(gw, ledger)
            elif arm.endswith("+jev"):
                model = arm.removesuffix("+jev")
                answer_ctx = transplanted(gw, model, ledger, Ledger(), once)
                arms[arm] = answer_ctx
                continue
            else:
                answer = llm_answerer(gw, escalation.SYSTEM, arm, ledger)
            arms[arm] = lambda c, a=answer: a(QUESTION_SETS[c.kind].prepare(c))
        variants = [
            (i, name, casts.cast(ctx, traits))
            for i, ctx in enumerate(states)
            for name, traits in casts.CASTS
        ]
        got = {
            arm: await gather([lambda v=v, f=f: f(v[2]) for v in variants])
            for arm, f in arms.items()
        }
    acts: Acts = {a: {} for a in arms}
    for arm in arms:
        for (i, name, ctx), dist in zip(variants, got[arm], strict=True):
            if dist is None or "act" not in dist:
                continue
            options = QUESTION_SETS[casts.KIND].prepare(ctx).asks[0].options
            for k in range(args.draws):
                u = derive_rng(20261250, "casts", ctx.person_id, ctx.sim_time, name, k)
                acts[arm].setdefault((i, k), {})[name] = _sampled(
                    dist["act"], options, u.random()
                )
    return acts, ledgers


def casts_mode(args: argparse.Namespace) -> int:
    """Each arm answers one moment under an outgoing and a reserved cast; the
    persona judge compares arms side by side on the same moments."""

    from jeve.evals import casts, judge, stats
    from jeve.evals.cli import _judge_conn, _suffix
    from jeve.evals.report import JUDGE_DIR

    states = contexts(args.from_db, casts.KIND, args.n, offset=args.offset)
    acts, ledgers = asyncio.run(cast_acts(args, states))
    arms = list(acts)
    rows: list[dict[str, Any]] = []
    conn = _judge_conn()
    for contrast in args.contrasts.split(","):
        a, b = contrast.split(":")
        pairs = [
            judge.Pair(
                f"cast:{a}:{b}:{i}:{k}",
                casts.side(states[i], acts[a][(i, k)]),
                casts.side(states[i], acts[b][(i, k)]),
                f"{b} over {a}",
                casts.SYSTEM,
            )
            for (i, k) in sorted(set(acts[a]) & set(acts[b]))
            if len(acts[a][(i, k)]) == len(acts[b][(i, k)]) == len(casts.CASTS)
        ]
        for model in args.judges.split(","):
            family = model.split("/")[0]
            if any(arm.split("/")[0] == family for arm in (a, b)):
                continue  # a judge never scores its own family (arXiv 2404.13076)
            valid = JUDGE_DIR / f"0-validation-casts{_suffix(model)}.json"
            if not valid.exists():
                print(f"{model}: not validated (judge-validate --casts); skipped")
                continue
            if json.loads(valid.read_text())["accuracy"] < judge.MIN_ACCURACY:
                continue
            run = judge.judge(conn, pairs, model=model, live=True)
            done = [s for s in run.scored if s.right_points is not None]
            points = sum(s.right_points or 0.0 for s in done)
            interval = stats.proportion_interval(points, len(done))
            same = sum(s.pair.left == s.pair.right for s in done)
            steady = sum(1 for s in done if s.consistent)
            rows.append({
                "contrast": f"{b} over {a}", "judge": model, "n": len(done),
                "right_preferred": points / max(1, len(done)), "wilson": interval,
                "identical_sides": same, "consistent": steady,
                "cost_usd": run.cost_usd, "failed": run.failed,
            })  # fmt: skip
            print(json.dumps(rows[-1]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "casts.json").write_text(
        json.dumps(
            {
                "from": args.from_db,
                "states": len(states),
                "offset": args.offset,
                "draws": args.draws,
                "arms": {a: {"calls": ledgers[a].calls, "failed": ledgers[a].failed}
                         for a in arms},
                "rows": rows,
                "acts": {
                    arm: {f"{i}:{k}": v for (i, k), v in sorted(acts[arm].items())}
                    for arm in arms
                },
            },
            indent=1,
            default=str,
        )
        + "\n"
    )  # fmt: skip
    return 0


# -- the audit -------------------------------------------------------------------

PERSONA: dict[str, tuple[str, str, str]] = {
    # The trait each set's question renders, and the act it ought to move
    # (the field report's persona pairs, and one for every other set that
    # renders a trait).
    "agent.tick": ("sociability", "interact", "yes"),
    "cafe.purchase": ("patience", "buy", "yes"),
    "payment.timing": ("promptness", "pay_today", "yes"),
    "file.ticket": ("vocality", "file", "yes"),
    "ticket.answer": ("diligence", "answer_now", "yes"),
    "time.log": ("diligence", "log", "yes"),
    "invoice.dispute": ("patience", "dispute", "yes"),
    "chase.invoice": ("vocality", "chase", "yes"),
    "episode.round": ("vocality", "act", "press"),
}


def tv(p: dict[str, float], q: dict[str, float]) -> float:
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in set(p) | set(q))


def reversed_questions(prepared: Prepared) -> dict[str, Noul | Choice]:
    return {
        a.key: Choice(
            instructions=a.question.instructions,
            criteria=dict(reversed(list(a.question.criteria.items()))),
        )
        for a in prepared.asks
        if isinstance(a.question, Choice)
    }


async def audit(args: argparse.Namespace) -> int:
    from jeve.decide import gates

    rows: list[dict[str, Any]] = []
    async with Gateway(settings=load_settings()) as gw:
        for kind in sorted(QUESTION_SETS):
            pool = [
                c
                for c in contexts(args.from_db, kind, args.n * 4)
                if gates.settle(c) is None
            ][: args.n]
            if not pool:
                continue
            ledger = Ledger()
            trait = PERSONA.get(kind)
            jobs: list[Callable[[], Awaitable[Dist | None]]] = []
            for c in pool:
                prepared = QUESTION_SETS[kind].prepare(c)
                if prepared.state is None:
                    continue
                flipped = reversed_questions(prepared)
                jobs += [
                    lambda p=prepared, lg=ledger: ask_jev(gw, p, lg),
                    lambda p=prepared, lg=ledger: ask_jev(
                        gw, p, lg, reference="ref-7c1e"
                    ),
                    lambda p=prepared, f=flipped, lg=ledger: ask_jev(
                        gw, p, lg, questions=f
                    ),
                ]
                if trait is not None:
                    for level in (LOW, HIGH):
                        low_high = QUESTION_SETS[kind].prepare(
                            with_trait(c, trait[0], level)
                        )
                        jobs.append(lambda p=low_high, lg=ledger: ask_jev(gw, p, lg))
            got = await gather(jobs)
            step = 5 if trait is not None else 3
            others, gaps, stab, order, persona = [], [], [], [], []
            for i in range(0, len(got), step):
                base, ref, flip = got[i], got[i + 1], got[i + 2]
                if base is None:
                    continue
                for key, dist in base.items():
                    if "other" in dist:
                        others.append(dist["other"])
                        gaps.append(float(dist["other"] >= 0.35))
                    if ref is not None and key in ref:
                        stab.append(tv(dist, ref[key]))
                    if flip is not None and key in flip and "other" in dist:
                        order.append(tv(dist, flip[key]))
                if trait is not None:
                    low, high = got[i + 3], got[i + 4]
                    _, key, option = trait
                    if low and high and key in low and option in low[key]:
                        persona.append(high[key][option] - low[key][option])
            rows.append(
                {
                    "set": kind,
                    "n": len(pool),
                    "other": _mean(others),
                    "gap_share": _mean(gaps),
                    "instability_tv": _mean(stab),
                    "order_tv": _mean(order),
                    "persona": trait[0] if trait else None,
                    "persona_gap": _mean(persona),
                    "failed": ledger.failed,
                }
            )
            print(rows[-1])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "audit.json").write_text(json.dumps(rows, indent=1) + "\n")
    return 0


# -- orders (DECIDE-0007) --------------------------------------------------------


def _arranged(ask: Ask, order: list[str]) -> Choice:
    assert isinstance(ask.question, Choice)
    criteria = dict(ask.question.criteria)
    tail = {"other": criteria["other"]} if "other" in criteria else {}
    return Choice(
        instructions=ask.question.instructions,
        criteria={**{o: criteria[o] for o in order}, **tail},
    )


def _verdict(dist: dict[str, float], body: Sequence[str]) -> str:
    return max(body, key=lambda option: dist.get(option, 0.0))


def _averaged(raw: Dist, ask: Ask) -> dict[str, float]:
    """A judgement's rotated copies, as Jev answered them, averaged the way
    the policy averages them."""

    from jeve.decide.jev_policy import collapse_rotations

    answers: dict[str, Answer] = {
        key: ChoiceAnswer(choice=max(dist, key=dist.__getitem__), probabilities=dist)
        for key, dist in raw.items()
    }
    got = collapse_rotations([ask], answers)[ask.key]
    assert isinstance(got, ChoiceAnswer)
    return got.distribution()


async def orders(args: argparse.Namespace) -> int:
    """How often a judgement's verdict changes with the order of its options:
    one order against another, and every rotation (bundled in one request, as
    `rotated_questions` asks) against every rotation of the reversed list, an
    order set the first never saw."""

    from jeve.decide import gates
    from jeve.decide.jev_policy import rotated_questions

    rows: dict[str, Any] = {}
    async with Gateway(settings=load_settings()) as gw:
        for kind in sorted(QUESTION_SETS):
            pool: list[DecisionContext] = []
            for db in args.from_db.split(","):
                pool += [
                    c for c in contexts(db, kind, args.n * 3) if gates.settle(c) is None
                ]
            jobs: list[Callable[[], Awaitable[Dist | None]]] = []
            meta: list[tuple[Ask, Ask, list[str]]] = []
            ledger = Ledger()
            for c in pool[: args.n]:
                prepared = QUESTION_SETS[kind].prepare(c)
                judged = [
                    a
                    for a in prepared.asks
                    if a.mode == "J" and isinstance(a.question, Choice)
                ]
                if prepared.state is None or not judged:
                    continue
                ask = judged[0]
                body = [o for o in ask.options if o != "other"]
                flipped = replace(ask, question=_arranged(ask, body[::-1]))
                # The whole request, as production sends it: every question
                # of the set, the judgement's copies with them.
                rest = [a for a in prepared.asks if a.key != ask.key]
                bundled = rotated_questions(prepared.asks)
                bundled_flipped = rotated_questions([flipped, *rest])
                rotated = {ask.key: _arranged(ask, body[1:] + body[:1])}
                jobs += [
                    lambda p=prepared, q=bundled, lg=ledger: ask_jev(
                        gw, p, lg, questions=q, keep_all=True
                    ),
                    lambda p=prepared, q=bundled_flipped, lg=ledger: ask_jev(
                        gw, p, lg, questions=q, keep_all=True
                    ),
                    lambda p=prepared, q=rotated, lg=ledger: ask_jev(
                        gw, p, lg, questions=q
                    ),
                ]
                meta.append((ask, flipped, body))
            if not meta:
                continue
            got = await gather(jobs)
            single = rotated_flips = n = 0
            for i, (ask, flipped, body) in enumerate(meta):
                declared, reversed_, other_order = got[3 * i : 3 * i + 3]
                if declared is None or reversed_ is None or other_order is None:
                    continue
                single += _verdict(declared[ask.key], body) != _verdict(
                    other_order[ask.key], body
                )
                rotated_flips += _verdict(_averaged(declared, ask), body) != _verdict(
                    _averaged(reversed_, flipped), body
                )
                n += 1
            rows[kind] = {
                "n": n,
                "single_order_flip": single / n if n else None,
                "rotated_flip": rotated_flips / n if n else None,
            }
            print(kind, rows[kind], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "orders.json").write_text(json.dumps(rows, indent=1) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prompt_lab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tier1")
    t.add_argument("--from-db", required=True)
    t.add_argument("--model", default="z-ai/glm-5.3-flash")
    t.add_argument("--dev", type=int, default=30)
    t.add_argument("--held-out", type=int, default=30)
    t.add_argument("--rounds", type=int, default=2)
    m = sub.add_parser("models")
    m.add_argument("--from-db", required=True)
    m.add_argument("--models", required=True)
    m.add_argument("--prompt", default="incumbent")
    m.add_argument("--dev", type=int, default=30)
    m.add_argument("--held-out", type=int, default=30)
    o = sub.add_parser("orders")
    o.add_argument("--from-db", required=True, help="comma-separated worlds")
    o.add_argument("--n", type=int, default=80)
    c = sub.add_parser("casts")
    c.add_argument("--from-db", required=True)
    c.add_argument("--n", type=int, default=60)
    c.add_argument("--offset", type=int, default=30)
    c.add_argument("--draws", type=int, default=2)
    c.add_argument(
        "--arms",
        default="jev,z-ai/glm-5.3-flash,z-ai/glm-5.3-flash+jev,openai/gpt-5.6-luna",
    )
    c.add_argument(
        "--contrasts",
        default="z-ai/glm-5.3-flash:z-ai/glm-5.3-flash+jev,"
        "z-ai/glm-5.3-flash:openai/gpt-5.6-luna,"
        "openai/gpt-5.6-luna:z-ai/glm-5.3-flash+jev,"
        "jev:z-ai/glm-5.3-flash+jev,jev:z-ai/glm-5.3-flash",
    )
    c.add_argument("--judges", default="openai/gpt-5.6-luna,anthropic/claude-sonnet-5")
    x = sub.add_parser("transplant")
    x.add_argument("--from-db", required=True)
    x.add_argument("--models", default="z-ai/glm-5.3-flash,openai/gpt-5.6-luna")
    x.add_argument("--dev", type=int, default=30)
    x.add_argument("--held-out", type=int, default=30)
    a = sub.add_parser("audit")
    a.add_argument("--from-db", required=True)
    a.add_argument("--n", type=int, default=12)
    args = parser.parse_args(argv)
    if args.command == "orders":
        return asyncio.run(orders(args))
    if args.command == "audit":
        return asyncio.run(audit(args))
    if args.command == "tier1":
        return asyncio.run(tier1(args))
    if args.command == "models":
        return asyncio.run(models(args))
    if args.command == "transplant":
        return asyncio.run(transplant(args))
    if args.command == "casts":
        return casts_mode(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
