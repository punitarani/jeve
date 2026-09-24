"""Customers who can leave, and bills that can be argued with (WORLD-0011).

Two of the scenario's behaviours had nowhere to happen. Churn bargaining (#7):
repeated incidents wear a customer's trust down, the account manager sees the
risk and offers something, and the customer stays or goes. And a
conflict-free economy (§6, "runaway politeness"): nobody in the field report's
232 days disputed a bill, declined an order or cancelled a subscription.

* **Trust in the vendor is a belief slot** (MEM-0001's "reliability"), on the
  person who holds the subscription: a level from 0 to 4 in `persons.beliefs`,
  revised by a J `score` after every outage they noticed. It is the first typed
  belief in the world, and it is what makes history matter: the distant past
  keeps influencing the present after the incident itself is gone.
* **Renewal** is a P decision at each monthly billing, asked only of a customer
  at risk — low trust, or bad news heard about the vendor — so that loyal
  customers are not given twelve chances a year to churn by accident
  (DECIDE-0001's hazard rule).
* **Retention**: before an at-risk customer worth keeping decides, the account
  manager decides whether to offer a month at a discount.
* **Disputes**: a client who receives a bill may query it; the issuer's head
  decides to stand firm, discount or write it off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jeve import memory
from jeve.core.clock import DAY, SimTime, next_office_open
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import economy, scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport

TRUST_START = 3
"""Reasonably confident: a customer who signed up believed in the product."""

AT_RISK_BELOW = 2
"""Trust at 0 or 1 puts a customer at risk; 2 and above renews without asking."""
LAPSE_MONTHLY = 0.01
"""A content customer's month: no complaint, but a business closes, a need
goes, a cheaper tool turns up (WORLD-0014). SaaS Capital 2025: about 90% of
revenue retained a year on small contracts, some 0.9% lost a month. Asking
them instead left Jev at 0.56 to renew a customer who trusts the vendor
fully: 41% of subscribers lost a month (three 60-day worlds)."""

RETENTION_DISCOUNT = 0.25
RETAIN_ABOVE_CENTS = 500_00
"""Only customers worth keeping get a call from the account manager."""

WIN_BACK_AFTER = 56 * DAY
WIN_BACK_CHANCE = 0.12

DISPUTE_WINDOW = 3 * DAY
DISPUTE_DISCOUNT = 0.15
LARGE_CENTS = 200_000
"""A large bill, as the firm that issued it sees size."""
UNEXPECTED_ABOVE = 1.5
"""A bill is larger than its payer expected when it is half as much again as
their last one from the same firm — or, for a first bill, as that firm's
median bill (WORLD-0014). It was `LARGE_CENTS`, a line two thirds of all bills
crossed, so most clients were told every bill was bigger than they expected,
and Jev queried 52-67% of those (three 60-day worlds)."""

VENDOR_BAD_NEWS = ("insolvency", "payroll_late", "churned")
"""Topics that, heard about the vendor, put a customer at risk: the scenario's
"knowing Tallybird lost data moves churn consideration at firms the incident
never touched"."""


# -- trust ------------------------------------------------------------------------


def trust(engine: Engine, person_id: str) -> int:
    row = engine.conn.execute(
        "SELECT beliefs->>'vendor_reliability' AS level FROM persons WHERE id = %s",
        (person_id,),
    ).fetchone()
    if row is None or row["level"] is None:
        return TRUST_START
    return int(row["level"])


def set_trust(engine: Engine, person_id: str, level: int) -> None:
    engine.conn.execute(
        "UPDATE persons SET beliefs = beliefs || jsonb_build_object("
        "'vendor_reliability', %s::int) WHERE id = %s",
        (max(0, min(4, level)), person_id),
    )


def heard_bad_news(engine: Engine, person_id: str) -> bool:
    """Whether this person has heard the vendor is in trouble, true or not."""

    row = engine.conn.execute(
        "SELECT 1 FROM knowledge k JOIN facts f ON f.id = k.fact_id "
        "WHERE k.person_id = %s AND f.about_org_id = 'tallybird' "
        "AND f.topic = ANY(%s) LIMIT 1",
        (person_id, list(VENDOR_BAD_NEWS)),
    ).fetchone()
    return row is not None


def heard_price_rise(engine: Engine, person_id: str, org_id: str = "tallybird") -> bool:
    row = engine.conn.execute(
        "SELECT 1 FROM knowledge WHERE person_id = %s AND fact_id = %s",
        (person_id, memory.Fact.price_rise(org_id).id),
    ).fetchone()
    return row is not None


