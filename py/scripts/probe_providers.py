"""Can each model actually be reached, not merely resolved?

A slug in the catalogue proves the model exists. It does not prove this account
may route to it: session 1 lost forty minutes to a decision model that resolved
perfectly and 404'd on every call, because the account's provider allowlist
excluded its only provider. So: one tiny real call per model, and a table.

    make providers        # writes ops/providers.md, costs well under a cent
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from jeve.config import load_settings
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
    lines += [
        "",
        f"First reachable generative model: `{reachable[0]}`."
        if reachable
        else "**No generative model is reachable.** Dialogue stays typed-only.",
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
