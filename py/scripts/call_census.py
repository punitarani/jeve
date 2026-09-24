"""What would this world cost Jev? A free census of the calls a run would make.

    make census                 # 5 sim-days on rules, on its own database
    make census DAYS=10

    make census LEVELS=5        # sociability and promptness in quintiles

The field report's headline was that the roster *is* the bill: `agent.tick` was
99.3% of calls, and listing everyone present by name blew 615 distinct contexts
up to 20,826. Whether a change to wording or to *when* a question is asked
helps is a question about distinct requests, and that can be answered without
a key and without a cent: run the world on the rules twin, and for every
decision it takes, render the request Jev would have been sent and hash it.

A rules world is not a Jev world — the answers differ, so the trajectory
differs — but which situations arise, how often, and how many of them are
byte-identical is a property of the question sets and the engine, which is
what this measures. The distinct-request count is the cold-cache bill; the
decisions count is how often somebody was asked at all.

`--levels` answers the trait-resolution question (outline 3.3): tertiles
flatten persona within a bucket (DECIDE-0003), so what would it cost the cache
to render the two traits that carry most in finer steps? The extra levels are
placeholders, distinct words per level: enough to count distinct requests,
never sent anywhere.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from jeve import db
from jeve.core.clock import at
from jeve.decide import gates
from jeve.decide.policy import Decision, DecisionContext, RulesPolicy
from jeve.decide.questions import QUESTION_SETS
from jeve.decide.recorder import call_key
from jeve.llm import DECISION_PIN, DECISION_PREFERENCE, DecisionRequest
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed


class Census(RulesPolicy):
    """The rules twin, taking a note of every request Jev would have been sent."""

    def __init__(self, root_seed: int) -> None:
        super().__init__(root_seed)
        self.asked: Counter[str] = Counter()
        self.gated: Counter[str] = Counter()
        self.distinct: dict[str, set[str]] = {}

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        for ctx in contexts:
            if gates.settle(ctx) is not None:
                self.gated[ctx.kind] += 1
                continue
            prepared = QUESTION_SETS[ctx.kind].prepare(ctx)
            assert prepared.state is not None
            request = DecisionRequest(
                model=DECISION_PREFERENCE[0],
                state=prepared.state,
                questions={ask.key: ask.question for ask in prepared.asks},
            )
            self.asked[ctx.kind] += 1
            self.distinct.setdefault(ctx.kind, set()).add(
                call_key(DECISION_PIN, request.wire_bytes())
            )
        return super().decide_many(contexts)


FINER = ("sociability", "promptness")


def _resolve_traits(levels: int) -> None:
    """Render `FINER` in `levels` steps instead of three, for this process."""

    from jeve.decide import questions

    coarse = questions.trait_level
    for name in FINER:
        words = questions._TRAIT_WORDS[name]
        questions._TRAIT_WORDS[name] = tuple(  # type: ignore[assignment]
            f"{words[min(2, k * 3 // levels)]} (step {k + 1} of {levels})"
            for k in range(levels)
        )

    def finer(name: str, value: object) -> int:
        if name not in FINER:
            return coarse(name, value)
        low, high = questions._TRAIT_RANGE[name]
        number = float(value) if isinstance(value, int | float) else (low + high) / 2
        step = (high - low) / levels
        return max(0, min(levels - 1, int((number - low) / step)))

    questions.trait_level = finer  # type: ignore[assignment]


def _dsn_for(name: str) -> str:
    parts = urlsplit(db.dsn())
    return urlunsplit(parts._replace(path=f"/{name}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make census", description=__doc__)
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--database", default="jeve_census")
    parser.add_argument("--levels", type=int, default=3)
    args = parser.parse_args(argv)
    if args.levels != 3:
        _resolve_traits(args.levels)

    with psycopg.connect(_dsn_for("postgres"), autocommit=True) as admin:
        if not admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (args.database,)
        ).fetchone():
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.database))
            )
    os.environ["JEVE_DATABASE_URL"] = _dsn_for(args.database)

    census = Census(ROOT_SEED)
    with db.connect() as conn:
        db.migrate(conn)
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(conn, census, root_seed=ROOT_SEED)
        advance(conn, engine, until=at(args.days))
        conn.commit()

    kinds = sorted(set(census.asked) | set(census.gated))
    asked = sum(census.asked.values())
    distinct = sum(len(v) for v in census.distinct.values())
    finer = f", {', '.join(FINER)} in {args.levels} steps" if args.levels != 3 else ""
    print(f"# Call census: {args.days} sim-days on rules{finer}\n")
    print("| question set | settled by a gate | asked | distinct requests |")
    print("|---|---:|---:|---:|")
    for kind in kinds:
        print(
            f"| `{kind}` | {census.gated[kind]} | {census.asked[kind]} | "
            f"{len(census.distinct.get(kind, ()))} |"
        )
    print(
        f"| **all** | {sum(census.gated.values())} | {asked} | {distinct} |\n\n"
        f"Cache hit rate if every distinct request were paid for once: "
        f"{1 - distinct / max(1, asked):.1%}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