def after_outage(
    engine: Engine,
    report: TickReport,
    *,
    incident_id: int,
    module_id: str,
    minutes: int,
    escalated: bool,
    cause: int,
) -> None:
    """Everyone who ran into this outage revises how far they trust the vendor.

    A J `score`: what a reasonable person would now conclude, given what they
    thought before and what happened — how long it lasted, whether they
    reported it and heard back, whether it was their second in a month.
    """

    rows = engine.conn.execute(
        "SELECT n.person_id, n.ticket_id, n.workaround, p.traits, "
        "  t.status AS ticket_status, "
        "  (SELECT count(*) FROM outage_notices o JOIN incidents i "
        "     ON i.id = o.incident_id WHERE o.person_id = n.person_id "
        "     AND i.started_sim > %s AND i.id <> n.incident_id) AS earlier "
        "FROM outage_notices n JOIN persons p ON p.id = n.person_id "
        "LEFT JOIN tickets t ON t.id = n.ticket_id "
        "WHERE n.incident_id = %s ORDER BY n.person_id",
        (report.sim_time - 28 * DAY, incident_id),
    ).fetchall()
    if not rows:
        return
    contexts = [
        DecisionContext(
            person_id=str(row["person_id"]),
            role="subscriber",
            sim_time=report.sim_time,
            kind="vendor.trust",
            facts={
                "trust": trust(engine, str(row["person_id"])),
                "module": module_id,
                "minutes": minutes,
                "reported": row["ticket_id"] is not None,
                "answered": row["ticket_status"] in ("answered", "closed"),
                "escalated": escalated,
                "repeat": int(row["earlier"]) > 0,
                "tried_another_tool": row["workaround"] == "other_tool",
            },
            traits=dict(row["traits"] or {}),
        )
        for row in rows
    ]
    for ctx, made in zip(contexts, engine.decide_many(report, contexts), strict=True):
        before = int(str(ctx.facts["trust"]))
        after = int(str(made.chosen.get("trust", before)))
        if after == before:
            continue
        set_trust(engine, ctx.person_id, after)
        engine.emit(
            report,
            "trust.revised",
            actor_id=ctx.person_id,
            org_id="tallybird",
            causes=[cause],
            decision_id=made.id,
            payload={
                "person_id": ctx.person_id,
                "from": before,
                "to": after,
                "incident_id": incident_id,
                "decided_by": made.source,
            },
        )


# -- renewal ----------------------------------------------------------------------


def holder_of(engine: Engine, subscription: dict[str, Any]) -> str | None:
    """Who decides whether this subscription continues: the outside subscriber,
    or whoever pays a subscribing firm's bills."""

    if subscription.get("person_id"):
        return str(subscription["person_id"])
    payer = engine.payer_of(str(subscription["org_id"]))
    return str(payer["id"]) if payer is not None else None


