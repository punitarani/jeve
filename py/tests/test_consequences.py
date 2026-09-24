"""The economy has consequences (WORLD-0009).

The field report's world warned of insolvency every week for 28 weeks and
nothing happened: nobody left, nobody borrowed, nothing failed, and a founder
who could not pay wages ordered lunch. Each test here fails on that world.
Rules policy throughout: the consequences are rules, and what is under test is
that they exist and are wired to the events that should trigger them.
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
from jeve.decide import gates
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.sim import advance
from jeve.world import economy
from jeve.world.engine import Engine, TickReport
from jeve.world.seed_world import ROOT_SEED, seed

pytestmark = pytest.mark.timeout(600)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def fresh(conn: Connection[DictRow], hour: int = 10) -> tuple[Engine, TickReport]:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(4, hour),))
    return engine, TickReport(tick_seq=1, sim_time=at(4, hour))


def drain(engine: Engine, org: str, keep: int = 0) -> None:
    """Take a firm's cash away, to the outside world."""

    cash = engine.cash_of(f"{org}.cash")
    if cash <= keep:
        return
    txn = engine.conn.execute(
        "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'test: drain') "
        "RETURNING id"
    ).fetchone()
    assert txn is not None
    for account, cents in ((f"{org}.cash", keep - cash), ("external", cash - keep)):
        engine.conn.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, %s, %s)",
            (txn["id"], account, cents),
        )


def count(conn: Connection[DictRow], query: str, *params: object) -> int:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return int(next(iter(row.values())) or 0)


# -- people -----------------------------------------------------------------------


