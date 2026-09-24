"""What an evaluation compares: arms, and the seeds they run on.

An arm is one way of running the same world. Arms differ in exactly one
thing from the arm they are compared against, so a paired difference on the
same seed is the effect of that one thing (CORE-0009 keys every draw by what it
is about, so two arms share every draw their difference does not touch).

An arm reaches the run loop only through the environment the daemon already
reads — `JEVE_ESCALATION`, `JEVE_ESCALATION_LIVE` — and the policy name. There
is no eval-only switch inside the world.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from jeve.decide import escalation

type PolicyName = Literal["rules", "jev"]

DEV_SEEDS: tuple[int, ...] = (20260920, 20260921, 20260922)
"""Where arms are developed and compared while a role is being built."""
HELD_OUT_SEEDS: tuple[int, ...] = (
    20261101,
    20261102,
    20261103,
    20261104,
    20261105,
    20261106,
)
"""Never looked at until the final run. The report's headline table is these."""


def _escalating() -> str:
    """Every set tier 1 may act on at all: medium and high stakes."""

    return ",".join(sorted(k for k, v in escalation.STAKES.items() if v != "low"))


@dataclass(frozen=True, slots=True)
class Arm:
    name: str
    policy: PolicyName
    against: str | None
    """The arm this one differs from by one thing; None for a baseline."""
    note: str
    env: Mapping[str, str] = field(default_factory=dict)


ARMS: dict[str, Arm] = {
    arm.name: arm
    for arm in (
        Arm(
            "rules",
            "rules",
            None,
            "The rules twin (null model N1): every decision by code, no model.",
        ),
        Arm(
            "jev",
            "jev",
            "rules",
            "Jev answers every question; tier 1 off, nothing routed. The world "
            "as it ran in production before DECIDE-0006.",
            {"JEVE_ESCALATION": "off", "JEVE_ESCALATION_ROUTE": "off"},
        ),
        Arm(
            "jev-tier1",
            "jev",
            "jev",
            "Jev decides, and an uncertain medium- or high-stakes answer is "
            "re-asked of a flash LLM whose answer the world acts on "
            "(DECIDE-0005 `live` for every set it allows).",
            {
                "JEVE_ESCALATION": "live",
                "JEVE_ESCALATION_LIVE": _escalating(),
                "JEVE_ESCALATION_ROUTE": "off",
            },
        ),
        Arm(
            "jev-llm-rounds",
            "jev",
            "jev",
            "Every `episode.round` question — what each person does in a "
            "conversation, whether they are done, their mood, whether they tell "
            "what they know — answered by a flash LLM in Jev's typed shape and "
            "sampled from its distribution (DECIDE-0006); everything else Jev.",
            {"JEVE_ESCALATION": "off", "JEVE_ESCALATION_ROUTE": "episode.round"},
        ),
        Arm(
            "jev-llm-done",
            "jev",
            "jev",
            "Only the `done` question of `episode.round` — has this person had "
            "their say? — answered by a flash LLM (DECIDE-0006, `set:ask`); what "
            "people do in the conversation, their mood and what they tell stay "
            "Jev's.",
            {"JEVE_ESCALATION": "off", "JEVE_ESCALATION_ROUTE": "episode.round:done"},
        ),
    )
}


def slug(name: str) -> str:
    return name.replace("-", "_")