def renewals(engine: Engine, report: TickReport) -> dict[int, float]:
    """Before the month is billed: who is at risk, whom the account manager
    tries to keep, and who goes. Returns subscription id -> discount."""

    discounts: dict[int, float] = {}
    _recover(engine, report)
    subs = [
        dict(row)
        for row in engine.conn.execute(
            "SELECT id, org_id, person_id, module_id, monthly_cents FROM subscriptions "
            "WHERE active ORDER BY id"
        ).fetchall()
    ]
    at_risk: list[tuple[dict[str, Any], str]] = []
    for sub in subs:
        holder = holder_of(engine, sub)
        if holder is None:
            continue
        if trust(engine, holder) < AT_RISK_BELOW or heard_bad_news(engine, holder):
            at_risk.append((sub, holder))
            continue
        # Content customers are not asked, and not immortal either: a month's
        # small chance of going for reasons of their own, keyed by the
        # subscription and the month (CORE-0009).
        rng = derive_rng(
            engine.root_seed,
            "subscription.lapse",
            int(sub["id"]),
            report.sim_time // economy.MONTH,
        )
        if rng.random() < LAPSE_MONTHLY:
            cancel(engine, report, sub, holder, None)
    if not at_risk:
        return discounts

    manager = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = 'tallybird' "
        "AND kind = 'staff' AND status <> 'left' "
        "AND role = ANY(ARRAY['account_manager', 'support_lead', 'founder']) "
        "ORDER BY array_position(ARRAY['account_manager', 'support_lead', "
        "'founder'], role), id LIMIT 1"
    ).fetchone()
    offers: dict[int, Made] = {}
    worth = [
        (s, h) for s, h in at_risk if int(s["monthly_cents"]) >= RETAIN_ABOVE_CENTS
    ]
    if manager is not None and worth:
        contexts = [
            DecisionContext(
                person_id=str(manager["id"]),
                role=str(manager["role"]),
                sim_time=report.sim_time,
                kind="retention.offer",
                facts={
                    "trust": trust(engine, holder),
                    "large": int(sub["monthly_cents"]) >= 1_000_00,
                    "runway_days": engine.runway_days("tallybird"),
                    "heard_bad_news": heard_bad_news(engine, holder),
                },
                traits=dict(manager["traits"] or {}),
            )
            for sub, holder in worth
        ]
        for (sub, holder), made in zip(
            worth, engine.decide_many(report, contexts), strict=True
        ):
            if made.chosen.get("offer"):
                offers[int(sub["id"])] = made
                discounts[int(sub["id"])] = RETENTION_DISCOUNT
                set_trust(engine, holder, trust(engine, holder) + 1)
                engine.emit(
                    report,
                    "retention.offered",
                    actor_id=str(manager["id"]),
                    org_id="tallybird",
                    decision_id=made.id,
                    payload={
                        "subscription_id": int(sub["id"]),
                        "to": holder,
                        "discount": RETENTION_DISCOUNT,
                        "decided_by": made.source,
                    },
                )

    contexts = []
    for sub, holder in at_risk:
        contexts.append(
            DecisionContext(
                person_id=holder,
                role="subscriber",
                sim_time=report.sim_time,
                kind="subscription.renew",
                facts={
                    "trust": trust(engine, holder),
                    "heard_bad_news": heard_bad_news(engine, holder),
                    "price_rise": heard_price_rise(engine, holder),
                    "offered_discount": int(sub["id"]) in offers,
                    "relies_on_it": int(sub["monthly_cents"]) >= 1_000_00
                    or sub.get("org_id") is not None,
                },
                traits=_traits(engine, holder),
            )
        )
    for (sub, holder), made in zip(
        at_risk, engine.decide_many(report, contexts), strict=True
    ):
        if made.chosen.get("renew"):
            continue
        cancel(engine, report, sub, holder, made)
        discounts.pop(int(sub["id"]), None)
    return discounts


TRUST_RECOVERS_AFTER = 28 * DAY


def _recover(engine: Engine, report: TickReport) -> None:
    """A month without a bad experience earns back a level, up to where a
    customer started. Without it trust only ever falls, and every customer is
    eventually lost to outages long forgotten (MEM-0001: the distant past
    should keep influencing the present, not decide it)."""

    engine.conn.execute(
        "UPDATE persons p SET beliefs = p.beliefs || jsonb_build_object("
        "'vendor_reliability', (p.beliefs->>'vendor_reliability')::int + 1) "
        "WHERE (p.beliefs->>'vendor_reliability')::int < %s "
        "AND NOT EXISTS (SELECT 1 FROM events e WHERE e.kind = 'trust.revised' "
        "  AND e.actor_id = p.id AND e.sim_time > %s)",
        (TRUST_START, report.sim_time - TRUST_RECOVERS_AFTER),
    )


def _traits(engine: Engine, person_id: str) -> dict[str, object]:
    row = engine.conn.execute(
        "SELECT traits FROM persons WHERE id = %s", (person_id,)
    ).fetchone()
    return dict(row["traits"] or {}) if row else {}


def cancel(
    engine: Engine,
    report: TickReport,
    sub: dict[str, Any],
    holder: str,
    made: Made | None,
) -> None:
    """A subscription ends: decided by its holder, or — `made` None — lapsed
    for a reason of the holder's own (LAPSE_MONTHLY)."""

    engine.conn.execute(
        "UPDATE subscriptions SET active = false, cancelled_sim = %s WHERE id = %s",
        (report.sim_time, int(sub["id"])),
    )
    seq = engine.emit(
        report,
        "subscription.cancelled",
        actor_id=holder,
        org_id="tallybird",
        decision_id=made.id if made is not None else None,
        payload={
            "subscription_id": int(sub["id"]),
            "by": holder,
            "trust": trust(engine, holder),
            "heard_bad_news": heard_bad_news(engine, holder),
            "reason": "unhappy" if made is not None else "lapsed",
            "module_id": str(sub["module_id"]),
            "monthly_cents": int(sub["monthly_cents"]),
            "decided_by": made.source if made is not None else "rules",
        },
    )
    # That the vendor is losing customers is news, and it travels (MEM-0002):
    # the account manager and the founder know first.
    fact = memory.Fact.churned("tallybird")
    memory.record_fact(engine.conn, fact, sim_time=report.sim_time, seq=seq)
    for row in engine.conn.execute(
        "SELECT id FROM persons WHERE org_id = 'tallybird' AND kind = 'staff' "
        "AND status <> 'left' AND role = ANY(ARRAY['account_manager', 'founder']) "
        "ORDER BY id"
    ).fetchall():
        memory.learn(
            engine.conn, str(row["id"]), fact.id, sim_time=report.sim_time, seq=seq
        )


