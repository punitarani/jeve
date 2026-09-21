"""Shared fixtures: the Compose Postgres, and the spend ledger on it.

Database tests skip rather than fail when Postgres is absent (`make check`
still works with no Docker); CI and `make e2e` run them for real.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db


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
