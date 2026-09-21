"""The ceiling (LLM-0004).

Three rungs, checked before a call is authorised:

    >= $12  refuse `explore`; only work that drives a milestone gate
    >= $16  refuse everything and signal that the handoff should be written
    >= $20  refuse everything, full stop

`$20 means stop, not slow down`, so the check runs against spend *including*
this call's worst-case reservation. Checking against settled spend alone would
let a burst of concurrent calls sail past the ceiling while all of them are
still in flight.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from jeve.config import Settings
from jeve.errors import BudgetExceededError
from jeve.llm.ledger import Spend, SpendLedger
from jeve.llm.protocol import Purpose

REMOTE_RECHECK_SECONDS = 15 * 60
DIVERGENCE_TOLERANCE = 0.10


@dataclass(frozen=True, slots=True)
class BudgetState:
    spend: Spend
    explore_allowed: bool
    any_allowed: bool
    should_halt: bool


class BudgetGuard:
    """Authorises calls, or refuses them."""

    def __init__(self, settings: Settings, ledger: SpendLedger) -> None:
        self._settings = settings
        self._ledger = ledger

    @property
    def ledger(self) -> SpendLedger:
        return self._ledger

    def state(self) -> BudgetState:
        return self._classify(self._ledger.read())

    def _classify(self, spend: Spend) -> BudgetState:
        used = spend.effective_usd
        return BudgetState(
            spend=spend,
            explore_allowed=used < self._settings.explore_ceiling_usd,
            any_allowed=used < self._settings.halt_ceiling_usd,
            should_halt=used >= self._settings.halt_ceiling_usd,
        )

    def authorise(
        self,
        call_id: str,
        *,
        worst_case_usd: float,
        purpose: Purpose,
        model: str,
    ) -> Spend:
        """Reserve worst-case cost, or raise.

        Returns the spend snapshot that includes the reservation. The caller
        must eventually settle or release `call_id`.
        """

        # LLM-0007: check and reserve in one serialised transaction. A read
        # outside the lock could pass for two processes at once, and both
        # reservations would sail the total past the ceiling.
        with self._ledger.locked():
            used = self._ledger.read().effective_usd

            if used >= self._settings.hard_ceiling_usd:
                raise BudgetExceededError(
                    f"hard ceiling reached: ${used:.4f} of "
                    f"${self._settings.hard_ceiling_usd:.2f}. No further calls."
                )
            if purpose == "explore" and used >= self._settings.explore_ceiling_usd:
                raise BudgetExceededError(
                    f"exploratory work is closed: ${used:.4f} spent, threshold "
                    f"${self._settings.explore_ceiling_usd:.2f}. Gate work only."
                )
            if used >= self._settings.halt_ceiling_usd:
                raise BudgetExceededError(
                    f"halt threshold reached: ${used:.4f} of "
                    f"${self._settings.halt_ceiling_usd:.2f}. Write the handoff."
                )

            projected = used + worst_case_usd
            if projected > self._settings.hard_ceiling_usd:
                raise BudgetExceededError(
                    f"call would breach the hard ceiling: ${used:.4f} spent, "
                    f"${worst_case_usd:.4f} worst case, "
                    f"${self._settings.hard_ceiling_usd:.2f} ceiling."
                )

            return self._ledger.reserve(
                call_id, worst_case_usd, purpose=purpose, model=model
            )

    def needs_remote_check(self, *, now: float | None = None) -> bool:
        spend = self._ledger.read()
        if spend.baseline_usd is None:
            return True
        if spend.remote_checked_at is None:
            return True
        current = time.time() if now is None else now
        return (current - spend.remote_checked_at) >= REMOTE_RECHECK_SECONDS

    def apply_remote(self, remote_usage_usd: float) -> tuple[Spend, float | None]:
        """Fold a `/key` reading in. Returns the new spend and any divergence.

        The first reading becomes the baseline, since the key's `usage` is
        lifetime spend for that credential and only the delta belongs to this
        project.
        """

        spend = self._ledger.read()
        if spend.baseline_usd is None:
            return self._ledger.record_baseline(remote_usage_usd), None

        spend = self._ledger.record_remote(remote_usage_usd)
        divergence = spend.divergence
        if divergence is not None and divergence > DIVERGENCE_TOLERANCE:
            return spend, divergence
        return spend, None
