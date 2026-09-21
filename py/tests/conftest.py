"""Shared fixtures: the Compose Postgres, the spend ledger on it, and spans.

Database tests skip rather than fail when Postgres is absent (`make check`
still works with no Docker); CI and `make e2e` run them for real.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.rows import DictRow

from jeve import db, tracing


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


# -- spans (LLM-0008) ------------------------------------------------------


@dataclass
class RecordedSpan:
    """One span, flattened. `log()` merges the way Braintrust merges."""

    name: str
    type: str | None
    parent: str | None
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    children: list[RecordedSpan] = field(default_factory=list)

    def log(self, **event: Any) -> None:
        for key, value in event.items():
            existing = self.fields.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                self.fields[key] = existing | value
            else:
                self.fields[key] = value

    def export(self) -> str:
        return f"span:{id(self):x}"

    def descendants(self) -> Iterator[RecordedSpan]:
        for child in self.children:
            yield child
            yield from child.descendants()


class RecordingSink:
    """The test seam from `jeve.tracing.configure(sink=...)`.

    Keeps the nesting the way the real sink does: a span opened inside another
    span's `with` block is its child, unless an explicit `parent` handle says
    otherwise — which is what crossing `JevPolicy._Bridge` looks like.
    """

    def __init__(self) -> None:
        self.roots: list[RecordedSpan] = []
        self.spans: list[RecordedSpan] = []
        self.flushes = 0
        self._open: list[RecordedSpan] = []

    def start_span(
        self, name: str, *, type: str | None, parent: str | None, **event: Any
    ) -> _RecordingContext:
        span = RecordedSpan(name=name, type=type, parent=parent)
        span.log(**event)
        self.spans.append(span)
        under = (
            self._by_handle(parent)
            if parent
            else (self._open[-1] if self._open else None)
        )
        if under is None:
            self.roots.append(span)
        else:
            under.children.append(span)
        return _RecordingContext(self, span)

    def flush(self) -> None:
        self.flushes += 1

    def named(self, name: str) -> list[RecordedSpan]:
        return [span for span in self.spans if span.name == name]

    def only(self, name: str) -> RecordedSpan:
        found = self.named(name)
        assert len(found) == 1, f"expected one {name!r} span, got {len(found)}"
        return found[0]

    def _by_handle(self, handle: str) -> RecordedSpan | None:
        return next((s for s in self.spans if s.export() == handle), None)


class _RecordingContext:
    def __init__(self, sink: RecordingSink, span: RecordedSpan) -> None:
        self._sink = sink
        self._span = span

    def __enter__(self) -> RecordedSpan:
        self._sink._open.append(self._span)
        return self._span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._sink._open.pop()
        if exc is not None:
            self._span.error = f"{type(exc).__name__}: {exc}"


class ExplodingSink(RecordingSink):
    """A sink that fails the way a broken Braintrust would."""

    def start_span(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("braintrust is having a moment")


@pytest.fixture
def spans() -> Iterator[RecordingSink]:
    """Tracing on, pointed at memory. Nothing leaves the process."""

    sink = RecordingSink()
    tracing.configure(sink=sink)
    try:
        yield sink
    finally:
        tracing.reset()


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No span leaves the process unless a test asks for one.

    Dropping the key rather than only resetting state, because a developer
    with `BRAINTRUST_API_KEY` exported must still get an offline run: "every
    module testable without network" is not conditional on someone's shell.
    """

    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    tracing.reset()
    yield
    tracing.reset()