def win_back(engine: Engine, report: TickReport, month: int) -> None:
    """A customer who left two months ago may come back, if the vendor's
    customers trust it on the whole. A rule, keyed by who and which month."""

    if economy.failed(engine, "tallybird"):
        return
    row = engine.conn.execute(
        "SELECT avg(COALESCE((p.beliefs->>'vendor_reliability')::float8, %s)) AS t "
        "FROM subscriptions s JOIN persons p ON p.id = s.person_id WHERE s.active",
        (TRUST_START,),
    ).fetchone()
    reputation = float(row["t"]) if row and row["t"] is not None else TRUST_START
    if reputation < AT_RISK_BELOW:
        return
    for sub in engine.conn.execute(
        "SELECT id, person_id FROM subscriptions WHERE NOT active "
        "AND person_id IS NOT NULL AND cancelled_sim IS NOT NULL "
        "AND cancelled_sim <= %s ORDER BY id",
        (report.sim_time - WIN_BACK_AFTER,),
    ).fetchall():
        rng = derive_rng(engine.root_seed, "win_back", str(sub["person_id"]), month)
        if rng.random() >= WIN_BACK_CHANCE * reputation / 4:
            continue
        engine.conn.execute(
            "UPDATE subscriptions SET active = true, cancelled_sim = NULL "
            "WHERE id = %s",
            (int(sub["id"]),),
        )
        set_trust(engine, str(sub["person_id"]), TRUST_START - 1)
        engine.emit(
            report,
            "subscription.started",
            actor_id=str(sub["person_id"]),
            org_id="tallybird",
            payload={"subscription_id": int(sub["id"]), "returning": True},
        )


# -- disputes ----------------------------------------------------------------------


def expected_amount(engine: Engine, bill: dict[str, Any]) -> float:
    """What the payer of this bill had reason to expect it to come to: their
    last services bill from the same firm, else the firm's median one."""

    row = engine.conn.execute(
        "SELECT amount_cents FROM invoices WHERE kind = 'services' "
        "AND from_org_id = %s AND id < %s AND (to_person_id = %s OR to_org_id = %s) "
        "ORDER BY id DESC LIMIT 1",
        (bill["from_org_id"], bill["id"], bill["to_person_id"], bill["to_org_id"]),
    ).fetchone()
    if row is None:
        row = engine.conn.execute(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount_cents) "
            "AS amount_cents FROM invoices WHERE kind = 'services' "
            "AND from_org_id = %s AND id < %s",
            (bill["from_org_id"], bill["id"]),
        ).fetchone()
    if row is None or row["amount_cents"] is None:
        return float(bill["amount_cents"])  # the first bill a firm ever sent
    return float(row["amount_cents"])


