"""The decision seam.

Everything an agent chooses goes through a `Policy`. `RulesPolicy` is the
rule-based twin — it is also null model N1 from the validation plan, and it
costs nothing to run, which is why the world is built and tuned against it
before a model is wired in at all.

`JevPolicy` (step 3b) implements the same protocol: typed questions in, a
sampled draw out. Nothing upstream of here knows which one answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from jeve.core.seed import derive_rng, path_of
from jeve.decide import gates

type Source = Literal["rules", "jev", "llm"]


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a policy may look at. Small on purpose: Jev's accuracy falls
    as irrelevant state grows, so a context that is cheap to render here is
    also the one that survives contact with the model."""

    person_id: str
    role: str
    sim_time: int
    kind: str
    """The question set being asked, e.g. `ticket.triage`."""
    facts: dict[str, object] = field(default_factory=dict)
    traits: dict[str, object] = field(default_factory=dict)
    decision_seq: int = -1
    """This person's nth decision: the path their luck is drawn from. Numbered
    by the engine when the decision is made, never by the caller. Callers used
    to do it, each adding its own offset for repeats within a batch, and a payer
    with two bills or a person in two conversations in one tick would have
    collided on `UNIQUE (person_id, decision_seq)`."""


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

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        """Decide several *independent* contexts at once.

        Independent means no context's facts depend on another's outcome. A
        model-backed policy issues them concurrently; the results must equal
        deciding each alone, in order.
        """
        ...


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
        settled = gates.settle(ctx)
        if settled is not None:
            # Not a choice, so no luck is spent on it — in either policy.
            return Decision(chosen=settled, source=self.source, prng_path=path)
        chosen, draws = handler(ctx, rng)
        return Decision(chosen=chosen, source=self.source, draws=draws, prng_path=path)

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        return [self.decide(ctx) for ctx in contexts]

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
        promptness = _num(ctx.traits.get("promptness"), 0.5)

        # Asked once a day per bill (WORLD-0005), so this is the chance of
        # paying *today*. Few pay ahead of the date; past it, pressure rises
        # with lateness and with being chased, and falls with a short runway.
        if days_until_due > 0:
            pressure = 0.25 * promptness
        else:
            pressure = promptness + 0.12 * -days_until_due
        if ctx.facts.get("chased") or ctx.facts.get("reminded_in_person"):
            pressure += 0.2
        if runway_days < 14:
            pressure -= 0.3
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
        return {"buy": True, "reason": "bought"}, {"buy": draw}

    def _file_ticket(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Whether a customer who has hit a problem actually reports it."""

        vocality = _num(ctx.traits.get("vocality"), 0.4)
        draw = _uniform(rng)
        return {"file": draw < vocality}, {"file": draw}

    def _ticket_confirm(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Told it is fixed, do they say so today and let the ticket close?"""

        diligence = _num(ctx.traits.get("diligence"), 0.5)
        draw = _uniform(rng)
        confirm = draw < 0.35 + 0.5 * diligence
        return {"confirm": confirm, "reason": "confirmed" if confirm else "silent"}, {
            "confirm": draw
        }

    def _chase_invoice(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Pick up the phone about a bill that is a week late, or let it ride."""

        vocality = _num(ctx.traits.get("vocality"), 0.4)
        weeks = _num(ctx.facts.get("days_late"), 7.0) / 7.0
        draw = _uniform(rng)
        return {"chase": draw < min(0.95, vocality + 0.15 * weeks)}, {"chase": draw}

    def _agent_tick(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Where next, and whether to stop and talk. Null model N1 for space.

        Always takes the same five draws in the same order, whatever branch is
        taken, so a change to one rule cannot shift the luck of another.
        """

        go, talk, who, about, push = (_uniform(rng) for _ in range(5))
        here = str(ctx.facts.get("here", ""))
        own = str(ctx.facts.get("own_zone", here))
        present = ctx.facts.get("present")
        people = (
            [p for p in present if isinstance(p, dict)]
            if isinstance(present, list)
            else []
        )
        outage = bool(ctx.facts.get("outage"))
        hour = (ctx.sim_time % 86400) // 3600
        lunch = 12 <= hour < 14

        if here != own:
            next_zone = own if go < 0.5 else here
        elif ctx.facts.get("org") == "thirdrail":
            next_zone = here  # someone has to mind the counter
        else:
            cafe = 0.25 if lunch else 0.04
            next_zone = "cafe" if go < cafe else "plaza" if go < cafe + 0.04 else here

        sociability = _num(ctx.traits.get("sociability"), 0.5)
        with_id: str | None = None
        if people and talk < 0.6 * sociability:
            with_id = str(people[int(who * len(people))]["id"])
        topic = None
        if with_id is not None:
            topic = "the_outage" if outage and about < 0.6 else "small_talk"
        vocality = _num(ctx.traits.get("vocality"), 0.4)
        raised = bool(with_id and ctx.facts.get("can_raise") and push < vocality)
        return (
            {
                "next_zone": next_zone,
                "interact": with_id is not None,
                "with": with_id,
                "topic": topic,
                "mood": 1 if outage else 2,
                "raise_outage": raised,
            },
            {"go": go, "talk": talk, "who": who, "about": about, "push": push},
        )

    def _credit_decision(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """What an outage is worth to a customer. A policy table, nothing more."""

        minutes = _num(ctx.facts.get("minutes"), 0.0)
        if minutes >= 12 * 60 or ctx.facts.get("blocked_billing"):
            return {"credit": "full_month"}, {}
        if minutes >= 3 * 60 or ctx.facts.get("escalated"):
            return {"credit": "partial"}, {}
        return {"credit": "none"}, {}

    def _payroll_release(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Release the wages unless the hours behind them cannot be seen."""

        ready = bool(ctx.facts.get("timesheets_available", True))
        return {"release": ready, "reason": "released" if ready else "timesheets"}, {}

    def _close_signoff(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """A month whose invoices have not gone out has no revenue to close on."""

        if ctx.facts.get("invoices_stuck"):
            return {"readiness": 0}, {}
        return {"readiness": 1 if _num(ctx.facts.get("overdue_bills"), 0) else 2}, {}

    def _catering_order(
        self, ctx: DecisionContext, rng: object
    ) -> tuple[dict[str, object], dict[str, float]]:
        """Lunch in, sometimes; more often when the week has been hard."""

        roll = _uniform(rng)
        stressed = _num(ctx.facts.get("team_mood"), 2.0) < 1.5
        small, large = (0.45, 0.2) if stressed else (0.3, 0.1)
        order = "large" if roll < large else "small" if roll < large + small else "none"
        return {"order": order}, {"order": roll}


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
