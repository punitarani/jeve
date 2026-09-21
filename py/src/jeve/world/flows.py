"""The second wave of flows: credits, payroll, the close, catering (WORLD-0004).

Each follows the same shape as the first six. The referee is code: what is
possible, what it costs and how the ledger moves are rules. A policy decides
only the judgement in the middle — and hard constraints (is there enough cash?)
never reach it.

Each exists to carry a cascade somewhere new:

- **Credits** take the chain that starts with a conversation in the cafe all
  the way to money: encounter -> escalation -> outage ends -> credit issued ->
  the customer's next invoice is smaller.
- **Payroll** makes an outage in one firm's software a late payday in another's:
  no TimeTrack, no timesheets, no wages until it is back.
- **The close** makes that same outage delay an accountant's sign-off, and her
  fee, at a third firm whose invoices were stuck behind it.
- **Catering** puts someone from the cafe inside another firm's office, which is
  the only way those people meet anywhere but over a counter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jeve.core.clock import DAY, TICK, SimTime, next_office_open
from jeve.decide.policy import DecisionContext
from jeve.world import scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, TickReport

# Weekly wage by role, in cents. A rule, like every price in this world.
WEEKLY_WAGE_CENTS: dict[str, int] = {
    "founder": 2_400_00, "eng_lead": 2_200_00, "engineer": 1_900_00,
    "sre": 2_000_00, "support_lead": 1_500_00, "support": 1_200_00,
    "account_manager": 1_500_00, "partner": 3_000_00,
    "senior_associate": 2_300_00, "junior_associate": 1_500_00,
    "paralegal": 1_100_00, "office_manager": 1_200_00, "principal": 2_400_00,
    "senior_accountant": 1_800_00, "staff_accountant": 1_300_00,
    "payroll": 1_200_00, "client_admin": 1_100_00, "owner": 900_00,
    "shift_lead": 800_00, "barista": 600_00, "baker": 700_00, "weekend": 300_00,
}  # fmt: skip

# What a credit is worth, as a share of the month's fee for the broken module.
CREDIT_SHARE: dict[str, float] = {"none": 0.0, "partial": 0.25, "full_month": 1.0}


def _person(engine: Engine, role: str, org: str) -> dict[str, Any] | None:
    row = engine.conn.execute(
        "SELECT id, traits FROM persons WHERE org_id = %s AND role = %s "
        "ORDER BY id LIMIT 1",
        (org, role),
    ).fetchone()
    return dict(row) if row else None


# -- flow 7: service credits after an outage ---------------------------------


def credits(
    engine: Engine,
    report: TickReport,
    *,
    module_id: str,
    incident_id: int,
    ended_seq: int,
    minutes: int,
    escalated: bool,
) -> None:
    """Tallybird's account manager decides what each affected firm is owed."""

    manager = _person(engine, "account_manager", "tallybird")
    if manager is None:
        return
    incident = engine.conn.execute(
        "SELECT started_sim, ended_sim FROM incidents WHERE id = %s", (incident_id,)
    ).fetchone()
    if incident is None:
        return
    firms = engine.conn.execute(
        "SELECT org_id, monthly_cents FROM subscriptions "
        "WHERE module_id = %s AND org_id IS NOT NULL AND active ORDER BY org_id",
        (module_id,),
    ).fetchall()

    contexts: list[DecisionContext] = []
    for firm in firms:
        blocked = engine.conn.execute(
            "SELECT count(*) AS n FROM events WHERE kind = 'invoice.blocked' "
            "AND org_id = %s AND sim_time BETWEEN %s AND %s",
            (firm["org_id"], incident["started_sim"], incident["ended_sim"]),
        ).fetchone()
        contexts.append(
            DecisionContext(
                person_id=str(manager["id"]),
                role="account_manager",
                sim_time=report.sim_time,
                kind="credit.decision",
                facts={
                    "customer": str(firm["org_id"]),
                    "module": module_id,
                    "minutes": minutes,
                    "escalated": escalated,
                    "blocked_billing": bool(blocked and int(blocked["n"]) > 0),
                },
                traits=dict(manager["traits"] or {}),
            )
        )

    for firm, made in zip(firms, engine.decide_many(report, contexts), strict=True):
        level = str(made.chosen.get("credit", "none"))
        share = CREDIT_SHARE.get(level, 0.0)
        if share <= 0.0:
            continue
        # A credit is applied against what the firm still owes for the service.
        # Money is never conjured: no unpaid invoice, nothing to credit against.
        invoice = engine.conn.execute(
            "SELECT id, amount_cents FROM invoices WHERE from_org_id = 'tallybird' "
            "AND to_org_id = %s AND kind = 'subscription' AND paid_sim IS NULL "
            "ORDER BY due_sim, id LIMIT 1",
            (firm["org_id"],),
        ).fetchone()
        if invoice is None:
            continue
        owed = int(invoice["amount_cents"])
        amount = min(int(int(firm["monthly_cents"]) * share), owed)
        if amount <= 0:
            continue
        settles = amount == owed
        seq = engine.emit(
            report,
            "credit.issued",
            actor_id=str(manager["id"]),
            org_id=str(firm["org_id"]),
            causes=[ended_seq],
            decision_id=made.id,
            payload={
                "to_org_id": str(firm["org_id"]),
                "module_id": module_id,
                "incident_id": incident_id,
                "invoice_id": int(invoice["id"]),
                "level": level,
                "amount_cents": amount,
                "settles_invoice": settles,
                "decided_by": made.source,
            },
        )
        # A credit note: the reverse of the entry that booked the invoice.
        engine.post(
            report.sim_time,
            f"tallybird credits {firm['org_id']} for the {module_id} outage",
            [("tallybird.receivable", -amount), ("tallybird.revenue", amount)],
            seq,
        )
        if settles:
            # Nothing left to pay. The invoice keeps its face value as history
            # and is closed; no cash moves, because none is owed.
            engine.conn.execute(
                "UPDATE invoices SET paid_sim = %s WHERE id = %s",
                (report.sim_time, invoice["id"]),
            )
        else:
            engine.conn.execute(
                "UPDATE invoices SET amount_cents = amount_cents - %s WHERE id = %s",
                (amount, invoice["id"]),
            )


