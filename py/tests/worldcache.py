"""Tests that only *read* a world need not each rebuild it.

A five-day run is a few thousand decisions and tens of thousands of statements.
Most tests in a module want the same one and then only query it, so rebuilding
it per test made the suite take minutes for no added confidence.

A finished run stamps `sim_meta.run_id` with a key naming exactly how it was
built. `seed()` resets `run_id`, so anything that reseeds — another test,
another module, a fixture — invalidates the stamp by construction, and a stale
world can never be mistaken for the one a test asked for. A test that changes
the world after building it must not use this.
"""

from __future__ import annotations

from collections.abc import Callable

from psycopg import Connection
from psycopg.rows import DictRow


def build_once(conn: Connection[DictRow], key: str, build: Callable[[], None]) -> bool:
    """Build the world unless the database already holds exactly this one.

    Returns True if it was reused.
    """

    stamp = f"test:{key}"
    conn.commit()
    row = conn.execute(
        "SELECT run_id FROM sim_meta WHERE to_regclass('sim_meta') IS NOT NULL"
    ).fetchone()
    if row is not None and row["run_id"] == stamp:
        conn.commit()
        return True
    build()
    conn.execute("UPDATE sim_meta SET run_id = %s", (stamp,))
    conn.commit()
    return False
