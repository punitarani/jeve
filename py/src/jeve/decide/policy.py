"""The decision seam.

Everything an agent chooses goes through a `Policy`. `RulesPolicy` is the
rule-based twin — it is also null model N1 from the validation plan, and it
costs nothing to run, which is why the world is built and tuned against it
before a model is wired in at all.

`JevPolicy` (step 3b) implements the same protocol: typed questions in, a
sampled draw out. Nothing upstream of here knows which one answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from jeve.core.seed import derive_rng, path_of

type Source = Literal["rules", "jev", "llm"]


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a policy may look at. Small on purpose: Jev's accuracy falls
    as irrelevant state grows, so a context that is cheap to render here is
    also the one that survives contact with the model."""

    person_id: str
    role: str
    decision_seq: int
    sim_time: int
    kind: str
    """The question set being asked, e.g. `ticket.triage`."""
    facts: dict[str, object] = field(default_factory=dict)
    traits: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Decision:
    """What was chosen, and enough to explain it afterwards."""

    chosen: dict[str, object]
    source: Source
    distributions: dict[str, dict[str, float]] = field(default_factory=dict)
    draws: dict[str, float] = field(default_factory=dict)
    prng_path: str = ""
    model_call: str | None = None


@runtime_checkable
class Policy(Protocol):
    def decide(self, ctx: DecisionContext) -> Decision: ...


class RulesPolicy:
    """Deterministic given the world and the seed. No model, no network.

    Its judgements are deliberately crude — the point is a world that runs and
    an honest baseline to compare a model against, not a good simulation of a
    support agent.
    """

    source: Source = "rules"

    def __init__(self, root_seed: int) -> None:
        self._root = root_seed

    def _rng(self, ctx: DecisionContext) -> tuple[object, str]:
        path = path_of("person", ctx.person_id, "decision", ctx.decision_seq, ctx.kind)
        return derive_rng(self._root, path), path

    def decide(self, ctx: DecisionContext) -> Decision:
        rng, path = self._rng(ctx)
        handler = getattr(self, f"_{ctx.kind.replace('.', '_')}", None)
        if handler is None:
            raise KeyError(f"no rule for decision kind {ctx.kind!r}")
        chosen, draws = handler(ctx, rng)
        return Decision(chosen=chosen, source=self.source, draws=draws, prng_path=path)

    # -- the six flows ----------------------------------------------------

    def _ticket_triage(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Queue and severity for a new ticket."""

        module_down = bool(ctx.facts.get("module_down"))
        mentions_billing = bool(ctx.facts.get("mentions_billing"))
        queue = "billing" if mentions_billing and not module_down else "technical"
        severity = 2.0 if module_down else 1.0
        return {"queue": queue, "severity": severity}, {}

    def _ticket_answer(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Whether to answer now or leave it for later in the queue."""

        backlog = _num(ctx.facts.get("backlog"), 0.0)
        diligence = _num(ctx.traits.get("diligence"), 0.5)
        # A crude worker: more diligent people clear more, a deep backlog
        # slows everyone.
        draw = _uniform(rng)
        probability = max(0.15, min(0.95, diligence - 0.03 * backlog))
        return {"answer_now": draw < probability}, {"answer_now": draw}

    def _payment_timing(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Pay this invoice now, or let it run late."""

        days_until_due = _num(ctx.facts.get("days_until_due"), 0.0)
        runway_days = _num(ctx.facts.get("runway_days"), 30.0)
        can_afford = bool(ctx.facts.get("can_afford", True))
        promptness = _num(ctx.traits.get("promptness"), 0.5)

        if not can_afford:
            return {"pay": False, "reason": "insufficient_cash"}, {}
        # Nobody pays early; past due, pressure rises with lateness and falls
        # with a short runway.
        if days_until_due > 0:
            return {"pay": False, "reason": "not_due"}, {}
        lateness = -days_until_due
        pressure = promptness + 0.12 * lateness - (0.3 if runway_days < 14 else 0.0)
        draw = _uniform(rng)
        pay = draw < max(0.05, min(0.98, pressure))
        return (
            {"pay": pay, "reason": "due" if pay else "deferred"},
            {"pay": draw},
        )

    def _cafe_purchase(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Buy, or walk out because the queue is too long.

        Someone who walked into a cafe came for coffee: the base rate of
        buying is high, and patience governs how fast a queue erodes it rather
        than whether they wanted anything. Treating patience as the buy
        probability instead produced a 45% walkout rate against an empty
        counter — a degenerate cafe that cannot transmit an outage, because
        nearly half the town was already leaving.
        """

        pos_down = bool(ctx.facts.get("pos_down"))
        queue_length = _num(ctx.facts.get("queue_length"), 0.0)
        patience = _num(ctx.traits.get("patience"), 0.5)

        # Cash-only service is slower per customer, so the same queue costs more.
        impatience = (1.0 - patience) * (0.20 if pos_down else 0.10)
        # A flat slice of goodwill for the inconvenience itself, queue aside.
        friction = 0.06 if pos_down else 0.0
        probability = max(0.05, min(0.99, 0.97 - impatience * queue_length - friction))

        draw = _uniform(rng)
        if draw > probability:
            return (
                {"buy": False, "reason": "queue" if queue_length else "changed_mind"},
                {"buy": draw},
            )
        amount = 350 + int(_uniform(rng) * 600)
        return {"buy": True, "amount_cents": amount}, {"buy": draw}

    def _file_ticket(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Whether a customer who has hit a problem actually reports it."""

        module_down = bool(ctx.facts.get("module_down"))
        already_open = bool(ctx.facts.get("already_open"))
        vocality = _num(ctx.traits.get("vocality"), 0.4)
        if not module_down or already_open:
            return {"file": False}, {}
        draw = _uniform(rng)
        return {"file": draw < vocality}, {"file": draw}


def _num(value: object, default: float) -> float:
    """Facts and traits come back from JSONB as `object`."""

    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _uniform(rng: object) -> float:
    # `derive_rng` returns a random.Random; the Protocol keeps the seam honest
    # without importing the banned module here.
    return float(rng.random())  # type: ignore[attr-defined]
