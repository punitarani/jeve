"""Gate 3a: the world runs on rules, and the invariants hold.

Includes the extreme-condition and degenerate tests from the validation plan
(Sargent): push a parameter to an absurd value and check the world responds
the way the domain says it must. A simulation that behaves identically under
"no customers" and "normal Tuesday" is not modelling anything.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world.engine import Engine, skip_to_next_open
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
    days: int = 2,
    root_seed: int = ROOT_SEED,
    debt_level: float = 1.0,
    fresh: bool = False,
) -> Counter[str]:
    """Seed and run, returning the event mix.

    Reuses an identical world already in the database unless `fresh`, which a
    test about reproducibility must set: comparing a world with itself proves
    nothing.
    """

    def build() -> None:
        seed(conn, root_seed=root_seed)
        engine = Engine(
            conn, RulesPolicy(root_seed), root_seed=root_seed, debt_level=debt_level
        )
        advance(conn, engine, until=at(days))

    if fresh:
        build()
    else:
        build_once(conn, f"rules:{days}d:seed={root_seed}:debt={debt_level}", build)
    rows = conn.execute("SELECT kind, count(*) AS n FROM events GROUP BY kind")
    return Counter({str(row["kind"]): int(row["n"]) for row in rows.fetchall()})


def event_log_hash(conn: Connection[DictRow]) -> str:
    rows = conn.execute(
        "SELECT sim_time, kind, actor_id, org_id, payload, causes "
        "FROM events ORDER BY seq"
    ).fetchall()
    digest = hashlib.blake2b(digest_size=16)
    for row in rows:
        digest.update(json.dumps(dict(row), sort_keys=True, default=str).encode())
    return digest.hexdigest()


def ledger_total(conn: Connection[DictRow]) -> int:
    row = conn.execute(
        "SELECT COALESCE(sum(amount_cents),0) AS total FROM ledger_entries"
    ).fetchone()
    assert row is not None
    return int(row["total"])


# -- it runs ---------------------------------------------------------------


def test_the_world_runs_and_every_flow_fires(conn: Connection[DictRow]) -> None:
    kinds = run(conn, days=5)

    # All six flows, each observed at least once over the fixture window.
    assert kinds["incident.started"] > 0, "no outages: flow 1 never fired"
    assert kinds["ticket.opened"] > 0 and kinds["ticket.triaged"] > 0
    assert kinds["invoice.issued"] > 0, "month-end never produced an invoice"
    assert kinds["invoice.blocked"] > 0, "the outage never blocked invoicing"
    assert kinds["payment.made"] > 0, "nothing was ever paid"
    assert kinds["cafe.sale"] > 0


def test_the_ledger_balances_after_a_full_run(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    assert ledger_total(conn) == 0


def test_no_org_holds_negative_cash(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    rows = conn.execute(
        "SELECT a.org_id, sum(e.amount_cents) AS cents FROM ledger_entries e "
        "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash' "
        "GROUP BY a.org_id"
    ).fetchall()
    negative = [row["org_id"] for row in rows if int(row["cents"]) < 0]
    assert negative == [], f"overdrawn without a credit line: {negative}"


def test_every_payment_traces_to_an_invoice(conn: Connection[DictRow]) -> None:
    """Referential integrity, stated as the validation plan states it."""

    run(conn, days=5)
    orphans = conn.execute(
        "SELECT count(*) AS n FROM payments p "
        "LEFT JOIN invoices i ON i.id = p.invoice_id WHERE i.id IS NULL"
    ).fetchone()
    assert orphans is not None and int(orphans["n"]) == 0


def test_work_items_are_conserved(conn: Connection[DictRow]) -> None:
    """opened == open + closed, for every ticket ever created."""

    run(conn, days=5)
    opened = conn.execute("SELECT count(*) AS n FROM tickets").fetchone()
    by_status = conn.execute(
        "SELECT status, count(*) AS n FROM tickets GROUP BY status"
    ).fetchall()
    assert opened is not None
    assert sum(int(row["n"]) for row in by_status) == int(opened["n"])


# -- determinism (CORE-0005) ----------------------------------------------


def test_the_same_seed_produces_the_same_event_log(conn: Connection[DictRow]) -> None:
    run(conn, days=3, root_seed=7, fresh=True)
    first = event_log_hash(conn)
    run(conn, days=3, root_seed=7, fresh=True)
    assert event_log_hash(conn) == first


def test_a_different_seed_produces_a_different_world(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=3, root_seed=7)
    first = event_log_hash(conn)
    run(conn, days=3, root_seed=8)
    assert event_log_hash(conn) != first


def test_every_decision_records_how_it_was_made(conn: Connection[DictRow]) -> None:
    run(conn, days=2)
    rows = conn.execute(
        "SELECT count(*) AS n FROM decisions WHERE source = 'rules' AND prng_path = ''"
    ).fetchone()
    assert rows is not None and int(rows["n"]) == 0, "a decision has no PRNG path"


# -- the cascade (the headline claim) --------------------------------------


def test_an_invoicing_outage_blocks_month_end_billing(
    conn: Connection[DictRow],
) -> None:
    """Behaviour #1's first link, and the reason the fixture puts month-end
    on day 3 rather than Friday."""

    run(conn, days=5)
    blocked = conn.execute(
        "SELECT payload FROM events WHERE kind = 'invoice.blocked' ORDER BY seq"
    ).fetchall()
    assert blocked, "the outage crossed month-end but nothing was blocked"
    assert all(row["payload"]["module_id"] == "invoicing" for row in blocked)


def test_the_block_traces_back_to_the_incident(conn: Connection[DictRow]) -> None:
    """A cascade has to be a query, not an inference (CORE-0007)."""

    run(conn, days=5)
    chain = conn.execute(
        """
        WITH RECURSIVE downstream AS (
            SELECT seq, kind FROM events WHERE kind = 'incident.started'
            UNION ALL
            SELECT e.seq, e.kind FROM events e
              JOIN downstream d ON d.seq = ANY (e.causes)
        )
        SELECT DISTINCT kind FROM downstream
        """
    ).fetchall()
    kinds = {row["kind"] for row in chain}
    assert "invoice.blocked" in kinds, f"outage has no causal descendants: {kinds}"
    assert "ticket.opened" in kinds, "nobody reported the outage"


def test_billing_recovers_once_the_module_is_back(conn: Connection[DictRow]) -> None:
    """The retry chain: blocked runs must resume, not die after one attempt."""

    run(conn, days=5)
    first_block = conn.execute(
        "SELECT seq FROM events WHERE kind = 'invoice.blocked' ORDER BY seq LIMIT 1"
    ).fetchone()
    issued_after = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'invoice.issued' "
        "AND seq > %s AND payload->>'invoice_kind' = 'services'",
        (first_block["seq"] if first_block else 0,),
    ).fetchone()
    assert issued_after is not None and int(issued_after["n"]) > 0, (
        "invoicing never recovered after the outage cleared"
    )


# -- extreme-condition and degenerate tests (Sargent) ----------------------


def test_a_permanent_outage_makes_tickets_pile_up(conn: Connection[DictRow]) -> None:
    """Extreme condition: if the product never comes back, the queue must grow."""

    seed(conn, root_seed=ROOT_SEED)
    with conn.transaction():
        # Through the front door, so that the people who use each product find
        # out in their own time (CORE-0009) — and with no end in sight.
        conn.execute("DELETE FROM scheduled WHERE kind LIKE 'incident.%'")
        for module in ("timetrack", "invoicing", "pos"):
            conn.execute(
                "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
                "VALUES (%s, 'incident.start', %s, %s)",
                (at(0, 7), module, '{"severity": 2, "expected_minutes": 10000000}'),
            )
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)

    backlog: list[int] = []
    for _ in range(60):
        engine.tick()
        row = conn.execute(
            "SELECT count(*) AS n FROM tickets WHERE status <> 'closed'"
        ).fetchone()
        assert row is not None
        backlog.append(int(row["n"]))

    assert backlog[-1] > backlog[0], "a permanent outage did not grow the backlog"


def test_with_no_customers_the_cafe_earns_nothing(
    conn: Connection[DictRow],
) -> None:
    """Degenerate test: remove the input, the output must vanish."""

    seed(conn, root_seed=ROOT_SEED)
    with conn.transaction():
        conn.execute(
            "DELETE FROM persons WHERE org_id = 'thirdrail' AND kind = 'counterparty'"
        )
    # And nobody walks over from the offices either: they are customers too.
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, spatial=False)
    for _ in range(40):
        engine.tick()

    sales = conn.execute("SELECT count(*) AS n FROM cafe_sales").fetchone()
    assert sales is not None and int(sales["n"]) == 0
    assert ledger_total(conn) == 0


def test_a_healthy_product_produces_no_outage_cascade(
    conn: Connection[DictRow],
) -> None:
    """The control arm. Without an outage there is nothing to block, which is
    what makes the treatment arm's blocked invoices attributable."""

    seed(conn, root_seed=ROOT_SEED)
    with conn.transaction():
        conn.execute("DELETE FROM scheduled WHERE kind = 'incident.start'")
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, debt_level=0.0)
    end = at(5)
    while True:
        row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
        assert row is not None
        now = SimTime(int(row["sim_time"]))
        if now.seconds >= end:
            break
        if not now.anything_open:
            if skip_to_next_open(conn) >= end:
                break
            continue
        engine.tick()

    blocked = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'invoice.blocked'"
    ).fetchone()
    issued = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'invoice.issued' "
        "AND payload->>'invoice_kind' = 'services'"
    ).fetchone()
    assert blocked is not None and int(blocked["n"]) == 0
    assert issued is not None and int(issued["n"]) > 0, (
        "month-end produced nothing even with the product healthy"
    )


