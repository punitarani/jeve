"""Tier 1: an uncertain typed answer, asked again of a flash LLM (DECIDE-0005,
implementing DECIDE-0002's first tier).

The preference order for who decides anything in this world:

1. **A code gate**, where the world has already decided (`gates.py`).
2. **Jev, typed**: every judgement and propensity (`jev_policy.py`).
3. **Tier 1, here**: the same typed questions, re-asked of a generative model
   that must answer in the same shape. Only the questions Jev was unsure of,
   only where the stakes justify it, in LLM-0006's model order.
4. **Tier 2, generative**, never in the causal loop: prose for a reader
   (GEN-0001) and ontology-gap proposals for a person to review.

"Unsure" is design/005-escalation.md's rule, per primitive:

* a **choice**, when its top option has under half the mass or leads the next
  by under 0.15;
* a **score**, when its most likely level has under 0.40 and at least a
  quarter of the mass lies on each side of the boundary next to it;
* a **noul**, within 0.12 of the threshold the code acts on (0.5).

High stakes widen every band by half. Low-stakes sets never escalate, and a
propensity (P) question escalates only when the stakes are high: a flat
distribution over plausible actions is what indecision looks like, and
sampling it is the right response (DECIDE-0002).

It runs **in shadow** first: both answers are kept and Jev's decides, so the
two tiers' agreement is measured before any question set goes live
(`make escalation-report`). A 2% uniform sample of confident answers is
escalated as well, because agreement measured only where Jev was unsure says
nothing about where it was sure. A set goes live only when a person names it in
`JEVE_ESCALATION_LIVE`. Then a judgement takes the LLM's answer and a
propensity samples an even mixture of both, so a persona signal in Jev's answer
is kept rather than overwritten.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.clock import DAY
from jeve.core.hashing import content_hash
from jeve.core.seed import derive_rng
from jeve.decide.questions import Ask, Prepared
from jeve.llm.protocol import (
    Answer,
    ChatMessage,
    ChatRequest,
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    ProviderPrefs,
    Score,
    ScoreAnswer,
)

type Mode = Literal["off", "shadow", "live"]
type Stakes = Literal["low", "medium", "high"]

KIND = "tier1"
"""`model_calls.kind` for a tier-1 answer: cached, replayed, priced and carried
in the cassette with everything else, and never mistaken for a Jev call."""

# Room for a model that reasons before it answers: GLM 5.3 Flash cannot be told
# not to (ChatRequest.reasoning), and a reply cut off mid-thought is empty.
# 1,600 was not room: every one of GLM's 50 unreadable replies on held-out
# seeds stopped at exactly 1,600 tokens, mid-reasoning, before any JSON.
MAX_TOKENS = 4000
PROVIDERS = ProviderPrefs(ignore=["together"])
"""LLM-0003, per request. Together served 134 of 330 of GLM's tier-1 calls on
held-out seeds and all 50 of the unreadable ones: it writes the model's
reasoning into the reply instead of honouring the schema. Wafer, Fireworks and
Baseten returned schema-shaped JSON every time (docs/ops/llm-integration.md)."""
SEED = 0
"""Fixed, so two people in the same situation share one cached answer, as they
share one Jev call."""

SHADOW_SAMPLE = 0.02
DAILY_SHARE = 0.05
DAILY_FLOOR = 25
"""The first day has no yesterday to take five percent of."""

CHOICE_TOP_BELOW = 0.50
CHOICE_MARGIN_BELOW = 0.15
SCORE_TOP_BELOW = 0.40
SCORE_SIDE_ABOVE = 0.25
NOUL_THRESHOLD = 0.5
NOUL_BAND = 0.12
HIGH_STAKES_WIDEN = 1.5

STAKES: dict[str, Stakes] = {
    # What someone does every quarter hour, at a till, or in passing: never.
    "agent.tick": "low",
    "cafe.purchase": "low",
    "episode.round": "low",
    "ticket.answer": "low",
    "ticket.confirm": "low",
    "catering.order": "low",
    # Money that moves, or somebody's standing with a customer.
    "file.ticket": "medium",
    "payment.timing": "medium",
    "chase.invoice": "medium",
    "deploy.decision": "medium",
    "vendor.trust": "medium",
    "time.log": "medium",
    "catering.accept": "medium",
    "supplier.order": "medium",
    "cover.shift": "medium",
    "close.order": "medium",
    "escalation.handoff": "medium",
    # A firm's course, a person's job, a customer won or lost.
    "ticket.triage": "high",
    "credit.decision": "high",
    "payroll.release": "high",
    "close.signoff": "high",
    "founder.review": "high",
    "leave.consider": "high",
    "career.review": "high",
    "hire.decision": "high",
    "eng.allocation": "high",
    "subscription.renew": "high",
    "retention.offer": "high",
    "invoice.dispute": "high",
    "dispute.resolution": "high",
}
_RANK: dict[Stakes, int] = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True, slots=True)
class Config:
    """Off unless asked for. `live` names the sets whose second opinion the
    world acts on; every other escalated set stays in shadow.

    `route` names sets tier 1 answers *outright* (DECIDE-0006): every question,
    every time, whatever Jev's confidence, and the world samples the LLM's
    distribution itself rather than a mixture. `set:ask` routes one question
    of a set and leaves the others to Jev. Jev is still asked, so each
    routed decision carries both answers — the cheapest way to measure whether
    a general-purpose model answers a set's typed questions any better. Routed
    rows are not escalations and do not use up the day's room."""

    mode: Mode = "off"
    live: frozenset[str] = frozenset()
    route: frozenset[str] = frozenset()

    def applies(self, kind: str) -> bool:
        return self.mode == "live" and kind in self.live

    def routes(self, kind: str) -> bool:
        return kind in self.route or any(
            entry.partition(":")[0] == kind for entry in self.route
        )

    def routed_asks(self, kind: str, asks: Sequence[Ask]) -> tuple[str, ...]:
        """Which of a set's questions tier 1 answers: all of them when the set
        is named, or only those named as `set:ask`. The rest stay Jev's."""

        if kind in self.route:
            return tuple(a.key for a in asks)
        named = {
            ask for entry in self.route
            for set_, _, ask in [entry.partition(":")] if set_ == kind and ask
        }  # fmt: skip
        return tuple(a.key for a in asks if a.key in named)


