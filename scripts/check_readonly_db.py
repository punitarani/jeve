"""Prove a database URL cannot write, from the database's own catalogue (OPS-0004).

    RO_URL=postgresql://... uv run --directory py python ../scripts/check_readonly_db.py

Reads the URL from `RO_URL`, never argv, so it stays out of `ps` and shell
history. Exit 0: the role holds no INSERT, UPDATE, DELETE or TRUNCATE on any
table in `public` and cannot CREATE there. Exit 1: it can write, and says how
much. Exit 2: no connection. Prints one line either way and never the URL.

The check asks `has_table_privilege`, which counts `pg_write_all_data`, rather
than trusting a config called `agent/prd` or a role called `agents_ro`.
Pointed at production's app role, it reports 26 writable tables.
"""

from __future__ import annotations

import os
import sys

import psycopg

WRITABLE = """
    SELECT count(*) FROM pg_class k JOIN pg_namespace n ON n.oid = k.relnamespace
    WHERE n.nspname = 'public' AND k.relkind IN ('r', 'p')
      AND (has_table_privilege(k.oid, 'INSERT')
           OR has_table_privilege(k.oid, 'UPDATE')
           OR has_table_privilege(k.oid, 'DELETE')
           OR has_table_privilege(k.oid, 'TRUNCATE'))
"""


def main() -> int:
    # Any failure here is exit 2, never 1: a query error must not read as
    # "this role can write", nor as "this role is safe".
    try:
        with psycopg.connect(
            os.environ["RO_URL"], connect_timeout=10, autocommit=True
        ) as conn:
            user = conn.execute("SELECT current_user").fetchone()
            writable = conn.execute(WRITABLE).fetchone()
            create = conn.execute(
                "SELECT has_schema_privilege('public', 'CREATE')"
            ).fetchone()
            seq = conn.execute("SELECT max(seq) FROM events").fetchone()
    except (KeyError, psycopg.Error) as error:
        print(f"unreachable: {type(error).__name__}")
        return 2
    assert user and writable and create and seq
    if writable[0] or create[0]:
        print(f"role {user[0]} CAN WRITE ({writable[0]} tables, CREATE={create[0]})")
        return 1
    print(f"read-only role {user[0]}, events to seq {seq[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
