"""Run the golden fixture end to end and report what happened.

    make fixture

Rules only by default (no model calls, no network, free). This is also null
model N1 from the validation plan, so it doubles as the baseline any later
model-driven run is compared against.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from jeve import db
from jeve.core.clock import SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.world.engine import Engine, skip_to_next_open
from jeve.world.seed_world import ROOT_SEED, seed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--seed", type=int, default=ROOT_SEED)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    with db.connect() as conn:
        db.migrate(conn)
        summary = seed(conn, root_seed=args.seed)
        print(
            f"seeded {summary.orgs} orgs, {summary.persons} persons "
            f"({summary.staff} staff + {summary.counterparties} counterparties), "
            f"{summary.invoices} open invoices, {summary.tickets} open tickets"
        )

        engine = Engine(conn, RulesPolicy(args.seed), root_seed=args.seed)
        end = at(args.days)
        kinds: Counter[str] = Counter()
        decisions = 0
        ticks = 0

        while True:
            row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
            assert row is not None
            now = SimTime(int(row["sim_time"]))
            if now.seconds >= end:
                break
            if not now.in_office_hours and not now.cafe_open:
                moved = skip_to_next_open(conn)
                if moved >= end:
                    break
                continue
            report = engine.tick()
            ticks += 1
            decisions += report.decisions
            kinds.update(report.events)

        print(f"\nran {ticks} ticks over {args.days} sim-days, {decisions} decisions")
        print("\nevents:")
        for kind, count in sorted(kinds.items()):
            print(f"  {count:6d}  {kind}")

        balance = conn.execute(
            "SELECT COALESCE(sum(amount_cents),0) AS total FROM ledger_entries"
        ).fetchone()
        assert balance is not None
        print(f"\nledger balances: {balance['total'] == 0} (sum={balance['total']})")

        cash = conn.execute(
            "SELECT a.org_id, sum(e.amount_cents) AS cents FROM ledger_entries e "
            "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash' "
            "GROUP BY a.org_id ORDER BY a.org_id"
        ).fetchall()
        print("\ncash:")
        for row in cash:
            print(f"  {row['org_id']:<12} ${int(row['cents']) / 100:>12,.2f}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
