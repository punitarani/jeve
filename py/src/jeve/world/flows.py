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

from jeve import memory
from jeve.core.clock import DAY, TICK, SimTime, next_office_open
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import economy, scheduler

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


def weekly_wages(engine: Engine, org_id: str) -> int:
    """This week's wage bill: everyone on the payroll, at their role's rate."""

    staff = engine.conn.execute(
        "SELECT role FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND status <> 'left'",
        (org_id,),
    ).fetchall()
    return sum(WEEKLY_WAGE_CENTS.get(str(row["role"]), 1_000_00) for row in staff)


def payroll_held(engine: Engine, org_id: str) -> bool:
    """Is this firm's payroll waiting on a retry right now?"""

    row = engine.conn.execute(
        "SELECT 1 FROM scheduled WHERE kind = 'payroll.run' AND subject_id = %s "
        "AND payload ? 'held' LIMIT 1",
        (org_id,),
    ).fetchone()
    return row is not None


def weekly_outgoings(engine: Engine, org_id: str) -> int:
    """What a week costs a firm to stay open: wages, and rent, stock and
    interest (WORLD-0010)."""

    return weekly_wages(engine, org_id) + economy.weekly_fixed(engine, org_id)


def _person(engine: Engine, role: str, org: str) -> dict[str, Any] | None:
    """Whoever does this job at this firm, or whoever covers it now that they
    have gone (WORLD-0010). A job with nobody in it used to stop its flow for
    ever without a word: no payroll clerk, no payroll, for the whole town."""

    roles = [role, *COVER.get(role, ())]
    row = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND kind = 'staff' "
        f"AND status <> 'left' AND role = ANY(%s) AND {economy.AT_WORK} "
        "ORDER BY array_position(%s::text[], role), id LIMIT 1",
        (org, roles, roles),
    ).fetchone()
    return dict(row) if row else None


COVER: dict[str, tuple[str, ...]] = {
    "payroll": ("client_admin", "staff_accountant", "principal"),
    "senior_accountant": ("staff_accountant", "principal"),
    "staff_accountant": ("senior_accountant", "principal"),
    "account_manager": ("support_lead", "founder"),
}
"""Who covers a job whose holder has left."""


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

    if economy.failed(engine, org_id):
        return
    # Ledgerline runs everybody's payroll; if Ledgerline cannot, the firm runs
    # its own rather than nobody being paid again.
    clerk = (
        None
        if economy.failed(engine, "ledgerline")
        else _person(engine, "payroll", "ledgerline")
    )
    if clerk is None:
        payer = engine.payer_of(org_id)
        clerk = dict(payer) if payer is not None else None
    staff = engine.conn.execute(
        "SELECT role FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND status <> 'left'",
        (org_id,),
    ).fetchall()
    total = weekly_wages(engine, org_id)
    if clerk is None or total <= 0:
        return

    cash = engine.cash_of(f"{org_id}.cash")
    if cash < 2 * total and not payload.get("held"):
        # Once per payday, not per retry. The warning used to be read by
        # nothing (field report, finding 2); now the head of the firm looks.
        warning = _warn_of_insolvency(
            engine, report, org_id, cash=cash, weekly_wages=total
        )
        economy.request_review(engine, report, org_id, warning)

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
    # The employer kept this week's hours on paper while TimeTrack was down
    # (WORLD-0011): the clerk can see them, and they must be reconciled later.
    on_paper = outage is not None and engine.by_hand(org_id, "timetrack")

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
                "on_paper": on_paper,
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
        missed = int(payload.get("missed", 0))
        if reason == "insufficient_cash" and not payload.get("held"):
            # That wages are late is news, and the staff are the first to know
            # (WORLD-0011). It travels from there.
            fact = memory.Fact.payroll_late(org_id)
            memory.record_fact(
                engine.conn, fact, sim_time=report.sim_time, seq=held_seq
            )
            memory.revive(engine.conn, fact.id)
            for person in engine.conn.execute(
                "SELECT id FROM persons WHERE org_id = %s AND kind = 'staff' "
                "AND status <> 'left' ORDER BY id",
                (org_id,),
            ).fetchall():
                memory.learn(
                    engine.conn,
                    str(person["id"]),
                    fact.id,
                    sim_time=report.sim_time,
                    seq=held_seq,
                )
        if reason == "insufficient_cash":
            # Paydays gone by unpaid, counted from this payday — or from when
            # the world came under WORLD-0010, for one that predates it.
            since = max(
                due, int(economy.policy(engine, org_id).get("economy_since", due))
            )
            behind = max(0, report.sim_time - since) // economy.WEEK + 1
            if behind > missed:
                missed = behind
                economy.missed_payday(
                    engine, report, org_id, weeks_behind=behind, held_seq=int(held_seq)
                )
                if economy.failed(engine, org_id):
                    return
        # Hours come back when the software does, so look again next tick. Cash
        # does not appear in fifteen minutes; look again tomorrow.
        retry = DAY if reason == "insufficient_cash" else TICK
        engine.schedule(
            report.sim_time + retry,
            "payroll.run",
            org_id,
            {"held": int(held_seq), "due": due, "missed": missed},
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
    # Wages are paid: late wages are no longer news, and a firm with a
    # couple of paydays in hand is no longer short.
    memory.make_stale(
        engine.conn, memory.Fact.payroll_late(org_id).id, sim_time=report.sim_time
    )
    if cash - total >= 2 * total:
        memory.make_stale(
            engine.conn, memory.Fact.insolvency(org_id).id, sim_time=report.sim_time
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
            (economy.household(org_id), total),
            (economy.household(org_id, "income"), -total),
        ],
        seq,
    )
    engine.schedule(due + 7 * DAY, "payroll.run", org_id, {"due": due + 7 * DAY})


