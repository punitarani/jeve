"""Gate 2: migrations apply from empty, and the ledger cannot go out of balance.

These need the Compose Postgres (`docker compose up -d`). They skip rather
than fail when it is absent, so `make check` still works on a machine with no
Docker — but CI and `make e2e` run them for real.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db

pytestmark = pytest.mark.timeout(60)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


@pytest.fixture
def fresh(conn: Connection[DictRow]) -> Connection[DictRow]:
    """An empty database with the schema applied."""

    db.reset(conn)
    applied = db.migrate(conn)
    assert applied, "migrate() found nothing to apply to an empty database"
    return conn


def _org(conn: Connection[DictRow]) -> None:
    conn.execute(
        "INSERT INTO orgs (id, name, kind) VALUES ('cafe', 'Third Rail', 'cafe')"
    )
    conn.execute(
        """
        INSERT INTO accounts (id, org_id, name, kind) VALUES
            ('cafe.cash', 'cafe', 'Cash', 'cash'),
            ('cafe.revenue', 'cafe', 'Revenue', 'revenue'),
            ('external', NULL, 'Outside world', 'external')
        """
    )


def _txn(conn: Connection[DictRow]) -> int:
    row = conn.execute(
        "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 't') RETURNING id"
    ).fetchone()
    assert row is not None
    return int(row["id"])


# -- migrations ------------------------------------------------------------


def test_migrations_apply_from_empty(fresh: Connection[DictRow]) -> None:
    tables = {
        row["tablename"]
        for row in fresh.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    assert {"events", "orgs", "persons", "ledger_entries", "decisions"} <= tables


def test_migrations_are_idempotent(fresh: Connection[DictRow]) -> None:
    fresh.commit()
    assert db.migrate(fresh) == []


def test_sim_meta_holds_exactly_one_row(fresh: Connection[DictRow]) -> None:
    fresh.execute("INSERT INTO sim_meta (run_id, root_seed) VALUES ('r1', 42)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        fresh.execute("INSERT INTO sim_meta (run_id, root_seed) VALUES ('r2', 43)")
    fresh.rollback()


# -- the ledger ------------------------------------------------------------


def test_a_balanced_transaction_commits(fresh: Connection[DictRow]) -> None:
    _org(fresh)
    txn = _txn(fresh)
    fresh.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) VALUES "
        "(%s, 'cafe.cash', 450), (%s, 'cafe.revenue', -450)",
        (txn, txn),
    )
    fresh.commit()

    row = fresh.execute(
        "SELECT sum(amount_cents) AS total FROM ledger_entries"
    ).fetchone()
    assert row is not None and row["total"] == 0


def test_an_unbalanced_transaction_is_rejected_by_the_database(
    fresh: Connection[DictRow],
) -> None:
    """The gate. Not a code check — the database refuses the COMMIT."""

    _org(fresh)
    txn = _txn(fresh)
    fresh.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
        "VALUES (%s, 'cafe.cash', 450)",
        (txn,),
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="does not balance"):
        fresh.commit()
    fresh.rollback()


def test_the_check_is_deferred_until_commit(fresh: Connection[DictRow]) -> None:
    """Entries arrive one at a time, so an immediate check would reject them all."""

    _org(fresh)
    txn = _txn(fresh)
    fresh.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
        "VALUES (%s, 'cafe.cash', 450)",
        (txn,),
    )
    # Momentarily unbalanced, and that is allowed.
    fresh.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
        "VALUES (%s, 'cafe.revenue', -450)",
        (txn,),
    )
    fresh.commit()


def test_deleting_one_side_is_also_rejected(fresh: Connection[DictRow]) -> None:
    _org(fresh)
    txn = _txn(fresh)
    fresh.execute(
        "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) VALUES "
        "(%s, 'cafe.cash', 450), (%s, 'cafe.revenue', -450)",
        (txn, txn),
    )
    fresh.commit()

    fresh.execute(
        "DELETE FROM ledger_entries WHERE txn_id = %s AND amount_cents = 450",
        (txn,),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        fresh.commit()
    fresh.rollback()


def test_a_zero_entry_is_meaningless_and_refused(fresh: Connection[DictRow]) -> None:
    _org(fresh)
    txn = _txn(fresh)
    with pytest.raises(psycopg.errors.CheckViolation):
        fresh.execute(
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, 'cafe.cash', 0)",
            (txn,),
        )
    fresh.rollback()


# -- round trip ------------------------------------------------------------


def test_events_round_trip_with_their_causes(fresh: Connection[DictRow]) -> None:
    _org(fresh)
    first = fresh.execute(
        "INSERT INTO events (sim_time, tick_seq, kind, org_id) "
        "VALUES (0, 0, 'incident.started', 'cafe') RETURNING seq"
    ).fetchone()
    assert first is not None
    second = fresh.execute(
        "INSERT INTO events (sim_time, tick_seq, kind, org_id, causes, payload) "
        "VALUES (60, 1, 'ticket.opened', 'cafe', %s, %s) RETURNING seq",
        ([first["seq"]], '{"subject": "POS is down"}'),
    ).fetchone()
    assert second is not None
    fresh.commit()

    row = fresh.execute(
        "SELECT kind, causes, payload FROM events WHERE seq = %s", (second["seq"],)
    ).fetchone()
    assert row is not None
    assert row["causes"] == [first["seq"]]
    assert row["payload"]["subject"] == "POS is down"


def test_a_cascade_is_one_recursive_query(fresh: Connection[DictRow]) -> None:
    """The read pattern the dashboard is built on (WEB-0001)."""

    _org(fresh)
    seqs: list[int] = []
    for index, kind in enumerate(
        ["incident.started", "ticket.opened", "invoice.blocked", "payment.late"]
    ):
        causes = [seqs[-1]] if seqs else []
        row = fresh.execute(
            "INSERT INTO events (sim_time, tick_seq, kind, causes) "
            "VALUES (%s, %s, %s, %s) RETURNING seq",
            (index * 60, index, kind, causes),
        ).fetchone()
        assert row is not None
        seqs.append(row["seq"])
    fresh.commit()

    downstream = fresh.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT seq, kind FROM events WHERE seq = %s
            UNION ALL
            SELECT e.seq, e.kind FROM events e
              JOIN chain c ON c.seq = ANY (e.causes)
        )
        SELECT kind FROM chain ORDER BY seq
        """,
        (seqs[0],),
    ).fetchall()

    assert [row["kind"] for row in downstream] == [
        "incident.started",
        "ticket.opened",
        "invoice.blocked",
        "payment.late",
    ]


def test_an_invoice_must_name_exactly_one_payer(fresh: Connection[DictRow]) -> None:
    _org(fresh)
    with pytest.raises(psycopg.errors.CheckViolation):
        fresh.execute(
            "INSERT INTO invoices "
            "(from_org_id, issued_sim, due_sim, amount_cents, kind) "
            "VALUES ('cafe', 0, 100, 5000, 'services')"
        )
    fresh.rollback()
