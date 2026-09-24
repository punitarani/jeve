"""Side by side: the same measures read from several worlds.

    uv run python scripts/field_compare.py base=postgresql://.../jeve_base \\
        now=postgresql://.../jeve_now > compare.md

Each argument is `label=dsn`. Every measure is one query, run on its own in
autocommit, so a world built by older code — without the tables a later
migration added — shows a dash where it cannot answer instead of failing the
comparison. Used to write `ops/field-report-v2.md`: the world this branch
started from and the world it ends with, both on the rules twin for the same
seed and horizon, so the difference is the code and nothing else.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import psycopg
from psycopg.rows import dict_row

from jeve.core.clock import DAY, HOUR
from jeve.world.engine import FRICTION

type Measure = tuple[str, str, Callable[[object], str]]


def _int(value: object) -> str:
    return f"{int(float(str(value))):,}" if value is not None else "0"


def _pct(value: object) -> str:
    return f"{float(str(value)):.1%}" if value is not None else "—"


def _dollars(value: object) -> str:
    return f"${float(str(value)) / 100:,.0f}" if value is not None else "—"


def _one(value: object) -> str:
    return f"{float(str(value)):.2f}" if value is not None else "—"


MEASURES: list[Measure] = [
    ("sim-days", f"SELECT max(sim_time) / {DAY} FROM events", _int),
    ("decisions", "SELECT count(*) FROM decisions", _int),
    (
        "decision kinds asked",
        "SELECT count(DISTINCT question_set) FROM decisions",
        _int,
    ),
    (
        "share of decisions that are agent.tick",
        "SELECT avg((question_set = 'agent.tick')::int) FROM decisions",
        _pct,
    ),
    ("events", "SELECT count(*) FROM events", _int),
    ("event kinds", "SELECT count(DISTINCT kind) FROM events", _int),
    (
        "friction events per week",
        f"SELECT count(*) * 7.0 * {DAY} / NULLIF(max(sim_time), 0) FROM events "
        "WHERE kind = ANY(%(friction)s)",
        _one,
    ),
    ("invoices issued", "SELECT count(*) FROM invoices", _int),
    (
        "invoices paid",
        "SELECT count(*) FROM invoices WHERE paid_sim IS NOT NULL",
        _int,
    ),
    (
        "invoices disputed",
        "SELECT count(*) FROM events WHERE kind = 'invoice.disputed'",
        _int,
    ),
    (
        "invoices written off",
        "SELECT count(*) FROM invoices WHERE written_off_sim IS NOT NULL",
        _int,
    ),
    (
        "subscriptions cancelled",
        "SELECT count(*) FROM events WHERE kind = 'subscription.cancelled'",
        _int,
    ),
    ("incidents", "SELECT count(*) FROM incidents", _int),
    (
        "outage hours",
        f"SELECT sum(COALESCE(ended_sim, (SELECT max(sim_time) FROM events)) "
        f"- started_sim) / {HOUR} FROM incidents",
        _int,
    ),
    (
        "outages escalated",
        "SELECT avg((escalated_sim IS NOT NULL)::int) FROM incidents",
        _pct,
    ),
    (
        "escalations raised in the cafe",
        "SELECT avg((payload->>'zone' = 'cafe')::int) FROM events "
        "WHERE kind = 'ticket.escalated'",
        _pct,
    ),
    (
        "tickets opened",
        "SELECT count(*) FROM events WHERE kind IN ('ticket.opened','ticket.reopened')",
        _int,
    ),
    ("encounters", "SELECT count(*) FROM events WHERE kind = 'encounter'", _int),
    ("episodes", "SELECT count(*) FROM episodes", _int),
    (
        "payroll runs held or missed",
        "SELECT count(*) FROM events WHERE kind IN ('payroll.held','payroll.missed')",
        _int,
    ),
    (
        "households' spending, as a share of wages",
        "SELECT (SELECT sum(e.amount_cents) FROM ledger_entries e JOIN accounts a "
        "ON a.id = e.account_id WHERE a.org_id IS NULL AND a.kind = 'expense')::float "
        "/ NULLIF(-(SELECT sum(e.amount_cents) FROM ledger_entries e JOIN accounts a "
        "ON a.id = e.account_id WHERE a.org_id IS NULL AND a.kind = 'revenue'), 0)",
        _pct,
    ),
    *[
        (
            f"{org} cash at the end",
            f"SELECT sum(amount_cents) FROM ledger_entries WHERE account_id = "
            f"'{org}.cash'",
            _dollars,
        )
        for org in ("tallybird", "halloran", "ledgerline", "thirdrail")
    ],
    (
        "cafe sales",
        "SELECT count(*) FROM events WHERE kind = 'cafe.sale'",
        _int,
    ),
    (
        "cafe walkouts",
        "SELECT count(*) FROM events WHERE kind = 'cafe.walkout'",
        _int,
    ),
]


def read(dsn: str) -> list[str]:
    values: list[str] = []
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        for _, query, show in MEASURES:
            try:
                params = {"friction": list(FRICTION)} if "%(" in query else None
                row = conn.execute(query, params).fetchone()  # type: ignore[arg-type]
                value = next(iter(row.values())) if row else None
                values.append(show(value))
            except psycopg.Error:
                values.append("—")
    return values


def main(argv: list[str]) -> int:
    worlds = [arg.split("=", 1) for arg in argv]
    columns = [read(dsn) for _, dsn in worlds]
    print("| measure | " + " | ".join(label for label, _ in worlds) + " |")
    print("|---|" + "---:|" * len(worlds))
    for index, (name, _, _) in enumerate(MEASURES):
        print(f"| {name} | " + " | ".join(col[index] for col in columns) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
