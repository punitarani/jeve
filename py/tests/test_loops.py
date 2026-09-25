"""The loops the scenario names and the field report found missing (WORLD-0011,
WORLD-0012).

Each test drives the real entry point — a scheduled job, the engine's flow, or
`episodes.escalate` — on the rules twin, and fails on a world without the loop.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.core.clock import DAY, SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world import (
    customers,
    economy,
    engineering,
    episodes,
    flows,
    scheduler,
    shocks,
    space,
    timesheets,
)
from jeve.world.engine import Engine, TickReport
from jeve.world.seed_world import ROOT_SEED, seed
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(600)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def fresh(
    conn: Connection[DictRow], day: int = 1, hour: int = 10
) -> tuple[Engine, TickReport]:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(day, hour),))
    return engine, TickReport(tick_seq=1, sim_time=at(day, hour))


def count(conn: Connection[DictRow], query: str, *params: object) -> int:
    row = conn.execute(query, params or None).fetchone()
    assert row is not None
    return int(next(iter(row.values())) or 0)


def outage(engine: Engine, report: TickReport, module: str = "invoicing") -> int:
    engine.schedule(
        report.sim_time, "incident.start", module, {"expected_minutes": 600}
    )
    engine._run_due(report)
    row = engine.conn.execute(
        "SELECT id FROM incidents WHERE module_id = %s AND ended_sim IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (module,),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def seven_weeks(conn: Connection[DictRow]) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
        advance(conn, engine, until=at(49))

    build_once(conn, "loops:49d", build)


# -- engineering (the firefighting trap) --------------------------------------------


def test_engineering_decides_the_week_and_the_debt_moves(
    conn: Connection[DictRow],
) -> None:
    seven_weeks(conn)
    allocated = conn.execute(
        "SELECT payload FROM events WHERE kind = 'eng.allocated' ORDER BY seq"
    ).fetchall()
    assert len(allocated) == 7
    levels = {float(r["payload"]["debt_level"]) for r in allocated}
    assert len(levels) > 1, "a week's work never moved the debt"
    deploys = count(
        conn,
        "SELECT count(*) FROM events WHERE kind IN ('deploy.shipped','deploy.held')",
    )
    # Tuesdays and Thursdays.
    assert deploys == 14


def test_a_pinned_debt_is_not_moved(conn: Connection[DictRow]) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, debt_level=0.0)
    report = TickReport(tick_seq=1, sim_time=at(0, 10))
    engineering.allocate(engine, report, "", {})
    assert engineering.debt(engine) == 0.0
    conn.rollback()


def test_a_long_outage_leaves_debt_unless_the_team_is_paying_it_down(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    before = engineering.debt(engine)
    assert engineering.postmortem(engine, report, minutes=30) is None
    after = engineering.postmortem(engine, report, minutes=300)
    assert after is not None and after > before
    economy.set_policy(
        engine,
        "tallybird",
        allocation="debt",
        allocation_until=report.sim_time + DAY,
    )
    assert engineering.postmortem(engine, report, minutes=300) is None
    conn.rollback()


# -- workarounds -----------------------------------------------------------------------


def test_invoices_done_by_hand_go_out_and_are_reconciled_at_the_close(
    conn: Connection[DictRow],
) -> None:
    """The same outage, a firm that works around it: its month-end is not
    blocked, and the close finds the work done by hand."""

    # The day before month-end, so nothing else has been billed yet.
    engine, report = fresh(conn, day=2, hour=10)
    incident = outage(engine, report)
    payer = engine.payer_of("halloran")
    assert payer is not None
    conn.execute(
        "INSERT INTO outage_notices (incident_id, person_id, notice_sim, workaround) "
        "VALUES (%s, %s, %s, 'by_hand') ON CONFLICT (incident_id, person_id) "
        "DO UPDATE SET workaround = 'by_hand'",
        (incident, str(payer["id"]), report.sim_time),
    )
    # Something to bill: a week of logged hours.
    conn.execute(
        "INSERT INTO timesheets (person_id, day, minutes, rate_cents, logged_day, "
        "logged_minutes) VALUES ('halloran.partner.8', 1, 240, 26000, 1, 240)"
    )
    engine._issue_invoices(report, "halloran", cause=0, month=0)
    engine._issue_invoices(report, "ledgerline", cause=0, month=0)
    manual = count(
        conn,
        "SELECT count(*) FROM invoices WHERE from_org_id = 'halloran' AND manual",
    )
    assert manual > 0
    assert (
        count(conn, "SELECT count(*) FROM events WHERE kind = 'invoice.blocked'") == 1
    )  # Ledgerline waited; Halloran did not.
    from jeve.world.flows import _reconcile

    rework = _reconcile(engine, report, "halloran", report.sim_time)
    assert (
        count(
            conn,
            "SELECT count(*) FROM invoices WHERE manual AND reconciled IS NOT NULL",
        )
        == manual
    )
    assert rework is None or rework[0] > 0
    conn.rollback()


# -- escalation routing ----------------------------------------------------------------


def test_cornering_an_engineer_is_immediate_and_support_must_pass_it_on(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    outage(engine, report)
    common = {
        "raised_by": "halloran.office_manager.12",
        "org_id": "halloran",
        "zone": "cafe",
        "cause_seq": None,
        "decision_id": None,
        "decided_by": "rules",
    }
    assert (
        episodes.escalate(
            engine,
            report,
            raised_with="tallybird.support.6",
            **common,  # type: ignore[arg-type]
        )
        is None
    )
    assert (
        count(conn, "SELECT count(*) FROM events WHERE kind = 'ticket.escalated'") == 0
    )
    assert (
        count(conn, "SELECT count(*) FROM scheduled WHERE kind = 'escalation.handoff'")
        == 1
    )
    later = TickReport(tick_seq=2, sim_time=report.sim_time + 15 * 60)
    engine._run_due(later)
    passed = conn.execute(
        "SELECT kind FROM events WHERE kind LIKE 'escalation.%'"
    ).fetchone()
    assert passed is not None and passed["kind"] in (
        "escalation.relayed",
        "escalation.dropped",
    )
    conn.rollback()

    engine, report = fresh(conn)
    outage(engine, report)
    seq = episodes.escalate(
        engine,
        report,
        raised_with="tallybird.engineer.2",
        **common,  # type: ignore[arg-type]
    )
    assert seq is not None
    conn.rollback()


def test_enough_blocked_customers_are_escalated_without_a_meeting(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    incident = outage(engine, report)
    for index in range(3):
        conn.execute(
            "INSERT INTO tickets (opened_sim, reporter_id, module_id, incident_id, "
            "subject, status, severity) VALUES (%s, %s, 'invoicing', %s, 'down', "
            "'triaged', 2)",
            (report.sim_time, f"tallybird.subscriber.{index}", incident),
        )
    due = conn.execute(
        "SELECT due_sim_time FROM scheduled WHERE kind = 'incident.end'"
    ).fetchone()
    assert due is not None
    engine._escalate_internally(report, "tallybird.support.6", "invoicing", 1)
    raised = conn.execute(
        "SELECT actor_id, payload FROM events WHERE kind = 'incident.prioritised'"
    ).fetchone()
    assert raised is not None and raised["actor_id"] == "tallybird.support.6"
    after = conn.execute(
        "SELECT due_sim_time FROM scheduled WHERE kind = 'incident.end'"
    ).fetchone()
    assert after is not None and int(after["due_sim_time"]) < int(due["due_sim_time"])
    # Once per incident, and it leaves the in-person escalation still to come.
    engine._escalate_internally(report, "tallybird.support.6", "invoicing", 1)
    assert (
        count(conn, "SELECT count(*) FROM events WHERE kind = 'incident.prioritised'")
        == 1
    )
    assert (
        count(conn, "SELECT count(*) FROM events WHERE kind = 'ticket.escalated'") == 0
    )
    conn.rollback()


# -- trust, renewal, disputes -----------------------------------------------------


def test_customers_remember_outages_and_some_leave(conn: Connection[DictRow]) -> None:
    seven_weeks(conn)
    revised = count(conn, "SELECT count(*) FROM events WHERE kind = 'trust.revised'")
    assert revised > 0
    lowered = count(
        conn,
        "SELECT count(*) FROM persons WHERE (beliefs->>'vendor_reliability')::int < 3",
    )
    assert lowered > 0
    # Renewal is asked only of customers at risk, at the monthly billing.
    asked = conn.execute(
        "SELECT person_id FROM decisions WHERE question_set = 'subscription.renew'"
    ).fetchall()
    assert asked, "customers lost trust and nobody was asked whether to stay"
    confident = count(
        conn,
        "SELECT count(*) FROM decisions d JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'subscription.renew' "
        "AND COALESCE((p.beliefs->>'vendor_reliability')::int, 3) >= 3",
    )
    assert confident < len(asked)
    cancelled = conn.execute(
        "SELECT payload FROM events WHERE kind = 'subscription.cancelled'"
    ).fetchall()
    if cancelled:
        # That the vendor is losing customers is news its staff hold.
        assert memory.holders_of(conn, "churned:tallybird")


def test_a_confident_customer_is_not_asked_whether_to_stay(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    assert customers.renewals(engine, report) == {}
    assert count(conn, "SELECT count(*) FROM decisions") == 0
    conn.rollback()


def test_the_content_are_not_asked_whether_to_leave_but_some_leave(
    conn: Connection[DictRow],
) -> None:
    """A month's base rate is a hazard, not a question (WORLD-0014): asked,
    Jev put a contented employee's resignation at about 0.10 a month. Nobody
    in a fresh town has anything pushing them, so nobody is asked — and over
    enough months, somebody still goes, for a reason Pew's survey names."""

    engine, report = fresh(conn)
    for month in range(12):
        later = TickReport(
            tick_seq=2 + month, sim_time=report.sim_time + month * 28 * DAY
        )
        economy.careers(engine, later)
    assert (
        count(
            conn, "SELECT count(*) FROM decisions WHERE question_set = 'career.review'"
        )
        == 0
    )
    notices = conn.execute(
        "SELECT payload FROM events WHERE kind = 'staff.notice'"
    ).fetchall()
    assert notices, "a year of hazards and nobody resigned"
    for row in notices:
        payload = dict(row["payload"])
        assert payload["pushed"] is False and payload["decided_by"] == "rules"
        assert payload["reason"] in {name for name, _ in economy.UNPUSHED_REASONS}
    conn.rollback()


