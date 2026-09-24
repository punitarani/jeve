"""Does the situation move Jev as much as the person does?

The golden field report's finding: in the "how likely is this person to..."
sets, temperament outweighed situation. How long an outage had lasted moved the
chance of filing a ticket by 0.04; a ticket's age moved confirmation by 0.007.
The review made those situations concrete (what the outage stops, the
calendar, how the person heard, how late the bill is). This measures whether
it worked, the way the report did, as main-effect ranges, but on a controlled
design instead of whatever the cache happened to hold:

    temperament  |P(yes) at the top of the trait - P(yes) at the bottom|,
                 with the situation held at its base
    each input   max - min of P(yes) over that input's levels,
                 with the person held at the middle of every trait

Each point is asked `SAMPLES` times with a throwaway reference field (TypeSafe's
method, as in `persona_probe.py`), so the noise of a point is reported beside
every range. An input whose range is inside the noise did not move Jev.

    make situation-probe          # ~155 live calls, well under a cent
    make situation-probe DRY=1    # the design and its call count, no key needed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from jeve.config import load_settings
from jeve.core.seed import derive_rng
from jeve.decide import questions
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS, Ask
from jeve.llm import DECISION_PREFERENCE, DecisionRequest, Gateway, Noul
from jeve.llm.protocol import NoulAnswer

SAMPLES = 5
MID_MORNING = 10 * 3600

# (set, the trait it reads, the base situation, each input and its levels)
DESIGN: tuple[tuple[str, str, dict[str, object], dict[str, list[object]]], ...] = (
    (
        "file.ticket",
        "vocality",
        {"module_down": True, "already_open": False, "module": "invoicing"},
        {
            "hours_down": [1, 6, 30],
            "module": ["invoicing", "timetrack", "pos"],
            "month_end": [False, True],
            "heard_hops": [0, 1, 3],
        },
    ),
    (
        "ticket.confirm",
        "diligence",
        {"module_down": False, "days_since_answer": 1},
        {"days_since_answer": [1, 3, 6]},
    ),
    (
        "chase.invoice",
        "vocality",
        {"org": "halloran", "days_late": 9, "large": False},
        {"days_late": [3, 9, 20, 40], "large": [False, True]},
    ),
    (
        "ticket.answer",
        "diligence",
        {"backlog": 5},
        {"backlog": [1, 5, 12, 30]},
    ),
)


@dataclass(frozen=True, slots=True)
class Point:
    kind: str
    label: str
    state: dict[str, object]
    ask: Ask


def _traits(kind: str, trait: str, level: str) -> dict[str, object]:
    """Every trait at its middle, and the one under test where asked."""

    middle = {
        name: (low + high) / 2 for name, (low, high) in questions._TRAIT_RANGE.items()
    }
    low, high = questions._TRAIT_RANGE[trait]
    middle[trait] = {"low": low, "mid": (low + high) / 2, "high": high}[level]
    return dict(middle)


def _point(
    kind: str, trait: str, facts: dict[str, object], level: str, label: str
) -> Point | None:
    prepared = QUESTION_SETS[kind].prepare(
        DecisionContext(
            person_id="probe",
            role="probe",
            decision_seq=0,
            sim_time=MID_MORNING,
            kind=kind,
            facts=facts,
            traits=_traits(kind, trait, level),
        )
    )
    if prepared.state is None:
        return None  # settled by a gate at this level: nothing to ask
    noul = next((a for a in prepared.asks if isinstance(a.question, Noul)), None)
    if noul is None:
        return None
    return Point(kind, label, prepared.state, noul)


def design() -> dict[str, dict[str, list[Point]]]:
    """Per set, per factor ("temperament" or an input), the points to ask."""

    plan: dict[str, dict[str, list[Point]]] = {}
    for kind, trait, base, inputs in DESIGN:
        factors: dict[str, list[Point]] = {}
        factors[f"temperament ({trait})"] = [
            p
            for level in ("low", "high")
            if (p := _point(kind, trait, base, level, level)) is not None
        ]
        for name, levels in inputs.items():
            points: dict[str, Point] = {}
            for value in levels:
                p = _point(kind, trait, {**base, name: value}, "mid", str(value))
                if p is not None:
                    # Two levels worded the same are one question: keep the first.
                    points.setdefault(json.dumps(p.state, sort_keys=True), p)
            if len(points) > 1:
                factors[name] = list(points.values())
        plan[kind] = factors
    return plan


async def _ask(gateway: Gateway, point: Point, nonces: list[str]) -> list[float]:
    async def one(nonce: str) -> float:
        reply = await gateway.decide(
            DecisionRequest(
                model=DECISION_PREFERENCE[0],
                state={**point.state, "reference": nonce},
                questions={point.ask.key: point.ask.question},
            ),
            purpose="gate",
        )
        answer = reply.answers[point.ask.key]
        assert isinstance(answer, NoulAnswer)
        return answer.noul

    return list(await asyncio.gather(*(one(n) for n in nonces)))


def render(
    plan: dict[str, dict[str, list[Point]]],
    measured: dict[tuple[str, str, str], list[float]],
    *,
    cost: float,
    calls: int,
) -> str:
    lines = [
        "# Situation probe",
        "",
        # Wall-clock on purpose: a record of when the measurement was taken.
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC against "
        f"`{DECISION_PREFERENCE[0]}`. {calls} live calls, ${cost:.6f}, cache "
        f"bypassed, {SAMPLES} samples a point. A range is how far P(yes) moves "
        "across a factor's levels; the noise is the mean spread of one point's "
        "samples.",
        "",
        "| set | factor | levels | range | noise | reading |",
        "|---|---|---|---:|---:|---|",
    ]
    for kind, factors in plan.items():
        spans: dict[str, float] = {}
        for factor, points in factors.items():
            means = [
                statistics.fmean(measured[(kind, factor, p.label)]) for p in points
            ]
            noise = statistics.fmean(
                statistics.pstdev(measured[(kind, factor, p.label)]) for p in points
            )
            span = max(means) - min(means) if means else 0.0
            spans[factor] = span
            reading = "moves it" if span > 3 * max(noise, 0.005) else "inside the noise"
            levels = ", ".join(
                f"{p.label} {m:.2f}" for p, m in zip(points, means, strict=True)
            )
            lines.append(
                f"| {kind} | {factor} | {levels} | {span:.3f} | {noise:.3f} "
                f"| {reading} |"
            )
        temperament = next(v for k, v in spans.items() if k.startswith("temperament"))
        situation = max(v for k, v in spans.items() if not k.startswith("temperament"))
        verdict = (
            "situation outweighs temperament"
            if situation > temperament
            else "temperament still outweighs situation"
        )
        lines.append(f"| {kind} | **verdict** | | | | {verdict} |")
    return "\n".join(lines) + "\n"


async def run() -> int:
    plan = design()
    rng = derive_rng(20260920, "situation-probe")
    measured: dict[tuple[str, str, str], list[float]] = {}
    async with Gateway(settings=load_settings()) as gateway:
        before = gateway.guard.state().spend
        for kind, factors in plan.items():
            for factor, points in factors.items():
                for point in points:
                    nonces = [f"ref-{rng.randrange(16**6):06x}" for _ in range(SAMPLES)]
                    measured[(kind, factor, point.label)] = await _ask(
                        gateway, point, nonces
                    )
                print(f"  {kind:<15} {factor}")
        after = gateway.guard.state().spend
    text = render(
        plan,
        measured,
        cost=after.settled_usd - before.settled_usd,
        calls=after.calls - before.calls,
    )
    out = load_settings().ops_dir / "situation-probe.md"
    out.write_text(text)
    print(text)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make situation-probe", description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        plan = design()
        points = sum(len(ps) for factors in plan.values() for ps in factors.values())
        for kind, factors in plan.items():
            for factor, ps in factors.items():
                print(f"{kind:<15} {factor:<24} {len(ps)} point(s)")
        print(f"{points} points x {SAMPLES} samples = {points * SAMPLES} live calls")
        return 0
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
