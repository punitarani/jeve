"""Shared fixtures: the Compose Postgres, and the spend ledger on it.

Database tests skip rather than fail when Postgres is absent (`make check`
still works with no Docker); CI and `make e2e` run them for real.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.rows import DictRow

from jeve import db


def pytest_configure(config: pytest.Config) -> None:
    """Under xdist, each worker gets a database of its own (OPS-0002).

    Every heavy module seeds, truncates or write-locks the one database behind
    `JEVE_DATABASE_URL`, and `test_db` drops its schema outright — two workers
    sharing it would wipe each other's worlds. Worker `gwN` runs on
    `<database>_gwN`, created here if it does not exist yet.

    Written to `os.environ` rather than monkeypatched because the daemon
    subprocesses in `test_resume` and `test_daemon` inherit the environment,
    and they must write to the same database their parent is watching.
    """

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return

    parts = urlsplit(db.dsn())
    name = f"{parts.path.lstrip('/') or 'jeve'}_{worker}"
    os.environ["JEVE_DATABASE_URL"] = urlunsplit(parts._replace(path=f"/{name}"))

    try:
        with psycopg.connect(
            urlunsplit(parts._replace(path="/postgres")), autocommit=True
        ) as admin:
            found = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if found is None:
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
    except psycopg.OperationalError:
        # No server at all: every database fixture skips, exactly as it does
        # without xdist. Anything else — no CREATEDB right, say — propagates
        # and fails the worker loudly. Several workers quietly sharing one
        # database is the failure this hook exists to prevent, and it would
        # show up as an unrelated test being wiped mid-run.
        return


@pytest.fixture(scope="module")
def db_conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as conn:
            yield conn
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


@pytest.fixture
def spend_table(db_conn: Connection[DictRow]) -> Connection[DictRow]:
    """A migrated database with an empty `spend_entries` (LLM-0007).

    Spend is a table now, not a file, so the ledger tests need the same
    Postgres the daemon and API share — and a clean one, since every row is
    real accounting.
    """

    db.migrate(db_conn)
    db_conn.execute("DELETE FROM spend_entries")
    db_conn.commit()
    return db_conn


def counter_points(data: object, name: str) -> dict[tuple[str, ...], float]:
    """Sum-metric points from an `InMemoryMetricReader`, keyed by attributes.

    The OTLP data model nests four levels deep and the point type is a union,
    so reading one number out of it is six lines of narrowing. Written once
    here rather than at each assertion (OBS-0001).
    """

    found: dict[tuple[str, ...], float] = {}
    for resource in getattr(data, "resource_metrics", ()):
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != name:
                    continue
                for point in getattr(metric.data, "data_points", ()):
                    value = getattr(point, "value", None)
                    if value is None:
                        continue
                    attributes = point.attributes or {}
                    key = tuple(f"{k}={attributes[k]}" for k in sorted(attributes))
                    found[key] = float(value)
    return found