def test_a_lapse_ends_a_subscription_quietly(conn: Connection[DictRow]) -> None:
    """A subscription left to lapse (WORLD-0014) is cancelled by rule, says
    why, and is not news that the vendor is in trouble."""

    engine, report = fresh(conn)
    sub = conn.execute(
        "SELECT id, org_id, person_id, module_id, monthly_cents FROM subscriptions "
        "WHERE active AND person_id IS NOT NULL ORDER BY id LIMIT 1"
    ).fetchone()
    assert sub is not None
    customers.cancel(engine, report, dict(sub), str(sub["person_id"]), None)
    event = conn.execute(
        "SELECT decision_id, payload FROM events WHERE kind = 'subscription.cancelled'"
    ).fetchone()
    assert event is not None and event["decision_id"] is None
    assert event["payload"]["decided_by"] == "rules"
    assert event["payload"]["reason"] == "lapsed"
    assert not memory.holders_of(conn, "churned:tallybird")
    conn.rollback()


def test_only_somebody_something_pushes_is_asked_whether_to_go(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    pair = conn.execute(
        "SELECT a.id AS x, b.id AS y FROM persons a JOIN persons b "
        "ON a.org_id = b.org_id AND a.id < b.id WHERE a.kind = 'staff' "
        "AND b.kind = 'staff' AND a.org_id = 'ledgerline' "
        "AND a.role <> 'principal' AND b.role <> 'principal' ORDER BY a.id LIMIT 1"
    ).fetchone()
    assert pair is not None
    memory.warm(conn, str(pair["x"]), str(pair["y"]), -2, sim_time=report.sim_time)
    economy.careers(engine, report)
    asked = {
        str(r["person_id"])
        for r in conn.execute(
            "SELECT person_id FROM decisions WHERE question_set = 'career.review'"
        ).fetchall()
    }
    assert asked == {str(pair["x"]), str(pair["y"])}
    conn.rollback()


def test_a_disputed_bill_is_not_paid_until_the_issuer_answers(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    bill = conn.execute(
        "SELECT id, from_org_id, to_org_id, to_person_id, amount_cents, issued_seq "
        "FROM invoices WHERE from_org_id = 'halloran' AND to_person_id IS NOT NULL "
        "ORDER BY id LIMIT 1"
    ).fetchone()
    assert bill is not None
    customers.dispute(engine, report, dict(bill), made=None, reason="test")
    open_bills = engine._open_bills(
        "i.id = %s", (report.sim_time + 60 * DAY, bill["id"])
    )
    assert open_bills and open_bills[0]["disputed"]
    job = conn.execute(
        "SELECT due_sim_time, payload FROM scheduled WHERE kind = 'dispute.resolve'"
    ).fetchone()
    assert job is not None
    later = TickReport(tick_seq=2, sim_time=int(job["due_sim_time"]))
    receivable = engine.cash_of("halloran.receivable")
    customers.resolve(engine, later, "halloran", dict(job["payload"]))
    resolved = conn.execute(
        "SELECT payload FROM events WHERE kind = 'dispute.resolved'"
    ).fetchone()
    assert resolved is not None
    after = conn.execute(
        "SELECT amount_cents, written_off_sim FROM invoices WHERE id = %s",
        (bill["id"],),
    ).fetchone()
    assert after is not None
    if resolved["payload"]["resolution"] == "discount":
        cut = int(bill["amount_cents"]) - int(after["amount_cents"])
        assert cut > 0 and engine.cash_of("halloran.receivable") == receivable - cut
    conn.rollback()


# -- the law firm's hours -----------------------------------------------------------


def test_the_law_firm_bills_the_hours_it_logged_and_loses_the_rest(
    conn: Connection[DictRow],
) -> None:
    seven_weeks(conn)
    logged = count(conn, "SELECT count(*) FROM timesheets WHERE logged_day IS NOT NULL")
    assert logged > 0
    billed = count(
        conn, "SELECT count(*) FROM timesheets WHERE billed_month IS NOT NULL"
    )
    assert billed > 0
    forgotten = count(
        conn,
        "SELECT COALESCE(sum(minutes - logged_minutes), 0) FROM timesheets "
        "WHERE logged_day IS NOT NULL",
    )
    assert forgotten > 0, "nobody ever logged late"


def test_nothing_can_be_logged_into_software_that_is_down(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn, day=1, hour=16)
    # Only the day-end this test runs, not the ones scheduled before it.
    conn.execute("DELETE FROM scheduled WHERE kind = 'time.day'")
    conn.execute(
        "UPDATE positions SET zone = 'law_office', x = 30, y = 30 "
        "WHERE person_id LIKE 'halloran.%'"
    )
    outage(engine, report, "timetrack")
    timesheets.day(engine, report, "halloran", {})
    assert count(conn, "SELECT count(*) FROM timesheets") == 4
    assert (
        count(conn, "SELECT count(*) FROM timesheets WHERE logged_day IS NOT NULL") == 0
    )
    conn.rollback()


# -- shocks -------------------------------------------------------------------------


def test_the_shock_deck_deals_about_one_and_a_half_a_week(
    conn: Connection[DictRow],
) -> None:
    seven_weeks(conn)
    dealt = count(conn, "SELECT count(*) FROM events WHERE kind LIKE 'shock.%'")
    assert 3 <= dealt <= 25


def test_somebody_off_sick_stays_home(conn: Connection[DictRow]) -> None:
    engine, _ = fresh(conn, day=1, hour=9)
    shocks._away(engine, "halloran.partner.8", at(1), 2, kind="absent", reason="sick")
    absent, extra = shocks.off(engine, at(1, 10))
    partner = next(a for a in space.load_agents(engine) if a.id == "halloran.partner.8")
    assert not space.on_shift(partner, SimTime(at(1, 10)), absent=absent, extra=extra)
    assert space.on_shift(partner, SimTime(at(3, 10)))
    conn.rollback()


def test_a_rumour_is_a_fact_that_is_not_true(conn: Connection[DictRow]) -> None:
    engine, report = fresh(conn)
    import random

    shocks._rumour(engine, report, random.Random(3))
    row = conn.execute(
        "SELECT id, true_fact, topic FROM facts WHERE id LIKE 'rumour:%'"
    ).fetchone()
    assert row is not None and row["true_fact"] is False
    assert row["topic"] == "insolvency"
    assert len(memory.holders_of(conn, str(row["id"]))) == 1
    conn.rollback()


# -- news ---------------------------------------------------------------------------


def test_late_wages_are_news_the_staff_hold(conn: Connection[DictRow]) -> None:
    engine, report = fresh(conn, day=4, hour=10)
    cash = engine.cash_of("thirdrail.cash")
    conn.execute(
        "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'drain') RETURNING id"
    )
    txn = conn.execute("SELECT max(id) AS id FROM ledger_txns").fetchone()
    assert txn is not None
    for account, cents in (("thirdrail.cash", -cash), ("external", cash)):
        conn.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, %s, %s)",
            (txn["id"], account, cents),
        )
    scheduler.get("payroll.run").run(
        engine, report, "thirdrail", {"due": report.sim_time}
    )
    holders = set(memory.holders_of(conn, "payroll_late:thirdrail"))
    assert "thirdrail.barista.20" in holders
    assert "halloran.partner.8" not in holders
    assert memory.holders_of(conn, "insolvency:thirdrail")
    conn.rollback()


