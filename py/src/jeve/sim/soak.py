"""`make soak`: run the world for weeks and check that it is still a world.

    make soak                                  # 35 days on rules: free, ~1 min
    make soak POLICY=jev CALLS=record DAYS=10  # live; spends money
    make soak COUNTERFACTUAL=1                 # the same run without the outage

Nothing ran the world past eight days until the audit did, and over thirty it
wound down: support fell silent, receivables were never collected, month-end
came once (WORLD-0005). This is the horizon test that would have caught it.

The checks are **invariants, not outcomes**. A firm may go under; the soak asks
only that it was seen going under, with the numbers that explain it. Tuning a
constant until a firm survives would make this pass and mean nothing.

Runs on a database of its own (`jeve_soak`), through the same daemon loop as
everything else (SIM-0001), with its own cassette so that a long live run never
rewrites the file `make e2e` replays.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row

from jeve import db
from jeve.config import find_repo_root
from jeve.core.clock import DAY, HOUR, SimTime
from jeve.core.orgs import ORGS
from jeve.sim import daemon
from jeve.world.engine import FRICTION
from jeve.world.seed_world import ROOT_SEED, seed

REPORTS = {
    # Free, and what `make soak` and its test assert on.
    "rules": find_repo_root() / "ops" / "soak.md",
    # Costs money, so it is run at gates and kept beside the other as evidence.
    "jev": find_repo_root() / "ops" / "soak.live.md",
}
SOAK_CASSETTE = find_repo_root() / "ops" / "soak.cassette.jsonl"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _one(conn: Connection[DictRow], query: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type, unused-ignore]
    assert row is not None
    value = next(iter(row.values()))
    return int(value or 0)


# -- invariants -----------------------------------------------------------------


def checks(conn: Connection[DictRow], *, days: int) -> list[Check]:
    end = days * DAY
    out: list[Check] = []

    total = _one(conn, "SELECT COALESCE(sum(amount_cents),0) FROM ledger_entries")
    out.append(
        Check("the ledger balances", total == 0, f"sum of all entries = {total}")
    )

    # Support is alive wherever there was something to report.
    late_incidents = _one(
        conn,
        "SELECT count(*) FROM incidents WHERE started_sim >= %s",
        (end - 14 * DAY,),
    )
    late_tickets = _one(
        conn,
        "SELECT count(*) FROM events WHERE kind IN ('ticket.opened','ticket.reopened') "
        "AND sim_time >= %s",
        (end - 14 * DAY,),
    )
    stale = _one(
        conn,
        "SELECT count(*) FROM tickets WHERE status = 'answered' AND answered_sim < %s",
        (end - 4 * DAY,),
    )
    out.append(
        Check(
            "tickets end, and support is still hearing from people",
            stale == 0 and (late_incidents == 0 or late_tickets > 0),
            f"{late_tickets} ticket(s) opened in the last 14 days against "
            f"{late_incidents} incident(s); {stale} answered ticket(s) left open "
            "more than four days",
        )
    )

    months = _one(conn, "SELECT count(*) FROM events WHERE kind = 'month.end'")
    closes = _one(
        conn,
        "SELECT count(DISTINCT (payload->>'client') || ':' || (sim_time / %s)::text) "
        "FROM events WHERE kind = 'close.completed'",
        (28 * DAY,),
    )
    expected_months = 1 + (days - 4) // 28 if days >= 4 else 0
    out.append(
        Check(
            "months recur",
            months >= expected_months and (days < 34 or closes >= 4),
            f"{months} month-end(s) in {days} days (expected {expected_months}); "
            f"{closes} monthly close(s) completed",
        )
    )

    # Nobody's bill is forgotten: anything overdue has been thought about lately.
    ignored = _one(
        conn,
        "SELECT count(*) FROM invoices WHERE paid_sim IS NULL "
        "AND written_off_sim IS NULL AND due_sim < %s "
        "AND (asked_day IS NULL OR asked_day < %s)",
        (end - 5 * DAY, days - 5),
    )
    ancient = _one(
        conn,
        "SELECT count(*) FROM invoices WHERE paid_sim IS NULL "
        "AND written_off_sim IS NULL AND due_sim < %s",
        (end - 63 * DAY,),
    )
    out.append(
        Check(
            "every overdue bill is being answered",
            ignored == 0 and ancient == 0,
            f"{ignored} overdue bill(s) nobody has been asked about in five days; "
            f"{ancient} more than 63 days past due and not written off",
        )
    )

    # Wages arrive somewhere and come back as demand. Households are accounts
    # without an org, one set per employer (WORLD-0010).
    wages = -_one(
        conn,
        "SELECT COALESCE(sum(e.amount_cents),0) FROM ledger_entries e "
        "JOIN accounts a ON a.id = e.account_id "
        "WHERE a.org_id IS NULL AND a.kind = 'revenue'",
    )
    spent = _one(
        conn,
        "SELECT COALESCE(sum(e.amount_cents),0) FROM ledger_entries e "
        "JOIN accounts a ON a.id = e.account_id "
        "WHERE a.org_id IS NULL AND a.kind = 'expense'",
    )
    # The field report's households took in $759k and spent $10.6k: a sink.
    out.append(
        Check(
            "wages come back as demand",
            days < 14 or (wages > 0 and spent >= wages // 2),
            f"households were paid ${wages / 100:,.0f} and spent ${spent / 100:,.0f}",
        )
    )

    # Nobody spends money they do not have: every cash account, firm or
    # household, stays at or above zero at every moment of the run.
    overdrawn = [
        str(r["account_id"])
        for r in conn.execute(
            "SELECT account_id FROM (SELECT e.account_id, sum(e.amount_cents) OVER "
            "(PARTITION BY e.account_id ORDER BY t.sim_time, e.id) AS running "
            "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
            "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash') s "
            "GROUP BY account_id HAVING min(running) < 0 ORDER BY 1"
        ).fetchall()
    ]
    out.append(
        Check(
            "no cash account is ever overdrawn",
            not overdrawn,
            "overdrawn: " + ", ".join(overdrawn) if overdrawn else "none",
        )
    )

    # A warning is read (WORLD-0010). It used to be emitted every week and read
    # by nothing (field report, finding 2): the head of the firm looks within
    # a week, or had just looked.
    unread = _one(
        conn,
        "SELECT count(*) FROM events w WHERE w.kind = 'insolvency.warning' "
        "AND w.sim_time < %s AND NOT EXISTS (SELECT 1 FROM events r "
        "  WHERE r.kind = 'firm.reviewed' AND r.org_id = w.org_id "
        "  AND r.sim_time BETWEEN w.sim_time - %s AND w.sim_time + %s)",
        (end - 7 * DAY, 7 * DAY, 7 * DAY),
    )
    out.append(
        Check(
            "an insolvency warning is answered by the head of the firm",
            unread == 0,
            f"{unread} warning(s) with no review within a week",
        )
    )

    # A firm may fail. It may not fail unexplained.
    unexplained: list[str] = []
    for org in ORGS:
        low = conn.execute(
            "SELECT min(running) AS low FROM (SELECT sum(e.amount_cents) OVER "
            "(ORDER BY t.sim_time, e.id) AS running FROM ledger_entries e "
            "JOIN ledger_txns t ON t.id = e.txn_id WHERE e.account_id = %s) s",
            (f"{org.id}.cash",),
        ).fetchone()
        wages_row = conn.execute(
            "SELECT COALESCE(max((payload->>'amount_cents')::bigint),0) AS w "
            "FROM events WHERE kind IN ('payroll.paid','payroll.held') AND org_id = %s",
            (org.id,),
        ).fetchone()
        lowest = int(low["low"] or 0) if low else 0
        weekly = int(wages_row["w"] or 0) if wages_row else 0
        warned = _one(
            conn,
            "SELECT count(*) FROM events WHERE kind = 'insolvency.warning' "
            "AND org_id = %s AND payload->>'cause' IS NOT NULL",
            (org.id,),
        )
        if weekly and lowest < weekly and warned == 0:
            unexplained.append(f"{org.id} (low ${lowest / 100:,.0f})")
    out.append(
        Check(
            "a firm running out of money was seen running out, with a cause",
            not unexplained,
            "unexplained: " + ", ".join(unexplained)
            if unexplained
            else "none unexplained",
        )
    )

    # No segment of the outside world is structurally shut out. The audit (B8)
    # found 251 of 400 counterparties never acted: `ORDER BY id LIMIT 12` billed
    # the same twelve clients every month for ever. "Reached" is billed or
    # deciding; a firm whose reach stays at one month's cohort has that bug.
    reached = conn.execute(
        "SELECT p.org_id, count(*) AS n FROM persons p WHERE p.kind = 'counterparty' "
        "AND (EXISTS (SELECT 1 FROM decisions d WHERE d.person_id = p.id) "
        "  OR EXISTS (SELECT 1 FROM invoices i WHERE i.to_person_id = p.id)) "
        "GROUP BY p.org_id"
    ).fetchall()
    acted = conn.execute(
        "SELECT p.org_id, count(DISTINCT d.person_id) AS n FROM decisions d "
        "JOIN persons p ON p.id = d.person_id WHERE p.kind = 'counterparty' "
        "GROUP BY p.org_id"
    ).fetchall()
    reach = {str(r["org_id"]): int(r["n"]) for r in reached}
    acts = {str(r["org_id"]): int(r["n"]) for r in acted}
    floor = 20 if days >= 32 else 5
    out.append(
        Check(
            "the economy reaches more than one month's clients",
            all(reach.get(org.id, 0) >= floor for org in ORGS),
            ", ".join(
                f"{org.id} {reach.get(org.id, 0)} reached / {acts.get(org.id, 0)} "
                "decided, of 100"
                for org in ORGS
            ),
        )
    )

    # Somebody, somewhere, falls out with somebody every week. The golden field
    # report counted no dispute, write-off or refusal in a month (WORLD-0011).
    quiet = [
        week + 1
        for week in range(1, days // 7)
        if _one(
            conn,
            "SELECT count(*) FROM events WHERE kind = ANY(%s) "
            "AND sim_time >= %s AND sim_time < %s",
            (list(FRICTION), week * 7 * DAY, (week + 1) * 7 * DAY),
        )
        == 0
    ]
    out.append(
        Check(
            "every week has friction in it",
            not quiet,
            "weeks with none: " + ", ".join(map(str, quiet)) if quiet else "every week",
        )
    )

    # A complaint passed to support or the account manager is decided on, not
    # parked: a handoff still queued an hour after it was due is one lost
    # (WORLD-0012).
    parked = _one(
        conn,
        "SELECT count(*) FROM scheduled WHERE kind = 'escalation.handoff' "
        "AND due_sim_time < %s",
        (end - HOUR,),
    )
    handed = _one(
        conn,
        "SELECT count(*) FROM decisions WHERE question_set = 'escalation.handoff'",
    )
    out.append(
        Check(
            "an escalation handed on is decided within the hour",
            parked == 0,
            f"{handed} handoff(s) decided, {parked} still queued past due",
        )
    )

    # The loops that run on a calendar decide something every time they are
    # due. A job that never reaches its question is a loop that is not there.
    silent = [
        kind
        for kind in SCHEDULED_KINDS
        if _one(conn, "SELECT count(*) FROM decisions WHERE question_set = %s", (kind,))
        == 0
    ]
    out.append(
        Check(
            "every loop on a calendar decides something",
            days < 14 or not silent,
            "silent: " + ", ".join(silent) if silent else ", ".join(SCHEDULED_KINDS),
        )
    )
    return out


SCHEDULED_KINDS: tuple[str, ...] = (
    # Asked on their own calendar, whatever else happens (WORLD-0010, WORLD-0011).
    "eng.allocation",
    "deploy.decision",
    "time.log",
    "supplier.order",
    "founder.review",
    "invoice.dispute",
    "payment.timing",
    "payroll.release",
    "close.order",
)


# -- measures: reported, never asserted ------------------------------------------


def _cash_by_week(conn: Connection[DictRow], days: int) -> list[str]:
    weeks = list(range(0, days + 1, 7))
    if weeks[-1] != days:
        weeks.append(days)
    lines = [
        "| firm | " + " | ".join(f"d{d}" for d in weeks) + " |",
        "|---|" + "---:|" * len(weeks),
    ]
    for account, label in [(f"{o.id}.cash", o.id) for o in ORGS] + [
        ("households.%.cash", "households")
    ]:
        cells = []
        for day in weeks:
            cents = _one(
                conn,
                "SELECT COALESCE(sum(e.amount_cents),0) FROM ledger_entries e "
                "JOIN ledger_txns t ON t.id = e.txn_id "
                "WHERE e.account_id LIKE %s AND t.sim_time <= %s",
                (account, day * DAY),
            )
            cells.append(f"${cents / 100:,.0f}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def measures(conn: Connection[DictRow], *, days: int) -> list[str]:
    lines = ["### Cash, by week", "", *_cash_by_week(conn, days), ""]

    lines += ["### Receivables", ""]
    rec = conn.execute(
        "SELECT from_org_id AS org, count(*) AS issued, "
        " count(*) FILTER (WHERE paid_sim IS NOT NULL) AS paid, "
        " count(*) FILTER (WHERE written_off_sim IS NOT NULL) AS written_off, "
        " count(*) FILTER (WHERE chased_sim IS NOT NULL) AS chased, "
        " COALESCE(sum(amount_cents) FILTER (WHERE paid_sim IS NULL "
        "   AND written_off_sim IS NULL), 0) AS outstanding, "
        " COALESCE(avg((paid_sim - due_sim) / 86400.0) "
        "   FILTER (WHERE paid_sim IS NOT NULL), 0)::float8 AS mean_days_late "
        "FROM invoices GROUP BY from_org_id ORDER BY from_org_id"
    ).fetchall()
    lines += [
        "| issuer | issued | paid | chased | written off | outstanding | "
        "paid, mean days after due |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rec:
        lines.append(
            f"| {r['org']} | {r['issued']} | {r['paid']} | {r['chased']} | "
            f"{r['written_off']} | ${int(r['outstanding']) / 100:,.0f} | "
            f"{float(r['mean_days_late']):+.1f} |"
        )

    lines += ["", "### Tickets, by week opened", ""]
    tickets = conn.execute(
        "SELECT (opened_sim / %s)::int AS week, count(*) AS opened, "
        " count(*) FILTER (WHERE status = 'closed') AS closed, "
        " COALESCE(sum(reopened),0) AS reopened FROM tickets WHERE opened_sim >= 0 "
        "GROUP BY 1 ORDER BY 1",
        (7 * DAY,),
    ).fetchall()
    lines += ["| week | opened | closed | reopened |", "|---:|---:|---:|---:|"]
    lines += [
        f"| {t['week']} | {t['opened']} | {t['closed']} | {t['reopened']} |"
        for t in tickets
    ]

    lines += ["", "### Decisions", ""]
    decisions = conn.execute(
        "SELECT question_set, source, count(*) AS n FROM decisions "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    total = sum(int(d["n"]) for d in decisions) or 1
    lines += ["| question set | decided by | n | share |", "|---|---|---:|---:|"]
    lines += [
        f"| `{d['question_set']}` | {d['source']} | {d['n']} | "
        f"{int(d['n']) / total:.1%} |"
        for d in decisions
    ]

    lines += ["", "### Events", ""]
    events = conn.execute(
        "SELECT kind, count(*) AS n FROM events GROUP BY kind ORDER BY kind"
    ).fetchall()
    lines += ["| kind | n |", "|---|---:|"]
    lines += [f"| `{e['kind']}` | {e['n']} |" for e in events]

    warnings = conn.execute(
        "SELECT org_id, sim_time, payload FROM events "
        "WHERE kind = 'insolvency.warning' ORDER BY seq"
    ).fetchall()
    if warnings:
        lines += ["", "### Insolvency warnings", ""]
        lines += ["| when | firm | cash | weekly wages | overdue to them | cause |"]
        lines += ["|---|---|---:|---:|---:|---|"]
        for w in warnings:
            p = w["payload"]
            lines.append(
                f"| {SimTime(int(w['sim_time']))} | {w['org_id']} | "
                f"${int(p['cash_cents']) / 100:,.0f} | "
                f"${int(p['weekly_wages_cents']) / 100:,.0f} | "
                f"${int(p['overdue_receivables_cents']) / 100:,.0f} | {p['cause']} |"
            )
    return lines


# -- the counterfactual -------------------------------------------------------------


def compare(with_outage: Connection[DictRow], calm: Connection[DictRow]) -> list[str]:
    """The same world with and without the scheduled month-end outage.

    CORE-0009's claim, stated as two numbers: the same invoices are for the same
    amounts in both arms (randomness is about the invoice, not about when it
    went out), and the firms' cash is *not* the same (the outage moved money).
    """

    def invoices(
        conn: Connection[DictRow],
    ) -> dict[tuple[str, str, int], tuple[int, int]]:
        # The law firm bills the hours it logged (WORLD-0011), and logging is
        # behaviour, which the counterfactual is allowed to change. What is
        # still a draw about the client and the month is everyone else's work.
        # The work as drawn: a firm may have raised its prices, or discounted
        # a disputed bill since, and both of those are behaviour too.
        rows = conn.execute(
            "SELECT i.from_org_id, COALESCE(i.to_person_id, i.to_org_id) AS payer, "
            " COALESCE((e.payload->>'work_cents')::bigint, "
            "   (e.payload->>'amount_cents')::bigint, i.amount_cents) "
            "   AS amount_cents, i.issued_sim "
            "FROM invoices i LEFT JOIN events e ON e.seq = i.issued_seq "
            "WHERE i.kind = 'services' AND i.issued_sim >= 0 "
            "AND i.to_person_id IS NOT NULL AND i.from_org_id <> 'halloran' "
            "ORDER BY i.id"
        ).fetchall()
        seen: dict[tuple[str, str, int], tuple[int, int]] = {}
        for r in rows:
            key = (
                str(r["from_org_id"]),
                str(r["payer"]),
                int(r["issued_sim"]) // (28 * DAY),
            )
            seen[key] = (int(r["amount_cents"]), int(r["issued_sim"]))
        return seen

    a, b = invoices(with_outage), invoices(calm)
    both = sorted(set(a) & set(b))
    same_amount = sum(1 for k in both if a[k][0] == b[k][0])
    moved = sum(1 for k in both if a[k][1] != b[k][1])
    lines = [
        "| | outage | no outage |",
        "|---|---:|---:|",
        f"| month-end client invoices issued | {len(a)} | {len(b)} |",
        f"| issued in both arms | {len(both)} | {len(both)} |",
        f"| of those, same amount in both arms | {same_amount} | {same_amount} |",
        f"| of those, issued at a different time | {moved} | {moved} |",
    ]
    differs = False
    for org in ORGS:
        x = _one(
            with_outage,
            "SELECT COALESCE(sum(amount_cents),0) FROM ledger_entries "
            "WHERE account_id = %s",
            (f"{org.id}.cash",),
        )
        y = _one(
            calm,
            "SELECT COALESCE(sum(amount_cents),0) FROM ledger_entries "
            "WHERE account_id = %s",
            (f"{org.id}.cash",),
        )
        differs = differs or x != y
        lines.append(
            f"| {org.id} cash at the end | ${x / 100:,.2f} | ${y / 100:,.2f} |"
        )
    lines += [
        "",
        f"**Invoice amounts constant across arms:** "
        f"{'yes' if both and same_amount == len(both) else 'NO'} "
        f"({same_amount} of {len(both)}). "
        f"**Cash differs across arms:** {'yes' if differs else 'NO'}.",
    ]
    return lines


def counterfactual_holds(
    with_outage: Connection[DictRow], calm: Connection[DictRow]
) -> Check:
    text = "\n".join(compare(with_outage, calm))
    ok = "constant across arms:** yes" in text and "differs across arms:** yes" in text
    return Check(
        "the outage moves money without re-rolling it",
        ok,
        "invoice amounts identical across arms and cash different"
        if ok
        else "see the counterfactual table",
    )


# -- running it ---------------------------------------------------------------------


def _dsn_for(name: str) -> str:
    parts = urlsplit(db.dsn())
    return urlunsplit(parts._replace(path=f"/{name}"))


def _watch(name: str) -> Connection[DictRow]:
    """A read-only look at one of the soak's databases."""

    return psycopg.connect(_dsn_for(name), row_factory=dict_row, autocommit=True)


