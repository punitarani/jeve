"""The spend ledger: append-only, in Postgres, the source of truth (LLM-0007).

Why a table and not the JSONL file this replaced: the ceiling has to survive a
container restart, and it has to be the same ledger for the daemon and the
API. A file on a Fly volume is neither. `ops/spend.json` survives as a
read-only checkpoint for `make spend`; the table is what wins any argument.

Accounting rule, unchanged: a call *reserves* its worst-case cost before it is
issued and *settles* at the real cost afterwards. Effective spend counts
settled costs plus every reservation that never settled. A crashed process
therefore leaves its reservation standing, which over-counts rather than
under-counts. That is the right direction for a ceiling.

What a spend check reads is `spend_totals` (LLM-0010): one row, moved by every
append under the ledger lock by exactly what folding the whole ledger would.
Folding the ledger on every read was 80% of the production database's time
at 86k rows — four folds per model call, on an eighth of a vCPU — and grew
with every call made. The fold survives as `rebuild()`: the seed, the repair,
and the check that the total is what the ledger says.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db


@dataclass(frozen=True, slots=True)
class Spend:
    """What has been committed and what is still in flight."""

    settled_usd: float
    reserved_usd: float
    calls: int
    estimated_calls: int
    baseline_usd: float | None
    remote_usd: float | None
    remote_checked_at: float | None

    @property
    def local_usd(self) -> float:
        return self.settled_usd + self.reserved_usd

    @property
    def remote_delta_usd(self) -> float | None:
        if self.remote_usd is None or self.baseline_usd is None:
            return None
        return max(0.0, self.remote_usd - self.baseline_usd)

    @property
    def effective_usd(self) -> float:
        """The number the ceiling is enforced against.

        The user's rule is to trust the remote figure on divergence. Taken
        literally that lets a lagging `/key` *lower* observed spend, which
        would hand back budget we have already used, so the local figure is a
        floor.
        """

        remote = self.remote_delta_usd
        if remote is None:
            return self.local_usd
        return max(self.local_usd, remote)

    @property
    def divergence(self) -> float | None:
        """Relative gap between local and remote, or None if not comparable."""

        remote = self.remote_delta_usd
        if remote is None or self.local_usd <= 0.0:
            return None
        return abs(remote - self.local_usd) / self.local_usd


_FOLD_SQL = """
SELECT
  COALESCE(max(seq), 0) AS as_of_seq,
  COALESCE(sum(amount_usd) FILTER (WHERE kind = 'settle'), 0) AS settled_usd,
  count(*) FILTER (WHERE kind = 'settle') AS calls,
  count(*) FILTER (WHERE kind = 'settle'
                    AND (detail->>'estimated')::boolean) AS estimated_calls,
  (SELECT COALESCE(sum(r.amount_usd), 0) FROM spend_entries r
    WHERE r.kind = 'reserve' AND NOT EXISTS (
      SELECT 1 FROM spend_entries s
      WHERE s.call_id = r.call_id AND s.kind IN ('settle', 'release'))
  ) AS reserved_usd,
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'baseline' ORDER BY seq LIMIT 1) AS baseline_usd,
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1) AS remote_usd,
  (SELECT ts FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1) AS remote_at
FROM spend_entries
"""

_REPLACE_TOTAL_SQL = """
INSERT INTO spend_totals (one, as_of_seq, settled_usd, calls, estimated_calls,
                          reserved_usd, baseline_usd, remote_usd, remote_at)
VALUES (true, %(as_of_seq)s, %(settled_usd)s, %(calls)s, %(estimated_calls)s,
        %(reserved_usd)s, %(baseline_usd)s, %(remote_usd)s, %(remote_at)s)
ON CONFLICT (one) DO UPDATE SET
  as_of_seq = EXCLUDED.as_of_seq, settled_usd = EXCLUDED.settled_usd,
  calls = EXCLUDED.calls, estimated_calls = EXCLUDED.estimated_calls,
  reserved_usd = EXCLUDED.reserved_usd, baseline_usd = EXCLUDED.baseline_usd,
  remote_usd = EXCLUDED.remote_usd, remote_at = EXCLUDED.remote_at
RETURNING *
"""

# One statement per append, whatever the kind: a delta of zero leaves a column
# where it was, and NULL leaves the baseline/remote columns alone. The first
# baseline wins and the last remote wins, exactly as the fold reads them.
_MOVE_TOTAL_SQL = """
UPDATE spend_totals SET
  as_of_seq       = %(seq)s,
  settled_usd     = settled_usd + %(settled)s,
  calls           = calls + %(calls)s,
  estimated_calls = estimated_calls + %(estimated)s,
  reserved_usd    = reserved_usd + %(reserved)s,
  baseline_usd    = COALESCE(baseline_usd, %(baseline)s),
  remote_usd      = COALESCE(%(remote)s, remote_usd),
  remote_at       = COALESCE(%(remote_at)s, remote_at)
