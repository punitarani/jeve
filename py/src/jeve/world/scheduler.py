"""Scheduled work, as a registry (WORLD-0005).

The engine used to dispatch due work through a nine-branch `if kind ==`, so a
new flow meant editing the engine, and whether a job could run while only the
cafe was open was nobody's decision: month-end invoices could be issued at seven
in the morning because that was when the outage ended.

A job says what it is and whether it needs the offices open. One that does, and
comes due when they are shut, is put back for the next office opening.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jeve.world.engine import Engine, TickReport

type Handler = Callable[["Engine", "TickReport", str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class Job:
    kind: str
    run: Handler
    office_hours_only: bool


JOBS: dict[str, Job] = {}


def job(kind: str, *, office_hours_only: bool = False) -> Callable[[Handler], Handler]:
    """Register the handler for one kind of scheduled work."""

    def register(run: Handler) -> Handler:
        if kind in JOBS:
            raise ValueError(f"two handlers for scheduled work of kind {kind!r}")
        JOBS[kind] = Job(kind, run, office_hours_only)
        return run

    return register


def get(kind: str) -> Job:
    try:
        return JOBS[kind]
    except KeyError:
        raise KeyError(f"nothing handles scheduled work of kind {kind!r}") from None
