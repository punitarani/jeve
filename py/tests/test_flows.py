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
from jeve.core.clock import DAY, SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world import episodes, flows
from jeve.world.engine import Engine
from jeve.world.flows import WEEKLY_WAGE_CENTS
from jeve.world.map import ORG_ZONE
from jeve.world.seed_world import ROOT_SEED, STAFF, seed
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
    the other, the outage ends sooner, and a credit moves on the ledger. The
    meeting is whichever kind it was — an episode when they had a stake between
    them, an encounter when not (WORLD-0007)."""

    run(conn, days=5)
    # Straight to an engineer, or through whoever was cornered deciding to pass
    # it on (WORLD-0012); in one shot or over rounds (WORLD-0007). Either way
    # the chain starts at a conversation.
    reached = conn.execute(
        """
        WITH RECURSIVE downstream AS (
            SELECT seq, kind, 0 AS depth FROM events
            WHERE kind IN ('encounter', 'episode.closed') AND seq IN (
                SELECT unnest(causes) FROM events
                WHERE kind IN ('ticket.escalated', 'escalation.relayed'))
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
    assert depth["ticket.escalated"] in (1, 2)
    assert depth["incident.ended"] == depth["ticket.escalated"] + 1
    assert depth["credit.issued"] == depth["incident.ended"] + 1
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
    assert [str(p["org_id"]) for p in paid] == [
        "halloran",
        "ledgerline",
        "tallybird",
        "thirdrail",
    ]
    for row in paid:
        when = SimTime(int(row["sim_time"]))
        assert when.weekday == 4 and when.in_office_hours
        expected = sum(
            WEEKLY_WAGE_CENTS[role] for org, role, _ in STAFF if org == row["org_id"]
        )
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
    assert again is not None and int(again["n"]) == 4
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
    # Halloran and the cafe keep their hours in TimeTrack; the others do not.
    assert lateness["tallybird"] == lateness["ledgerline"] == 0
    assert lateness["halloran"] >= 60 and lateness["thirdrail"] >= 60

    held = conn.execute(
        "SELECT org_id, causes FROM events WHERE kind = 'payroll.held' ORDER BY seq"
    ).fetchall()
    assert {str(h["org_id"]) for h in held} == {"halloran", "thirdrail"}
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

    monkeypatch.setitem(flows.WEEKLY_WAGE_CENTS, "barista", 90_000_00)
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
    assert others is not None and int(others["n"]) == 3
    books_balance(conn)


# -- the monthly close -----------------------------------------------------


def test_books_close_when_the_month_can_be_stated(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    closed = conn.execute(
        "SELECT org_id, seq, payload FROM events WHERE kind = 'close.completed' "
        "ORDER BY org_id"
    ).fetchall()
    assert [str(c["org_id"]) for c in closed] == ["halloran", "tallybird", "thirdrail"]
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
        assert fee["payload"]["amount_cents"] == flows.CLOSE_FEE_CENTS[close["org_id"]]
    books_balance(conn)


def test_an_outage_nobody_chased_delays_the_close_and_the_fee(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second thing space changes. With encounters, someone presses the
    vendor, the invoices go out on Thursday, and Halloran's books close on
    Friday morning. Without anybody chasing it, the invoices are still stuck on
    Friday, the close is put off, and Ledgerline bills for it days later.

    "Anybody" is more people than it was: support's own queue and a customer's
    call to the account manager prioritise an outage too (WORLD-0012), and
    either would clear this one by Friday. The unchased arm switches them off,
    so what it measures is still the outage nobody chased.
    """

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
    with monkeypatch.context() as patch:
        patch.setattr(episodes, "prioritise", lambda *args, **kwargs: None)
        run(conn, days=8, encounters=False, variant="no-queue")
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

    delivered = 0
    for order in orders:
        # The cafe may turn an order down (WORLD-0011): then the refusal, and
        # nothing else, is what the order caused.
        declined = conn.execute(
            "SELECT 1 FROM events WHERE kind = 'catering.declined' "
            "AND %s = ANY(causes)",
            (order["seq"],),
        ).fetchone()
        delivery = conn.execute(
            "SELECT seq, sim_time, actor_id, payload FROM events "
            "WHERE kind = 'catering.delivered' AND %s = ANY(causes)",
            (order["seq"],),
        ).fetchone()
        if declined is not None:
            assert delivery is None, order["org_id"]
            continue
        assert delivery is not None, order["org_id"]
        delivered += 1
        when = SimTime(int(delivery["sim_time"]))
        assert when.day == SimTime(int(order["sim_time"])).day + 1
        assert when.time_of_day == 12 * 3600
        assert delivery["payload"]["amount_cents"] == order["payload"]["amount_cents"]

        bill = conn.execute(
            "SELECT payload FROM events WHERE kind = 'invoice.issued' "
            "AND org_id = 'thirdrail' AND %s = ANY(causes)",
            (delivery["seq"],),
        ).fetchone()
        assert bill is not None and bill["payload"]["to"] == order["org_id"]

        # Somebody from the cafe actually walked it over: at that tick they are
        # recorded moving into the customer's building.
        assert delivery["actor_id"] is not None
        carried = conn.execute(
            "SELECT payload FROM events WHERE kind = 'agent.moved' "
            "AND actor_id = %s AND sim_time = %s AND payload->>'to_zone' = %s",
            (
                delivery["actor_id"],
                delivery["sim_time"],
                ORG_ZONE[str(order["org_id"])].value,
            ),
        ).fetchone()
        assert carried is not None, (order["org_id"], delivery["actor_id"])

    assert delivered, "every order was declined, so no delivery was checked"
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