@dataclass(frozen=True, slots=True)
class Trigger:
    ask: str
    rule: str
    value: float

    def row(self) -> dict[str, object]:
        return {"ask": self.ask, "rule": self.rule, "value": round(self.value, 4)}


ROUTED = Trigger("*", "routed", 1.0)
"""The trigger a routed decision's row carries: asked because its set is
routed, not because Jev was unsure."""
ROUTED_ROW = json.dumps([{"rule": ROUTED.rule}])
"""Containment pattern for a routed row, so the day's room skips it."""


def stakes(kind: str) -> Stakes:
    return STAKES.get(kind, "low")


def rank(kind: str) -> int:
    return _RANK[stakes(kind)]


def distribution(ask: Ask, answer: Answer) -> dict[str, float]:
    """An answer as mass over the ask's declared options, in declared order."""

    if isinstance(answer, NoulAnswer):
        p = min(max(float(answer.noul), 0.0), 1.0)
        return {"yes": p, "no": 1.0 - p}
    raw: dict[str, float] = {}
    if isinstance(answer, ChoiceAnswer):
        raw = answer.probabilities or {answer.choice: 1.0}
    elif isinstance(answer, ScoreAnswer):
        raw = answer.probabilities or {str(round(answer.score)): 1.0}
    values = {o: max(0.0, float(raw.get(o, 0.0))) for o in ask.options}
    total = sum(values.values()) or 1.0
    return {o: v / total for o, v in values.items()}


def _score_straddles(levels: list[float], widen: float) -> float | None:
    """The top level's mass, if the distribution sits across a boundary."""

    if not levels:
        return None
    best = max(range(len(levels)), key=lambda i: levels[i])
    top = levels[best]
    if top >= SCORE_TOP_BELOW * widen:
        return None
    neighbours = [i for i in (best - 1, best + 1) if 0 <= i < len(levels)]
    heavier = max(neighbours, key=lambda i: levels[i])
    boundary = max(best, heavier)
    below, above = sum(levels[:boundary]), sum(levels[boundary:])
    return top if min(below, above) >= SCORE_SIDE_ABOVE else None


def triggers(
    kind: str, asks: Sequence[Ask], answers: Mapping[str, Answer]
) -> list[Trigger]:
    """Which of these answers design/005's rule calls uncertain."""

    level = stakes(kind)
    if level == "low":
        return []
    widen = HIGH_STAKES_WIDEN if level == "high" else 1.0
    found: list[Trigger] = []
    for ask in asks:
        answer = answers.get(ask.key)
        if answer is None or (ask.mode == "P" and level != "high"):
            continue
        dist = distribution(ask, answer)
        if isinstance(ask.question, Choice):
            ranked = sorted(dist.values(), reverse=True)
            top, second = ranked[0], ranked[1] if len(ranked) > 1 else 0.0
            if top < CHOICE_TOP_BELOW * widen:
                found.append(Trigger(ask.key, "choice.confidence", top))
            elif top - second < CHOICE_MARGIN_BELOW * widen:
                found.append(Trigger(ask.key, "choice.margin", top - second))
        elif isinstance(ask.question, Score):
            top_mass = _score_straddles([dist[o] for o in ask.options], widen)
            if top_mass is not None:
                found.append(Trigger(ask.key, "score.straddle", top_mass))
        elif abs(dist["yes"] - NOUL_THRESHOLD) < NOUL_BAND * widen:
            found.append(Trigger(ask.key, "noul.threshold", dist["yes"]))
    return found


