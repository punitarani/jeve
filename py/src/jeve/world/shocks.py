"""The shock deck: the world's weather (WORLD-0010).

The scenario seeds "a module outage, a key person out sick, an unusually large
catering order, a supplier price rise, an outside client disputing a bill, an
audit notice, a rumour" as a Poisson process, mean 1.5 a week. The field
report's world had only the first. Shocks are environment, drawn in code and
keyed by the week (CORE-0009); what is emergent is the response to them, and
that is what the decisions they set off measure.

Absence lives in `rota`: somebody off sick is not on shift, whatever their
usual hours, and whoever covers for them is on shift when they would not be.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from jeve import memory
from jeve.core.clock import DAY, HOUR, SimTime
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import economy, scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, TickReport

PER_WEEK = 1.5
KINDS = (
    "sick",
    "sick",
    "large_catering",
    "supplier_price",
    "client_dispute",
    "audit",
    "rumour",
    "outage",
)
"""Drawn uniformly; sickness twice, because it is twice as common."""

COUNTER_ROLES = ("owner", "manager", "shift_lead", "barista", "weekend")
SUPPLIER_MARKUP = 1.10
SUPPLIER_MARKUP_FOR = 28 * DAY
AUDIT_FEE_CENTS = 300_00


def _poisson(rng: Any, mean: float) -> int:
    """Knuth's method: small means, and the draws come from `rng`."""

    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


# -- the rota -------------------------------------------------------------------------


def off(engine: Engine, now: int) -> tuple[frozenset[str], frozenset[str]]:
    """Who is off sick now, and who is covering a shift that is not theirs."""

    rows = engine.conn.execute(
        "SELECT person_id, kind FROM rota WHERE starts_sim <= %s AND ends_sim > %s",
        (now, now),
    ).fetchall()
    absent = frozenset(str(r["person_id"]) for r in rows if r["kind"] == "absent")
    extra = frozenset(str(r["person_id"]) for r in rows if r["kind"] == "extra")
    return absent, extra


def _away(
    engine: Engine,
    person_id: str,
    starts: int,
    days: int,
    *,
    kind: str,
    reason: str,
) -> None:
    engine.conn.execute(
        "INSERT INTO rota (person_id, starts_sim, ends_sim, kind, reason) "
        "VALUES (%s, %s, %s, %s, %s)",
        (person_id, starts, starts + days * DAY, kind, reason),
    )


# -- the deck -------------------------------------------------------------------------


@scheduler.job("shocks.week")
def week(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """Monday morning: what the week has in store, drawn about the week."""

    engine.schedule(report.sim_time + 7 * DAY, "shocks.week", None, {})
    number = report.sim_time // (7 * DAY)
    rng = derive_rng(engine.root_seed, "shocks", number)
    for index in range(_poisson(rng, PER_WEEK)):
        draw = derive_rng(engine.root_seed, "shock", number, index)
        kind = KINDS[int(draw.random() * len(KINDS))]
        # Spread over the working week, on the hour.
        when = SimTime(report.sim_time).day * DAY + int(draw.random() * 5) * DAY
        at = when + (9 + int(draw.random() * 7)) * HOUR
        engine.schedule(
            max(at, report.sim_time),
            "shock",
            kind,
            {"week": number, "index": index},
        )


@scheduler.job("shock", office_hours_only=True)
def shock(
    engine: Engine, report: TickReport, kind: str, payload: dict[str, Any]
) -> None:
    rng = derive_rng(
        engine.root_seed,
        "shock.detail",
        int(payload.get("week", 0)),
        int(payload.get("index", 0)),
    )
    handler = HANDLERS.get(kind)
    if handler is not None:
        handler(engine, report, rng)


def _staff(
    engine: Engine, where: str = "", params: tuple[object, ...] = ()
) -> list[Any]:
    return engine.conn.execute(
        "SELECT p.id, p.org_id, p.role FROM persons p WHERE p.kind = 'staff' "
        f"AND p.status <> 'left' {where} ORDER BY p.id",
        params,
    ).fetchall()


def _sick(engine: Engine, report: TickReport, rng: Any) -> None:
    people = [p for p in _staff(engine) if not economy.failed(engine, str(p["org_id"]))]
    if not people:
        return
    person = people[int(rng.random() * len(people))]
    days = 1 + int(rng.random() * 3)
    starts = SimTime(report.sim_time).day * DAY
    _away(engine, str(person["id"]), starts, days, kind="absent", reason="sick")
    seq = engine.emit(
        report,
        "shock.sick",
        actor_id=str(person["id"]),
        org_id=str(person["org_id"]),
        payload={"person_id": str(person["id"]), "days": days},
    )
    if person["org_id"] == "thirdrail" and person["role"] in COUNTER_ROLES:
        _cover(engine, report, str(person["role"]), starts, days, seq)


def _cover(
    engine: Engine, report: TickReport, role: str, starts: int, days: int, cause: int
) -> None:
    """Somebody behind the counter is off. The owner decides what to do
    (the scenario's "cover for an absent barista or run short")."""

    head = economy.head_of(engine, "thirdrail")
    if head is None:
        return
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(head["id"]),
            role=str(head["role"]),
            sim_time=report.sim_time,
            kind="cover.shift",
            facts={
                "absent_role": role,
                "runway_days": engine.runway_days("thirdrail"),
            },
            traits=dict(head["traits"] or {}),
        ),
    )
    choice = str(made.chosen.get("cover", "run_short"))
    covered_by: str | None = None
    if choice == "cover_it":
        covered_by = str(head["id"])
    elif choice == "call_in":
        extra = _staff(engine, "AND p.org_id = 'thirdrail' AND p.role = 'weekend'")
        covered_by = str(extra[0]["id"]) if extra else None
    if covered_by is not None:
        _away(engine, covered_by, starts, days, kind="extra", reason="cover")
    engine.emit(
        report,
        "shift.covered" if covered_by else "shift.short",
        actor_id=str(head["id"]),
        org_id="thirdrail",
        causes=[cause],
        decision_id=made.id,
        payload={"choice": choice, "by": covered_by, "decided_by": made.source},
    )


