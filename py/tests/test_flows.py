"""Credits and payroll (WORLD-0004): each carries a cascade somewhere new.

On the rules policy, so no cassette is needed. Each test is written to fail if
its flow is removed: not "an event of this kind exists" but "this consequence
follows from that cause, and the books still balance".
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core import orgs
from jeve.core.clock import DAY, SimTime, at
from jeve.core.orgs import (
    BY_ID,
    ORGS,
    RoleSpec,
    bank,
    clients_of,
    modules_of,
    tenants_of,
    vendors,
)
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world import engine as engine_module
from jeve.world import flows
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def run(
    conn: Connection[DictRow],
    *,
    days: int,
    encounters: bool = True,
    variant: str = "",
) -> None:
    """`variant` names anything monkeypatched, so a patched world is never
    mistaken for a plain one."""

    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(
            conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, encounters=encounters
        )
        advance(conn, engine, until=at(days))

    build_once(conn, f"rules:{days}d:encounters={encounters}:{variant}", build)


def books_balance(conn: Connection[DictRow]) -> None:
    total = conn.execute(
        "SELECT COALESCE(sum(amount_cents),0) AS cents FROM ledger_entries"
    ).fetchone()
    assert total is not None and int(total["cents"]) == 0
    negative = conn.execute(
        "SELECT a.id, sum(e.amount_cents) AS cents FROM ledger_entries e "
        "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'receivable' "
        "GROUP BY a.id HAVING sum(e.amount_cents) < 0"
    ).fetchall()
    assert negative == [], negative


# -- credits ---------------------------------------------------------------


def test_a_long_outage_earns_a_credit_and_the_invoice_shrinks(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5)
    credits = conn.execute(
        "SELECT seq, org_id, payload, causes FROM events WHERE kind = 'credit.issued' "
        "ORDER BY seq"
    ).fetchall()
    assert credits, "the invoicing outage spans a working day; somebody is owed"

    for credit in credits:
        payload = credit["payload"]
        assert payload["level"] in ("partial", "full_month")
        assert payload["amount_cents"] > 0
        # Caused by the end of a specific outage, not by the calendar.
        cause = conn.execute(
            "SELECT kind, payload FROM events WHERE seq = %s", (credit["causes"][0],)
        ).fetchone()
        assert cause is not None and cause["kind"] == "incident.ended"
        assert cause["payload"]["module_id"] == payload["module_id"]
        # Only a firm that pays for the broken module is owed anything.
        subscribed = conn.execute(
            "SELECT monthly_cents FROM subscriptions WHERE org_id = %s "
            "AND module_id = %s",
            (credit["org_id"], payload["module_id"]),
        ).fetchone()
        assert subscribed is not None
        assert payload["amount_cents"] <= int(subscribed["monthly_cents"])

    # The credit came off what the firm still owes, and nothing went negative.
    owed = conn.execute(
        "SELECT min(amount_cents) AS least FROM invoices WHERE kind = 'subscription'"
    ).fetchone()
    assert owed is not None and int(owed["least"]) >= 0
    books_balance(conn)


def test_a_credit_is_never_more_than_is_still_owed(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    by_invoice = conn.execute(
        "SELECT (payload->>'invoice_id')::bigint AS invoice, "
        "       sum((payload->>'amount_cents')::bigint) AS credited "
        "FROM events WHERE kind = 'credit.issued' GROUP BY 1"
    ).fetchall()
    assert by_invoice
    for row in by_invoice:
        invoice = conn.execute(
            "SELECT amount_cents FROM invoices WHERE id = %s", (row["invoice"],)
        ).fetchone()
        assert invoice is not None and int(invoice["amount_cents"]) >= 0


def test_a_conversation_in_the_cafe_reaches_money(conn: Connection[DictRow]) -> None:
    """The longest chain in the world, end to end: two people meet, one presses
    the other, the outage ends sooner, and a credit moves on the ledger."""

    run(conn, days=5)
    reached = conn.execute(
        """
        WITH RECURSIVE downstream AS (
            SELECT seq, kind, 0 AS depth FROM events
            WHERE kind = 'encounter' AND seq IN (
                SELECT unnest(causes) FROM events WHERE kind = 'ticket.escalated')
            UNION
            SELECT e.seq, e.kind, d.depth + 1
            FROM events e JOIN downstream d ON d.seq = ANY(e.causes)
        )
        SELECT d.kind, min(d.depth) AS depth,
               count(*) FILTER (WHERE t.id IS NOT NULL) AS postings
        FROM downstream d LEFT JOIN ledger_txns t ON t.event_seq = d.seq
        GROUP BY d.kind
        """
    ).fetchall()
    depth = {str(r["kind"]): int(r["depth"]) for r in reached}
    assert depth["ticket.escalated"] == 1
    assert depth["incident.ended"] == 2
    assert depth["credit.issued"] == 3
    postings = {str(r["kind"]): int(r["postings"]) for r in reached}
    assert postings["credit.issued"] > 0


# -- payroll ---------------------------------------------------------------


def test_everyone_is_paid_on_friday_and_the_books_balance(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5, encounters=False)
    paid = conn.execute(
        "SELECT org_id, sim_time, payload FROM events WHERE kind = 'payroll.paid' "
        "ORDER BY org_id"
    ).fetchall()
    assert [str(p["org_id"]) for p in paid] == sorted(org.id for org in ORGS)
    for row in paid:
        when = SimTime(int(row["sim_time"]))
        assert when.weekday == 4 and when.in_office_hours
        expected = BY_ID[str(row["org_id"])].wages_per_week_cents
        assert row["payload"]["amount_cents"] == expected
        spent = conn.execute(
            "SELECT e.amount_cents FROM ledger_entries e JOIN ledger_txns t "
            "ON t.id = e.txn_id WHERE t.memo = %s AND e.account_id = %s",
            (f"{row['org_id']} weekly payroll", f"{row['org_id']}.cash"),
        ).fetchone()
        assert spent is not None and int(spent["amount_cents"]) == -expected
    # Next Friday is already in the diary.
    again = conn.execute(
        "SELECT count(*) AS n FROM scheduled WHERE kind = 'payroll.run'"
    ).fetchone()
    assert again is not None and int(again["n"]) == len(ORGS)
    books_balance(conn)


def test_no_timetrack_no_timesheets_no_payday(conn: Connection[DictRow]) -> None:
    """An outage in one firm's software is a late payday in another's — but only
    for the firms whose hours live in that software."""

    seed(conn, root_seed=ROOT_SEED)
    with conn.transaction():
        conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s, 'incident.start', 'timetrack', %s)",
            (at(4, 9, 30), json.dumps({"severity": 2, "expected_minutes": 120})),
        )
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, encounters=False)
    advance(conn, engine, until=at(5))

    lateness = {
        str(r["org_id"]): int(r["payload"]["minutes_late"])
        for r in conn.execute(
            "SELECT org_id, payload FROM events WHERE kind = 'payroll.paid'"
        ).fetchall()
    }
    # The firms whose hours live in Tallybird's TimeTrack are late; the ones on
    # paper, or on Quill's, are not. Which is which is data (CORE-0012).
    on_it = {
        org.id for org in ORGS if modules_of(org.id, "timetrack") == ("timetrack",)
    }
    assert 2 <= len(on_it) < len(ORGS)
    for org in ORGS:
        if org.id in on_it:
            assert lateness[org.id] >= 60, org.id
        else:
            assert lateness[org.id] == 0, org.id

    held = conn.execute(
        "SELECT org_id, causes FROM events WHERE kind = 'payroll.held' ORDER BY seq"
    ).fetchall()
    assert {str(h["org_id"]) for h in held} == on_it
    outage = conn.execute(
        "SELECT seq FROM events WHERE kind = 'incident.started' "
        "AND payload->>'module_id' = 'timetrack' AND sim_time = %s",
        (at(4, 9, 30),),
    ).fetchone()
    assert outage is not None
    assert all(int(outage["seq"]) in h["causes"] for h in held)

    # And the late payday says why it was late.
    late = conn.execute(
        "SELECT causes FROM events WHERE kind = 'payroll.paid' AND org_id = 'halloran'"
    ).fetchone()
    assert late is not None
    kinds = {
        str(r["kind"])
        for r in conn.execute(
            "SELECT kind FROM events WHERE seq = ANY(%s)", (late["causes"],)
        ).fetchall()
    }
    assert kinds == {"payroll.held", "incident.ended"}
    books_balance(conn)


def test_wages_cannot_be_paid_from_an_empty_account(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whether the money exists is a ledger fact. No policy is asked, no wages
    leave, and the cafe's account never goes below zero."""

    monkeypatch.setitem(orgs.ROLES, "barista", RoleSpec("barista", 90_000_00))
    run(conn, days=5, encounters=False, variant="unaffordable-wages")

    cafe = conn.execute(
        "SELECT e.kind, e.payload, d.source FROM events e "
        "JOIN decisions d ON d.id = e.decision_id "
        "WHERE e.org_id = 'thirdrail' AND e.kind LIKE 'payroll.%%' ORDER BY e.seq"
    ).fetchall()
    assert [r["kind"] for r in cafe] == ["payroll.held"]
    assert cafe[0]["payload"]["reason"] == "insufficient_cash"
    assert cafe[0]["source"] == "rules"
    # It will be looked at again tomorrow, not every fifteen minutes.
    retry = conn.execute(
        "SELECT due_sim_time FROM scheduled WHERE kind = 'payroll.run' "
        "AND subject_id = 'thirdrail'"
    ).fetchone()
    assert retry is not None and int(retry["due_sim_time"]) >= at(5, 10) - DAY
    others = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'payroll.paid'"
    ).fetchone()
    assert others is not None and int(others["n"]) == len(ORGS) - 1
    books_balance(conn)