def _warn_of_insolvency(
    engine: Engine, report: TickReport, org_id: str, *, cash: int, weekly_wages: int
) -> int:
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
    seq = engine.emit(
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
    # Whoever runs the firm, and whoever pays its bills, know it is short; the
    # news travels from them (WORLD-0011).
    fact = memory.Fact.insolvency(org_id)
    memory.record_fact(engine.conn, fact, sim_time=report.sim_time, seq=seq)
    memory.revive(engine.conn, fact.id)
    knowers = [economy.head_of(engine, org_id), engine.payer_of(org_id)]
    for person in sorted({str(k["id"]) for k in knowers if k is not None}):
        memory.learn(engine.conn, person, fact.id, sim_time=report.sim_time, seq=seq)
    return seq


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

    if economy.failed(engine, org_id) or economy.failed(engine, "ledgerline"):
        return
    role = "senior_accountant" if org_id != "thirdrail" else "staff_accountant"
    accountant = _person(engine, role, "ledgerline")
    if accountant is None:
        return
    role = str(accountant["role"])
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
                "attempt": attempt,
            },
            traits=dict(accountant["traits"] or {}),
        ),
    )
    ready = int(made.chosen.get("readiness", 1)) >= 1
    late = str(made.chosen.get("if_not_ready", "wait"))
    # Close on an estimate and fix it next month (WORLD-0011): the month is
    # closed, marked as estimated, and the true-up is billed with the next one.
    estimated = not ready and late == "estimate"
    ready = ready or estimated
    first_deferral = payload.get("deferred")
    rework_fee = int(payload.get("rework_fee", 0))

    if ready and attempt < CLOSE_ATTEMPTS and not payload.get("reconciled"):
        rework = _reconcile(engine, report, org_id, int(payload.get("due") or 0))
        if rework:
            fee, items = rework
            seq = engine.emit(
                report,
                "close.rework",
                actor_id=str(accountant["id"]),
                org_id=org_id,
                decision_id=made.id,
                payload={"client": org_id, "items": items, "fee_cents": fee},
            )
            engine.schedule(
                next_office_open(report.sim_time + DAY - report.sim_time % DAY),
                "close.run",
                org_id,
                {
                    "attempt": attempt + 1,
                    "deferred": first_deferral or seq,
                    "due": payload.get("due"),
                    "reconciled": True,
                    "rework_fee": rework_fee + fee,
                },
            )
            return

    if not ready and attempt < CLOSE_ATTEMPTS:
        if late == "nag":
            engine.emit(
                report,
                "close.nagged",
                actor_id=str(accountant["id"]),
                org_id=org_id,
                decision_id=made.id,
                payload={"client": org_id, "decided_by": made.source},
            )
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
                "reconciled": bool(payload.get("reconciled")),
                "rework_fee": rework_fee,
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
            "estimated": estimated,
            "days_late": max(0, report.sim_time - due) // DAY,
            "decided_by": made.source,
        },
    )
    # A month closed on an estimate is corrected, and paid for, next month.
    true_up = int(economy.policy(engine, org_id).get("true_up_cents", 0))
    economy.set_policy(engine, org_id, true_up_cents=TRUE_UP_CENTS if estimated else 0)
    # The accountant's fee goes out when the work is done, and not before.
    engine.bill(
        report,
        from_org="ledgerline",
        to_org=org_id,
        amount=round(
            CLOSE_FEE_CENTS.get(org_id, 600_00)
            * economy.price_index(engine, "ledgerline")
        )
        + rework_fee
        + true_up,
        terms_days=14,
        kind="services",
        causes=[closed],
    )
    # Next month's close, a month after this one was *due*: a late close does
    # not push every close after it.
    engine.schedule(due + 28 * DAY, "close.run", org_id, {"due": due + 28 * DAY})


REWORK_FEE_CENTS = 120_00
"""What Ledgerline charges to put right one thing done by hand that did not
reconcile (the scenario's "manual work later fails reconciliation")."""
TRUE_UP_CENTS = 200_00
AUDIT_FEE_CENTS = 300_00
RECONCILE_FAILS = 0.5


