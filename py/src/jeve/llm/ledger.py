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
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, obs

log = obs.logger("jeve.llm")

_LATEST: dict[str, float] = {}


def _publish(spend: Spend) -> None:
    _LATEST["effective"] = spend.effective_usd
    _LATEST["settled"] = spend.settled_usd
    _LATEST["reserved"] = spend.reserved_usd


def _reader(key: str) -> Callable[[], float | None]:
    """A gauge callback for one cached figure.

    A factory rather than `lambda key=key:` — the default-argument trick for
    late binding is a puzzle at the point of use, and this is read by whoever
    is trying to work out where a number on a chart came from.
    """

    return lambda: _LATEST.get(key)


for _name, _key, _description in (
    ("jeve.spend.effective", "effective", "Settled plus unsettled reservations."),
    ("jeve.spend.settled", "settled", "Cost of calls that have come back."),
    ("jeve.spend.reserved", "reserved", "Worst-case cost of calls in flight."),
):
    obs.register_gauge(_name, "USD", _description, _reader(_key))


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


_READ_SQL = """
SELECT
  COALESCE(sum(amount_usd) FILTER (WHERE kind = 'settle'), 0) AS settled,
  count(*) FILTER (WHERE kind = 'settle') AS calls,
  count(*) FILTER (WHERE kind = 'settle'
                    AND (detail->>'estimated')::boolean) AS estimated,
  (SELECT COALESCE(sum(r.amount_usd), 0) FROM spend_entries r
    WHERE r.kind = 'reserve' AND NOT EXISTS (
      SELECT 1 FROM spend_entries s
      WHERE s.call_id = r.call_id AND s.kind IN ('settle', 'release'))
  ) AS reserved,
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'baseline' ORDER BY seq LIMIT 1) AS baseline,
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1) AS remote,
  (SELECT EXTRACT(EPOCH FROM ts) FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1) AS remote_at
FROM spend_entries
"""

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

    def _c(self) -> Connection[DictRow]:
        if self._conn is None:
            self._conn = db.connect_autocommit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

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

    def _append(
        self,
        kind: str,
        call_id: str | None = None,
        amount_usd: float | None = None,
        **detail: object,
    ) -> None:
        self._c().execute(
            "INSERT INTO spend_entries (pid, kind, call_id, amount_usd, detail) "
            "VALUES (%s, %s, %s, %s, %s)",
            (os.getpid(), kind, call_id, amount_usd, json.dumps(detail)),
        )

    def read(self) -> Spend:
        row = self._c().execute(_READ_SQL).fetchone()
        assert row is not None  # aggregates always produce a row
        return Spend(
            settled_usd=float(row["settled"]),
            reserved_usd=float(row["reserved"]),
            calls=int(row["calls"]),
            estimated_calls=int(row["estimated"]),
            baseline_usd=(None if row["baseline"] is None else float(row["baseline"])),
            remote_usd=None if row["remote"] is None else float(row["remote"]),
            remote_checked_at=(
                None if row["remote_at"] is None else float(row["remote_at"])
            ),
        )

    def reserve(
        self, call_id: str, amount_usd: float, *, purpose: str, model: str
    ) -> Spend:
        """Book worst-case cost and return spend *including* this reservation."""

        with self.locked():
            self._append(
                "reserve",
                call_id,
                round(amount_usd, 8),
                purpose=purpose,
                model=model,
            )
            spend = self.read()
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
            self._append(
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
            spend = self.read()
        self._write_checkpoint(spend)
        return spend

    def release(self, call_id: str, *, reason: str) -> Spend:
        """Give a reservation back. Only for requests that were never billed."""

        with self.locked():
            self._append("release", call_id, reason=reason)
            spend = self.read()
        self._write_checkpoint(spend)
        return spend

    def record_baseline(self, remote_usage_usd: float) -> Spend:
        with self.locked():
            spend = self.read()
            if spend.baseline_usd is None:
                self._append("baseline", amount_usd=round(remote_usage_usd, 8))
                spend = self.read()
        self._write_checkpoint(spend)
        return spend

    def record_remote(self, remote_usage_usd: float) -> Spend:
        with self.locked():
            self._append("remote", amount_usd=round(remote_usage_usd, 8))
            spend = self.read()
        self._write_checkpoint(spend)
        return spend

    def _write_checkpoint(self, spend: Spend) -> None:
        # OBS-0001: every write path passes through here with a fresh Spend,
        # so this is where the gauges get their value. Pushed into a cache
        # rather than pulled: a gauge callback runs on the metric reader's
        # thread, and a database round trip there would block collection and
        # raise inside the exporter when Postgres is the thing that is down.
        _publish(spend)
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
            log.warn(
                f"spend checkpoint disabled: {error}",
                {
                    "jeve.error_type": type(error).__name__,
                    "jeve.path": str(self._checkpoint),
                },
            )
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
