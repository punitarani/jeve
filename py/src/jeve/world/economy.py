"""The economy has consequences (WORLD-0010).

The golden-20260920 field report ran production for 232 sim-days and found an
economy with no consequences in it. Tallybird paid $14.6k a week in wages
against about $5.7k a month of revenue, held its payroll for 28 of 33 weeks,
warned of insolvency every week — and nothing read the warning. Its founder
ordered $420 of catering. Households took in $759k of wages and spent $10.6k,
because the only thing a household could buy was coffee. Three of four firms
only accumulated: nobody paid rent, a supplier or tax.

This module is what was missing, in three layers, each a rule unless it is a
judgement:

* **Sinks.** Every firm pays rent; the cafe buys its stock; profitable firms
  pay tax each quarter; households spend most of what they earn on the rest of
  their lives, from an account of their own per firm (a Tallybird engineer's
  unpaid week no longer comes out of Halloran's wages).
* **People.** Staff who have gone two paydays without wages consider leaving
  (`leave.consider`, asked at the event, not on a timer); a firm with a vacancy
  considers filling it (`hire.decision`).
* **The firm.** Each firm's head reviews its position once a month and whenever
  it warns of insolvency (`founder.review`): raise prices, cut costs, chase
  debts, borrow, or carry on. A firm four paydays behind has failed, and that
  is absorbing.

What a firm decided lives in `orgs.policy`, the column the first migration made
for "an org's rules are data" and nothing ever wrote (field report, defect 7).
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.core.clock import DAY, HOUR, TICK, SimTime, at
from jeve.core.orgs import BY_ID, ORGS
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport

WEEK = 7 * DAY
MONTH = 28 * DAY
"""The world's month: `month.end` has always recurred every 28 days."""

RENT_MONTHLY_CENTS: dict[str, int] = {
    "tallybird": 4_000_00,
    "halloran": 5_500_00,
    "ledgerline": 3_500_00,
    "thirdrail": 4_000_00,
}
"""Premises, and for the software company its hosting. A rule, like every price."""

HOUSEHOLD_SPEND_SHARE = 0.9
"""Of a week's wages, what a household spends on everything that is not the
cafe: rent, groceries, the rest of life, all outside the four firms."""

HOUSEHOLD_BUFFER_WEEKS = 3
"""Savings beyond this many weeks of wages are spent too. Without a ceiling a
household is a sink by another name."""

SUPPLIER_SHARE = 0.35
"""The cafe's stock costs about a third of what it sells."""

SUPPLIER_FLOOR_CENTS = 300_00

TAX_RATE = 0.20
"""On a quarter's profit, never on a loss."""

QUARTER = 91 * DAY

LOAN_WEEKS = 6
"""A bank lends a firm about six weeks of its running costs."""

LOAN_WEEKLY_INTEREST = 0.0025
"""About 13% a year."""

REPAY_ABOVE_WEEKS = 12
REPAY_DOWN_TO_WEEKS = 8

PRICE_RISE = 1.10
PRICE_CEILING = 1.6

FRUGAL_FOR = 28 * DAY
CHASE_HARDER_FOR = 28 * DAY
REVIEW_COOLDOWN = 7 * DAY

LEAVE_FROM_WEEKS_BEHIND = 2
"""Hysteresis (DECIDE-0001's hazard rule): one late payday is an apology, not a
reason to quit; people start to consider it from the second."""

FAILED_AFTER_WEEKS = 4
"""Four paydays missed for want of cash, and the firm has failed. Absorbing:
nothing in the world revives it."""

HEADS: dict[str, str] = {
    "tallybird": "founder",
    "halloran": "partner",
    "ledgerline": "principal",
    "thirdrail": "owner",
}
"""Who runs each firm: reviews its position, decides to hire, and never quits."""

REVIEW_CHOICES = ("raise_prices", "cut_costs", "chase_debts", "borrow", "hold_course")


AT_WORK = (
    "NOT EXISTS (SELECT 1 FROM rota r, sim_meta m WHERE r.person_id = persons.id "
    "AND r.kind = 'absent' AND r.starts_sim <= m.sim_time AND r.ends_sim > m.sim_time)"
)
"""Not off sick right now (WORLD-0011), for a query over `persons`: a job whose
holder is away is done by whoever covers it, which is how an absence reaches a
flow."""


# -- accounts -------------------------------------------------------------------


def household(org_id: str, kind: str = "cash") -> str:
    """The account of the households whose wages come from `org_id`."""

    return f"households.{org_id}.{kind}"


def household_accounts() -> list[tuple[str, str | None, str, str]]:
    """No org on them: households are not a firm, and the dashboard's per-firm
    cash must not count them."""

    out: list[tuple[str, str | None, str, str]] = []
    for org in ORGS:
        out += [
            (household(org.id), None, f"Households ({org.name}): cash", "cash"),
            (
                household(org.id, "income"),
                None,
                f"Households ({org.name}): wages received",
                "revenue",
            ),
            (
                household(org.id, "spending"),
                None,
                f"Households ({org.name}): spending",
                "expense",
            ),
        ]
    return out


def loan_account(org_id: str) -> str:
    return f"{org_id}.loan"


# -- what a firm has decided ------------------------------------------------------


def policy(engine: Engine, org_id: str) -> dict[str, Any]:
    row = engine.conn.execute(
        "SELECT policy FROM orgs WHERE id = %s", (org_id,)
    ).fetchone()
    return dict(row["policy"] or {}) if row else {}


def set_policy(engine: Engine, org_id: str, **changes: object) -> None:
    engine.conn.execute(
        "UPDATE orgs SET policy = policy || %s::jsonb WHERE id = %s",
        (json.dumps(changes), org_id),
    )


def failed(engine: Engine, org_id: str) -> bool:
    return policy(engine, org_id).get("failed_sim") is not None


def price_index(engine: Engine, org_id: str) -> float:
    return float(policy(engine, org_id).get("price_index", 1.0))


def frugal(engine: Engine, org_id: str, now: int) -> bool:
    until = policy(engine, org_id).get("frugal_until")
    return until is not None and now < int(until)


