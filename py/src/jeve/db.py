"""Database access and migrations.

Numbered SQL files applied in order, recorded in a table, wrapped in a
transaction each. No ORM and no migration framework: the schema is the
interesting artefact (CORE-0007), and a generated one hides the constraints
that carry the invariants.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import psycopg
import psycopg.sql
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from jeve.config import find_repo_root

MIGRATIONS = Path(__file__).resolve().parent.parent.parent / "migrations"

DEFAULT_DSN = "postgresql://jeve:jeve@127.0.0.1:55432/jeve"


def dsn() -> str:
    """The direct connection string — for writers and migrations.

    The port defaults to 55432, not 5432: connecting to a developer's existing
    Postgres and migrating it would be a bad morning. `DATABASE_URL` is the
    fallback because `fly postgres attach` sets exactly that.
    """

    if explicit := os.environ.get("JEVE_DATABASE_URL"):
        return explicit
    if attached := os.environ.get("DATABASE_URL"):
        return attached
    port = os.environ.get("JEVE_PG_PORT", "55432")
    return f"postgresql://jeve:jeve@127.0.0.1:{port}/jeve"


def pooled_dsn() -> str:
    """The API's connection string, through the pooler when there is one.

    `JEVE_DATABASE_POOLED_URL` is the managed side of a Fly Postgres pair;
    without it the API shares `dsn()`. Advisory locks and migrations must
    never use this — a transaction-mode pooler does not hold session state.

    Without a pooled URL it is `dsn()` exactly, never `DATABASE_URL` first:
    with both that and `JEVE_DATABASE_URL` set, the api read one database and
    the daemon wrote the other, and the page showed a world nobody was running.
    """

    return os.environ.get("JEVE_DATABASE_POOLED_URL") or dsn()


# Prepared statements are cached per physical connection; behind a
# transaction-mode pooler the next statement lands on a different one, so the
# name is stale and the query fails. None means never prepare.
KWA = {"prepare_threshold": None}


@contextmanager
def connect(*, autocommit: bool = False) -> Iterator[Connection[DictRow]]:
    with psycopg.connect(
        dsn(), row_factory=dict_row, autocommit=autocommit, **KWA
    ) as conn:
        yield conn


def connect_autocommit() -> Connection[DictRow]:
    """A long-lived connection that commits each statement on its own.

    For writes that must survive the tick they happened in being rolled back —
    a recorded model response has been paid for whatever the tick does next.
    The caller closes it.
    """

    return psycopg.connect(dsn(), row_factory=dict_row, autocommit=True, **KWA)


def connect_pool() -> ConnectionPool[Connection[DictRow]]:
    """The API's shared pool — one per process, opened at lifespan start.

    Read-mostly, autocommit: a pooled connection has no transaction of its own
    to pin. `check` verifies a checkout is alive before handing it to a
    request, which is what keeps a dead pooled backend from becoming a 500.
    """

    return ConnectionPool(
        pooled_dsn(),
        open=False,
        min_size=2,
        max_size=8,
        check=ConnectionPool.check_connection,
        kwargs={"row_factory": dict_row, "autocommit": True, **KWA},
    )


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9]*.sql"))


def applied(conn: Connection[DictRow]) -> set[str]:
    # CREATE ... IF NOT EXISTS still demands CREATE privilege on the schema —
    # Postgres checks the right before it checks existence. On PlanetScale the
    # app role is deliberately denied it (DDL goes through the migrations role),
    # so "are we migrated?" has to be a read first and a create only when the
    # table is genuinely absent, which only a DDL-capable role may reach anyway.
    found = conn.execute(
        "SELECT to_regclass('public.schema_migrations') AS t"
    ).fetchone()
    if found is None or found["t"] is None:
        conn.execute(
            """
            CREATE TABLE schema_migrations (
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


def executemany(
    conn: Connection[DictRow], sql: str, params: Sequence[Sequence[object]]
) -> None:
    """Batch insert. `executemany` lives on the cursor, not the connection."""

    with conn.cursor() as cursor:
        cursor.executemany(sql, params)


# One writer per database (SIM-0001). An arbitrary constant: "jeve" in hex.
WRITER_LOCK_KEY = 0x6A657665


class WriterBusyError(RuntimeError):
    """Another session holds the writer lock on this database."""


def take_writer_lock(conn: Connection[DictRow], *, wait_s: float = 0.0) -> None:
    """Become the one process allowed to advance or reset this world.

    A session-level advisory lock: held until the connection closes, released
    by Postgres itself if the process dies, and re-entrant within a session.
    After a `kill -9` the dead backend can hold it for a moment until Postgres
    notices the socket is gone, which is what `wait_s` is for — without it a
    supervisor's immediate restart loses the race against its own corpse.
    """

    import time  # wall-clock: this is about real processes, not sim time

    deadline = time.monotonic() + wait_s
    while True:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (WRITER_LOCK_KEY,)
        ).fetchone()
        conn.commit()
        if row is not None and row["ok"]:
            return
        if time.monotonic() >= deadline:
            raise WriterBusyError(
                f"another process is writing to {dsn().rsplit('@', 1)[-1]} — "
                "a sim daemon is probably running. Stop it (`make sim-stop`) or "
                "point JEVE_DATABASE_URL somewhere else."
            )
        time.sleep(0.25)


def resync_sequences(conn: Connection[DictRow]) -> int:
    """Set every serial column's sequence to max+1 (WORLD-0002).

    Postgres sequences do not roll back. A tick that dies mid-transaction undoes
    its rows but not the ids it drew, so the re-run gets different `events.seq`
    values — and those are *content*: they appear inside `causes` and payloads.
    With one writer it is safe to simply put the counters back. The columns are
    read from the catalogue, so a table added later is covered without anyone
    remembering to list it here.
    """

    owned = conn.execute(
        """
        SELECT s.oid::regclass::text AS sequence,
               t.oid::regclass::text AS tbl,
               a.attname             AS col
        FROM pg_class s
        JOIN pg_depend d    ON d.objid = s.oid AND d.deptype IN ('a', 'i')
        JOIN pg_class t     ON t.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE s.relkind = 'S' AND t.relnamespace = 'public'::regnamespace
        ORDER BY 1
        """
    ).fetchall()
    for row in owned:
        conn.execute(
            psycopg.sql.SQL(
                "SELECT setval({seq}, COALESCE((SELECT max({col}) FROM {tbl}), 0) + 1, "
                "false)"
            ).format(
                seq=psycopg.sql.Literal(row["sequence"]),
                col=psycopg.sql.Identifier(row["col"]),
                tbl=psycopg.sql.SQL(row["tbl"]),
            )
        )
    return len(owned)


def seed_path() -> Path:
    return find_repo_root() / "py" / "fixtures"
