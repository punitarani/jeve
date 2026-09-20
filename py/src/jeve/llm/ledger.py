"""The spend ledger: append-only JSONL, locked, and the source of truth.

Why a file and not a counter in memory: the ceiling has to survive a restart,
and it has to hold when the simulation process and a one-off script are both
issuing calls. `ops/spend.json` is a convenience checkpoint derived from this
file; if the two ever disagree, this file wins.

Accounting rule: a call *reserves* its worst-case cost before it is issued and
*settles* at the real cost afterwards. Effective spend counts settled costs
plus every reservation that never settled. A crashed process therefore leaves
its reservation standing, which over-counts rather than under-counts. That is
the right direction for a ceiling.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type EntryKind = Literal["reserve", "settle", "release", "baseline", "remote"]


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


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock for the whole read-modify-write."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SpendLedger:
    """Append-only spend record shared by every process in the project."""

    def __init__(self, path: Path, *, checkpoint: Path | None = None) -> None:
        self._path = path
        self._checkpoint = checkpoint

    @property
    def path(self) -> Path:
        return self._path

    def _append_locked(self, entry: dict[str, object]) -> None:
        entry.setdefault("ts", time.time())
        entry.setdefault("pid", os.getpid())
        with open(self._path, "a") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def _read_locked(self) -> Spend:
        if not self._path.exists():
            return Spend(0.0, 0.0, 0, 0, None, None, None)

        settled = 0.0
        calls = 0
        estimated = 0
        open_reservations: dict[str, float] = {}
        baseline: float | None = None
        remote: float | None = None
        remote_at: float | None = None

        with open(self._path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # A torn final line from a killed process. Everything
                    # before it still counts.
                    continue
                kind = entry.get("kind")
                if kind == "reserve":
                    open_reservations[str(entry["id"])] = float(entry["amount_usd"])
                elif kind == "settle":
                    open_reservations.pop(str(entry["id"]), None)
                    settled += float(entry["amount_usd"])
                    calls += 1
                    if entry.get("estimated"):
                        estimated += 1
                elif kind == "release":
                    open_reservations.pop(str(entry["id"]), None)
                elif kind == "baseline":
                    baseline = float(entry["amount_usd"])
                elif kind == "remote":
                    remote = float(entry["amount_usd"])
                    remote_at = float(entry["ts"])

        return Spend(
            settled_usd=settled,
            reserved_usd=sum(open_reservations.values()),
            calls=calls,
            estimated_calls=estimated,
            baseline_usd=baseline,
            remote_usd=remote,
            remote_checked_at=remote_at,
        )

    def read(self) -> Spend:
        with _locked(self._path):
            return self._read_locked()

    def reserve(
        self, call_id: str, amount_usd: float, *, purpose: str, model: str
    ) -> Spend:
        """Book worst-case cost and return spend *including* this reservation."""

        with _locked(self._path):
            self._append_locked(
                {
                    "kind": "reserve",
                    "id": call_id,
                    "amount_usd": round(amount_usd, 8),
                    "purpose": purpose,
                    "model": model,
                }
            )
            spend = self._read_locked()
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
        with _locked(self._path):
            self._append_locked(
                {
                    "kind": "settle",
                    "id": call_id,
                    "amount_usd": round(amount_usd, 8),
                    "estimated": estimated,
                    "model": model,
                    "outcome": outcome,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_s": round(latency_s, 4),
                    "provider": provider,
                }
            )
            spend = self._read_locked()
        self._write_checkpoint(spend)
        return spend

    def release(self, call_id: str, *, reason: str) -> Spend:
        """Give a reservation back. Only for requests that were never billed."""

        with _locked(self._path):
            self._append_locked({"kind": "release", "id": call_id, "reason": reason})
            spend = self._read_locked()
        self._write_checkpoint(spend)
        return spend

    def record_baseline(self, remote_usage_usd: float) -> Spend:
        with _locked(self._path):
            spend = self._read_locked()
            if spend.baseline_usd is None:
                self._append_locked(
                    {"kind": "baseline", "amount_usd": round(remote_usage_usd, 8)}
                )
                spend = self._read_locked()
        self._write_checkpoint(spend)
        return spend

    def record_remote(self, remote_usage_usd: float) -> Spend:
        with _locked(self._path):
            self._append_locked(
                {"kind": "remote", "amount_usd": round(remote_usage_usd, 8)}
            )
            spend = self._read_locked()
        self._write_checkpoint(spend)
        return spend

    def _write_checkpoint(self, spend: Spend) -> None:
        if self._checkpoint is None:
            return
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