def chase_after_days(engine: Engine, org_id: str, now: int) -> int:
    """How late a bill must be before the firm rings about it: a week, or three
    days while the firm has decided to chase harder."""

    until = policy(engine, org_id).get("chase_harder_until")
    return 3 if until is not None and now < int(until) else 7


# -- running costs --------------------------------------------------------------


def weekly_fixed(engine: Engine, org_id: str) -> int:
    """Rent, stock and interest, as a week. With wages, the denominator of every
    runway (`Engine.runway_days`)."""

    rent = RENT_MONTHLY_CENTS.get(org_id, 0) * 12 // 52
    stock = 0
    if org_id == "thirdrail":
        stock = int(SUPPLIER_SHARE * _sales(engine, engine_now(engine), 7))
    loan = -engine.cash_of(loan_account(org_id)) if _has_loan(engine, org_id) else 0
    return rent + stock + int(loan * LOAN_WEEKLY_INTEREST)


def engine_now(engine: Engine) -> int:
    row = engine.conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    return int(row["sim_time"]) if row else 0


def _sales(engine: Engine, now: int, days: int) -> int:
    row = engine.conn.execute(
        "SELECT COALESCE(sum(amount_cents), 0) AS cents FROM cafe_sales "
        "WHERE sim_time >= %s AND sim_time < %s",
        (now - days * DAY, now),
    ).fetchone()
    return int(row["cents"]) if row else 0


def _has_loan(engine: Engine, org_id: str) -> bool:
    row = engine.conn.execute(
        "SELECT 1 FROM accounts WHERE id = %s", (loan_account(org_id),)
    ).fetchone()
    return row is not None


def _pay_out(
    engine: Engine,
    report: TickReport,
    *,
    org_id: str,
    amount: int,
    kind: str,
    memo: str,
    payload: dict[str, object],
    causes: list[int] | None = None,
    decision_id: int | None = None,
) -> int:
    seq = engine.emit(
        report,
        kind,
        org_id=org_id,
        causes=causes or [],
        decision_id=decision_id,
        payload={"org_id": org_id, "amount_cents": amount, **payload},
    )
    engine.post(
        report.sim_time,
        memo,
        [(f"{org_id}.cash", -amount), (f"{org_id}.expense", amount)],
        seq,
    )
    return seq


# -- the sinks ------------------------------------------------------------------


