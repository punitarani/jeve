"""Hard constraints, written once (WORLD-0005).

A gate is a fact about the world that leaves nothing to decide: the bill cannot
be afforded, the ticket is already open, the software is still down. It never
reaches a model, and it is recorded as `source="rules"` whichever policy is
running.

These used to be written twice — once in each question set's `prepare`, once in
the rules twin — agreeing by convention, and not always agreeing: the rules
twin's catering handler drew its random number *before* checking the gate, so
the two policies consumed different amounts of luck for the same non-decision.
Both policies now ask here first.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jeve.decide.policy import DecisionContext

type Settled = dict[str, object]
type Gate = Callable[[DecisionContext], Settled | None]

ASK_FROM_DAYS_BEFORE_DUE = 2
"""A payer starts thinking about a bill two days before it is due. Earlier than
that there is no question to ask: nobody pays a month early."""


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    # ruff 0.16.8's formatter rewrites this tuple to `except A, B:` — a
    # SyntaxError, and how all three of these got into the tree in the
    # first place. The skip is what keeps the package importable.
    except (TypeError, ValueError):  # fmt: skip
        return default


def _file_ticket(ctx: DecisionContext) -> Settled | None:
    if not ctx.facts.get("module_down") or ctx.facts.get("already_open"):
        # Nothing is broken, or they already have a ticket open: not a choice.
        return {"file": False}
    return None


def _payment_timing(ctx: DecisionContext) -> Settled | None:
    if ctx.facts.get("disputed"):
        # Queried and not yet answered: nobody pays a bill they are arguing
        # about (WORLD-0011).
        return {"pay": False, "reason": "disputed"}
    if not ctx.facts.get("can_afford", True):
        return {"pay": False, "reason": "insufficient_cash"}
    days_until_due = _number(ctx.facts.get("days_until_due"))
    if days_until_due > ASK_FROM_DAYS_BEFORE_DUE:
        return {"pay": False, "reason": "not_due"}
    if ctx.facts.get("autopay") and days_until_due <= 0:
        # A standing instruction pays on the day. WORLD-0005 said so and the
        # engine computed it, but nothing here read it: the four prompter
        # fifths were asked every day once due and paid 0.5 to 2.2 days late
        # (field report, golden-20260920, defect 1).
        return {"pay": True, "reason": "standing_instruction"}
    return None


def _ticket_confirm(ctx: DecisionContext) -> Settled | None:
    if ctx.facts.get("module_down"):
        # They have been told it is fixed and can see that it is not.
        return {"confirm": False, "reason": "still_down"}
    return None


def _payroll_release(ctx: DecisionContext) -> Settled | None:
    if not ctx.facts.get("can_afford", True):
        return {"release": False, "reason": "insufficient_cash"}
    return None


def _catering_order(ctx: DecisionContext) -> Settled | None:
    if not ctx.facts.get("can_afford", True) or ctx.facts.get("payroll_held"):
        return {"order": "none"}
    return None


def _cafe_purchase(ctx: DecisionContext) -> Settled | None:
    if not ctx.facts.get("can_afford", True):
        return {"buy": False, "reason": "no_money"}
    if ctx.facts.get("sold_out"):
        # The cafe could not pay for its stock this week (WORLD-0010).
        return {"buy": False, "reason": "sold_out"}
    if _number(ctx.facts.get("queue_length")) <= 0 and not ctx.facts.get("pos_down"):
        # Nobody ahead of them and the till works: someone who walked into a
        # cafe and was served at once has bought a coffee. Asking a model to
        # confirm that was the most-asked, least-informative question in the
        # world (audit B5: max-p above 0.95).
        return {"buy": True, "reason": "no_line"}
    return None


HEAD_ROLES = frozenset({"founder", "partner", "principal", "owner"})
"""Whoever runs a firm does not quit it (WORLD-0010): the firm fails instead."""


def _leave_consider(ctx: DecisionContext) -> Settled | None:
    if ctx.role in HEAD_ROLES:
        return {"leave": False, "reason": "runs_the_firm"}
    return None


def _hire_decision(ctx: DecisionContext) -> Settled | None:
    if ctx.facts.get("frugal") or ctx.facts.get("payroll_held"):
        # A firm that cannot pay the people it has, or has decided to cut
        # costs, does not take on another.
        return {"hire": False}
    if _number(ctx.facts.get("runway_days"), 60.0) < 21:
        return {"hire": False}
    return None


def _time_log(ctx: DecisionContext) -> Settled | None:
    if ctx.facts.get("timetrack_down") and not ctx.facts.get("on_paper"):
        # The software the hours go into is down, and nobody kept a note.
        return {"log": False, "reason": "timetrack_down"}
    return None


GATES: dict[str, Gate] = {
    "file.ticket": _file_ticket,
    "payment.timing": _payment_timing,
    "ticket.confirm": _ticket_confirm,
    "payroll.release": _payroll_release,
    "catering.order": _catering_order,
    "cafe.purchase": _cafe_purchase,
    "leave.consider": _leave_consider,
    "hire.decision": _hire_decision,
    "time.log": _time_log,
}


def settle(ctx: DecisionContext) -> Settled | None:
    """What the world has already decided, or None if there is a real choice."""

    gate = GATES.get(ctx.kind)
    return gate(ctx) if gate is not None else None