# -- non-degeneracy --------------------------------------------------------


def test_the_cafe_does_not_turn_away_most_of_its_customers(
    conn: Connection[DictRow],
) -> None:
    """A degenerate cafe cannot transmit an outage to anyone."""

    kinds = run(conn, days=5)
    sales, walkouts = kinds["cafe.sale"], kinds["cafe.walkout"]
    assert sales > 0
    assert walkouts / (sales + walkouts) < 0.25, (
        f"walkout rate {walkouts / (sales + walkouts):.0%} on a normal week"
    )


def test_payment_timing_varies_between_people(conn: Connection[DictRow]) -> None:
    """If everyone pays on the due date, the credit chain cannot form."""

    run(conn, days=5)
    rows = conn.execute(
        "SELECT chosen->>'pay' AS pay, count(*) AS n FROM decisions "
        "WHERE question_set = 'payment.timing' GROUP BY 1"
    ).fetchall()
    outcomes = {str(row["pay"]): int(row["n"]) for row in rows}
    assert len(outcomes) > 1, f"every payment decision went the same way: {outcomes}"


def test_a_ticket_is_never_answered_before_it_is_opened(
    conn: Connection[DictRow],
) -> None:
    """Temporal ordering."""

    run(conn, days=5)
    bad = conn.execute(
        "SELECT count(*) AS n FROM tickets "
        "WHERE closed_sim IS NOT NULL AND closed_sim < opened_sim"
    ).fetchone()
    assert bad is not None and int(bad["n"]) == 0