# -- the monthly close -----------------------------------------------------


def test_books_close_when_the_month_can_be_stated(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    closed = conn.execute(
        "SELECT org_id, seq, payload FROM events WHERE kind = 'close.completed' "
        "ORDER BY org_id"
    ).fetchall()
    clients = sorted(org.id for org in clients_of("ledgerline"))
    assert len(clients) >= 3
    assert [str(c["org_id"]) for c in closed] == clients
    for close in closed:
        # The accountant's fee goes out because the work was done: an invoice
        # from Ledgerline that cites the close, booked as a receivable.
        fee = conn.execute(
            "SELECT e.seq, e.payload FROM events e WHERE e.kind = 'invoice.issued' "
            "AND e.org_id = 'ledgerline' AND %s = ANY(e.causes)",
            (close["seq"],),
        ).fetchone()
        assert fee is not None, close["org_id"]
        assert fee["payload"]["to"] == close["org_id"]
        assert fee["payload"]["amount_cents"] == BY_ID[close["org_id"]].close_fee_cents
    books_balance(conn)


def test_an_outage_nobody_chased_delays_the_close_and_the_fee(
    conn: Connection[DictRow],
) -> None:
    """The second thing space changes. With encounters, someone presses the
    vendor, the invoices go out on Thursday, and Halloran's books close on
    Friday morning. Without, the invoices are still stuck on Friday, the close
    is put off, and Ledgerline bills for it days later."""

    def halloran_close() -> tuple[int, int]:
        done = conn.execute(
            "SELECT sim_time, payload FROM events WHERE kind = 'close.completed' "
            "AND org_id = 'halloran'"
        ).fetchone()
        deferred = conn.execute(
            "SELECT count(*) AS n FROM events WHERE kind = 'close.deferred' "
            "AND org_id = 'halloran'"
        ).fetchone()
        assert deferred is not None
        return (int(done["sim_time"]) if done else -1, int(deferred["n"]))

    run(conn, days=8, encounters=True)
    chased_at, chased_deferrals = halloran_close()
    run(conn, days=8, encounters=False)
    unchased_at, unchased_deferrals = halloran_close()

    assert chased_deferrals == 0 and chased_at == at(4, 9)
    assert unchased_deferrals >= 1
    assert unchased_at > chased_at

    # The deferral says why, and the late close says what unblocked it.
    deferral = conn.execute(
        "SELECT seq, causes FROM events WHERE kind = 'close.deferred' "
        "AND org_id = 'halloran' ORDER BY seq LIMIT 1"
    ).fetchone()
    assert deferral is not None
    why = conn.execute(
        "SELECT kind FROM events WHERE seq = ANY(%s)", (deferral["causes"],)
    ).fetchall()
    assert [str(w["kind"]) for w in why] == ["invoice.blocked"]
    late = conn.execute(
        "SELECT causes FROM events WHERE kind = 'close.completed' "
        "AND org_id = 'halloran'"
    ).fetchone()
    assert late is not None and int(deferral["seq"]) in late["causes"]
    # A firm with nothing stuck closes on time either way.
    cafe = conn.execute(
        "SELECT sim_time FROM events WHERE kind = 'close.completed' "
        "AND org_id = 'thirdrail'"
    ).fetchone()
    assert cafe is not None and int(cafe["sim_time"]) == at(4, 9)


# -- catering --------------------------------------------------------------


def test_lunch_ordered_is_lunch_delivered_billed_and_carried(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5)
    orders = conn.execute(
        "SELECT seq, org_id, sim_time, payload FROM events "
        "WHERE kind = 'catering.ordered' ORDER BY seq"
    ).fetchall()
    assert orders, "nobody ordered lunch in a whole week"

    for order in orders:
        delivery = conn.execute(
            "SELECT seq, sim_time, actor_id, payload FROM events "
            "WHERE kind = 'catering.delivered' AND %s = ANY(causes)",
            (order["seq"],),
        ).fetchone()
        assert delivery is not None, order["org_id"]
        when = SimTime(int(delivery["sim_time"]))
        assert when.day == SimTime(int(order["sim_time"])).day + 1
        assert when.time_of_day == 12 * 3600
        assert delivery["payload"]["amount_cents"] == order["payload"]["amount_cents"]

        caterer = BY_ID[str(order["org_id"])].caterer
        assert caterer is not None
        bill = conn.execute(
            "SELECT payload FROM events WHERE kind = 'invoice.issued' "
            "AND org_id = %s AND %s = ANY(causes)",
            (caterer, delivery["seq"]),
        ).fetchone()
        assert bill is not None and bill["payload"]["to"] == order["org_id"]

        # Somebody from the cafe actually walked it over: at that tick they are
        # recorded moving into the customer's building.
        assert delivery["actor_id"] is not None
        carried = conn.execute(
            "SELECT payload FROM events WHERE kind = 'agent.moved' "
            "AND actor_id = %s AND sim_time = %s AND payload->>'to_zone' = %s",
            (delivery["actor_id"], delivery["sim_time"], order["org_id"]),
        ).fetchone()
        assert carried is not None, (order["org_id"], delivery["actor_id"])

    # Nobody carries two lunches to two offices in the same fifteen minutes.
    doubled = conn.execute(
        "SELECT actor_id, sim_time, count(*) AS n FROM events "
        "WHERE kind = 'catering.delivered' GROUP BY 1, 2 HAVING count(*) > 1"
    ).fetchall()
    assert doubled == []
    books_balance(conn)


def test_a_firm_that_cannot_afford_lunch_is_not_asked(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(flows.CATERING_CENTS, "large", 90_000_00)
    run(conn, days=3, encounters=False, variant="unaffordable-lunch")
    asked = conn.execute(
        "SELECT chosen, source FROM decisions WHERE question_set = 'catering.order'"
    ).fetchall()
    assert asked
    assert all(a["chosen"] == {"order": "none"} for a in asked)
    ordered = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'catering.ordered'"
    ).fetchone()
    assert ordered is not None and int(ordered["n"]) == 0


# -- the archetype flows (WORLD-0010) -----------------------------------------


def test_rent_is_billed_by_the_landlord_and_paid_by_every_tenant(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=12)
    landlords = {org.landlord for org in ORGS if org.landlord is not None}
    assert landlords
    for landlord in sorted(landlords):
        tenants = [t for t in tenants_of(landlord) if t.rent_cents > 0]
        rows = conn.execute(
            "SELECT to_org_id, amount_cents, paid_sim FROM invoices "
            "WHERE kind = 'rent' AND from_org_id = %s ORDER BY to_org_id",
            (landlord,),
        ).fetchall()
        assert [str(r["to_org_id"]) for r in rows] == sorted(t.id for t in tenants)
        for row in rows:
            assert int(row["amount_cents"]) == BY_ID[str(row["to_org_id"])].rent_cents
            # Seven-day terms, answered by the same daily question as any bill.
            assert row["paid_sim"] is not None, row["to_org_id"]
    # And somebody from the landlord came round: a person from one firm
    # standing on another's floor, which is what encounters are made of.
    visits = conn.execute(
        "SELECT payload FROM events WHERE kind = 'maintenance.visited'"
    ).fetchall()
    assert visits
    assert any(v["payload"].get("visited_by") for v in visits)
    books_balance(conn)


def test_supplies_are_ordered_delivered_on_foot_and_billed(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=12)
    orders = conn.execute(
        "SELECT seq, org_id, sim_time, payload FROM events "
        "WHERE kind = 'supply.ordered' ORDER BY seq"
    ).fetchall()
    assert {str(o["org_id"]) for o in orders} == {
        org.id for org in ORGS if org.supplier is not None
    }
    for order in orders:
        supplier = BY_ID[str(order["org_id"])].supplier
        delivery = conn.execute(
            "SELECT seq, sim_time, actor_id, payload FROM events "
            "WHERE kind = 'supply.delivered' AND %s = ANY(causes)",
            (order["seq"],),
        ).fetchone()
        assert delivery is not None, order["org_id"]
        assert (
            SimTime(int(delivery["sim_time"])).day > SimTime(int(order["sim_time"])).day
        )
        assert delivery["payload"]["units"] == order["payload"]["units"]
        # Carried by the supplier's driver, who is then standing in the shop.
        assert delivery["actor_id"] is not None
        carried = conn.execute(
            "SELECT 1 FROM events WHERE kind = 'agent.moved' AND actor_id = %s "
            "AND sim_time = %s AND payload->>'to_zone' = %s",
            (delivery["actor_id"], delivery["sim_time"], order["org_id"]),
        ).fetchone()
        assert carried is not None
        assert str(delivery["actor_id"]).startswith(f"{supplier}.")
        bill = conn.execute(
            "SELECT payload FROM events WHERE kind = 'invoice.issued' "
            "AND org_id = %s AND %s = ANY(causes)",
            (supplier, delivery["seq"]),
        ).fetchone()
        assert bill is not None
        assert bill["payload"]["invoice_kind"] == "supplies"
        assert bill["payload"]["amount_cents"] == order["payload"]["amount_cents"]
    # Stock is what was delivered less what was sold, and never negative.
    stock = conn.execute("SELECT min(stock_units) AS low FROM orgs").fetchone()
    assert stock is not None and int(stock["low"]) >= 0
    books_balance(conn)


def test_a_price_rise_reaches_the_buyer_and_shrinks_the_order(
    conn: Connection[DictRow],
) -> None:
    """The supplier reprices in week two; on rules a buyer told of it buys
    smaller. The words reach the buyer through the question, so this is
    also what a model would be told."""

    run(conn, days=12)
    repriced = conn.execute(
        "SELECT sim_time, payload FROM events WHERE kind = 'supply.repriced'"
    ).fetchone()
    assert repriced is not None and float(repriced["payload"]["multiplier"]) > 1
    asked = conn.execute(
        "SELECT sim_time, chosen FROM decisions WHERE question_set = 'supply.order' "
        "AND sim_time > %s ORDER BY sim_time",
        (repriced["sim_time"],),
    ).fetchall()
    assert asked, "nobody ordered after the price rise"
    # Once prices are up, nobody on rules places a large order.
    assert all(a["chosen"]["order"] != "large" for a in asked)


def test_a_bare_shelf_sends_customers_away_by_rule(
    conn: Connection[DictRow],
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    shop = next(org for org in ORGS if org.supplier is not None and org.retail)
    with conn.transaction():
        conn.execute("UPDATE orgs SET stock_units = 0 WHERE id = %s", (shop.id,))
        conn.execute("DELETE FROM scheduled WHERE kind = 'supply.order'")
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, spatial=False)
    advance(conn, engine, until=at(0, 12))
    sales = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'retail.sale' AND org_id = %s",
        (shop.id,),
    ).fetchone()
    walkouts = conn.execute(
        "SELECT payload->>'reason' AS reason, count(*) AS n FROM events "
        "WHERE kind = 'retail.walkout' AND org_id = %s GROUP BY 1",
        (shop.id,),
    ).fetchall()
    assert sales is not None and int(sales["n"]) == 0
    assert {str(w["reason"]) for w in walkouts} == {"no_stock"}
    # Settled by the gate, not asked: the walkouts are rules decisions.
    asked = conn.execute(
        "SELECT count(*) AS n FROM decisions d JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'retail.purchase' AND p.org_id = %s "
        "AND d.source <> 'rules'",
        (shop.id,),
    ).fetchone()
    assert asked is not None and int(asked["n"]) == 0