@scheduler.job("rent.run")
def rent(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """The month's rent. Not a judgement: the landlord is paid if the money is
    there, and asked again tomorrow if it is not."""

    if failed(engine, org_id):
        return
    amount = RENT_MONTHLY_CENTS.get(org_id, 0)
    due = int(payload.get("due") or report.sim_time)
    if amount <= 0:
        return
    cash = engine.cash_of(f"{org_id}.cash")
    if cash < amount:
        if not payload.get("late"):
            engine.emit(
                report,
                "rent.late",
                org_id=org_id,
                payload={"org_id": org_id, "amount_cents": amount, "cash_cents": cash},
            )
        engine.schedule(
            report.sim_time + DAY, "rent.run", org_id, {"due": due, "late": True}
        )
        return
    _pay_out(
        engine,
        report,
        org_id=org_id,
        amount=amount,
        kind="rent.paid",
        memo=f"{org_id} rent",
        payload={"days_late": max(0, report.sim_time - due) // DAY},
    )
    engine.schedule(due + MONTH, "rent.run", org_id, {"due": due + MONTH})


@scheduler.job("tax.quarter", office_hours_only=True)
def tax(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """A fifth of the quarter's profit, if there was one."""

    due = int(payload.get("due") or report.sim_time)
    engine.schedule(due + QUARTER, "tax.quarter", org_id, {"due": due + QUARTER})
    if failed(engine, org_id):
        return
    row = engine.conn.execute(
        "SELECT COALESCE(sum(e.amount_cents) FILTER (WHERE a.kind = 'revenue'), 0) "
        "  AS revenue, "
        "COALESCE(sum(e.amount_cents) FILTER (WHERE a.kind = 'expense'), 0) "
        "  AS expense "
        "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
        "JOIN accounts a ON a.id = e.account_id "
        "WHERE a.org_id = %s AND t.sim_time > %s AND t.sim_time <= %s",
        (org_id, due - QUARTER, report.sim_time),
    ).fetchone()
    if row is None:
        return
    profit = -int(row["revenue"]) - int(row["expense"])
    owed = int(profit * TAX_RATE)
    amount = min(owed, max(0, engine.cash_of(f"{org_id}.cash")))
    if amount <= 0:
        return
    _pay_out(
        engine,
        report,
        org_id=org_id,
        amount=amount,
        kind="tax.paid",
        memo=f"{org_id} quarterly tax",
        payload={"profit_cents": profit},
    )


@scheduler.job("households.week")
def households_week(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """What households spend outside the town each week.

    Three quarters of a week's wages, and anything saved beyond a few weeks of
    them. A household that was not paid still pays its rent, so a firm that
    holds its payroll empties its staff's accounts, and they stop buying coffee:
    that is the whole channel from a firm's cash to another firm's till.
    """

    engine.schedule(report.sim_time + WEEK, "households.week", None, {})
    for org in ORGS:
        account = household(org.id)
        balance = engine.cash_of(account)
        if balance <= 0:
            continue
        wages = engine.weekly_wages(org.id)
        spend = min(balance, int(HOUSEHOLD_SPEND_SHARE * wages))
        spend += max(0, balance - spend - HOUSEHOLD_BUFFER_WEEKS * wages)
        if spend <= 0:
            continue
        seq = engine.emit(
            report,
            "households.spent",
            payload={"org_id": org.id, "amount_cents": spend},
        )
        engine.post(
            report.sim_time,
            f"households of {org.id} spend",
            [(account, -spend), (household(org.id, "spending"), spend)],
            seq,
        )


ORDER_FACTORS: dict[str, float] = {"usual": 1.0, "more": 1.25, "less": 0.8}
SHORT_OF_STOCK = 0.25
"""Share of customers who find nothing they want when the cafe could not pay
for its stock."""
ORDERED_LIGHT = 0.1
"""The same, when the owner chose to order light."""


@scheduler.job("supplier.order")
def supplier_order(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """The cafe's weekly stock, about a third of what it sold last week.

    How much is the owner's call (WORLD-0011): the usual, more, or less, from
    how last week compared with the one before — and with the card reader down
    the till's records are not there to compare. Paid on the spot; a cafe that
    cannot pay for all of it buys what it can and runs short, which the till
    feels as customers finding nothing they want.
    """

    engine.schedule(report.sim_time + WEEK, "supplier.order", org_id, {})
    if failed(engine, org_id):
        return
    last = _sales(engine, report.sim_time, 7)
    before = _sales(engine, report.sim_time - WEEK, 7)
    choice = "usual"
    made = None
    head = head_of(engine, org_id)
    if head is not None:
        pos = engine.conn.execute(
            "SELECT status FROM modules WHERE id = 'pos'"
        ).fetchone()
        made = engine.decide(
            report,
            DecisionContext(
                person_id=str(head["id"]),
                role=str(head["role"]),
                sim_time=report.sim_time,
                kind="supplier.order",
                facts={
                    "trend": last / before if before else 1.0,
                    "pos_down": pos is not None and pos["status"] == "down",
                    "runway_days": engine.runway_days(org_id),
                },
                traits=dict(head["traits"] or {}),
            ),
        )
        choice = str(made.chosen.get("order", "usual"))
    wanted = max(SUPPLIER_FLOOR_CENTS, int(SUPPLIER_SHARE * last))
    wanted = int(wanted * ORDER_FACTORS.get(choice, 1.0))
    rules = policy(engine, org_id)
    if report.sim_time < int(rules.get("supplier_markup_until", 0)):
        wanted = int(wanted * float(rules.get("supplier_markup", 1.0)))
    if frugal(engine, org_id, report.sim_time):
        wanted = int(wanted * 0.9)
    cash = engine.cash_of(f"{org_id}.cash")
    amount = min(wanted, max(0, cash))
    short = amount < wanted
    share = SHORT_OF_STOCK if short else ORDERED_LIGHT if choice == "less" else 0.0
    set_policy(
        engine,
        org_id,
        stock_short_until=report.sim_time + WEEK if share else 0,
        stock_short_share=share,
    )
    if amount <= 0:
        engine.emit(
            report,
            "supplier.unpaid",
            org_id=org_id,
            payload={"org_id": org_id, "wanted_cents": wanted, "cash_cents": cash},
        )
        return
    _pay_out(
        engine,
        report,
        org_id=org_id,
        amount=amount,
        kind="supplier.paid",
        memo=f"{org_id} weekly stock",
        payload={"wanted_cents": wanted, "short": short, "order": choice},
        decision_id=made.id if made is not None else None,
    )


@scheduler.job("loans.week")
def loans_week(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """Interest on what is borrowed, and repayment once the firm is flush."""

    engine.schedule(report.sim_time + WEEK, "loans.week", None, {})
    for org in ORGS:
        if not _has_loan(engine, org.id):
            continue
        owed = -engine.cash_of(loan_account(org.id))
        if owed <= 0:
            continue
        interest = max(1, math.ceil(owed * LOAN_WEEKLY_INTEREST))
        cash = engine.cash_of(f"{org.id}.cash")
        seq = engine.emit(
            report,
            "loan.interest",
            org_id=org.id,
            payload={"org_id": org.id, "amount_cents": interest, "owed_cents": owed},
        )
        # Interest the firm cannot pay is added to what it owes.
        source = f"{org.id}.cash" if cash >= interest else loan_account(org.id)
        engine.post(
            report.sim_time,
            f"{org.id} loan interest",
            [(source, -interest), (f"{org.id}.expense", interest)],
            seq,
        )
        cash = engine.cash_of(f"{org.id}.cash")
        weekly = engine.weekly_outgoings(org.id)
        owed = -engine.cash_of(loan_account(org.id))
        if cash > REPAY_ABOVE_WEEKS * weekly and owed > 0:
            repay = min(owed, cash - REPAY_DOWN_TO_WEEKS * weekly)
            if repay > 0:
                paid = engine.emit(
                    report,
                    "loan.repaid",
                    org_id=org.id,
                    payload={
                        "org_id": org.id,
                        "amount_cents": repay,
                        "owed_cents": owed - repay,
                    },
                )
                engine.post(
                    report.sim_time,
                    f"{org.id} repays its loan",
                    [(f"{org.id}.cash", -repay), (loan_account(org.id), repay)],
                    paid,
                )


def borrow(engine: Engine, report: TickReport, org_id: str, cause: int) -> bool:
    """A bank loan of about six weeks' running costs, once at a time."""

    if _has_loan(engine, org_id) and engine.cash_of(loan_account(org_id)) < 0:
        return False
    amount = LOAN_WEEKS * engine.weekly_outgoings(org_id)
    if amount <= 0:
        return False
    engine.conn.execute(
        "INSERT INTO accounts (id, org_id, name, kind) VALUES (%s, %s, %s, 'payable') "
        "ON CONFLICT (id) DO NOTHING",
        (loan_account(org_id), org_id, f"{BY_ID[org_id].name}: bank loan"),
    )
    seq = engine.emit(
        report,
        "loan.taken",
        org_id=org_id,
        causes=[cause],
        payload={"org_id": org_id, "amount_cents": amount},
    )
    engine.post(
        report.sim_time,
        f"{org_id} borrows from the bank",
        [(f"{org_id}.cash", amount), (loan_account(org_id), -amount)],
        seq,
    )
    return True


# -- the firm reviews its position (founder.review) --------------------------------


def head_of(engine: Engine, org_id: str) -> DictRow | None:
    return engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND role = %s AND status <> 'left' ORDER BY id LIMIT 1",
        (org_id, HEADS[org_id]),
    ).fetchone()
    # Whoever runs the firm runs it from their sickbed too: nobody else can
    # decide to borrow.


def request_review(engine: Engine, report: TickReport, org_id: str, cause: int) -> None:
    """A warning is a reason for the head of the firm to look again — soon, and
    not more than once a week. The warning that nothing read (finding 2)."""

    last = policy(engine, org_id).get("reviewed_sim")
    if last is not None and report.sim_time - int(last) < REVIEW_COOLDOWN:
        return
    pending = engine.conn.execute(
        "SELECT 1 FROM scheduled WHERE kind = 'founder.review' AND subject_id = %s "
        "AND due_sim_time <= %s LIMIT 1",
        (org_id, report.sim_time + REVIEW_COOLDOWN),
    ).fetchone()
    if pending is not None:
        return
    engine.schedule(
        report.sim_time + TICK,
        "founder.review",
        org_id,
        {"cause": cause, "ad_hoc": True},
    )


def _trend(engine: Engine, org_id: str, now: int) -> tuple[int, int]:
    row = engine.conn.execute(
        "SELECT "
        " COALESCE(sum(amount_cents) FILTER (WHERE amount_cents > 0), 0) AS money_in, "
        " COALESCE(-sum(amount_cents) FILTER (WHERE amount_cents < 0), 0) AS money_out "
        "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
        "WHERE e.account_id = %s AND t.sim_time > %s",
        (f"{org_id}.cash", now - MONTH),
    ).fetchone()
    return (int(row["money_in"]), int(row["money_out"])) if row else (0, 0)


def _overdue_to(engine: Engine, org_id: str, now: int) -> int:
    row = engine.conn.execute(
        "SELECT COALESCE(sum(amount_cents), 0) AS cents FROM invoices "
        "WHERE from_org_id = %s AND paid_sim IS NULL AND written_off_sim IS NULL "
        "AND due_sim < %s",
        (org_id, now),
    ).fetchone()
    return int(row["cents"]) if row else 0


@scheduler.job("founder.review", office_hours_only=True)
def review(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """The head of the firm looks at the money and decides what to do about it."""

    if not payload.get("ad_hoc"):
        engine.schedule(report.sim_time + MONTH, "founder.review", org_id, {})
    if failed(engine, org_id):
        return
    head = head_of(engine, org_id)
    if head is None:
        return
    now = report.sim_time
    cash = engine.cash_of(f"{org_id}.cash")
    money_in, money_out = _trend(engine, org_id, now)
    held = engine.payroll_held(org_id)
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(head["id"]),
            role=str(head["role"]),
            sim_time=now,
            kind="founder.review",
            facts={
                "org": org_id,
                "runway_days": engine.runway_days(org_id, cash),
                "money_in": money_in,
                "money_out": money_out,
                "overdue_to_them": _overdue_to(engine, org_id, now),
                "weekly_outgoings": engine.weekly_outgoings(org_id),
                "payroll_held": held,
                "raised_recently": _raised_recently(engine, org_id, now),
                "has_loan": _has_loan(engine, org_id)
                and engine.cash_of(loan_account(org_id)) < 0,
                "prompted": bool(payload.get("ad_hoc")),
            },
            traits=dict(head["traits"] or {}),
        ),
    )
    choice = str(made.chosen.get("choice", "hold_course"))
    set_policy(engine, org_id, reviewed_sim=now)
    causes = [int(payload["cause"])] if payload.get("cause") else []
    seq = engine.emit(
        report,
        "firm.reviewed",
        actor_id=str(head["id"]),
        org_id=org_id,
        causes=causes,
        decision_id=made.id,
        payload={
            "org_id": org_id,
            "choice": choice,
            "cash_cents": cash,
            "decided_by": made.source,
        },
    )
    apply_review(engine, report, org_id, choice, seq)


def _raised_recently(engine: Engine, org_id: str, now: int) -> bool:
    raised = policy(engine, org_id).get("raised_sim")
    return raised is not None and now - int(raised) < 3 * MONTH


def apply_review(
    engine: Engine, report: TickReport, org_id: str, choice: str, cause: int
) -> None:
    """What each answer does. Rules: the head chose a course; what it costs and
    what it changes are written here."""

    now = report.sim_time
    if choice == "raise_prices":
        raise_prices(engine, report, org_id, cause)
    elif choice == "cut_costs":
        set_policy(engine, org_id, frugal_until=now + FRUGAL_FOR)
    elif choice == "chase_debts":
        set_policy(engine, org_id, chase_harder_until=now + CHASE_HARDER_FOR)
    elif choice == "borrow":
        borrow(engine, report, org_id, cause)


def raise_prices(engine: Engine, report: TickReport, org_id: str, cause: int) -> None:
    """A tenth on everything the firm sells, to a ceiling. The seeded rumour
    that Tallybird "is planning to put its prices up" can now come true, and
    the news of it travels like any other fact (MEM-0002)."""

    index = price_index(engine, org_id)
    if index * PRICE_RISE > PRICE_CEILING:
        return
    new = round(index * PRICE_RISE, 4)
    set_policy(engine, org_id, price_index=new, raised_sim=report.sim_time)
    if org_id == "tallybird":
        engine.conn.execute(
            "UPDATE subscriptions SET monthly_cents = "
            "round(monthly_cents * %s)::bigint WHERE active",
            (PRICE_RISE,),
        )
    seq = engine.emit(
        report,
        "prices.raised",
        org_id=org_id,
        causes=[cause],
        payload={"org_id": org_id, "price_index": new},
    )
    fact = memory.Fact.price_rise(org_id)
    memory.record_fact(engine.conn, fact, sim_time=report.sim_time, seq=seq)
    # Everyone who works there knows, and every customer has had the letter.
    for row in engine.conn.execute(
        "SELECT id FROM persons WHERE org_id = %s AND status <> 'left' ORDER BY id",
        (org_id,),
    ).fetchall():
        memory.learn(
            engine.conn, str(row["id"]), fact.id, sim_time=report.sim_time, seq=seq
        )
    if org_id == "tallybird":
        for row in engine.conn.execute(
            "SELECT DISTINCT p.id FROM subscriptions s JOIN persons p "
            "ON p.org_id = s.org_id AND p.kind = 'staff' AND p.status <> 'left' "
            "WHERE s.active AND s.org_id IS NOT NULL ORDER BY p.id"
        ).fetchall():
            memory.learn(
                engine.conn, str(row["id"]), fact.id, sim_time=report.sim_time, seq=seq
            )


# -- people: leaving, and being replaced ---------------------------------------------


def missed_payday(
    engine: Engine,
    report: TickReport,
    org_id: str,
    *,
    weeks_behind: int,
    held_seq: int,
) -> None:
    """Another payday has gone by unpaid. The event is the decision point.

    From the second, everyone who works there (bar whoever runs the place)
    decides whether to leave; at the fourth, the firm has failed. Asked once per
    missed payday, never per tick or per day: a propensity re-asked on a timer
    is the rare-event inflation the scenario warns of (DECIDE-0001).
    """

    engine.emit(
        report,
        "payroll.missed",
        org_id=org_id,
        causes=[held_seq],
        payload={"org_id": org_id, "weeks_behind": weeks_behind},
    )
    if weeks_behind >= FAILED_AFTER_WEEKS:
        fail(engine, report, org_id, cause=held_seq, weeks_behind=weeks_behind)
        return
    if weeks_behind < LEAVE_FROM_WEEKS_BEHIND:
        return
    staff = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND status <> 'left' AND role <> %s ORDER BY id",
        (org_id, HEADS[org_id]),
    ).fetchall()
    contexts = [
        DecisionContext(
            person_id=str(person["id"]),
            role=str(person["role"]),
            sim_time=report.sim_time,
            kind="leave.consider",
            facts={"org": org_id, "weeks_behind": weeks_behind},
            traits=dict(person["traits"] or {}),
        )
        for person in staff
    ]
    for person, made in zip(staff, engine.decide_many(report, contexts), strict=True):
        if made.chosen.get("leave"):
            leave(
                engine,
                report,
                str(person["id"]),
                org_id,
                reason="unpaid",
                cause=held_seq,
                decision_id=made.id,
                decided_by=made.source,
            )


NOTICE = 14 * DAY
"""Two weeks' notice: somebody who decides to go works it out."""
PAY_LATE_LOOKBACK = 56 * DAY
QUITS_MONTHLY: dict[str, float] = {"thirdrail": 0.040}
"""The month's chance that somebody with nothing pushing them resigns anyway —
a better offer, a step up, a move (WORLD-0014). BLS JOLTS quits, seasonally
adjusted, March-July 2026: accommodation and food services 3.5-4.2% a month;
professional and business services 1.8-2.2%, the rest of the street."""
QUITS_MONTHLY_DEFAULT = 0.020
UNPUSHED_REASONS: tuple[tuple[str, float], ...] = (
    ("better_offer", 37.0),
    ("advancement", 33.0),
    ("flexibility", 24.0),
    ("moving_on", 22.0),
)
"""Why the content leave, weighted as Pew Research Center's February 2022
survey of people who quit in 2021 named each a major reason: low pay 37%, no
advancement 33%, inflexible hours 24%, relocating 22%."""


def careers(engine: Engine, report: TickReport) -> None:
    """Once a month, everyone but the head of each firm may move on
    (WORLD-0014). Before, the only ways to leave were unpaid wages and a firm
    failing, so a healthy town had no turnover at all; real small businesses
    lose 2-4% of their staff a month to quits (BLS JOLTS).

    Somebody with something pushing them — wages late, a colleague they have
    fallen out with, a desk that is swamped, a firm in trouble, a bad month —
    is asked (`career.review`) how much likelier than an ordinary month they
    are to go, and faces their industry's quit rate times that. Somebody with
    nothing pushing them is not asked and faces the rate as it is. Asked for
    the chance outright, Jev put a contented employee's resignation at about
    0.10 a month (three 60-day worlds), five times the rate at which people
    actually quit: a month's base rate is data, the situation's effect on it
    a judgement."""

    from jeve.world.space import SWAMPED_AT  # space -> shocks -> economy

    backlog = engine.conn.execute(
        "SELECT count(*) AS n FROM tickets WHERE status IN ('open','triaged')"
    ).fetchone()
    swamped = bool(backlog and int(backlog["n"]) > SWAMPED_AT)
    staff = engine.conn.execute(
        "SELECT p.id, p.org_id, p.role, p.traits, COALESCE(s.mood, 2) AS mood "
        "FROM persons p LEFT JOIN positions s ON s.person_id = p.id "
        "WHERE p.kind = 'staff' AND p.status <> 'left' AND NOT EXISTS ("
        "  SELECT 1 FROM scheduled q WHERE q.kind = 'staff.leaves' "
        "  AND q.subject_id = p.id) ORDER BY p.id"
    ).fetchall()
    since = report.sim_time - PAY_LATE_LOOKBACK
    # What is true of a firm is asked once per firm, not once per person in it.
    troubles = {
        str(r["org_id"]): (int(r["pay_late"]), int(r["struggling"]))
        for r in engine.conn.execute(
            "SELECT org_id, count(*) FILTER (WHERE kind IN ('payroll.held', "
            "'payroll.missed')) AS pay_late, count(*) FILTER (WHERE kind = "
            "'insolvency.warning') AS struggling FROM events WHERE kind IN "
            "('payroll.held', 'payroll.missed', 'insolvency.warning') "
            "AND sim_time >= %s GROUP BY org_id",
            (since,),
        ).fetchall()
        if r["org_id"] is not None
    }
    contexts: list[DecisionContext] = []
    asked: list[DictRow] = []
    for person in staff:
        org = str(person["org_id"])
        if person["role"] == HEADS.get(org) or failed(engine, org):
            continue
        colleagues = [
            memory.Tie(int(r["met"]), int(r["warmth"]))
            for r in engine.conn.execute(
                "SELECT t.met, t.warmth FROM ties t JOIN persons o ON o.id = "
                "CASE WHEN t.a = %s THEN t.b ELSE t.a END "
                "WHERE (t.a = %s OR t.b = %s) AND o.org_id = %s "
                "AND o.status <> 'left'",
                (person["id"], person["id"], person["id"], org),
            ).fetchall()
        ]
        pay_late, struggling = troubles.get(org, (0, 0))
        facts: dict[str, object] = {
            "org": org,
            "mood": int(person["mood"]),
            "friends_at_work": sum(tie.friend for tie in colleagues),
            "fallen_out_at_work": sum(tie.fallen_out for tie in colleagues),
            "pay_late": pay_late > 0,
            "firm_struggling": struggling > 0,
            "swamped": org == "tallybird" and swamped,
        }
        pushed = (
            facts["pay_late"]
            or facts["firm_struggling"]
            or facts["swamped"]
            or int(facts["fallen_out_at_work"]) > 0  # type: ignore[call-overload]
            or int(person["mood"]) == 0
        )
        if not pushed:
            rng = _month_rng(engine, report, str(person["id"]))
            if rng.random() < QUITS_MONTHLY.get(org, QUITS_MONTHLY_DEFAULT):
                point, total = rng.random() * sum(w for _, w in UNPUSHED_REASONS), 0.0
                reason = UNPUSHED_REASONS[-1][0]
                for name, weight in UNPUSHED_REASONS:
                    total += weight
                    if point < total:
                        reason = name
                        break
                _give_notice(engine, report, person, reason, facts, made=None)
            continue
        asked.append(person)
        contexts.append(
            DecisionContext(
                person_id=str(person["id"]),
                role=str(person["role"]),
                sim_time=report.sim_time,
                kind="career.review",
                facts=facts,
                traits=dict(person["traits"] or {}),
            )
        )
    for person, ctx, made in zip(
        asked, contexts, engine.decide_many(report, contexts), strict=True
    ):
        # The industry's rate, times how much likelier than an ordinary month
        # Jev judges this person to go; the same draw a content person gets.
        base = QUITS_MONTHLY.get(str(person["org_id"]), QUITS_MONTHLY_DEFAULT)
        risk = float(made.chosen.get("relative_risk", 1.0))
        if _month_rng(engine, report, str(person["id"])).random() < base * risk:
            reason = str(made.chosen.get("reason") or "other")
            _give_notice(engine, report, person, reason, ctx.facts, made=made)


def _month_rng(engine: Engine, report: TickReport, person_id: str) -> Any:
    """One draw per person per month (CORE-0009), content or pushed alike."""

    return derive_rng(
        engine.root_seed, "career.lapse", person_id, report.sim_time // MONTH
    )


def _give_notice(
    engine: Engine,
    report: TickReport,
    person: DictRow,
    reason: str,
    facts: dict[str, object],
    *,
    made: Made | None,
) -> None:
    """Somebody resigns: said now, worked for two weeks, then gone. A notice
    no decision made (the month's hazard) says so, with what was true of them
    all the same."""

    decided_by = made.source if made is not None else "rules"
    seq = engine.emit(
        report,
        "staff.notice",
        actor_id=str(person["id"]),
        org_id=str(person["org_id"]),
        decision_id=made.id if made is not None else None,
        payload={
            "person_id": str(person["id"]),
            "role": str(person["role"]),
            "reason": reason,
            "pushed": made is not None,
            "mood": facts.get("mood"),
            "pay_late": facts.get("pay_late"),
            "fallen_out_at_work": facts.get("fallen_out_at_work"),
            "leaves_sim": report.sim_time + NOTICE,
            "decided_by": decided_by,
        },
    )
    engine.schedule(
        report.sim_time + NOTICE,
        "staff.leaves",
        str(person["id"]),
        {
            "org": str(person["org_id"]),
            "reason": reason,
            "cause": seq,
            "decision_id": made.id if made is not None else None,
            "decided_by": decided_by,
        },
    )


@scheduler.job("staff.leaves")
def _job_staff_leaves(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """The notice is worked; they go."""

    row = engine.conn.execute(
        "SELECT status FROM persons WHERE id = %s", (subject,)
    ).fetchone()
    if row is None or row["status"] == "left":
        return
    leave(
        engine,
        report,
        subject,
        str(payload.get("org", "")),
        reason=str(payload.get("reason", "other")),
        cause=int(payload["cause"]) if payload.get("cause") else None,
        decision_id=int(payload["decision_id"]) if payload.get("decision_id") else None,
        decided_by=str(payload.get("decided_by", "rules")),
    )


def leave(
    engine: Engine,
    report: TickReport,
    person_id: str,
    org_id: str,
    *,
    reason: str,
    cause: int | None,
    decision_id: int | None = None,
    decided_by: str = "rules",
) -> None:
    """Somebody stops working here. Their desk empties; the wage bill falls."""

    engine.conn.execute(
        "UPDATE persons SET status = 'left' WHERE id = %s", (person_id,)
    )
    engine.conn.execute(
        "UPDATE positions SET zone = 'home', x = NULL, y = NULL, path = '[]'::jsonb "
        "WHERE person_id = %s",
        (person_id,),
    )
    role = engine.conn.execute(
        "SELECT role FROM persons WHERE id = %s", (person_id,)
    ).fetchone()
    engine.emit(
        report,
        "staff.left",
        actor_id=person_id,
        org_id=org_id,
        causes=[cause] if cause else [],
        decision_id=decision_id,
        payload={
            "person_id": person_id,
            "org_id": org_id,
            "role": str(role["role"]) if role else None,
            "reason": reason,
            "decided_by": decided_by,
        },
    )


def fail(
    engine: Engine,
    report: TickReport,
    org_id: str,
    *,
    cause: int,
    weeks_behind: int,
) -> None:
    """The firm has failed. Absorbing: it bills nobody, pays nobody, employs
    nobody, and what it owed is written off by whoever it owed.

    When the firm is the software company, its customers move to another
    vendor: their subscriptions end and the product's outages stop reaching
    them. The rest of the town goes on.
    """

    cash = engine.cash_of(f"{org_id}.cash")
    set_policy(engine, org_id, failed_sim=report.sim_time)
    seq = engine.emit(
        report,
        "firm.failed",
        org_id=org_id,
        causes=[cause],
        payload={
            "org_id": org_id,
            "weeks_behind": weeks_behind,
            "cash_cents": cash,
        },
    )
    for row in engine.conn.execute(
        "SELECT id FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND status <> 'left' ORDER BY id",
        (org_id,),
    ).fetchall():
        leave(engine, report, str(row["id"]), org_id, reason="firm_failed", cause=seq)
    engine.conn.execute(
        "DELETE FROM scheduled WHERE subject_id = %s AND kind = ANY(%s)",
        (
            org_id,
            [
                "payroll.run",
                "close.run",
                "catering.consider",
                "founder.review",
                "hiring.review",
                "rent.run",
                "tax.quarter",
                "supplier.order",
                "invoice.run",
            ],
        ),
    )
    engine.conn.execute(
        "UPDATE subscriptions SET active = false WHERE org_id = %s", (org_id,)
    )
    if org_id == "tallybird":
        engine.conn.execute("UPDATE subscriptions SET active = false")
    # Bills owed *to* the failed firm by other firms stand; bills it owed are
    # written off by whoever it owed, now rather than in sixty days.
    for bill in engine.conn.execute(
        "SELECT id, amount_cents, due_sim, from_org_id, to_org_id, to_person_id, "
        "issued_seq FROM invoices WHERE to_org_id = %s AND paid_sim IS NULL "
        "AND written_off_sim IS NULL ORDER BY id",
        (org_id,),
    ).fetchall():
        engine.write_off(report, bill)


def _joined(alias: str) -> str:
    """The number a staff id ends in: the order people joined (`hire`)."""

    return f"substring({alias}.id from '[0-9]+$')::int"


@scheduler.job("hiring.review", office_hours_only=True)
def hiring(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """Once a week, a firm with an empty desk decides whether to fill it."""

    engine.schedule(report.sim_time + WEEK, "hiring.review", org_id, {})
    if failed(engine, org_id):
        return
    # A desk is empty when someone in the role left and nobody has been hired
    # into it since. "Since" is the number `hire` gives a person, compared as a
    # number: compared as text, `account_manager.25` came before
    # `account_manager.7`, the desk never filled, and one firm hired four
    # account managers in four weeks for the one who left.
    vacancy = engine.conn.execute(
        f"SELECT p.role FROM persons p WHERE p.org_id = %s AND p.kind = 'staff' "
        f"AND p.status = 'left' AND NOT EXISTS (SELECT 1 FROM persons q "
        f"  WHERE q.org_id = p.org_id AND q.kind = 'staff' AND q.status <> 'left' "
        f"  AND q.role = p.role AND {_joined('q')} > {_joined('p')}) "
        f"ORDER BY {_joined('p')} DESC LIMIT 1",
        (org_id,),
    ).fetchone()
    if vacancy is None:
        return
    head = head_of(engine, org_id)
    if head is None:
        return
    cash = engine.cash_of(f"{org_id}.cash")
    role = str(vacancy["role"])
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(head["id"]),
            role=str(head["role"]),
            sim_time=report.sim_time,
            kind="hire.decision",
            facts={
                "org": org_id,
                "vacancy": role,
                "runway_days": engine.runway_days(org_id, cash),
                "frugal": frugal(engine, org_id, report.sim_time),
                "payroll_held": engine.payroll_held(org_id),
            },
            traits=dict(head["traits"] or {}),
        ),
    )
    if made.chosen.get("hire"):
        hire(engine, report, org_id, role, decision_id=made.id, decided_by=made.source)


_FIRST = ("Alex", "Sam", "Jordan", "Robin", "Casey", "Morgan", "Jamie", "Avery",
          "Quinn", "Rowan", "Harper", "Emerson", "Reese", "Skyler", "Dakota",
          "Hayden")  # fmt: skip
_LAST = ("Moreau", "Novak", "Okafor", "Silva", "Tanaka", "Walsh", "Ibrahim",
         "Kowal", "Lindgren", "Mensah", "Petrov", "Quispe", "Rahman", "Santos",
         "Varga", "Yilmaz")  # fmt: skip


def hire(
    engine: Engine,
    report: TickReport,
    org_id: str,
    role: str,
    *,
    decision_id: int | None,
    decided_by: str,
) -> str:
    """A new person, with traits drawn from who they are (CORE-0009), at home
    until their first shift."""

    from jeve.world.seed_world import traits_for

    row = engine.conn.execute(
        "SELECT count(*) AS n FROM persons WHERE kind = 'staff'"
    ).fetchone()
    number = int(row["n"]) if row else 0
    person_id = f"{org_id}.{role}.{number}"
    rng = derive_rng(engine.root_seed, "hire", org_id, number)
    first = _FIRST[int(rng.random() * len(_FIRST))]
    name = f"{first} {_LAST[int(rng.random() * len(_LAST))]}"
    engine.conn.execute(
        "INSERT INTO persons (id, org_id, name, role, kind, traits) "
        "VALUES (%s, %s, %s, %s, 'staff', %s)",
        (person_id, org_id, name, role, json.dumps(traits_for(rng))),
    )
    engine.conn.execute(
        "INSERT INTO positions (person_id, zone) VALUES (%s, 'home')", (person_id,)
    )
    engine.emit(
        report,
        "staff.hired",
        actor_id=person_id,
        org_id=org_id,
        decision_id=decision_id,
        payload={
            "person_id": person_id,
            "org_id": org_id,
            "role": role,
            "decided_by": decided_by,
        },
    )
    return person_id


# -- bringing a world up to date -------------------------------------------------------


def install(conn: Connection[DictRow], *, root_seed: int) -> None:
    """Give a world everything this module needs, idempotently.

    A world seeded by this code already has it and nothing happens. The world in
    production was seeded before it, and production migrates while the old
    daemon is still writing (WORLD-0007's reason for doing this at engine start
    rather than in a migration): so the new daemon brings its world up to date
    here, under the writer lock, once.
    """

    now_row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    if now_row is None:
        return
    now = int(now_row["sim_time"])
    db.executemany(
        conn,
        "INSERT INTO accounts (id, org_id, name, kind) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        household_accounts(),
    )
    _split_the_household_purse(conn)
    _schedule_missing(conn, now)
    _plan_the_next_close(conn, now)
    _price_seats(conn, root_seed=root_seed)
    # Paydays missed before now were missed under an economy with no
    # consequences; they are not counted against anyone.
    conn.execute(
        "UPDATE orgs SET policy = policy || jsonb_build_object('economy_since', "
        "%s::bigint) WHERE NOT policy ? 'economy_since'",
        (now,),
    )


def _split_the_household_purse(conn: Connection[DictRow]) -> None:
    """One purse for the whole town becomes one per firm, pro rata to wages.

    The field report's defect 11: an unpaid Tallybird engineer's coffee came out
    of Halloran's wages. The old account keeps its history and is left empty.
    """

    row = conn.execute(
        "SELECT COALESCE(sum(amount_cents), 0) AS cents FROM ledger_entries "
        "WHERE account_id = 'households.cash'"
    ).fetchone()
    balance = int(row["cents"]) if row else 0
    if balance <= 0:
        return
    from jeve.world.flows import WEEKLY_WAGE_CENTS

    weights = {
        org.id: sum(
            WEEKLY_WAGE_CENTS.get(str(r["role"]), 1_000_00)
            for r in conn.execute(
                "SELECT role FROM persons WHERE org_id = %s AND kind = 'staff' "
                "AND status <> 'left'",
                (org.id,),
            ).fetchall()
        )
        for org in ORGS
    }
    total = sum(weights.values()) or 1
    shares = {org: balance * w // total for org, w in weights.items()}
    shares[ORGS[0].id] += balance - sum(shares.values())
    txn = conn.execute(
        "INSERT INTO ledger_txns (sim_time, memo) SELECT sim_time, "
        "'households split by employer' FROM sim_meta RETURNING id"
    ).fetchone()
    assert txn is not None
    legs = [(int(txn["id"]), "households.cash", -balance)] + [
        (int(txn["id"]), household(org), cents)
        for org, cents in shares.items()
        if cents
    ]
    db.executemany(
        conn,
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
        "VALUES (%s, %s, %s)",
        legs,
    )


def recurring(now: int) -> list[tuple[int, str, str | None, dict[str, object]]]:
    """Every recurring job this module owns, first due at or after `now`."""

    day = SimTime(now).day
    monday = at(day + (7 - SimTime(now).weekday) % 7)
    month_start = at(day + 1, 10)
    # The next Tuesday or Thursday, and the next working day, from today.
    deploy_day = next(d for d in range(day, day + 8) if d % 7 in (1, 3))
    workday = next(d for d in range(day, day + 8) if d % 7 < 5)
    jobs: list[tuple[int, str, str | None, dict[str, object]]] = [
        (monday + 7 * HOUR, "households.week", None, {}),
        (monday + 7 * HOUR, "loans.week", None, {}),
        (monday + 7 * HOUR, "supplier.order", "thirdrail", {}),
        # WORLD-0011: the engineering week, the deploy train, the shock deck
        # and the law firm's timesheets.
        (monday + 7 * HOUR, "shocks.week", None, {}),
        (monday + 9 * HOUR + 30 * 60, "eng.allocate", None, {}),
        (at(deploy_day, 14), "eng.deploy", None, {}),
        (at(workday, 16, 30), "time.day", "halloran", {}),
    ]
    for org in ORGS:
        rent_due = at(day + 1, 9)
        jobs += [
            (rent_due, "rent.run", org.id, {"due": rent_due}),
            (month_start + 3 * DAY, "founder.review", org.id, {}),
            (monday + 7 * DAY + 11 * HOUR, "hiring.review", org.id, {}),
            (at(day + 90, 10), "tax.quarter", org.id, {"due": at(day + 90, 10)}),
        ]
    return jobs


def _plan_the_next_close(conn: Connection[DictRow], now: int) -> None:
    """A world seeded before `close.plan` gets one, a quarter of an hour before
    its next month-end closes. It then schedules itself a month on."""

    if conn.execute("SELECT 1 FROM scheduled WHERE kind = 'close.plan'").fetchone():
        return
    row = conn.execute(
        "SELECT min(due_sim_time) AS due FROM scheduled WHERE kind = 'close.run' "
        "AND NOT payload ? 'attempt' AND due_sim_time > %s",
        (now + 15 * 60,),
    ).fetchone()
    if row is not None and row["due"] is not None:
        conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s, 'close.plan', 'ledgerline', '{}')",
            (int(row["due"]) - 15 * 60,),
        )


def _schedule_missing(conn: Connection[DictRow], now: int) -> None:
    for due, kind, subject, payload in recurring(now):
        exists = conn.execute(
            "SELECT 1 FROM scheduled WHERE kind = %s "
            "AND subject_id IS NOT DISTINCT FROM %s LIMIT 1",
            (kind, subject),
        ).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
                "VALUES (%s, %s, %s, %s)",
                (due, kind, subject, json.dumps(payload)),
            )


SEAT_PRICE_CENTS = 49_00


def seats_for(root_seed: int, person_id: str) -> int:
    """How many seats an outside subscriber pays for: three to twenty, a fact
    about the subscriber (CORE-0009)."""

    return 3 + int(derive_rng(root_seed, "seats", person_id).random() * 18)


def _price_seats(conn: Connection[DictRow], *, root_seed: int) -> None:
    """Outside subscribers are small firms that pay per seat.

    A hundred of them at $49 a month each was about $5.7k a month against $63k
    of Tallybird wages: structurally insolvent from day zero (field report,
    finding 1). Per seat, they come to about $57k — five months of runway at the
    seeded cash, which is what the scenario asks of the software company.
    """

    row = conn.execute("SELECT policy FROM orgs WHERE id = 'tallybird'").fetchone()
    if row is None or dict(row["policy"] or {}).get("seats_priced"):
        return
    subs = conn.execute(
        "SELECT id, person_id FROM subscriptions WHERE person_id IS NOT NULL "
        "AND monthly_cents = %s ORDER BY id",
        (SEAT_PRICE_CENTS,),
    ).fetchall()
    db.executemany(
        conn,
        "UPDATE subscriptions SET monthly_cents = %s WHERE id = %s",
        [
            (SEAT_PRICE_CENTS * seats_for(root_seed, str(s["person_id"])), int(s["id"]))
            for s in subs
        ],
    )
    conn.execute(
        "UPDATE orgs SET policy = policy || '{\"seats_priced\": true}'::jsonb "
        "WHERE id = 'tallybird'"
    )
