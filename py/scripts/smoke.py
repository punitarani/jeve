"""Gate 1a: prove the gateway works against the real API, for under a cent.

One Decisions request carrying all three primitives, and one chat completion.
Both must land in the ledger with a real cost. Run:

    make smoke

The two paths are reported independently: an account-level provider block on
one model must not read as a broken gateway.
"""

from __future__ import annotations

import asyncio
import sys

from jeve.errors import JeveError
from jeve.llm import (
    ChatMessage,
    ChatRequest,
    Choice,
    ChoiceAnswer,
    DecisionRequest,
    DecisionResponse,
    Gateway,
    Noul,
    NoulAnswer,
    ProviderPrefs,
    Score,
    ScoreAnswer,
)
from jeve.llm.catalog import DECISION_PREFERENCE, GENERATIVE_PREFERENCE

CEILING_USD = 0.01

STATE = {
    "ticket": {
        "from": "ops@ledgerline.example",
        "subject": "Invoicing exports failing since 14:20",
        "body": (
            "Every invoice export has failed for the last forty minutes. "
            "We have month-end billing due Thursday and cannot issue anything. "
            "Is there a workaround?"
        ),
    },
    "customer": {"org": "Ledgerline Accounting", "plan": "business", "open_tickets": 2},
}

QUESTIONS = {
    "is_urgent": Noul(
        instructions="Does `ticket.body` describe work that is blocked right now?"
    ),
    "queue": Choice(
        instructions="Which team should handle `ticket`?",
        criteria={
            "billing": "Invoices, payments, refunds, subscriptions",
            "technical": "Bugs, outages, failing integrations",
            "account": "Plans, renewals, access",
            "other": "Anything the options above do not cover",
        },
    ),
    "severity": Score(
        instructions="How severe is the problem in `ticket`?",
        criteria=[
            "Cosmetic; the customer can still work",
            "A feature is degraded but a workaround exists",
            "The customer is blocked with no workaround",
        ],
    ),
}


async def _decisions(gateway: Gateway) -> tuple[bool, str]:
    """Returns (passed, note)."""

    try:
        answer: DecisionResponse = await gateway.decide(
            DecisionRequest(
                model=DECISION_PREFERENCE[0],
                state=STATE,
                questions=QUESTIONS,
                # Jev declares no supported parameters; the gateway strips
                # require_parameters for it. Kept to exercise that path.
                provider=ProviderPrefs(sort="throughput"),
            ),
            purpose="gate",
        )
    except JeveError as error:
        return False, f"{type(error).__name__}: {error}"

    noul = answer.answers["is_urgent"]
    queue = answer.answers["queue"]
    severity = answer.answers["severity"]
    if not isinstance(noul, NoulAnswer):
        return False, f"is_urgent came back as {type(noul).__name__}"
    if not isinstance(queue, ChoiceAnswer):
        return False, f"queue came back as {type(queue).__name__}"
    if not isinstance(severity, ScoreAnswer):
        return False, f"severity came back as {type(severity).__name__}"

    print(f"     model={answer.model}  latency={answer.latency_s * 1000:.0f}ms")
    print(f"     noul   is_urgent = {noul.noul:.3f}")
    print(
        f"     choice queue     = {queue.choice}  confidence={queue.confidence}\n"
        f"                        {queue.probabilities}"
    )
    print(f"     score  severity  = {severity.score:.3f}  {severity.probabilities}")
    print(
        f"     usage  in={answer.usage.input_tokens} out={answer.usage.output_tokens} "
        f"cost=${answer.usage.cost_usd:.8f}"
        f"{' (estimated)' if answer.usage.cost_is_estimated else ''}"
    )

    # A distribution is what makes an agent samplable. Without it the design is
    # argmax-only, so this is a gate condition, not a nicety.
    if queue.probabilities is None:
        return False, "choice answer carried no probabilities; sampling is impossible"
    return True, "noul, choice and score all returned with distributions"


async def _chat(gateway: Gateway) -> tuple[bool, str]:
    try:
        chat = await gateway.complete(
            ChatRequest(
                model=GENERATIVE_PREFERENCE[0],
                messages=[
                    ChatMessage(
                        role="system", content="Reply with exactly one short sentence."
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            "Acknowledge a support ticket about failing invoice "
                            "exports. Do not promise a fix time."
                        ),
                    ),
                ],
                # Room for mandatory reasoning tokens ahead of the answer.
                max_tokens=400,
                seed=2**63 + 17,  # above the gateway's limit, masked on the wire
                provider=ProviderPrefs(sort="throughput"),
            ),
            purpose="gate",
        )
    except JeveError as error:
        return False, f"{type(error).__name__}: {error}"

    print(f"     model={chat.model}  provider={chat.provider}")
    print(f"     latency={chat.latency_s * 1000:.0f}ms")
    print(f"     text: {chat.text.strip()[:160]}")
    print(
        f"     usage  in={chat.usage.input_tokens} out={chat.usage.output_tokens} "
        f"cost=${chat.usage.cost_usd:.8f}"
        f"{' (estimated)' if chat.usage.cost_is_estimated else ''}"
    )
    return True, f"prose generated via {chat.provider}"


async def main() -> int:
    gateway = Gateway()
    try:
        print("resolving model slugs against OpenRouter ...")
        catalog = await gateway.start()
        print(f"  catalogue: {len(catalog)} models")
        for slug in DECISION_PREFERENCE + GENERATIVE_PREFERENCE:
            card = catalog.get(slug)
            print(
                f"  ok  {slug:<32} ctx={card.context_length:>8}  "
                f"in=${card.prompt_usd_per_token * 1e6:.3f}/M  "
                f"out=${card.completion_usd_per_token * 1e6:.3f}/M"
            )

        start = gateway.guard.state().spend
        print(f"\nspend before: ${start.effective_usd:.6f}")

        print("\n1/2  decisions: noul + choice + score in one request ...")
        decisions_ok, decisions_note = await _decisions(gateway)
        if not decisions_ok:
            print(f"     BLOCKED: {decisions_note}")

        print(f"\n2/2  chat completion via {GENERATIVE_PREFERENCE[0]} ...")
        chat_ok, chat_note = await _chat(gateway)
        if not chat_ok:
            print(f"     BLOCKED: {chat_note}")

        end = gateway.guard.state().spend
        spent = end.effective_usd - start.effective_usd
        print("\nledger:")
        print(f"  calls        {end.calls}  ({end.estimated_calls} estimated cost)")
        print(f"  settled      ${end.settled_usd:.6f}")
        print(f"  in flight    ${end.reserved_usd:.6f}")
        print(f"  baseline     ${end.baseline_usd:.4f} (key lifetime usage)")
        print(f"  this run     ${spent:.6f}")

        problems: list[str] = []
        if not decisions_ok:
            problems.append(f"decisions path: {decisions_note}")
        if not chat_ok:
            problems.append(f"chat path: {chat_note}")
        if end.reserved_usd > 1e-9:
            problems.append(
                f"${end.reserved_usd:.6f} left reserved; a call never settled"
            )
        if spent > CEILING_USD:
            problems.append(f"cost ${spent:.6f} over the ${CEILING_USD:.2f} gate")

        if problems:
            print("\n  FAILED")
            for problem in problems:
                print(f"    - {problem}")
            return 1

        print(f"\n  PASSED  under ${CEILING_USD:.2f}, both calls recorded")
        print(f"    decisions: {decisions_note}")
        print(f"    chat:      {chat_note}")
        return 0
    finally:
        await gateway.aclose()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