def sampled(root_seed: int, person_id: str, decision_seq: int, kind: str) -> bool:
    """The shadow's uniform sample: a fact about the decision, not about when
    it was taken (CORE-0009), and a path the decision's own draws never use."""

    rng = derive_rng(root_seed, "tier1.sample", person_id, decision_seq, kind)
    return rng.random() < SHADOW_SAMPLE


@dataclass(frozen=True, slots=True)
class Room:
    """What is left of today's allowance: for any second opinion, and for one
    that acts. They are counted apart so that shadow's rows, which depend on
    how fast the network was, can never change which live answers the world
    gets."""

    any: int
    acting: int


def room(conn: Connection[DictRow], now: int) -> Room:
    """How many more decisions may be escalated today.

    Five percent of yesterday's decisions, less what today has already used,
    counted from committed rows, so a tick sees the same room on a retry as on
    its first attempt. The caller subtracts what the tick itself has used.
    """

    day = now - now % DAY
    row = conn.execute(
        "SELECT (SELECT count(*) FROM decisions WHERE sim_time >= %s "
        "AND sim_time < %s) AS yesterday, (SELECT count(*) FROM escalations "
        "WHERE sim_time >= %s AND sim_time < %s AND NOT triggers @> %s) AS used, "
        "(SELECT count(*) FROM escalations WHERE applied AND sim_time >= %s "
        "AND sim_time < %s AND NOT triggers @> %s) AS used_live",
        (day - DAY, day, day, day + DAY, ROUTED_ROW, day, day + DAY, ROUTED_ROW),
    ).fetchone()
    assert row is not None
    allowance = max(DAILY_FLOOR, math.ceil(DAILY_SHARE * int(row["yesterday"])))
    return Room(
        any=max(0, allowance - int(row["used"])),
        acting=max(0, allowance - int(row["used_live"])),
    )


# -- the request ---------------------------------------------------------------

SYSTEM = (
    "You are deciding for one person in a simulation of a small town's "
    "businesses. You are given their situation and one or more questions. For "
    "each question, give a probability for every option: how likely this person "
    "is to choose it, or how likely it is to be the right answer, judging only "
    "by what you are told. A question's probabilities sum to one. Answer in the "
    "JSON shape required, and nothing else."
)


def _question_for(ask: Ask) -> dict[str, object]:
    question = ask.question
    if isinstance(question, Noul):
        criteria = question.criteria
        return {
            "question": question.instructions,
            "options": {
                "yes": criteria.true_ if criteria else "Yes",
                "no": criteria.false_ if criteria else "No",
            },
        }
    if isinstance(question, Choice):
        return {"question": question.instructions, "options": dict(question.criteria)}
    return {
        "question": question.instructions,
        "options": {str(i): level for i, level in enumerate(question.criteria)},
    }


def request_for(prepared: Prepared, keys: Sequence[str], model: str) -> ChatRequest:
    """The state and questions Jev saw, as a chat whose strict schema mirrors
    Jev's answer shape: a probability for every declared option."""

    asks = [ask for ask in prepared.asks if ask.key in keys]
    body = {
        "situation": prepared.state,
        "questions": {ask.key: _question_for(ask) for ask in asks},
    }
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=SYSTEM),
            ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
        ],
        max_tokens=MAX_TOKENS,
        seed=SEED,
        temperature=0.0,
        provider=PROVIDERS,
        response_schema={
            "type": "object",
            "properties": {
                ask.key: {
                    "type": "object",
                    "properties": {o: {"type": "number"} for o in ask.options},
                    "required": list(ask.options),
                    "additionalProperties": False,
                }
                for ask in asks
            },
            "required": [ask.key for ask in asks],
            "additionalProperties": False,
        },
    )


def request_key(request: ChatRequest) -> str:
    """Keyed by everything that was sent, model included (DECIDE-0004)."""

    return content_hash({"kind": KIND, **request.model_dump(mode="json")})