def disputes(engine: Engine, report: TickReport, now: SimTime) -> None:
    """A bill just received is read, and perhaps queried, at the payer's own
    moment for their inbox (CORE-0009)."""

    bills = engine.conn.execute(
        "SELECT i.id, i.from_org_id, i.to_org_id, i.to_person_id, i.amount_cents, "
        "  i.issued_seq FROM invoices i "
        "WHERE i.kind = 'services' AND NOT i.dispute_asked AND i.paid_sim IS NULL "
        "AND i.written_off_sim IS NULL AND i.issued_sim >= %s "
        "ORDER BY i.id",
        (report.sim_time - DISPUTE_WINDOW,),
    ).fetchall()
    asked: list[dict[str, Any]] = []
    contexts: list[DecisionContext] = []
    for bill in bills:
        if bill["to_person_id"]:
            payer = str(bill["to_person_id"])
            traits = _traits(engine, payer)
        else:
            row = engine.payer_of(str(bill["to_org_id"]))
            if row is None:
                continue
            payer, traits = str(row["id"]), dict(row["traits"] or {})
        if not engine.gets_to_it(payer, now, "inbox", None):
            continue
        asked.append({**dict(bill), "payer": payer})
        contexts.append(
            DecisionContext(
                person_id=payer,
                role="client",
                sim_time=report.sim_time,
                kind="invoice.dispute",
                facts={
                    "issuer": str(bill["from_org_id"]),
                    "larger_than_expected": int(bill["amount_cents"])
                    > UNEXPECTED_ABOVE * expected_amount(engine, bill),
                    "price_rise": heard_price_rise(
                        engine, payer, str(bill["from_org_id"])
                    ),
                    "firm": bill["to_org_id"] is not None,
                },
                traits=traits,
            )
        )
    if not asked:
        return
    engine.conn.execute(
        "UPDATE invoices SET dispute_asked = true WHERE id = ANY(%s)",
        ([int(b["id"]) for b in asked],),
    )
    for bill, made in zip(asked, engine.decide_many(report, contexts), strict=True):
        if made.chosen.get("dispute"):
            dispute(engine, report, bill, made=made, reason="queried")


def dispute(
    engine: Engine,
    report: TickReport,
    bill: dict[str, Any],
    *,
    made: Made | None,
    reason: str,
) -> None:
    seq = engine.emit(
        report,
        "invoice.disputed",
        actor_id=str(bill.get("payer") or bill.get("to_person_id") or "") or None,
        org_id=str(bill["from_org_id"]),
        causes=[int(bill["issued_seq"])] if bill.get("issued_seq") else [],
        decision_id=made.id if made else None,
        payload={
            "invoice_id": int(bill["id"]),
            "reason": reason,
            "amount_cents": int(bill["amount_cents"]),
            "decided_by": made.source if made else "rules",
        },
    )
    engine.conn.execute(
        "UPDATE invoices SET disputed_sim = %s, dispute_asked = true WHERE id = %s",
        (report.sim_time, int(bill["id"])),
    )
    engine.schedule(
        next_office_open(report.sim_time + DAY - report.sim_time % DAY) + 3600,
        "dispute.resolve",
        str(bill["from_org_id"]),
        {"invoice": int(bill["id"]), "cause": seq},
    )


@scheduler.job("dispute.resolve", office_hours_only=True)
def resolve(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """The issuer's head decides what a queried bill is worth to the firm."""

    bill = engine.conn.execute(
        "SELECT id, from_org_id, to_org_id, to_person_id, amount_cents, due_sim, "
        "issued_seq, paid_sim, written_off_sim FROM invoices WHERE id = %s",
        (int(payload.get("invoice", 0)),),
    ).fetchone()
    if bill is None or bill["paid_sim"] is not None or bill["written_off_sim"]:
        return
    head = economy.head_of(engine, org_id)
    if head is None:
        return
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(head["id"]),
            role=str(head["role"]),
            sim_time=report.sim_time,
            kind="dispute.resolution",
            facts={
                "org": org_id,
                "large": int(bill["amount_cents"]) >= LARGE_CENTS,
                "runway_days": engine.runway_days(org_id),
                "client_firm": bill["to_org_id"] is not None,
            },
            traits=dict(head["traits"] or {}),
        ),
    )
    outcome = str(made.chosen.get("resolution", "stand_firm"))
    amount = int(bill["amount_cents"])
    seq = engine.emit(
        report,
        "dispute.resolved",
        actor_id=str(head["id"]),
        org_id=org_id,
        causes=[int(payload["cause"])] if payload.get("cause") else [],
        decision_id=made.id,
        payload={
            "invoice_id": int(bill["id"]),
            "resolution": outcome,
            "decided_by": made.source,
        },
    )
    engine.conn.execute(
        "UPDATE invoices SET dispute_resolution = %s WHERE id = %s",
        (outcome, int(bill["id"])),
    )
    if outcome == "write_off":
        engine.write_off(report, bill)
    elif outcome == "discount":
        cut = int(amount * DISPUTE_DISCOUNT)
        engine.post(
            report.sim_time,
            f"{org_id} discounts invoice {bill['id']}",
            [(f"{org_id}.receivable", -cut), (f"{org_id}.revenue", cut)],
            seq,
        )
        engine.conn.execute(
            "UPDATE invoices SET amount_cents = amount_cents - %s WHERE id = %s",
            (cut, int(bill["id"])),
        )
