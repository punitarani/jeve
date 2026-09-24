"""Hot queries stay index-backed, whatever the tables grow to (LLM-0010).

The world never ends, so anything read per tick, per model call or per poll
of the page must cost the same on day 300 as on day 3: one row, an index
range, or a running total. The ledger fold that broke this rule was 80% of
the production database's time by day three on an eighth of a vCPU.

The planner prefers a sequential scan of a small table whatever indexes
exist, so `enable_seqscan` is turned off for the check: a query that then
still sequential-scans one of the growing tables has no index that can
serve it. Add every new hot query here.
"""

from __future__ import annotations

import re

import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve.api.app import CROWD_SQL, ORG_BALANCES_SQL
from jeve.llm.ledger import _HEAD_SQL, _OPEN_RESERVE_SQL

pytestmark = pytest.mark.timeout(60)

# The tables that grow without bound. Everything else is a few hundred rows.
GROWING = ("events", "decisions", "ledger_entries", "ledger_txns", "spend_entries")

# Each hot query and the index that makes it a range. Naming the index matters:
# the crowd count had (kind, seq) to fall back on, and that was the slow plan —
# a bitmap over every cafe event ever — so "no sequential scan" alone would
# have passed it.
HOT: list[tuple[str, str, tuple[object, ...], str | None]] = [
    ("spend read", "SELECT * FROM spend_totals", (), None),
    ("spend head", _HEAD_SQL, (), "spend_entries_pkey"),
    ("open reservation", _OPEN_RESERVE_SQL, ("call",), "spend_entries_call"),
    ("org balances", ORG_BALANCES_SQL, ("cash",), "ledger_entries_account"),
    ("cafe crowd", CROWD_SQL, (100,), "events_kind_tick"),
    (
        "cash of account",
        "SELECT COALESCE(sum(amount_cents),0) FROM ledger_entries "
        "WHERE account_id = %s",
        ("acct",),
        "ledger_entries_account",
    ),
    (
        # DECIDE-0005: once per batch with a tier-1 candidate.
        "tier-1 room",
        "SELECT count(*) FROM decisions WHERE sim_time >= %s AND sim_time < %s",
        (0, 86400),
        "decisions_time",
    ),
    (
        "events after seq",
        "SELECT seq FROM events WHERE seq > %s ORDER BY seq LIMIT 50",
        (0,),
        "events_pkey",
    ),
]


@pytest.mark.parametrize(
    ("name", "sql", "params", "index"), HOT, ids=[h[0] for h in HOT]
)
def test_hot_queries_run_on_their_index(
    spend_table: Connection[DictRow],
    name: str,
    sql: str,
    params: tuple[object, ...],
    index: str | None,
) -> None:
    conn = spend_table
    # SET is transactional, so the rollback also undoes it — and clears an
    # aborted transaction if the EXPLAIN itself failed.
    try:
        conn.execute("SET enable_seqscan = off")
        rows = conn.execute(f"EXPLAIN (COSTS OFF) {sql}", params).fetchall()
    finally:
        conn.rollback()
    plan = "\n".join(str(row["QUERY PLAN"]) for row in rows)
    scanned = re.findall(r"Seq Scan on (\w+)", plan)
    assert not [t for t in scanned if t in GROWING], f"{name} scans a table:\n{plan}"
    if index is not None:
        assert index in plan, f"{name} does not use {index}:\n{plan}"


def test_the_spend_read_never_touches_the_ledger(
    spend_table: Connection[DictRow],
) -> None:
    """The one row is the point: a fold, however indexed, grows with the run."""

    rows = spend_table.execute(
        "EXPLAIN (COSTS OFF) SELECT * FROM spend_totals"
    ).fetchall()
    spend_table.commit()
    plan = "\n".join(str(row["QUERY PLAN"]) for row in rows)
    assert "spend_entries" not in plan
