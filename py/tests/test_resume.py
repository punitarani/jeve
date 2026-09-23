"""kill -9, restart, and get the same world (CORE-0007, WORLD-0002).

The claim: a tick is one transaction, so a process killed at *any* instant
leaves the world at the end of its last complete tick, and running it again
produces a world byte-identical to one that was never interrupted.

Argued from the design in session 1; tested here. The child kills itself with
SIGKILL from inside `_emit`, after an event row has been written and before the
tick commits — no handler runs, nothing is flushed. Then it is simply started
again, with no resume flag, because there is no resume procedure.

Runs Jev in strict replay, so the comparison covers model-made decisions,
sampled draws, positions and money — and again on rules, which needs no cassette.
Between recordings the cassette is stale and the Jev arm cannot run; the rules
arm is what keeps this guarantee tested every hour of a working day.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.sim import CASSETTE

pytestmark = pytest.mark.timeout(600)

DAYS = "2"
ARGS = ["--until-day", DAYS, "--day-minutes", "0", "--calls", "replay"]

# Everything that is world state, in a stable order. `seq`, ids and `causes`
# are included on purpose: they are content, and they are exactly what a
# sequence that failed to roll back would change.
TABLES = {
    "events": "seq",
    "decisions": "id",
    "ledger_txns": "id",
    "ledger_entries": "id",
    "positions": "person_id",
    "tickets": "id",
    "invoices": "id",
    "payments": "id",
    "incidents": "id",
    "scheduled": "id",
    "retail_sales": "id",
    "persons": "id",
    "modules": "id",
    "outage_notices": "incident_id, person_id",
    # Stock, prices and lines of credit move with the world (WORLD-0010).
    "orgs": "id",
    "loans": "id",
}


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    if not CASSETTE.exists():
        pytest.skip(f"no cassette at {CASSETTE}")
    try:
        # Autocommit: this connection only *watches* a world another process
        # writes. A plain SELECT would otherwise leave a transaction open, and
        # that holds a lock the daemon's TRUNCATE then waits on for ever.
        with db.connect(autocommit=True) as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def world_hash(conn: Connection[DictRow]) -> dict[str, str]:
    conn.commit()
    hashes: dict[str, str] = {}
    for table, key in TABLES.items():
        digest = hashlib.blake2b(digest_size=16)
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}").fetchall():
            row.pop("created_at", None)
            digest.update(json.dumps(row, sort_keys=True, default=str).encode())
        hashes[table] = digest.hexdigest()
    meta = conn.execute("SELECT sim_time, tick_seq, status FROM sim_meta").fetchone()
    hashes["sim_meta"] = json.dumps(meta, sort_keys=True)
    return hashes


def sim(*extra: str, policy: str, die_at: int = 0) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    env["JEVE_TEST_DIE_AT_EVENT"] = str(die_at)
    # `sys.executable`, not `uv run`: SIGKILL on a wrapper orphans the child it
    # started, which would go on writing while the test restarted a second one.
    return subprocess.run(
        [sys.executable, "-m", "jeve.sim", *extra, "--policy", policy, *ARGS],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("policy", ["rules", "jev"])
def test_a_killed_run_restarted_is_byte_identical_to_one_never_interrupted(
    conn: Connection[DictRow], policy: str
) -> None:
    clean = sim("--seed-world", policy=policy)
    assert clean.returncode == 0, clean.stderr
    expected = world_hash(conn)
    total = conn.execute("SELECT count(*) AS n FROM events").fetchone()
    assert total is not None and int(total["n"]) > 600

    # Three deaths: early in a morning, deep in the first day, and on day two —
    # each somewhere inside a tick, with rows written and not yet committed.
    first = sim("--seed-world", policy=policy, die_at=40)
    assert first.returncode == -signal.SIGKILL, (first.returncode, first.stderr)

    survivors = conn.execute(
        "SELECT count(*) AS n, max(seq) AS top, max(tick_seq) AS tick FROM events"
    ).fetchone()
    # Durable: the ticks before the fatal one were committed and are still here.
    assert survivors is not None and 0 < int(survivors["top"]) < 40
    meta = conn.execute("SELECT tick_seq FROM sim_meta").fetchone()
    # Atomic: no event survives from the tick that was in flight.
    assert meta is not None and int(survivors["tick"]) <= int(meta["tick_seq"])

    for die_at in (275, int(total["n"]) - 150):
        again = sim(policy=policy, die_at=die_at)
        assert again.returncode == -signal.SIGKILL, (again.returncode, again.stderr)

    finished = sim(policy=policy)
    assert finished.returncode == 0, finished.stderr
    if policy == "jev":
        assert "0 live" in finished.stdout

    actual = world_hash(conn)
    differing = [table for table in expected if expected[table] != actual[table]]
    assert differing == [], f"tables that differ after kill-and-resume: {differing}"


def test_the_event_sequence_has_no_gaps_after_the_kills(
    conn: Connection[DictRow],
) -> None:
    """API-0001 promises clients that `seq` is dense, so a cursor can never
    skip an event. That has to stay true after a crash, not just on a good day."""

    gaps = conn.execute(
        "SELECT count(*) AS n FROM (SELECT seq - lag(seq) OVER (ORDER BY seq) AS step "
        "FROM events) s WHERE step > 1"
    ).fetchone()
    assert gaps is not None and int(gaps["n"]) == 0