def _large_catering(engine: Engine, report: TickReport, rng: Any) -> None:
    offices = [
        org for org in ("halloran", "ledgerline", "tallybird")
        if not economy.failed(engine, org)
    ]  # fmt: skip
    if not offices or economy.failed(engine, "thirdrail"):
        return
    org = offices[int(rng.random() * len(offices))]
    seq = engine.emit(
        report, "shock.large_catering", org_id=org, payload={"org_id": org}
    )
    from jeve.world.flows import take_order

    take_order(engine, report, org, "large", ordered_by=None, cause=seq)


def _supplier_price(engine: Engine, report: TickReport, rng: Any) -> None:
    economy.set_policy(
        engine,
        "thirdrail",
        supplier_markup=SUPPLIER_MARKUP,
        supplier_markup_until=report.sim_time + SUPPLIER_MARKUP_FOR,
    )
    engine.emit(
        report,
        "shock.supplier_price",
        org_id="thirdrail",
        payload={"markup": SUPPLIER_MARKUP},
    )


def _client_dispute(engine: Engine, report: TickReport, rng: Any) -> None:
    bills = engine.conn.execute(
        "SELECT id, from_org_id, to_org_id, to_person_id, amount_cents, issued_seq "
        "FROM invoices WHERE kind = 'services' AND to_person_id IS NOT NULL "
        "AND paid_sim IS NULL AND written_off_sim IS NULL AND disputed_sim IS NULL "
        "ORDER BY id"
    ).fetchall()
    if not bills:
        return
    bill = dict(bills[int(rng.random() * len(bills))])
    from jeve.world.customers import dispute

    engine.emit(
        report,
        "shock.client_dispute",
        org_id=str(bill["from_org_id"]),
        payload={"invoice_id": int(bill["id"])},
    )
    dispute(engine, report, bill, made=None, reason="shock")


def _audit(engine: Engine, report: TickReport, rng: Any) -> None:
    """An audit notice for one of Ledgerline's clients: the next close takes
    an extra day and costs more."""

    clients = [
        org for org in ("halloran", "tallybird", "thirdrail")
        if not economy.failed(engine, org)
    ]  # fmt: skip
    if not clients or economy.failed(engine, "ledgerline"):
        return
    client = clients[int(rng.random() * len(clients))]
    economy.set_policy(engine, client, audit_pending=True)
    engine.emit(report, "shock.audit", org_id=client, payload={"client": client})


def _rumour(engine: Engine, report: TickReport, rng: Any) -> None:
    """A false fact, in one head: somebody has heard a firm is going under.
    It travels exactly like a true one (MEM-0002), and nothing that moves money
    reads it — only people, through what they have heard."""

    firms = [o for o in ("tallybird", "halloran", "ledgerline", "thirdrail")]
    about = firms[int(rng.random() * len(firms))]
    people = [p for p in _staff(engine) if p["org_id"] != about]
    if not people:
        return
    teller = str(people[int(rng.random() * len(people))]["id"])
    seq = engine.emit(
        report,
        "shock.rumour",
        actor_id=teller,
        payload={"about": about, "person_id": teller},
    )
    fact = memory.Fact.rumour(about, report.sim_time // (7 * DAY))
    memory.record_fact(engine.conn, fact, sim_time=report.sim_time, seq=seq)
    memory.learn(engine.conn, teller, fact.id, sim_time=report.sim_time, seq=seq)


def _outage(engine: Engine, report: TickReport, rng: Any) -> None:
    if economy.failed(engine, "tallybird"):
        return
    module = ("invoicing", "timetrack", "pos")[int(rng.random() * 3)]
    seq = engine.emit(
        report, "shock.outage", org_id="tallybird", payload={"module_id": module}
    )
    engine.schedule(
        report.sim_time,
        "incident.start",
        module,
        {"severity": 1, "expected_minutes": 60 + int(rng.random() * 180), "cause": seq},
    )


HANDLERS = {
    "sick": _sick,
    "large_catering": _large_catering,
    "supplier_price": _supplier_price,
    "client_dispute": _client_dispute,
    "audit": _audit,
    "rumour": _rumour,
    "outage": _outage,
}
