"""The loops that close (WORLD-0005), and randomness that is about something
(CORE-0009). Rules policy throughout: what is under test is the plumbing."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, at
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.sim import advance
from jeve.world import scheduler
from jeve.world.engine import WRITE_OFF_AFTER, Engine, TickReport
from jeve.world.seed_world import ROOT_SEED, seed
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(600)

WORLD = Path(__file__).resolve().parent.parent / "src" / "jeve" / "world"


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def two_weeks(conn: Connection[DictRow]) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
        advance(conn, engine, until=14 * DAY)

    build_once(conn, "economy:14d", build)


# -- CORE-0009 -------------------------------------------------------------------


def test_no_draw_in_the_world_is_keyed_by_the_tick() -> None:
    """Six were. An outage that delayed billing by a day re-rolled every invoice,
    and the experiment could not tell late money from different money."""

    offenders: list[str] = []
    for path in sorted(WORLD.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name not in ("derive_rng", "derive_seed"):
                continue
            source = ast.unparse(node)
            if "tick_seq" in source or "report.seq" in source:
                offenders.append(f"{path.name}:{node.lineno}: {source}")
    assert offenders == []


def test_an_invoice_is_the_same_amount_whenever_it_goes_out(
    conn: Connection[DictRow],
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    first = engine.engaged_clients("halloran", 0)
    conn.execute("UPDATE sim_meta SET sim_time = %s, tick_seq = 999", (at(9, 11),))
    assert engine.engaged_clients("halloran", 0) == first
    # Another month is other clients, and other work.
    assert engine.engaged_clients("halloran", 1) != first
    assert 3 <= len(first) <= 25
    conn.rollback()


# -- the engine numbers decisions -----------------------------------------------


def test_two_decisions_by_one_person_in_one_batch_are_consecutive(
    conn: Connection[DictRow],
) -> None:
    """A payer with two bills, or a person in two conversations, in one tick.
    Callers used to number decisions themselves and would have collided."""

    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    payer = "halloran.office_manager.12"
    other = "ledgerline.client_admin.17"

    def bill(person: str, days: int) -> DecisionContext:
        return DecisionContext(
            person_id=person,
            role="office_manager",
            sim_time=at(0, 10),
            kind="payment.timing",
            facts={"days_until_due": days, "can_afford": True, "runway_days": 30},
            traits={"promptness": 0.6},
        )

    report = TickReport(tick_seq=1, sim_time=at(0, 10))
    engine.decide_many(report, [bill(payer, 0), bill(other, -3), bill(payer, -9)])
    rows = conn.execute(
        "SELECT person_id, decision_seq, prng_path FROM decisions ORDER BY id"
    ).fetchall()
    assert [(r["person_id"], r["decision_seq"]) for r in rows] == [
        (payer, 0),
        (other, 0),
        (payer, 1),
    ]
    assert len({r["prng_path"] for r in rows}) == 3
    conn.rollback()


# -- the loops ----------------------------------------------------------------------


def test_tickets_end(conn: Connection[DictRow]) -> None:
    """Answered tickets were never closed, so everyone who had ever filed one was
    'already open' for ever and support went quiet after the first week."""

    two_weeks(conn)
    counts = {
        str(r["status"]): int(r["n"])
        for r in conn.execute(
            "SELECT status, count(*) AS n FROM tickets GROUP BY status"
        ).fetchall()
    }
    assert counts.get("closed", 0) > 20
    lingering = conn.execute(
        "SELECT count(*) AS n FROM tickets WHERE status = 'answered' "
        "AND answered_sim < %s",
        (14 * DAY - 3 * DAY,),
    ).fetchone()
    assert lingering is not None and int(lingering["n"]) == 0
    reasons = {
        str(r["reason"])
        for r in conn.execute(
            "SELECT DISTINCT payload->>'reason' AS reason FROM events "
            "WHERE kind = 'ticket.closed'"
        ).fetchall()
    }
    assert "confirmed" in reasons
    # A close cites the answer it confirms.
    orphan = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'ticket.closed' "
        "AND cardinality(causes) = 0"
    ).fetchone()
    assert orphan is not None and int(orphan["n"]) == 0


def test_a_bill_is_asked_about_once_a_day_not_once_a_tick(
    conn: Connection[DictRow],
) -> None:
    two_weeks(conn)
    worst = conn.execute(
        "SELECT max(n) AS n FROM (SELECT count(*) AS n FROM decisions "
        "WHERE question_set = 'payment.timing' "
        "GROUP BY person_id, sim_time / %s) s",
        (DAY,),
    ).fetchone()
    assert worst is not None
    # One payer can have several bills in a day; nobody has forty.
    assert 1 <= int(worst["n"]) <= 12
    deferred = conn.execute(
        "SELECT max(n) AS n FROM (SELECT count(*) AS n FROM events "
        "WHERE kind = 'payment.deferred' GROUP BY payload->>'invoice_id') s"
    ).fetchone()
    # Said once per bill, not once per die roll.
    assert deferred is not None and int(deferred["n"] or 0) <= 1


def test_wages_arrive_somewhere_and_are_spent(conn: Connection[DictRow]) -> None:
    two_weeks(conn)
    rows = {
        str(r["account_id"]): int(r["cents"])
        for r in conn.execute(
            "SELECT account_id, sum(amount_cents) AS cents FROM ledger_entries "
            "WHERE account_id LIKE 'households.%' GROUP BY account_id"
        ).fetchall()
    }
    assert rows["households.income"] < 0  # credited: wages received
    assert rows["households.spending"] > 0
    total = conn.execute(
        "SELECT COALESCE(sum(amount_cents),0) AS c FROM ledger_entries"
    ).fetchone()
    assert total is not None and int(total["c"]) == 0


def test_a_bill_nobody_will_ever_pay_is_written_off(conn: Connection[DictRow]) -> None:
    """Sixty days past due: not an asset any more. The rule, and its ledger."""

    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    now = at(7, 10)  # a Monday, mid-morning
    conn.execute("UPDATE sim_meta SET sim_time = %s", (now,))
    target = conn.execute(
        "UPDATE invoices SET due_sim = %s, issued_sim = %s WHERE id = "
        "(SELECT min(id) FROM invoices WHERE to_person_id IS NOT NULL "
        " AND from_org_id = 'halloran') RETURNING id, amount_cents",
        (now - WRITE_OFF_AFTER - DAY, now - WRITE_OFF_AFTER - 31 * DAY),
    ).fetchone()
    assert target is not None
    before = engine.cash_of("halloran.receivable")

    engine.tick()

    gone = conn.execute(
        "SELECT payload FROM events WHERE kind = 'invoice.written_off'"
    ).fetchall()
    assert [g["payload"]["invoice_id"] for g in gone] == [int(target["id"])]
    assert before - engine.cash_of("halloran.receivable") >= int(target["amount_cents"])
    row = conn.execute(
        "SELECT written_off_sim FROM invoices WHERE id = %s", (target["id"],)
    ).fetchone()
    assert row is not None and row["written_off_sim"] == now
    total = conn.execute(
        "SELECT COALESCE(sum(amount_cents),0) AS c FROM ledger_entries"
    ).fetchone()
    assert total is not None and int(total["c"]) == 0


def test_office_work_waits_for_the_office_and_keeps_its_place() -> None:
    assert scheduler.get("invoice.run").office_hours_only
    assert scheduler.get("close.run").office_hours_only
    assert not scheduler.get("incident.end").office_hours_only
    with pytest.raises(KeyError, match="nothing handles"):
        scheduler.get("no.such.job")
