"""Record and replay of model calls, keyed by content hash (DECIDE-0003).

`model_calls` is a cache, not world state: it survives a reseed, and a row is
the raw response exactly as it arrived. Three consequences follow.

- A decision is always made **from the stored row**, even on the call that
  created it. Postgres JSONB reorders keys and normalises numbers, so deciding
  from the in-memory response on a miss and from the row on a hit would be two
  code paths that can disagree. There is one.
- Writes go through their own autocommit connection, outside the tick's
  transaction. A tick that rolls back must not un-record a response that was
  paid for.
- In `replay` mode a miss is an error naming the question set. It never falls
  back to rules: a replay that quietly substitutes a different decider is not a
  replay.

The cassette is the same rows as sorted JSON lines, so a clean clone can run the
whole simulation without a key.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.hashing import content_hash
from jeve.errors import JeveError

type Mode = Literal["record", "replay"]


class ReplayMissError(JeveError):
    """Strict replay was asked for a call the cassette does not hold."""


@dataclass(frozen=True, slots=True)
class StoredCall:
    hash: str
    model: str
    response: dict[str, Any]
    input_tokens: int
    cost_usd: float


@dataclass(slots=True)
class RecorderStats:
    lookups: int = 0
    hits: int = 0
    live_calls: int = 0
    live_cost_usd: float = 0.0
    by_kind: dict[str, int] = field(default_factory=dict)


def request_hash(model: str, state: object, questions: object) -> str:
    """The cache key: what is asked, of which model. Nothing about who asks."""

    return content_hash({"model": model, "state": state, "questions": questions})


class Recorder:
    def __init__(self, *, mode: Mode, cassette: Path | None = None) -> None:
        self.mode: Mode = mode
        self._cassette = cassette
        self._conn: Connection[DictRow] | None = None
        self.stats = RecorderStats()

    def _connection(self) -> Connection[DictRow]:
        if self._conn is None or self._conn.closed:
            self._conn = db.connect_autocommit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    # -- reads -------------------------------------------------------------

    def lookup(self, hashes: Iterable[str]) -> dict[str, StoredCall]:
        wanted = sorted(set(hashes))
        if not wanted:
            return {}
        rows = self._connection().execute(
            "SELECT hash, model, response, input_tokens, cost_usd "
            "FROM model_calls WHERE hash = ANY(%s)",
            (wanted,),
        )
        return {
            str(row["hash"]): StoredCall(
                hash=str(row["hash"]),
                model=str(row["model"]),
                response=dict(row["response"]),
                input_tokens=int(row["input_tokens"]),
                cost_usd=float(row["cost_usd"]),
            )
            for row in rows.fetchall()
        }

    # -- writes ------------------------------------------------------------

    def store(
        self,
        call_hash: str,
        *,
        kind: str,
        model: str,
        provider: str | None,
        request: dict[str, Any],
        response: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cost_estimated: bool,
        latency_s: float,
    ) -> None:
        """Keep a response. First writer wins; a duplicate is dropped."""

        row = {
            "hash": call_hash,
            "kind": kind,
            "model": model,
            "provider": provider,
            "request": request,
            "response": response,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "cost_estimated": cost_estimated,
            "latency_s": round(latency_s, 4),
        }
        inserted = insert_call(self._connection(), row)
        self.stats.live_calls += 1
        self.stats.live_cost_usd += cost_usd
        if inserted and self._cassette is not None:
            # Write-through: a run that dies halfway keeps what it paid for.
            self._cassette.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cassette, "a") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def note(self, kind: str, *, hit: bool) -> None:
        self.stats.lookups += 1
        self.stats.hits += 1 if hit else 0
        self.stats.by_kind[kind] = self.stats.by_kind.get(kind, 0) + 1


def insert_call(conn: Connection[DictRow], row: dict[str, Any]) -> bool:
    """Keep one model response. First writer wins. True if this row was new."""

    cursor = conn.execute(
        "INSERT INTO model_calls (hash, kind, model, provider, request, response, "
        "input_tokens, output_tokens, cost_usd, cost_estimated, latency_s) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (hash) DO NOTHING",
        (
            row["hash"],
            row.get("kind", ""),
            row["model"],
            row.get("provider"),
            json.dumps(row.get("request")),
            json.dumps(row["response"]),
            int(row.get("input_tokens", 0)),
            int(row.get("output_tokens", 0)),
            float(row.get("cost_usd", 0.0)),
            bool(row.get("cost_estimated", False)),
            float(row.get("latency_s", 0.0)),
        ),
    )
    return cursor.rowcount == 1


def load_cassette(conn: Connection[DictRow], path: Path) -> int:
    """Preload a cassette into `model_calls`. Returns how many rows were new."""

    if not path.exists():
        return 0
    added = 0
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn final line from a killed recording run
            added += 1 if insert_call(conn, row) else 0
    return added


def finalize_cassette(path: Path) -> int:
    """Sort and de-duplicate, so the committed file diffs cleanly.

    Append order is call-completion order, which depends on network timing.
    Sorted by hash, the same set of calls is the same file.
    """

    if not path.exists():
        return 0
    rows: dict[str, str] = {}
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.setdefault(str(parsed["hash"]), json.dumps(parsed, sort_keys=True))
    path.write_text("".join(rows[key] + "\n" for key in sorted(rows)))
    return len(rows)