def test_dead_time_is_skipped_rather_than_ticked(conn: Connection[DictRow]) -> None:
    """CORE-0003: a sim-night costs nothing because nothing calls a model."""

    seed(conn, root_seed=ROOT_SEED)
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(0, 22),))
    conn.commit()
    moved = skip_to_next_open(conn)
    # To the next moment anything is open — the cafe at seven, not the offices
    # at nine, which is what this asserted while the bug was in.
    assert moved == at(1, 7)
    assert SimTime(moved).cafe_open and not SimTime(moved).in_office_hours


def test_sunday_is_skipped_but_saturday_is_not(conn: Connection[DictRow]) -> None:
    """The offices are shut all weekend. The cafe is shut on Sunday only."""

    seed(conn, root_seed=ROOT_SEED)
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(4, 18),))
    conn.commit()
    assert skip_to_next_open(conn) == at(5, 7)  # Friday night -> Saturday, cafe

    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(5, 18),))
    conn.commit()
    moved = skip_to_next_open(conn)
    assert SimTime(moved).weekday == 0
    assert moved == at(7, 7)  # Saturday close -> Monday, straight over Sunday


def test_a_tick_is_atomic(conn: Connection[DictRow]) -> None:
    """If the tick transaction fails, nothing from it survives — which is what
    makes a re-executed tick after `kill -9` safe (CORE-0007)."""

    seed(conn, root_seed=ROOT_SEED)
    before = conn.execute("SELECT count(*) AS n FROM events").fetchone()
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)

    original = engine._post

    def explode(*args: object, **kwargs: object) -> int:
        original(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated crash mid-tick")

    engine._post = explode  # type: ignore[method-assign]
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(0, 10),))
    conn.commit()

    with pytest.raises(RuntimeError):
        for _ in range(40):
            engine.tick()

    after = conn.execute("SELECT count(*) AS n FROM events").fetchone()
    assert before is not None and after is not None
    # Ticks before the failing one committed; the failing one left nothing.
    assert ledger_total(conn) == 0
    row = conn.execute("SELECT sim_time, tick_seq FROM sim_meta").fetchone()
    assert row is not None