def _json_in(text: str) -> object:
    """The answer object in a reply: the whole reply when it is JSON, else the
    last JSON object in it — a provider that ignores the schema writes its
    reasoning first and the answer after, and the answer is still the answer.
    A reply with no object in it is not JSON."""

    stripped = text.strip()
    if stripped.startswith("```"):
        # A model that honours the schema but fences it anyway.
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as error:
        decoder = json.JSONDecoder()
        found: object = None
        at = stripped.find("{")
        while at != -1:
            try:
                found, end = decoder.raw_decode(stripped, at)
            except json.JSONDecodeError:
                at = stripped.find("{", at + 1)
                continue
            at = stripped.find("{", end)
        if not isinstance(found, dict):
            raise error
        return found


def parse(text: str, asks: Sequence[Ask]) -> dict[str, Answer]:
    """Answers in Jev's own types, so sampling cannot tell who gave them.

    Raises ValueError on anything unusable: a reply that cannot be read is not
    an answer, and the caller moves on to the next model.
    """

    try:
        raw = _json_in(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"tier-1 reply is not JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("tier-1 reply is not an object")
    answers: dict[str, Answer] = {}
    for ask in asks:
        values = raw.get(ask.key)
        if not isinstance(values, dict):
            raise ValueError(f"no answer for {ask.key}")
        try:
            weights = [max(0.0, float(values.get(o, 0.0))) for o in ask.options]
        except (TypeError, ValueError) as error:
            raise ValueError(f"{ask.key}: not a number: {error}") from error
        total = sum(weights)
        if not math.isfinite(total) or total <= 0:
            raise ValueError(f"no probability mass for {ask.key}")
        probs = {o: w / total for o, w in zip(ask.options, weights, strict=True)}
        answers[ask.key] = _answer(ask, probs)
    return answers


def _answer(ask: Ask, probs: dict[str, float]) -> Answer:
    best = max(ask.options, key=lambda o: probs[o])
    if isinstance(ask.question, Noul):
        return NoulAnswer(noul=probs["yes"])
    if isinstance(ask.question, Choice):
        return ChoiceAnswer(choice=best, probabilities=probs)
    return ScoreAnswer(score=float(best), probabilities=probs)


def applied(
    ask: Ask,
    jev: Answer,
    llm: Answer,
    *,
    routed: bool = False,
    average: Answer | None = None,
) -> Answer:
    """What the world acts on when a set is live: the LLM's judgement, or an
    even mixture for a propensity (design/005, "what the second opinion does").

    A routed set's judgement is the LLM's whole: that is what it was routed to
    make. Its propensities are the LLM's answer for the average person in the
    situation, moved to this person by Jev (DECIDE-0008). Moved as well, the
    judgement of whether someone had had their say fell below one half more
    often: settled conversations 0.84 -> 0.72, a third of a round longer (six
    14-day worlds)."""

    if routed:
        if ask.mode == "J" or average is None:
            return llm
        return transplant(ask, llm, jev, average)
    if ask.mode == "J":
        return llm
    a, b = distribution(ask, jev), distribution(ask, llm)
    return _answer(ask, {o: (a[o] + b[o]) / 2 for o in ask.options})


FLOOR = 0.01
"""Added to both of Jev's answers before one is divided by the other, so an
option Jev all but rules out for the average person cannot blow up."""


def transplant(ask: Ask, situation: Answer, person: Answer, average: Answer) -> Answer:
    """DECIDE-0008: the LLM's answer for an average person in this situation,
    moved by as much as Jev moves when the average person becomes this one.

    Jev keeps people distinct and the LLM follows a conversation; each is
    asked only for what it does well, and the product is still a
    distribution over the declared options."""

    s = distribution(ask, situation)
    p, a = distribution(ask, person), distribution(ask, average)
    weights = {o: s[o] * (p[o] + FLOOR) / (a[o] + FLOOR) for o in ask.options}
    total = sum(weights.values())
    if total <= 0.0:
        return person
    return _answer(ask, {o: w / total for o, w in weights.items()})


def agrees(
    asks: Sequence[Ask], jev: Mapping[str, Answer], llm: Mapping[str, Answer]
) -> bool:
    """Do both tiers put their most mass on the same option, for every
    escalated question?"""

    for ask in asks:
        if ask.key in llm and ask.key in jev:
            a, b = distribution(ask, jev[ask.key]), distribution(ask, llm[ask.key])
            if max(a, key=lambda o: a[o]) != max(b, key=lambda o: b[o]):
                return False
    return True


def distributions(
    asks: Sequence[Ask], answers: Mapping[str, Answer]
) -> dict[str, dict[str, float]]:
    kept: dict[str, dict[str, float]] = {}
    for ask in asks:
        if ask.key in answers:
            dist = distribution(ask, answers[ask.key])
            kept[ask.key] = {option: round(p, 6) for option, p in dist.items()}
    return kept