RETURNING *
"""

# What a settle or release gives back: the reservation it closes, if it is
# still open. Two index probes on `spend_entries_call`.
_OPEN_RESERVE_SQL = """
SELECT COALESCE(sum(r.amount_usd), 0) AS usd FROM spend_entries r
WHERE r.call_id = %s AND r.kind = 'reserve' AND NOT EXISTS (
  SELECT 1 FROM spend_entries s
  WHERE s.call_id = r.call_id AND s.kind IN ('settle', 'release'))
"""

_HEAD_SQL = """
SELECT (SELECT as_of_seq FROM spend_totals) AS seen,
       COALESCE((SELECT max(seq) FROM spend_entries), 0) AS head
"""


def _spend_from(row: Mapping[str, Any]) -> Spend:
    remote_at = row["remote_at"]
    return Spend(
        settled_usd=float(row["settled_usd"]),
        reserved_usd=float(row["reserved_usd"]),
        calls=int(row["calls"]),
        estimated_calls=int(row["estimated_calls"]),
        baseline_usd=(
            None if row["baseline_usd"] is None else float(row["baseline_usd"])
        ),
        remote_usd=None if row["remote_usd"] is None else float(row["remote_usd"]),
        remote_checked_at=None if remote_at is None else remote_at.timestamp(),
    )


# "jevl" — distinct from the writer lock, so ledger serialisation never
# contends with who is allowed to tick.
LEDGER_LOCK_KEY = 0x6A65766C


class SpendLedger:
    """Append-only spend record shared by every process on this database.

    Holds one dedicated autocommit connection — accounting must not ride the
    tick's transaction, because a rolled-back tick must not un-record money
    that was actually spent. The connection opens lazily so constructing a
    gateway without a database is still legal.
    """

    def __init__(
        self,
        conn: Connection[DictRow] | None = None,
        *,
        checkpoint: Path | None = None,
    ) -> None:
        self._conn = conn
        self._checkpoint = checkpoint
        self._reconciled = False

    def _c(self) -> Connection[DictRow]:
        if self._conn is None:
            self._conn = db.connect_autocommit()
        if not self._reconciled:
            # Set first: `_reconcile` takes the lock, and the lock calls back
            # here for the connection. Unset if it fails, or one dropped packet
            # on open would leave the total unreconciled for the process's life.
            self._reconciled = True
            try:
                self._reconcile()
            except BaseException:
                self._reconciled = False
                raise
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._reconciled = False

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialise a read-modify-write against every other ledger user.

        `pg_advisory_xact_lock` is re-entrant in the session that holds it, so
        a method called under an outer `locked()` joins that transaction
        rather than deadlocking on itself.
        """

        conn = self._c()
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LEDGER_LOCK_KEY,))
            yield

    def _reconcile(self) -> None:
        """Fold in whatever the total has not seen, once, when a ledger opens.

        The total is behind the ledger's head exactly when something appended
        without moving it: the previous version of this code, still running
        between migration 0011 and its own restart, or a hand-run INSERT.
        Either way the fold is right and the total is not.
        """

        with self.locked():
            row = self._c().execute(_HEAD_SQL).fetchone()
            assert row is not None  # a scalar subquery always yields a row
            if row["seen"] is None or int(row["seen"]) != int(row["head"]):
                self.rebuild()

    def _append(
        self,
        kind: str,
        call_id: str | None = None,
        amount_usd: float | None = None,
        **detail: object,
    ) -> Spend:
        """Append one row and move the total by exactly what the fold would.

        Only ever called under `locked()`: the open-reservation lookup, the
        insert and the update are one read-modify-write.
        """

        conn = self._c()
        closing = 0.0
        if kind in ("settle", "release"):
            assert call_id is not None  # both kinds name the reservation
            open_reserve = conn.execute(_OPEN_RESERVE_SQL, (call_id,)).fetchone()
            closing = float(open_reserve["usd"]) if open_reserve else 0.0
        entry = conn.execute(
            "INSERT INTO spend_entries (pid, kind, call_id, amount_usd, detail) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING seq, ts",
            (os.getpid(), kind, call_id, amount_usd, json.dumps(detail)),
        ).fetchone()
        assert entry is not None  # RETURNING on a single-row insert

        amount = 0.0 if amount_usd is None else amount_usd
        delta: dict[str, object] = {
            "seq": entry["seq"],
            "settled": 0.0,
            "calls": 0,
            "estimated": 0,
            "reserved": 0.0,
            "baseline": None,
            "remote": None,
            "remote_at": None,
        }
        if kind == "reserve":
            delta["reserved"] = amount
        elif kind == "settle":
            delta["settled"] = amount
            delta["calls"] = 1
            delta["estimated"] = int(bool(detail.get("estimated")))
            delta["reserved"] = -closing
        elif kind == "release":
            delta["reserved"] = -closing
        elif kind == "baseline":
            delta["baseline"] = amount
        elif kind == "remote":
            delta["remote"] = amount
            delta["remote_at"] = entry["ts"]
        total = conn.execute(_MOVE_TOTAL_SQL, delta).fetchone()
        assert total is not None  # the row exists from migration 0011 on
        return _spend_from(total)

    def read(self) -> Spend:
        row = self._c().execute("SELECT * FROM spend_totals").fetchone()
        if row is None:
            raise RuntimeError("spend_totals is empty: migration 0011 has not run")
        return _spend_from(row)

    def rebuild(self) -> Spend:
        """Fold the whole ledger and replace the total with the result.

        The one O(n) path. Run when a ledger opens against a total behind
        the ledger's head, and by hand if the two are ever suspected to
        disagree; the fold is the definition of what the total must say.
        """

        with self.locked():
            conn = self._c()
            fold = conn.execute(_FOLD_SQL).fetchone()
            assert fold is not None  # aggregates always produce a row
            row = conn.execute(_REPLACE_TOTAL_SQL, fold).fetchone()
            assert row is not None  # RETURNING on an upsert
        return _spend_from(row)

    def reserve(
        self, call_id: str, amount_usd: float, *, purpose: str, model: str
    ) -> Spend:
        """Book worst-case cost and return spend *including* this reservation."""

        with self.locked():
            spend = self._append(
                "reserve",
                call_id,
                round(amount_usd, 8),
                purpose=purpose,
                model=model,
            )
        self._write_checkpoint(spend)
        return spend

    def settle(
        self,
        call_id: str,
        amount_usd: float,
        *,
        estimated: bool,
        model: str,
        outcome: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_s: float = 0.0,
        provider: str | None = None,
    ) -> Spend:
        with self.locked():
            spend = self._append(
                "settle",
                call_id,
                round(amount_usd, 8),
                estimated=estimated,
                model=model,
                outcome=outcome,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_s=round(latency_s, 4),
                provider=provider,
            )
        self._write_checkpoint(spend)
        return spend

    def release(self, call_id: str, *, reason: str) -> Spend:
        """Give a reservation back. Only for requests that were never billed."""

        with self.locked():
            spend = self._append("release", call_id, reason=reason)
        self._write_checkpoint(spend)
        return spend

    def record_baseline(self, remote_usage_usd: float) -> Spend:
        with self.locked():
            spend = self.read()
            if spend.baseline_usd is None:
                spend = self._append("baseline", amount_usd=round(remote_usage_usd, 8))
        self._write_checkpoint(spend)
        return spend

    def record_remote(self, remote_usage_usd: float) -> Spend:
        with self.locked():
            spend = self._append("remote", amount_usd=round(remote_usage_usd, 8))
        self._write_checkpoint(spend)
        return spend

    def _write_checkpoint(self, spend: Spend) -> None:
        if self._checkpoint is None:
            return
        try:
            self._write_checkpoint_unsafe(spend)
        except OSError as error:
            # The checkpoint is a human-readable mirror; the table is
            # authoritative. A read-only container fs (the sim image runs as
            # uid 1001 with /app owned by root) must not kill accounting —
            # this took the daemon down on boot under compose. Warn once and
            # stop trying: permissions do not heal mid-process.
            print(f"spend checkpoint disabled: {error}", file=sys.stderr)
            self._checkpoint = None

    def _write_checkpoint_unsafe(self, spend: Spend) -> None:
        assert self._checkpoint is not None
        self._checkpoint.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "effective_usd": round(spend.effective_usd, 6),
            "settled_usd": round(spend.settled_usd, 6),
            "reserved_usd": round(spend.reserved_usd, 6),
            "calls": spend.calls,
            "estimated_calls": spend.estimated_calls,
            "baseline_usd": spend.baseline_usd,
            "remote_usd": spend.remote_usd,
            "remote_delta_usd": spend.remote_delta_usd,
            "updated_at": time.time(),
        }
        tmp = self._checkpoint.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(self._checkpoint)
