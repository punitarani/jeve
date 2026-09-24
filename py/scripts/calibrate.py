"""Where does the money go? A free look at a long run on the rules twin.

    make calibrate               # 84 sim-days (twelve weeks), rules, own database
    make calibrate DAYS=180 SEED=7

The scenario asks every firm to run *warm* — cash that moves, runways of weeks
for the cafe and months for the software company — and the field report found
one firm structurally insolvent and three that only accumulated (WORLD-0009).
Tuning prices and costs against a model would cost money for each attempt and
mix the economy's shape up with the model's temperament. This runs the world on
the rules twin, which is free and deterministic, and prints what a person
tuning the constants needs: each firm's cash week by week, what came in and
went out per month, and every consequence the economy can have.

It asserts nothing. The soak asserts invariants; this is for choosing numbers.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from jeve import db
from jeve.core.clock import DAY, at
from jeve.core.orgs import ORGS
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world.economy import household
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed

CONSEQUENCES = (
    "insolvency.warning",
    "payroll.held",
    "payroll.missed",
    "firm.reviewed",
    "prices.raised",
    "loan.taken",
    "loan.repaid",
    "staff.left",
    "staff.hired",
    "firm.failed",
    "rent.late",
    "supplier.paid",
    "supplier.unpaid",
    "tax.paid",
    "households.spent",
)


def _dsn_for(name: str) -> str:
    parts = urlsplit(db.dsn())
    return urlunsplit(parts._replace(path=f"/{name}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make calibrate", description=__doc__)
    parser.add_argument("--days", type=int, default=84)
    parser.add_argument("--seed", type=int, default=ROOT_SEED)
    parser.add_argument("--database", default="jeve_calibrate")
    args = parser.parse_args(argv)

    with psycopg.connect(_dsn_for("postgres"), autocommit=True) as admin:
        if not admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (args.database,)
        ).fetchone():
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.database))
            )
    os.environ["JEVE_DATABASE_URL"] = _dsn_for(args.database)

    with db.connect() as conn:
        db.migrate(conn)
        seed(conn, root_seed=args.seed)
        engine = Engine(conn, RulesPolicy(args.seed), root_seed=args.seed)
        advance(conn, engine, until=at(args.days))
        conn.commit()

        weeks = list(range(0, args.days + 1, 7))
        print(f"# Calibration: {args.days} sim-days on rules, seed {args.seed}\n")
        print("## Cash by week\n")
        print("| account | " + " | ".join(f"d{d}" for d in weeks) + " |")
        print("|---|" + "---:|" * len(weeks))
        accounts = [(f"{o.id}.cash", o.id) for o in ORGS] + [
            (household(o.id), f"households of {o.id}") for o in ORGS
        ]
        for account, label in accounts:
            cells = []
            for day in weeks:
                row = conn.execute(
                    "SELECT COALESCE(sum(e.amount_cents), 0) AS c "
                    "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
                    "WHERE e.account_id = %s "
                    "AND t.sim_time <= %s",
                    (account, day * DAY),
                ).fetchone()
                cells.append(f"${int(row['c']) / 100:,.0f}" if row else "-")
            print(f"| {label} | " + " | ".join(cells) + " |")

        print("\n## Revenue and expense per 28 days\n")
        print("| firm | revenue | expense | net |")
        print("|---|---:|---:|---:|")
        months = max(1.0, args.days / 28)
        for org in ORGS:
            row = conn.execute(
                "SELECT COALESCE(sum(e.amount_cents) FILTER "
                "(WHERE a.kind = 'revenue'), 0) AS r, "
                "COALESCE(sum(e.amount_cents) FILTER "
                "(WHERE a.kind = 'expense'), 0) AS x "
                "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
                "JOIN accounts a ON a.id = e.account_id WHERE a.org_id = %s "
                "AND t.sim_time > 0",
                (org.id,),
            ).fetchone()
            assert row is not None
            revenue, expense = -int(row["r"]) / months, int(row["x"]) / months
            print(
                f"| {org.id} | ${revenue / 100:,.0f} | ${expense / 100:,.0f} | "
                f"${(revenue - expense) / 100:,.0f} |"
            )

        print("\n## Consequences\n")
        print("| event | " + " | ".join(o.id for o in ORGS) + " | all |")
        print("|---|" + "---:|" * (len(ORGS) + 1))
        for kind in CONSEQUENCES:
            rows = {
                str(r["org"]): int(r["n"])
                for r in conn.execute(
                    "SELECT COALESCE(org_id, payload->>'org_id') AS org, count(*) AS n "
                    "FROM events WHERE kind = %s GROUP BY 1",
                    (kind,),
                ).fetchall()
            }
            cells = [str(rows.get(o.id, 0)) for o in ORGS]
            print(f"| `{kind}` | " + " | ".join(cells) + f" | {sum(rows.values())} |")

        reviews = conn.execute(
            "SELECT org_id, payload->>'choice' AS choice, count(*) AS n FROM events "
            "WHERE kind = 'firm.reviewed' GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        if reviews:
            print("\n## What the heads of the firms decided\n")
            for r in reviews:
                print(f"- {r['org_id']}: {r['choice']} x{r['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