def test_a_firm_short_of_runway_draws_a_line_and_repays_it(
    conn: Connection[DictRow],
) -> None:
    """Insolvency is a process: cash runs short, the payer applies, the bank's
    officer approves, wages are paid from the line, and when the firm can it
    clears the line by rule."""

    seed(conn, root_seed=ROOT_SEED)
    lender = bank()
    assert lender is not None
    # A tenant that earns nothing from beyond the district, so a drained
    # account stays drained until the bank or its clients refill it.
    borrower = next(
        org
        for org in ORGS
        if org.landlord is not None
        and org.id != lender
        and not org.outside_income_cents
    )
    weekly = borrower.wages_per_week_cents
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, encounters=False)
    payer = engine.payer_of(borrower.id)
    assert payer is not None
    # Take the firm down to a week of wages: a fact on the ledger, not a mood.
    # And make its bill-payer the borrowing kind, so the rules twin's roll
    # is about whether the flow works rather than about one temperament.
    cash = engine.cash_of(f"{borrower.id}.cash")
    with conn.transaction():
        conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'test: drain') "
            "RETURNING id"
        )
        txn = conn.execute("SELECT max(id) AS id FROM ledger_txns").fetchone()
        assert txn is not None
        drain = cash - weekly
        conn.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) VALUES "
            "(%s, %s, %s), (%s, 'external', %s)",
            (txn["id"], f"{borrower.id}.cash", -drain, txn["id"], drain),
        )
        conn.execute(
            "UPDATE persons SET traits = traits || '{\"risk_appetite\": 0.9}'::jsonb "
            "WHERE id = %s",
            (str(payer["id"]),),
        )
    advance(conn, engine, until=at(2))

    applied = conn.execute(
        "SELECT seq, org_id, payload FROM events WHERE kind = 'credit.applied' "
        "AND org_id = %s ORDER BY seq LIMIT 1",
        (borrower.id,),
    ).fetchone()
    assert applied is not None, "a firm a week from empty never asked the bank"
    assert applied["payload"]["amount_cents"] == flows.LINE_WEEKS * weekly
    drawn = conn.execute(
        "SELECT seq, payload FROM events WHERE kind = 'loan.drawn' "
        "AND %s = ANY(causes)",
        (applied["seq"],),
    ).fetchone()
    assert drawn is not None and drawn["payload"]["lender"] == lender
    loan = conn.execute(
        "SELECT * FROM loans WHERE borrower_org_id = %s", (borrower.id,)
    ).fetchone()
    assert loan is not None and int(loan["balance_cents"]) == flows.LINE_WEEKS * weekly
    books_balance(conn)

    # With the line in the account, the firm can afford a payroll it could
    # not have before; and once it holds four weeks of wages beyond the
    # balance, the line is cleared without anyone being asked.
    with conn.transaction():
        conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo) VALUES (%s, 'test: windfall')",
            (at(2),),
        )
        txn = conn.execute("SELECT max(id) AS id FROM ledger_txns").fetchone()
        assert txn is not None
        windfall = flows.REPAY_AT_WEEKS * weekly + int(loan["balance_cents"])
        conn.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) VALUES "
            "(%s, %s, %s), (%s, 'external', %s)",
            (txn["id"], f"{borrower.id}.cash", windfall, txn["id"], -windfall),
        )
    advance(conn, engine, until=at(3))
    repaid = conn.execute(
        "SELECT payload FROM events WHERE kind = 'loan.repaid' AND org_id = %s",
        (borrower.id,),
    ).fetchone()
    assert repaid is not None
    closed = conn.execute(
        "SELECT closed_sim, balance_cents FROM loans WHERE id = %s", (loan["id"],)
    ).fetchone()
    assert closed is not None and closed["closed_sim"] is not None
    assert int(closed["balance_cents"]) == 0
    books_balance(conn)


