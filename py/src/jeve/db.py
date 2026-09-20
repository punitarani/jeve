"""Database access and migrations.

Numbered SQL files applied in order, recorded in a table, wrapped in a
transaction each. No ORM and no migration framework: the schema is the
interesting artefact (CORE-0007), and a generated one hides the constraints
that carry the invariants.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from jeve.config import find_repo_root

MIGRATIONS = Path(__file__).resolve().parent.parent.parent / "migrations"

DEFAULT_DSN = "postgresql://jeve:jeve@127.0.0.1:55432/jeve"


def dsn() -> str:
    """Connection string.

    The port defaults to 55432, not 5432: connecting to a developer's existing
    Postgres and migrating it would be a bad morning.
    """

    if explicit := os.environ.get("JEVE_DATABASE_URL"):
        return explicit
    port = os.environ.get("JEVE_PG_PORT", "55432")
    return f"postgresql://jeve:jeve@127.0.0.1:{port}/jeve"


@contextmanager
def connect(*, autocommit: bool = False) -> Iterator[Connection[DictRow]]:
    with psycopg.connect(dsn(), row_factory=dict_row, autocommit=autocommit) as conn:
        yield conn


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9]*.sql"))


def applied(conn: Connection[DictRow]) -> set[str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name       text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {row["name"] for row in rows}


def migrate(conn: Connection[DictRow] | None = None) -> list[str]:
    """Apply outstanding migrations. Returns the names applied."""

    if conn is None:
        with connect() as owned:
            return migrate(owned)

    done = applied(conn)
    conn.commit()

    fresh: list[str] = []
    for path in migration_files():
        if path.name in done:
            continue
        # One transaction per migration: a failure leaves the schema at the
        # last complete step rather than half-way through this one.
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,)
            )
        fresh.append(path.name)
    return fresh


def reset(conn: Connection[DictRow]) -> None:
    """Drop everything. For tests and for a deliberate re-seed only."""

    with conn.transaction():
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


def seed_path() -> Path:
    return find_repo_root() / "py" / "fixtures"