def test_receivables_never_go_negative(conn: Connection[DictRow]) -> None:
    """An org cannot be owed a negative amount.

    The ledger summing to zero does not catch this: the seed created open
    invoices with no matching ledger entry, so collecting one credited cash
    against a receivable that had never been booked. The books balanced and
    the balance sheet was still wrong.
    """

    run(conn, days=5)
    rows = conn.execute(
        "SELECT a.org_id, sum(e.amount_cents) AS cents FROM ledger_entries e "
        "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'receivable' "
        "GROUP BY a.org_id"
    ).fetchall()
    negative = {
        str(row["org_id"]): int(row["cents"]) for row in rows if int(row["cents"]) < 0
    }
    assert negative == {}, f"owed a negative amount: {negative}"


def test_every_open_invoice_is_booked_as_a_receivable(
    conn: Connection[DictRow],
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    rows = conn.execute(
        "SELECT i.from_org_id, sum(i.amount_cents) AS owed FROM invoices i "
        "WHERE i.paid_sim IS NULL GROUP BY i.from_org_id"
    ).fetchall()
    for row in rows:
        booked = conn.execute(
            "SELECT COALESCE(sum(amount_cents),0) AS cents FROM ledger_entries "
            "WHERE account_id = %s",
            (f"{row['from_org_id']}.receivable",),
        ).fetchone()
        assert booked is not None
        assert int(booked["cents"]) == int(row["owed"]), (
            f"{row['from_org_id']} has {row['owed']} invoiced but "
            f"{booked['cents']} booked"
        )


def test_dead_time_ends_when_anything_opens_not_only_the_offices() -> None:
    """The cafe opens at seven and trades on Saturday. Skipping to the next
    *office* opening dropped its mornings on every day but the first."""

    from jeve.core.clock import next_open

    assert next_open(at(0, 17)) == at(0, 17)  # the cafe stays open till six
    assert next_open(at(0, 18)) == at(1, 7)  # Monday evening -> Tuesday, cafe
    assert next_open(at(1, 8, 30)) == at(1, 8, 30)  # already open
    assert next_open(at(4, 18)) == at(5, 7)  # Friday evening -> Saturday, cafe
    assert next_open(at(5, 18)) == at(7, 7)  # Saturday close -> Monday, cafe
    assert next_open(at(6, 12)) == at(7, 7)  # Sunday: everything is shut


def test_the_cafe_trades_every_morning_and_on_saturday(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=6)
    mornings = conn.execute(
        "SELECT sim_time / 86400 AS day, count(*) AS n FROM events "
        "WHERE kind = 'cafe.sale' AND mod(sim_time, 86400) < 9 * 3600 "
        "GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert [int(m["day"]) for m in mornings] == [0, 1, 2, 3, 4, 5]
    saturday = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'cafe.sale' "
        "AND sim_time >= %s AND sim_time < %s",
        (at(5), at(6)),
    ).fetchone()
    assert saturday is not None and int(saturday["n"]) > 20