def test_the_bank_declines_a_firm_that_is_not_paying_its_way(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rules twin's bank: held payroll and a stack of overdue bills is a
    decline, recorded with its reason and citing the application."""

    seed(conn, root_seed=ROOT_SEED)
    lender = bank()
    assert lender is not None
    borrower = next(
        org for org in ORGS if org.landlord is not None and org.id != lender
    )
    with conn.transaction():
        # Already in debt: the one thing the rules twin never lends into.
        conn.execute(
            "INSERT INTO loans (lender_org_id, borrower_org_id, principal_cents, "
            "balance_cents, rate_bp, opened_sim) "
            "VALUES (%s, %s, 1000000000, 1000000000, 900, 0)",
            (lender, borrower.id),
        )
        conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s, 'credit.decide', %s, %s)",
            (at(0, 10), borrower.id, json.dumps({"amount": 1_000_00})),
        )
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, spatial=False)
    advance(conn, engine, until=at(0, 11))
    declined = conn.execute(
        "SELECT payload, org_id FROM events WHERE kind = 'credit.declined'"
    ).fetchone()
    assert declined is not None and declined["org_id"] == lender
    assert declined["payload"]["applicant"] == borrower.id
    assert declined["payload"]["reason"] == "not_paying_its_way"
    lines = conn.execute("SELECT count(*) AS n FROM loans").fetchone()
    assert lines is not None and int(lines["n"]) == 1


@pytest.mark.parametrize("which", [0, 1], ids=["first_vendor", "second_vendor"])
def test_the_second_vendors_outage_reaches_its_own_customers_till(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch, which: int
) -> None:
    """A vendor's register goes down; the tills on *its* product slow and the
    other vendor's customers notice nothing. Which till depends on which
    product is data, so it is tried from both sides."""

    seed(conn, root_seed=ROOT_SEED)
    vendor = vendors()[which].id
    other = vendors()[1 - which].id
    till = next(m for m in modules_of(vendor) if m.endswith("pos"))
    users = [
        org.id for org in ORGS if org.retail and modules_of(org.id, "pos") == (till,)
    ]
    bystanders = [
        org.id
        for org in ORGS
        if org.retail and modules_of(org.id, "pos") not in ((till,), ())
    ]
    assert users and bystanders
    with conn.transaction():
        conn.execute("DELETE FROM scheduled WHERE kind = 'incident.start'")
        conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s, 'incident.start', %s, %s)",
            (at(0, 9), till, '{"severity": 2, "expected_minutes": 480}'),
        )
    # One outage, the scheduled one: the hazard would otherwise be free to
    # take the other vendor's register down the same morning.
    monkeypatch.setattr(engine_module, "HAZARD_PER_HOUR", 0.0)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, spatial=False)
    advance(conn, engine, until=at(0, 14))
    down = {
        str(r["org_id"]): int(r["n"])
        for r in conn.execute(
            "SELECT org_id, count(*) AS n FROM retail_sales WHERE till_down "
            "AND sim_time < %s GROUP BY 1",
            (at(0, 14),),
        ).fetchall()
    }
    assert all(down.get(org, 0) > 0 for org in users), down
    assert all(down.get(org, 0) == 0 for org in bystanders), down
    # And the tickets about it go to the vendor that sells it, not the other
    # one. (Both support desks also start the day warm on seeded tickets that
    # are about nothing in particular; those are not the ones being counted.)
    triaged = conn.execute(
        "SELECT DISTINCT e.org_id FROM events e "
        "JOIN tickets t ON t.id = (e.payload->>'ticket_id')::bigint "
        "JOIN incidents i ON i.id = t.incident_id "
        "WHERE e.kind = 'ticket.triaged' AND i.module_id = %s",
        (till,),
    ).fetchall()
    assert {str(t["org_id"]) for t in triaged} == {vendor}
    assert other != vendor