# -- flow 8: payroll ---------------------------------------------------------


@scheduler.job("payroll.run", office_hours_only=True)
def payroll(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Friday's wages. Ledgerline runs payroll for every firm in town."""

    clerk = _person(engine, "payroll", "ledgerline")
    staff = engine.conn.execute(
        "SELECT role FROM persons WHERE org_id = %s AND kind = 'staff'", (org_id,)
    ).fetchall()
    total = sum(WEEKLY_WAGE_CENTS.get(str(row["role"]), 1_000_00) for row in staff)
    if clerk is None or total <= 0:
        return

    cash = engine.cash_of(f"{org_id}.cash")
    if cash < 2 * total:
        _warn_of_insolvency(engine, report, org_id, cash=cash, weekly_wages=total)

    # Timesheets come out of TimeTrack, for the firms that use it.
    uses_timetrack = engine.conn.execute(
        "SELECT 1 FROM subscriptions WHERE org_id = %s AND module_id = 'timetrack' "
        "AND active",
        (org_id,),
    ).fetchone()
    outage = None
    if uses_timetrack is not None:
        outage = engine.conn.execute(
            "SELECT cause_event_seq FROM incidents WHERE module_id = 'timetrack' "
            "AND ended_sim IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()

    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(clerk["id"]),
            role="payroll",
            sim_time=report.sim_time,
            kind="payroll.release",
            facts={
                "employer": org_id,
                "can_afford": cash >= total,
                "cash_multiple": cash / total,
                "timesheets_available": outage is None,
                "held_before": bool(payload.get("held")),
            },
            traits=dict(clerk["traits"] or {}),
        ),
    )

    held_seq = payload.get("held")
    due = int(payload.get("due") or report.sim_time)
    if not made.chosen.get("release"):
        reason = str(made.chosen.get("reason", "held for review"))
        if not held_seq:
            # Said once. The retries that follow are the same fact, and an
            # event per retry would bury the payday it is about.
            causes: list[int] = []
            if outage is not None and outage["cause_event_seq"]:
                causes.append(int(outage["cause_event_seq"]))
            held_seq = engine.emit(
                report,
                "payroll.held",
                actor_id=str(clerk["id"]),
                org_id=org_id,
                causes=causes,
                decision_id=made.id,
                payload={
                    "org_id": org_id,
                    "amount_cents": total,
                    "reason": reason,
                    "decided_by": made.source,
                },
            )
        # Hours come back when the software does, so look again next tick. Cash
        # does not appear in fifteen minutes; look again tomorrow.
        retry = DAY if reason == "insufficient_cash" else TICK
        engine.schedule(
            report.sim_time + retry,
            "payroll.run",
            org_id,
            {"held": int(held_seq), "due": due},
        )
        return

    causes = [int(held_seq)] if held_seq else []
    if held_seq:
        ended = engine.conn.execute(
            "SELECT seq FROM events WHERE kind = 'incident.ended' "
            "AND payload->>'module_id' = 'timetrack' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if ended is not None:
            causes.append(int(ended["seq"]))
    seq = engine.emit(
        report,
        "payroll.paid",
        actor_id=str(clerk["id"]),
        org_id=org_id,
        causes=causes,
        decision_id=made.id,
        payload={
            "org_id": org_id,
            "amount_cents": total,
            "staff": len(staff),
            "minutes_late": max(0, report.sim_time - due) // 60,
            "decided_by": made.source,
        },
    )
    # Four legs: the firm's cost, and the households' income. Wages used to
    # leave the firm and arrive nowhere, so nothing anyone earned was ever
    # spent, and a late payday could not reach the cafe's till.
    engine.post(
        report.sim_time,
        f"{org_id} weekly payroll",
        [
            (f"{org_id}.cash", -total),
            (f"{org_id}.expense", total),
            ("households.cash", total),
            ("households.income", -total),
        ],
        seq,
    )
    engine.schedule(due + 7 * DAY, "payroll.run", org_id, {"due": due + 7 * DAY})


def _warn_of_insolvency(
    engine: Engine, report: TickReport, org_id: str, *, cash: int, weekly_wages: int
) -> None:
    """Less than two paydays in the bank: say so, and say why.

    The soak does not require a firm to survive — that would be tuning. It
    requires that a firm going under was seen going under, with the numbers
    that explain it, so that a decline is a finding and not a mystery.
    """

    owed = engine.conn.execute(
        "SELECT COALESCE(sum(amount_cents),0) AS cents, count(*) AS n FROM invoices "
        "WHERE from_org_id = %s AND paid_sim IS NULL AND written_off_sim IS NULL "
        "AND due_sim < %s",
        (org_id, report.sim_time),
    ).fetchone()
    overdue = int(owed["cents"]) if owed else 0
    month = engine.conn.execute(
        "SELECT "
        " COALESCE(sum(amount_cents) FILTER (WHERE amount_cents > 0), 0) AS money_in, "
        " COALESCE(-sum(amount_cents) FILTER (WHERE amount_cents < 0), 0) AS money_out "
        "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
        "WHERE e.account_id = %s AND t.sim_time > %s",
        (f"{org_id}.cash", report.sim_time - 28 * DAY),
    ).fetchone()
    money_in = int(month["money_in"]) if month else 0
    money_out = int(month["money_out"]) if month else 0
    shortfall = max(0, 2 * weekly_wages - cash)
    if overdue >= shortfall and overdue > 0:
        cause = "uncollected_receivables"
    elif money_out > money_in:
        cause = "spending_exceeds_income"
    else:
        cause = "thin_reserves"
    engine.emit(
        report,
        "insolvency.warning",
        org_id=org_id,
        payload={
            "org_id": org_id,
            "cash_cents": cash,
            "weekly_wages_cents": weekly_wages,
            "overdue_receivables_cents": overdue,
            "overdue_invoices": int(owed["n"]) if owed else 0,
            "cash_in_28d_cents": money_in,
            "cash_out_28d_cents": money_out,
            "cause": cause,
        },
    )


# -- flow 9: the monthly close -----------------------------------------------

CLOSE_FEE_CENTS: dict[str, int] = {
    "halloran": 1_200_00,
    "tallybird": 900_00,
    "thirdrail": 450_00,
}
CLOSE_ATTEMPTS = 5


@scheduler.job("close.run", office_hours_only=True)
def close_books(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Ledgerline closes a client's month — if the month can be stated yet.

    A firm whose month-end invoices are stuck behind an outage has no revenue
    figure to close on. So an outage at the software vendor delays the
    accountant's sign-off at a third firm, and the accountant's own fee with it.
    """

    role = "senior_accountant" if org_id != "thirdrail" else "staff_accountant"
    accountant = _person(engine, role, "ledgerline")
    if accountant is None:
        return
    # Stuck means: a month-end run was blocked and nothing has gone out since.
    # Read from the event log rather than the scheduler's queue, because the
    # scheduler has already taken this tick's due rows off the queue by the
    # time any of them is handled.
    blocked = engine.conn.execute(
        "SELECT max(seq) AS seq FROM events WHERE kind = 'invoice.blocked' "
        "AND org_id = %s",
        (org_id,),
    ).fetchone()
    blocked_seq = int(blocked["seq"]) if blocked and blocked["seq"] else None
    stuck = None
    if blocked_seq is not None:
        sent = engine.conn.execute(
            "SELECT 1 FROM events WHERE kind = 'invoice.issued' AND org_id = %s "
            "AND seq > %s AND payload->>'invoice_kind' = 'services' LIMIT 1",
            (org_id, blocked_seq),
        ).fetchone()
        stuck = blocked_seq if sent is None else None
    overdue = engine.conn.execute(
        "SELECT count(*) AS n FROM invoices WHERE to_org_id = %s "
        "AND paid_sim IS NULL AND due_sim < %s",
        (org_id, report.sim_time),
    ).fetchone()
    attempt = int(payload.get("attempt", 1))

    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(accountant["id"]),
            role=role,
            sim_time=report.sim_time,
            kind="close.signoff",
            facts={
                "client": org_id,
                "invoices_stuck": stuck is not None,
                "overdue_bills": int(overdue["n"]) if overdue else 0,
            },
            traits=dict(accountant["traits"] or {}),
        ),
    )
    ready = int(made.chosen.get("readiness", 1)) >= 1
    first_deferral = payload.get("deferred")

    if not ready and attempt < CLOSE_ATTEMPTS:
        causes = [int(first_deferral)] if first_deferral else []
        if stuck is not None:
            causes.append(stuck)
        seq = engine.emit(
            report,
            "close.deferred",
            actor_id=str(accountant["id"]),
            org_id=org_id,
            causes=causes,
            decision_id=made.id,
            payload={
                "client": org_id,
                "attempt": attempt,
                "reason": "month-end invoices have not gone out"
                if stuck is not None
                else "not ready",
                "decided_by": made.source,
            },
        )
        # Looked at again at the start of the next working day.
        engine.schedule(
            next_office_open(report.sim_time + DAY - report.sim_time % DAY),
            "close.run",
            org_id,
            {
                "attempt": attempt + 1,
                "deferred": first_deferral or seq,
                "due": payload.get("due"),
            },
        )
        return

    due = int(payload.get("due") or report.sim_time)
    causes = [int(first_deferral)] if first_deferral else []
    if first_deferral:
        issued = engine.conn.execute(
            "SELECT min(seq) AS seq FROM events WHERE kind = 'invoice.issued' "
            "AND org_id = %s AND seq > %s",
            (org_id, int(first_deferral)),
        ).fetchone()
        if issued is not None and issued["seq"]:
            causes.append(int(issued["seq"]))
    closed = engine.emit(
        report,
        "close.completed",
        actor_id=str(accountant["id"]),
        org_id=org_id,
        causes=causes,
        decision_id=made.id,
        payload={
            "client": org_id,
            "readiness": int(made.chosen.get("readiness", 1)),
            "days_late": max(0, report.sim_time - due) // DAY,
            "decided_by": made.source,
        },
    )
    # The accountant's fee goes out when the work is done, and not before.
    engine.bill(
        report,
        from_org="ledgerline",
        to_org=org_id,
        amount=CLOSE_FEE_CENTS.get(org_id, 600_00),
        terms_days=14,
        kind="services",
        causes=[closed],
    )
    # Next month's close, a month after this one was *due*: a late close does
    # not push every close after it.
    engine.schedule(due + 28 * DAY, "close.run", org_id, {"due": due + 28 * DAY})


# -- flow 10: catering -------------------------------------------------------

CATERING_CENTS: dict[str, int] = {"small": 180_00, "large": 420_00}
CATERING_BUYERS = ("office_manager", "client_admin", "founder")


@scheduler.job("catering.consider", office_hours_only=True)
def consider_catering(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Does the firm order lunch in from the cafe for tomorrow?"""

    buyer = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND role = ANY(%s) "
        "ORDER BY id LIMIT 1",
        (org_id, list(CATERING_BUYERS)),
    ).fetchone()
    if buyer is None:
        return
    cash = engine.cash_of(f"{org_id}.cash")
    mood = engine.conn.execute(
        "SELECT avg(s.mood) AS mood FROM positions s JOIN persons p "
        "ON p.id = s.person_id WHERE p.org_id = %s",
        (org_id,),
    ).fetchone()
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(buyer["id"]),
            role=str(buyer["role"]),
            sim_time=report.sim_time,
            kind="catering.order",
            facts={
                "org": org_id,
                "can_afford": cash >= 10 * CATERING_CENTS["large"],
                "team_mood": float(mood["mood"]) if mood and mood["mood"] else 2.0,
            },
            traits=dict(buyer["traits"] or {}),
        ),
    )
    # Considered twice a week, whatever was decided this time.
    engine.schedule(
        report.sim_time + (2 if SimTime(report.sim_time).weekday == 1 else 5) * DAY,
        "catering.consider",
        org_id,
        {},
    )
    size = str(made.chosen.get("order", "none"))
    if size not in CATERING_CENTS:
        return
    seq = engine.emit(
        report,
        "catering.ordered",
        actor_id=str(buyer["id"]),
        org_id=org_id,
        decision_id=made.id,
        payload={
            "org_id": org_id,
            "size": size,
            "amount_cents": CATERING_CENTS[size],
            "decided_by": made.source,
        },
    )
    tomorrow_noon = report.sim_time - report.sim_time % DAY + DAY + 12 * 3600
    engine.schedule(
        tomorrow_noon, "catering.deliver", org_id, {"ordered": seq, "size": size}
    )


@scheduler.job("catering.deliver")
def deliver_catering(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Lunch arrives — carried across the plaza by someone from the cafe.

    Which matters: it puts a cafe employee inside another firm's office, where
    they can meet people they would otherwise only ever see over a counter.
    """

    from jeve.world import space
    from jeve.world.map import ORG_ZONE

    size = str(payload.get("size", "small"))
    amount = CATERING_CENTS.get(size, CATERING_CENTS["small"])
    carrier = space.send(
        engine,
        report,
        org="thirdrail",
        to=ORG_ZONE[org_id],
        prefer=("baker", "barista", "weekend", "shift_lead"),
    )
    delivered = engine.emit(
        report,
        "catering.delivered",
        actor_id=carrier,
        org_id="thirdrail",
        causes=[int(payload["ordered"])] if payload.get("ordered") else [],
        payload={
            "to_org_id": org_id,
            "size": size,
            "amount_cents": amount,
            # None when nobody at the cafe was free: the customer collected it.
            "carried_by": carrier,
        },
    )
    engine.bill(
        report,
        from_org="thirdrail",
        to_org=org_id,
        amount=amount,
        terms_days=7,
        kind="services",
        causes=[delivered],
    )
