"""Run the golden fixture end to end and report what happened.

    make fixture

    make fixture                       # Jev, replayed from the cassette: free
    make fixture POLICY=rules          # null model N1, no model at all
    make fixture CALLS=record          # live: hit-or-call, appends to the cassette

`--policy rules` is null model N1 from the validation plan, so it doubles as
the baseline a model-driven run is compared against.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jeve import db
from jeve.core.clock import at
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.recorder import finalize_cassette, load_cassette
from jeve.sim import CASSETTE, advance, build_policy
from jeve.sim.runner import policy_from_env
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed


def main() -> int:
    default_policy, default_calls = policy_from_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--seed", type=int, default=ROOT_SEED)
    parser.add_argument("--policy", choices=("rules", "jev"), default=default_policy)
    parser.add_argument("--calls", choices=("record", "replay"), default=default_calls)
    parser.add_argument("--stats", type=Path, help="write call statistics here")
    args = parser.parse_args()

    with db.connect() as conn:
        db.migrate(conn)
        summary = seed(conn, root_seed=args.seed)
        print(
            f"seeded {summary.orgs} orgs, {summary.persons} persons "
            f"({summary.staff} staff + {summary.counterparties} counterparties), "
            f"{summary.invoices} open invoices, {summary.tickets} open tickets"
        )
        if args.policy == "jev":
            # Both modes: a record run must not pay again for what it has.
            loaded = load_cassette(conn, CASSETTE)
            conn.commit()
            print(f"cassette: {loaded} new call(s) preloaded from {CASSETTE.name}")

        policy = build_policy(args.policy, args.calls, root_seed=args.seed)
        engine = Engine(conn, policy, root_seed=args.seed)
        try:
            totals = advance(conn, engine, until=at(args.days))
        finally:
            if isinstance(policy, JevPolicy):
                stats = policy.recorder.stats
                policy.close()
                if args.calls == "record":
                    finalize_cassette(CASSETTE)
                if args.stats is not None:
                    args.stats.write_text(
                        json.dumps(
                            {
                                "mode": args.calls,
                                "asked": stats.lookups,
                                "from_cache": stats.hits,
                                "live_calls": stats.live_calls,
                                "live_usd": round(stats.live_cost_usd, 8),
                            }
                        )
                    )
                print(
                    f"\nmodel calls: {stats.lookups} asked, {stats.hits} from "
                    f"cache, {stats.live_calls} live, ${stats.live_cost_usd:.6f} "
                    f"spent this run ({args.calls})"
                )

        print(
            f"\nran {totals.ticks} ticks over {args.days} sim-days, "
            f"{totals.decisions} decisions ({args.policy})"
        )
        print("\nevents:")
        for kind, count in sorted(totals.events.items()):
            print(f"  {count:6d}  {kind}")

        by_source = conn.execute(
            "SELECT source, count(*) AS n FROM decisions "
            "GROUP BY source ORDER BY source"
        ).fetchall()
        print("\ndecided by:")
        for row in by_source:
            print(f"  {int(row['n']):6d}  {row['source']}")

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