def test_nobody_considers_leaving_over_one_late_payday(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    economy.missed_payday(engine, report, "tallybird", weeks_behind=1, held_seq=1)
    assert count(conn, "SELECT count(*) FROM decisions") == 0
    assert count(conn, "SELECT count(*) FROM events WHERE kind = 'payroll.missed'") == 1
    conn.rollback()


def test_staff_unpaid_for_weeks_leave_and_the_wage_bill_falls(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    before = engine.weekly_wages("tallybird")
    economy.missed_payday(engine, report, "tallybird", weeks_behind=3, held_seq=1)
    asked = count(
        conn, "SELECT count(*) FROM decisions WHERE question_set = 'leave.consider'"
    )
    # Everyone but whoever runs the firm is asked, once, at the event.
    assert asked == 7
    left = conn.execute(
        "SELECT actor_id, payload FROM events WHERE kind = 'staff.left'"
    ).fetchall()
    assert left, "three unpaid weeks and nobody left"
    assert all(r["payload"]["reason"] == "unpaid" for r in left)
    assert "tallybird.founder.0" not in {r["actor_id"] for r in left}
    assert engine.weekly_wages("tallybird") < before
    gone = conn.execute(
        "SELECT zone, x FROM positions WHERE person_id = %s", (left[0]["actor_id"],)
    ).fetchone()
    assert gone is not None and gone["zone"] == "home" and gone["x"] is None
    conn.rollback()


def test_whoever_runs_a_firm_never_quits_it() -> None:
    ctx = DecisionContext(
        person_id="p",
        role="founder",
        sim_time=0,
        kind="leave.consider",
        facts={"org": "tallybird", "weeks_behind": 3},
    )
    assert gates.settle(ctx) == {"leave": False, "reason": "runs_the_firm"}


def test_a_firm_four_paydays_behind_has_failed_and_that_is_absorbing(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    economy.missed_payday(engine, report, "halloran", weeks_behind=4, held_seq=1)
    assert economy.failed(engine, "halloran")
    assert (
        count(
            conn,
            "SELECT count(*) FROM persons WHERE org_id = 'halloran' "
            "AND kind = 'staff' AND status <> 'left'",
        )
        == 0
    )
    # It schedules nothing more for itself, and bills nobody at month-end.
    assert (
        count(
            conn,
            "SELECT count(*) FROM scheduled WHERE subject_id = 'halloran' "
            "AND kind IN ('payroll.run', 'founder.review', 'rent.run')",
        )
        == 0
    )
    # What it owed the software company is written off by the software company.
    assert (
        count(
            conn,
            "SELECT count(*) FROM invoices WHERE to_org_id = 'halloran' "
            "AND paid_sim IS NULL AND written_off_sim IS NULL",
        )
        == 0
    )
    assert count(conn, "SELECT count(*) FROM events WHERE kind = 'firm.failed'") == 1
    conn.rollback()


def test_when_the_software_company_fails_its_outages_stop_reaching_anyone(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    economy.fail(engine, report, "tallybird", cause=1, weeks_behind=4)
    assert count(conn, "SELECT count(*) FROM subscriptions WHERE active") == 0
    for minute in range(0, 8 * 60, 15):
        engine._maybe_incident(report, SimTime(at(4, 9, minute)))
    started = "SELECT count(*) FROM events WHERE kind = 'incident.started'"
    assert count(conn, started) == 0
    conn.rollback()


# -- the firm -----------------------------------------------------------------------


def test_a_founder_who_cannot_pay_wages_borrows_once(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    drain(engine, "tallybird")
    conn.execute(
        "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
        "VALUES (%s, 'payroll.run', 'tallybird', %s)",
        (report.sim_time + DAY, json.dumps({"held": 1, "due": report.sim_time})),
    )
    # Six weeks of what the firm costs to run, as it stood before it borrowed.
    weekly = engine.weekly_outgoings("tallybird")
    economy.review(engine, report, "tallybird", {"ad_hoc": True, "cause": 1})
    assert engine.cash_of("tallybird.cash") == economy.LOAN_WEEKS * weekly
    assert engine.cash_of(economy.loan_account("tallybird")) < 0
    # A second loan is not on offer while the first is owed.
    assert not economy.borrow(engine, report, "tallybird", 1)
    conn.rollback()


def test_a_price_rise_is_real_and_is_news(conn: Connection[DictRow]) -> None:
    engine, report = fresh(conn)
    before = count(conn, "SELECT sum(monthly_cents) FROM subscriptions WHERE active")
    economy.raise_prices(engine, report, "tallybird", 1)
    after = count(conn, "SELECT sum(monthly_cents) FROM subscriptions WHERE active")
    assert after == pytest.approx(before * economy.PRICE_RISE, rel=0.01)
    assert economy.price_index(engine, "tallybird") == pytest.approx(1.1)
    # The rumour one engineer started with is now everyone's news: the
    # customers' firms have had the letter.
    holders = set(memory.holders_of(conn, "price_rise:tallybird"))
    assert "halloran.office_manager.12" in holders
    assert "ledgerline.client_admin.17" in holders
    conn.rollback()


def test_cutting_costs_stops_the_lunches(conn: Connection[DictRow]) -> None:
    engine, report = fresh(conn)
    economy.apply_review(engine, report, "tallybird", "cut_costs", 1)
    assert economy.frugal(engine, "tallybird", report.sim_time)
    assert not economy.frugal(engine, "tallybird", report.sim_time + 30 * DAY)
    conn.rollback()


def test_an_empty_desk_is_filled_when_the_money_is_there(
    conn: Connection[DictRow],
) -> None:
    engine, report = fresh(conn)
    economy.leave(
        engine,
        report,
        "ledgerline.staff_accountant.15",
        "ledgerline",
        reason="test",
        cause=None,
    )
    economy.hiring(engine, report, "ledgerline", {})
    hired = conn.execute(
        "SELECT payload FROM events WHERE kind = 'staff.hired'"
    ).fetchone()
    assert hired is not None and hired["payload"]["role"] == "staff_accountant"
    person = str(hired["payload"]["person_id"])
    row = conn.execute(
        "SELECT p.traits, s.zone FROM persons p JOIN positions s "
        "ON s.person_id = p.id WHERE p.id = %s",
        (person,),
    ).fetchone()
    assert row is not None and row["zone"] == "home" and "diligence" in row["traits"]
    conn.rollback()


# -- households ---------------------------------------------------------------------


def test_an_unpaid_firm_empties_only_its_own_staffs_purses(
    conn: Connection[DictRow],
) -> None:
    """Field report defect 11: one purse for the town, so an unpaid engineer's
    coffee came out of the lawyers' wages."""

    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    # Tallybird cannot pay anyone, and cannot borrow: it already owes the bank.
    drain(engine, "tallybird")
    report = TickReport(tick_seq=1, sim_time=at(0, 9))
    economy.borrow(engine, report, "tallybird", 1)
    drain(engine, "tallybird")
    conn.execute("UPDATE subscriptions SET active = false WHERE person_id IS NOT NULL")
    conn.commit()
    start = {
        org: engine.cash_of(economy.household(org)) for org in ("tallybird", "halloran")
    }
    advance(conn, engine, until=at(12))
    assert engine.cash_of(economy.household("tallybird")) < start["tallybird"]
    assert engine.cash_of(economy.household("halloran")) > start["halloran"]
    events = "SELECT count(*) FROM events WHERE kind = %s AND org_id = %s"
    assert count(conn, events, "payroll.held", "tallybird") >= 1
    assert count(conn, events, "payroll.paid", "halloran") >= 1
    conn.rollback()


# -- a world from before -----------------------------------------------------------


def test_a_world_seeded_before_the_economy_is_brought_up_to_date(
    conn: Connection[DictRow],
) -> None:
    """Production's world predates WORLD-0009 and migrates while the old daemon
    writes, so the upgrade happens when the new engine starts, once."""

    seed(conn, root_seed=ROOT_SEED)
    # Make it look like the old world: one purse, flat prices, no new jobs.
    total = count(
        conn,
        "SELECT sum(e.amount_cents) FROM ledger_entries e JOIN accounts a "
        "ON a.id = e.account_id WHERE a.org_id IS NULL AND a.kind = 'cash'",
    )
    conn.execute(
        "INSERT INTO accounts (id, org_id, name, kind) "
        "VALUES ('households.cash', NULL, 'Households: cash', 'cash')"
    )
    txn = conn.execute(
        "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'old') RETURNING id"
    ).fetchone()
    assert txn is not None
    for org in ("tallybird", "halloran", "ledgerline", "thirdrail"):
        cents = engine_cash(conn, economy.household(org))
        if cents:
            conn.execute(
                "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
                "VALUES (%s, %s, %s)",
                (txn["id"], economy.household(org), -cents),
            )
    conn.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
        "VALUES (%s, 'households.cash', %s)",
        (txn["id"], total),
    )
    conn.execute(
        "UPDATE subscriptions SET monthly_cents = 4900 WHERE person_id IS NOT NULL"
    )
    conn.execute("UPDATE orgs SET policy = '{}'::jsonb")
    conn.execute(
        "DELETE FROM scheduled WHERE kind IN ('rent.run', 'households.week', "
        "'founder.review', 'hiring.review', 'tax.quarter', 'supplier.order', "
        "'loans.week')"
    )
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(40, 9),))
    conn.commit()

    Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    assert engine_cash(conn, "households.cash") == 0
    split = sum(
        engine_cash(conn, economy.household(org))
        for org in ("tallybird", "halloran", "ledgerline", "thirdrail")
    )
    assert split == total
    assert (
        count(conn, "SELECT count(*) FROM subscriptions WHERE monthly_cents = 4900")
        == 0
    )
    for kind in ("rent.run", "households.week", "founder.review", "tax.quarter"):
        assert count(conn, "SELECT count(*) FROM scheduled WHERE kind = %s", kind) > 0
    since = conn.execute(
        "SELECT policy->>'economy_since' AS s FROM orgs WHERE id = 'tallybird'"
    ).fetchone()
    # Paydays missed under the old economy are not held against anyone.
    assert since is not None and int(since["s"]) == at(40, 9)

    # And a second start changes nothing.
    before = count(conn, "SELECT count(*) FROM scheduled")
    Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    assert count(conn, "SELECT count(*) FROM scheduled") == before
    conn.rollback()


def engine_cash(conn: Connection[DictRow], account: str) -> int:
    return count(
        conn,
        "SELECT COALESCE(sum(amount_cents), 0) FROM ledger_entries "
        "WHERE account_id = %s",
        account,
    )
