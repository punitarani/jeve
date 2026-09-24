"""Can each model actually be reached, not merely resolved?

A slug in the catalogue proves the model exists. It does not prove this account
may route to it: session 1 lost forty minutes to a decision model that resolved
perfectly and 404'd on every call, because the account's provider allowlist
excluded its only provider. So: one tiny real call per model, and a table.

    make providers        # writes ops/providers.md, costs well under a cent

Each generative model is probed twice: once for plain prose, and once with a
tier-1 request (DECIDE-0005), which passes only if the model honours the strict
schema well enough for `escalation.parse` to read a typed answer back. A model
that is reachable but cannot do that is skipped by tier 1 at run time anyway;
this says so before the first shadow day rather than after it.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from jeve.config import load_settings
from jeve.decide import escalation
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS
from jeve.errors import JeveError
from jeve.llm import (
    DECISION_PREFERENCE,
    GENERATIVE_PREFERENCE,
    ChatMessage,
    ChatRequest,
    DecisionRequest,
    Gateway,
    Noul,
)


@dataclass(frozen=True, slots=True)
class Probe:
    slug: str
    path: str
    ok: bool
    served_as: str
    provider: str
    latency_ms: int
    cost_usd: float
    note: str


async def _probe_chat(gateway: Gateway, slug: str) -> Probe:
    if slug not in gateway.catalog:
        return Probe(slug, "chat", False, "-", "-", 0, 0.0, "not in the catalogue")
    try:
        reply = await gateway.complete(
            ChatRequest(
                model=slug,
                messages=[ChatMessage(role="user", content="Reply with one word: ok")],
                # Several of these models reason whether asked to or not; leave
                # room for that ahead of the one word.
                max_tokens=400,
                seed=7,
            ),
            purpose="gate",
        )
    except JeveError as error:
        return Probe(slug, "chat", False, "-", "-", 0, 0.0, str(error)[:160])
    return Probe(
        slug,
        "chat",
        True,
        reply.model,
        reply.provider or "?",
        int(reply.latency_s * 1000),
        reply.usage.cost_usd,
        reply.text.strip()[:40].replace("|", "/").replace("\n", " "),
    )


# A real, high-stakes question as the world asks it: a firm deciding what to
# do about a disputed bill.
_TIER1 = QUESTION_SETS["dispute.resolution"].prepare(
    DecisionContext(
        person_id="probe",
        role="partner",
        sim_time=10 * 3600,
        kind="dispute.resolution",
        facts={"org": "halloran", "large": True, "runway_days": 40},
    )
)


async def _probe_tier1(gateway: Gateway, slug: str) -> Probe:
    if slug not in gateway.catalog:
        return Probe(slug, "tier1", False, "-", "-", 0, 0.0, "not in the catalogue")
    keys = [ask.key for ask in _TIER1.asks]
    try:
        reply = await gateway.complete(
            escalation.request_for(_TIER1, keys, slug), purpose="gate"
        )
    except JeveError as error:
        return Probe(slug, "tier1", False, "-", "-", 0, 0.0, str(error)[:160])
    try:
        answers = escalation.parse(reply.text, _TIER1.asks)
        note = "typed: " + ", ".join(
            f"{key}={getattr(answer, 'choice', '?')}" for key, answer in answers.items()
        )
        ok = True
    except ValueError as error:
        note, ok = f"unreadable: {str(error)[:120]}", False
    return Probe(
        slug,
        "tier1",
        ok,
        reply.model,
        reply.provider or "?",
        int(reply.latency_s * 1000),
        reply.usage.cost_usd,
        note,
    )


async def _probe_decision(gateway: Gateway, slug: str) -> Probe:
    try:
        reply = await gateway.decide(
            DecisionRequest(
                model=slug,
                state={"note": "The office is open and the door is unlocked."},
                questions={"open": Noul(instructions="Is the office open?")},
            ),
            purpose="gate",
        )
    except JeveError as error:
        return Probe(slug, "decisions", False, "-", "-", 0, 0.0, str(error)[:160])
    return Probe(
        slug,
        "decisions",
        True,
        reply.model,
        reply.provider or "typesafe",
        int(reply.latency_s * 1000),
        reply.usage.cost_usd,
        "noul answered",
    )


async def main() -> int:
    settings = load_settings()
    async with Gateway(settings=settings) as gateway:
        before = gateway.guard.state().spend.effective_usd
        probes = [await _probe_decision(gateway, s) for s in DECISION_PREFERENCE]
        probes += [await _probe_chat(gateway, s) for s in GENERATIVE_PREFERENCE]
        probes += [await _probe_tier1(gateway, s) for s in GENERATIVE_PREFERENCE]
        spent = gateway.guard.state().spend.effective_usd - before

    lines = [
        "# Provider reachability",
        "",
        # Wall-clock on purpose: this is a record of when the probe ran.
        f"Probed {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. One real call per "
        f"model, in preference order. Cost of this probe: ${spent:.6f}.",
        "",
        "| # | model | path | reachable | served as | provider | latency | cost "
        "| note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, probe in enumerate(probes):
        lines.append(
            f"| {index} | `{probe.slug}` | {probe.path} | "
            f"{'yes' if probe.ok else '**NO**'} | `{probe.served_as}` | "
            f"{probe.provider} | {probe.latency_ms} ms | "
            f"${probe.cost_usd:.6f} | {probe.note} |"
        )
    reachable = [p.slug for p in probes if p.ok and p.path == "chat"]
    typed = [p.slug for p in probes if p.ok and p.path == "tier1"]
    lines += [
        "",
        f"First reachable generative model: `{reachable[0]}`."
        if reachable
        else "**No generative model is reachable.** Dialogue stays typed-only.",
        "",
        f"First model tier 1 can read: `{typed[0]}`."
        if typed
        else "**No generative model returns a readable typed answer.** Tier 1 "
        "would record nothing; leave JEVE_ESCALATION off.",
        "",
    ]
    out = settings.ops_dir / "providers.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"wrote {out}")
    decisions_ok = all(p.ok for p in probes if p.path == "decisions")
    return 0 if decisions_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