def _reconcile(
    engine: Engine, report: TickReport, org_id: str, due: int
) -> tuple[int, int] | None:
    """What the client did by hand this month, checked against the books.

    Invoices sent by hand and records kept on paper while a feature was down
    (`outage.workaround`) each fail to reconcile half the time, drawn about the
    item (CORE-0009); an audit notice (a shock) is extra work whatever else.
    Returns the fee and the number of items to rework, or None if nothing is.
    """

    manual = engine.conn.execute(
        "UPDATE invoices SET reconciled = false WHERE from_org_id = %s AND manual "
        "AND reconciled IS NULL RETURNING id",
        (org_id,),
    ).fetchall()
    policy = economy.policy(engine, org_id)
    paper = int(policy.get("paper_records", 0))
    audit = bool(policy.get("audit_pending"))
    economy.set_policy(engine, org_id, paper_records=0, audit_pending=False)
    items = 0
    for row in manual:
        if derive_rng(engine.root_seed, "reconcile", int(row["id"])).random() < (
            RECONCILE_FAILS
        ):
            items += 1
    for index in range(paper):
        rng = derive_rng(engine.root_seed, "reconcile", org_id, due, index)
        if rng.random() < RECONCILE_FAILS:
            items += 1
    fee = items * REWORK_FEE_CENTS + (AUDIT_FEE_CENTS if audit else 0)
    if fee <= 0:
        return None
    return fee, items + (1 if audit else 0)


# -- flow 10: catering -------------------------------------------------------

CATERING_CENTS: dict[str, int] = {"small": 180_00, "large": 420_00}
CATERING_BUYERS = ("office_manager", "client_admin", "founder")


@scheduler.job("catering.consider", office_hours_only=True)
def consider_catering(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Does the firm order lunch in from the cafe for tomorrow?"""

    if economy.failed(engine, org_id):
        return
    # Considered twice a week, whatever is decided this time.
    engine.schedule(
        report.sim_time + (2 if SimTime(report.sim_time).weekday == 1 else 5) * DAY,
        "catering.consider",
        org_id,
        {},
    )
    if economy.failed(engine, "thirdrail"):
        return
    buyer = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND role = ANY(%s) "
        "AND status <> 'left' ORDER BY id LIMIT 1",
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
                "can_afford": cash >= 10 * CATERING_CENTS["large"]
                # A firm that has decided to cut costs orders no lunch.
                and not economy.frugal(engine, org_id, report.sim_time),
                # A firm that cannot pay its staff does not buy them lunch. The
                # founder of an insolvent Tallybird ordered $420 of catering
                # (field report, finding 3): the question said funds were
                # "comfortably enough" whatever the balance.
                "payroll_held": payroll_held(engine, org_id),
                "runway_days": engine.runway_days(org_id, cash),
                "team_mood": float(mood["mood"]) if mood and mood["mood"] else 2.0,
            },
            traits=dict(buyer["traits"] or {}),
        ),
    )
    size = str(made.chosen.get("order", "none"))
    if size not in CATERING_CENTS:
        return
    take_order(
        engine,
        report,
        org_id,
        size,
        ordered_by=str(buyer["id"]),
        decision_id=made.id,
        decided_by=made.source,
    )


def take_order(
    engine: Engine,
    report: TickReport,
    org_id: str,
    size: str,
    *,
    ordered_by: str | None,
    decision_id: int | None = None,
    decided_by: str = "rules",
    cause: int | None = None,
) -> None:
    """An office orders lunch for tomorrow, and the cafe decides whether it
    can take it on (the scenario's "accept a catering order at capacity").

    Nothing was ever declined in the field report's world: the scenario calls
    that "runaway politeness", and it is what the acceptance rate measures.
    """

    amount = round(CATERING_CENTS[size] * economy.price_index(engine, "thirdrail"))
    seq = engine.emit(
        report,
        "catering.ordered",
        actor_id=ordered_by,
        org_id=org_id,
        causes=[cause] if cause else [],
        decision_id=decision_id,
        payload={
            "org_id": org_id,
            "size": size,
            "amount_cents": amount,
            "decided_by": decided_by,
        },
    )
    taker = engine.payer_of("thirdrail")
    if taker is None:
        return
    tomorrow_noon = report.sim_time - report.sim_time % DAY + DAY + 12 * 3600
    from jeve.world import shocks

    absent, _ = shocks.off(engine, tomorrow_noon)
    counter = engine.conn.execute(
        "SELECT id FROM persons WHERE org_id = 'thirdrail' AND kind = 'staff' "
        "AND status <> 'left' AND role = ANY(%s)",
        (list(shocks.COUNTER_ROLES),),
    ).fetchall()
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(taker["id"]),
            role=str(taker["role"]),
            sim_time=report.sim_time,
            kind="catering.accept",
            facts={
                "size": size,
                "short_staffed": any(str(p["id"]) in absent for p in counter),
            },
            traits=dict(taker["traits"] or {}),
        ),
    )
    if not made.chosen.get("accept"):
        engine.emit(
            report,
            "catering.declined",
            actor_id=str(taker["id"]),
            org_id="thirdrail",
            causes=[seq],
            decision_id=made.id,
            payload={"to_org_id": org_id, "size": size, "decided_by": made.source},
        )
        return
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

    if economy.failed(engine, "thirdrail"):
        return
    size = str(payload.get("size", "small"))
    amount = round(
        CATERING_CENTS.get(size, CATERING_CENTS["small"])
        * economy.price_index(engine, "thirdrail")
    )
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
