"""The run loop (SIM-0001).

There is one. The golden fixture, the tests and the daemon all advance the
world through `advance`, so "it worked in the fixture" and "it works in the
daemon" are the same statement rather than two hopes.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.config import find_repo_root, load_settings
from jeve.core.clock import SimTime
from jeve.decide import escalation
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.policy import Policy, RulesPolicy
from jeve.decide.recorder import Recorder
from jeve.world.engine import Engine, TickReport, skip_to_next_open

CASSETTE = find_repo_root() / "py" / "fixtures" / "cassettes" / "golden.jsonl"

type PolicyName = Literal["rules", "jev"]
type CallMode = Literal["record", "replay"]


@dataclass(slots=True)
class Totals:
    ticks: int = 0
    decisions: int = 0
    events: Counter[str] = field(default_factory=Counter)


def policy_from_env() -> tuple[PolicyName, CallMode]:
    """`JEVE_POLICY` and `JEVE_CALLS`, defaulting to the free, keyless pair."""

    policy = os.environ.get("JEVE_POLICY", "jev")
    calls = os.environ.get("JEVE_CALLS", "replay")
    if policy not in ("rules", "jev"):
        raise ValueError(f"JEVE_POLICY must be rules or jev, not {policy!r}")
    if calls not in ("record", "replay"):
        raise ValueError(f"JEVE_CALLS must be record or replay, not {calls!r}")
    return policy, calls  # type: ignore[return-value]


def build_policy(
    name: PolicyName,
    calls: CallMode,
    *,
    root_seed: int,
    cassette: Path | None = CASSETTE,
) -> Policy:
    if name == "rules":
        return RulesPolicy(root_seed)
    recorder = Recorder(mode=calls, cassette=cassette if calls == "record" else None)
    settings = load_settings()
    tier1 = escalation.Config(
        mode=settings.escalation,
        live=frozenset(settings.escalation_live),
        route=frozenset(settings.escalation_route),
    )
    return JevPolicy(root_seed, recorder, settings=settings, tier1=tier1)


def advance(
    conn: Connection[DictRow],
    engine: Engine,
    *,
    until: int,
    on_tick: Callable[[TickReport], None] | None = None,
) -> Totals:
    """Tick until sim time reaches `until`, skipping hours when nothing is open."""

    totals = Totals()
    while True:
        row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
        assert row is not None
        now = SimTime(int(row["sim_time"]))
        if now.seconds >= until:
            return totals
        if not now.anything_open:
            if skip_to_next_open(conn) >= until:
                return totals
            continue
        report = engine.tick()
        totals.ticks += 1
        totals.decisions += report.decisions
        totals.events.update(report.events)
        if on_tick is not None:
            on_tick(report)