def test_three_closes_due_together_and_one_waits_a_working_day(
    conn: Connection[DictRow],
) -> None:
    """Ledgerline can close two months a day; the third client waits, and the
    principal decides whose (the scenario's "which client to close first")."""

    engine, _ = fresh(conn, day=4, hour=8)
    plan = conn.execute(
        "SELECT due_sim_time FROM scheduled WHERE kind = 'close.plan'"
    ).fetchone()
    assert plan is not None and int(plan["due_sim_time"]) == at(4, 8, 45)

    def closes() -> dict[str, int]:
        return {
            str(r["subject_id"]): int(r["due_sim_time"])
            for r in conn.execute(
                "SELECT subject_id, due_sim_time FROM scheduled "
                "WHERE kind = 'close.run'"
            ).fetchall()
        }

    assert set(closes().values()) == {at(4, 9)}
    flows.plan_closes(
        engine, TickReport(tick_seq=1, sim_time=at(4, 8, 45)), "ledgerline", {}
    )
    due = closes()
    # Day 4 is a Friday: the one that waits is closed on Monday.
    waiting = [client for client, when in due.items() if when == at(7, 9)]
    assert len(waiting) == 1
    assert sorted(due.values()) == [at(4, 9), at(4, 9), at(7, 9)]
    asked = conn.execute(
        "SELECT chosen FROM decisions WHERE question_set = 'close.order'"
    ).fetchone()
    assert asked is not None and asked["chosen"]["waits"] == waiting[0]
    # Nobody's month is stuck, so the rules twin keeps back the smallest fee.
    assert waiting == ["thirdrail"]
    queued = count(conn, "SELECT count(*) FROM events WHERE kind = 'close.queued'")
    assert queued == 1
    # And next month's plan is already on the calendar.
    assert (
        count(
            conn,
            "SELECT count(*) FROM scheduled WHERE kind = 'close.plan' "
            "AND due_sim_time = %s",
            at(32, 8, 45),
        )
        == 1
    )


def test_a_world_seeded_before_the_plan_gets_one(conn: Connection[DictRow]) -> None:
    fresh(conn, day=1)
    conn.execute("DELETE FROM scheduled WHERE kind = 'close.plan'")
    economy.install(conn, root_seed=ROOT_SEED)
    plan = conn.execute(
        "SELECT due_sim_time FROM scheduled WHERE kind = 'close.plan'"
    ).fetchone()
    assert plan is not None and int(plan["due_sim_time"]) == at(4, 8, 45)


def test_every_new_scheduled_job_has_a_handler() -> None:
    for _, kind, _, _ in economy.recurring(at(0, 7)):
        scheduler.get(kind)
    for kind in ("shock", "escalation.handoff", "dispute.resolve", "time.day"):
        scheduler.get(kind)
    json.dumps(economy.recurring(at(10, 11)))
