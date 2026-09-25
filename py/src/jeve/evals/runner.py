"""Run one arm on one seed, on a database of its own, through the one run loop.

`python -m jeve.sim` is the only run loop (SIM-0001); this is it, called the
way the soak calls it, with the clock off and a horizon. Each (arm, seed) gets
`jeve_eval_<arm>_<seed>` beside the dev database, so worlds can run in
parallel and be re-measured later for nothing.

Money: each run records to a cassette of its own under `EVAL_CASSETTES`, and
before it starts, every cassette already there — and the golden one — is loaded
into its cache. A situation any earlier run paid for is free here; a prompt
costs money once however many arms and seeds meet it. Files are never shared
for writing, so parallel runs cannot tear each other's lines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from jeve import db
from jeve.config import find_repo_root
from jeve.decide.policy import DecisionContext
from jeve.decide.recorder import load_cassette
from jeve.evals.arms import ARMS, Arm, slug
from jeve.evals.metrics import Measures, measure
from jeve.sim import daemon
from jeve.sim.runner import CASSETTE

EVAL_CASSETTES = find_repo_root() / "ops" / "evals" / "cassettes"
"""Not committed: tens of megabytes per sweep. The report says how to rebuild."""
RUNS = find_repo_root() / "ops" / "evals" / "runs"
"""One JSON file of measures per (arm, seed): small, committed, what the
report is rendered from."""


def database(arm: Arm | str, seed: int) -> str:
    """By name too, so a retired arm's worlds can still be measured and judged."""

    return f"jeve_eval_{slug(arm if isinstance(arm, str) else arm.name)}_{seed}"


def dsn_for(name: str) -> str:
    parts = urlsplit(db.dsn())
    return urlunsplit(parts._replace(path=f"/{name}"))


def ensure_database(name: str) -> str:
    with psycopg.connect(dsn_for("postgres"), autocommit=True) as conn:
        found = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if found is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return dsn_for(name)


def decision_contexts(
    name: str, kind: str, n: int, *, offset: int = 0
) -> list[DecisionContext]:
    """`n` real decisions of `kind` from a finished world, as they were asked,
    in a fixed order (by a hash of the row id, so a first `n` and the next
    never overlap). Decisions keep their facts (WORLD-0013)."""

    with psycopg.connect(dsn_for(name), autocommit=True, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT d.person_id, d.sim_time, d.facts, p.role, p.traits "
            "FROM decisions d JOIN persons p ON p.id = d.person_id "
            "WHERE d.question_set = %s AND d.facts IS NOT NULL "
            "ORDER BY md5(d.id::text) OFFSET %s LIMIT %s",
            (kind, offset, n),
        ).fetchall()
    return [
        DecisionContext(
            person_id=str(r["person_id"]),
            role=str(r["role"]),
            sim_time=int(r["sim_time"]),
            kind=kind,
            facts=dict(r["facts"] or {}),
            traits=dict(r["traits"] or {}),
        )
        for r in rows
    ]


def cassette_for(arm: Arm, seed: int) -> Path:
    return EVAL_CASSETTES / f"{slug(arm.name)}-{seed}.jsonl"


def run(
    arm: Arm, seed: int, days: int, *, calls: str = "record", resume: bool = False
) -> int:
    """Seed the arm's world and run it to `days`. Returns the daemon's exit.

    `resume` carries on a world that stopped short of its horizon (a halt on an
    exhausted upstream budget, say) from its last committed tick, as the
    daemon always resumes (SIM-0001), rather than seeding it again.

    Sets `JEVE_DATABASE_URL` for this process, as the soak does: the recorder,
    the ledger and the gateway each open their own connection, and all of them
    must land on this world's database.
    """

    dsn = ensure_database(database(arm, seed))
    os.environ["JEVE_DATABASE_URL"] = dsn
    os.environ.update(arm.env)
    own = cassette_for(arm, seed)
    if arm.policy == "jev":
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
            db.migrate(conn)
            shared = (
                sorted(EVAL_CASSETTES.glob("*.jsonl"))
                if EVAL_CASSETTES.exists()
                else []
            )
            for path in [CASSETTE, *shared]:
                if path != own:
                    load_cassette(conn, path)
    return daemon.main(
        [
            *("--seed", str(seed)),
            *(() if resume else ("--seed-world",)),
            *("--until-day", str(days)),
            *("--day-minutes", "0"),
            *("--policy", arm.policy),
            *("--calls", calls),
            *("--cassette", str(own)),
            *("--max-wait", "900"),
        ]
    )


def measure_world(arm: Arm, seed: int) -> Measures:
    """Measure a world that has run, and keep the numbers beside the others."""

    with psycopg.connect(
        dsn_for(database(arm, seed)), autocommit=True, row_factory=dict_row
    ) as conn:
        measures = measure(conn)
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{slug(arm.name)}-{seed}.json"
    path.write_text(
        json.dumps(
            {
                "arm": arm.name,
                "against": arm.against,
                "note": arm.note,
                "seed": seed,
                **measures.as_json(),
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    return measures


def arm(name: str) -> Arm:
    if name not in ARMS:
        raise SystemExit(f"no arm {name!r}; known: {', '.join(sorted(ARMS))}")
    return ARMS[name]