def _ensure_database(name: str) -> None:
    admin = _dsn_for("postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if exists is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def run_world(
    name: str,
    *,
    days: int,
    policy: str,
    calls: str,
    outage: bool,
    max_wait: float,
) -> int:
    """Seed `name` and run it to `days` through the daemon loop. Returns its exit."""

    _ensure_database(name)
    os.environ["JEVE_DATABASE_URL"] = _dsn_for(name)
    with db.connect() as conn:
        db.migrate(conn)
        seed(conn, root_seed=ROOT_SEED)
        if not outage:
            conn.execute(
                "DELETE FROM scheduled WHERE kind = 'incident.start' "
                "AND subject_id = 'invoicing'"
            )
        conn.commit()
    return daemon.main(
        [
            *("--until-day", str(days)),
            *("--day-minutes", "0"),
            *("--policy", policy),
            *("--calls", calls),
            *("--cassette", str(SOAK_CASSETTE)),
            *("--max-wait", str(max_wait)),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make soak", description=__doc__)
    parser.add_argument("--days", type=int, default=35)
    parser.add_argument("--policy", choices=("rules", "jev"), default="rules")
    parser.add_argument("--calls", choices=("record", "replay"), default="replay")
    parser.add_argument("--counterfactual", action="store_true")
    parser.add_argument("--database", default="jeve_soak")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--max-wait", type=float, default=900.0)
    args = parser.parse_args(argv)

    before = os.environ.get("JEVE_DATABASE_URL")
    try:
        code = run_world(
            args.database,
            days=args.days,
            policy=args.policy,
            calls=args.calls,
            outage=True,
            max_wait=args.max_wait,
        )
        if code != 0:
            print(f"the world stopped early (exit {code}); no report", file=sys.stderr)
            return code
        calm = f"{args.database}_calm"
        if args.counterfactual:
            code = run_world(
                calm,
                days=args.days,
                policy=args.policy,
                calls=args.calls,
                outage=False,
                max_wait=args.max_wait,
            )
            if code != 0:
                return code

        with _watch(args.database) as conn:
            results = checks(conn, days=args.days)
            body = measures(conn, days=args.days)
            spend = conn.execute(
                "SELECT count(*) AS calls, COALESCE(sum(c.cost_usd),0)::float8 AS usd "
                "FROM model_calls c WHERE c.hash IN (SELECT DISTINCT model_call "
                "FROM decisions WHERE model_call IS NOT NULL)"
            ).fetchone()
            versus: list[str] = []
            if args.counterfactual:
                with _watch(calm) as other:
                    results.append(counterfactual_holds(conn, other))
                    versus = compare(conn, other)
    finally:
        if before is None:
            os.environ.pop("JEVE_DATABASE_URL", None)
        else:
            os.environ["JEVE_DATABASE_URL"] = before

    ok = all(check.ok for check in results)
    report = args.report or REPORTS[args.policy]
    calls = int(spend["calls"]) if spend else 0
    usd = float(spend["usd"]) if spend else 0.0
    lines = [
        f"# Soak: {args.days} sim-days, decided by `{args.policy}`",
        "",
        "Written by `make soak`. Invariants, not outcomes: a firm may fail here; it "
        "may not fail unexplained (WORLD-0005).",
        "",
        f"**{'PASS' if ok else 'FAIL'}** — {sum(c.ok for c in results)} of "
        f"{len(results)} invariants hold."
        + (
            f" Distinct model calls behind this run: {calls} (${usd:.4f}, "
            f"${usd / max(1, args.days):.4f} per sim-day)."
            if args.policy == "jev"
            else ""
        ),
        "",
        "| invariant | holds | evidence |",
        "|---|---|---|",
        *[
            f"| {c.name} | {'yes' if c.ok else '**NO**'} | {c.detail} |"
            for c in results
        ],
        "",
    ]
    if versus:
        lines += ["## Counterfactual: the same world without the month-end outage", ""]
        lines += [*versus, ""]
    lines += ["## Measures (reported, not asserted)", "", *body, ""]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines))
    for check in results:
        print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    print(f"\n{'PASS' if ok else 'FAIL'}  report: {report}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
