"""The metric inventory, declared once.

Every instrument jeve exports is a module constant here rather than a
`meter.create_*` call at a call site. Two reasons. A dashboard is written
against these names, so a rename should be a diff in one file and a failing
test (`tests/test_obs.py::test_the_metric_inventory_is_stable`), not a silent
gap in a chart. And an instrument must outlive the call that first records to
it — creating one per call would leak a new instrument per invocation.

Instruments resolve lazily against the running meter and cache themselves
against `Live.generation`, so a start/shutdown/start cycle re-resolves cleanly
instead of recording into a dead provider.

Units follow UCUM, as the OTel spec requires: `s`, `USD`, `1`, and the
annotation form `{tick}` for dimensionless counts.
"""

from __future__ import annotations

from typing import Any

from jeve.obs import wiring
from jeve.obs.spans import Attrs


class _Instrument:
    """Lazily bound to whatever meter is live, or to nothing."""

    __slots__ = ("_cached", "_generation", "_kind", "description", "name", "unit")

    def __init__(self, kind: str, name: str, unit: str, description: str) -> None:
        self._kind = kind
        self.name = name
        self.unit = unit
        self.description = description
        self._cached: Any | None = None
        self._generation = 0

    def _resolve(self) -> Any | None:
        state = wiring.live()
        if state is None:
            self._cached, self._generation = None, 0
            return None
        if self._cached is None or self._generation != state.generation:
            create = getattr(state.meter, f"create_{self._kind}")
            self._cached = create(
                self.name, unit=self.unit, description=self.description
            )
            self._generation = state.generation
        return self._cached


class Counter(_Instrument):
    def add(self, amount: float = 1, attrs: Attrs | None = None) -> None:
        if (instrument := self._resolve()) is not None:
            instrument.add(amount, attrs or {})


class UpDown(_Instrument):
    def add(self, amount: float, attrs: Attrs | None = None) -> None:
        if (instrument := self._resolve()) is not None:
            instrument.add(amount, attrs or {})


class Histogram(_Instrument):
    def record(self, value: float, attrs: Attrs | None = None) -> None:
        if (instrument := self._resolve()) is not None:
            instrument.record(value, attrs or {})


def _counter(name: str, unit: str, description: str) -> Counter:
    return Counter("counter", name, unit, description)


def _updown(name: str, unit: str, description: str) -> UpDown:
    return UpDown("up_down_counter", name, unit, description)


def _histogram(name: str, unit: str, description: str) -> Histogram:
    return Histogram("histogram", name, unit, description)


# --- the simulation ---------------------------------------------------------

TICKS = _counter("jeve.sim.ticks", "{tick}", "Ticks attempted, by outcome.")
TICK_DURATION = _histogram(
    "jeve.sim.tick.duration", "s", "Wall time inside Engine.tick()."
)
# The advance is always exactly one quantum of sim time, so the gap between
# that and the wall time it took is the whole question: is the world keeping up.
TICK_LAG = _histogram("jeve.sim.tick.lag", "s", "How far behind its pace a tick ran.")
DECISIONS = _counter("jeve.sim.decisions", "{decision}", "Decisions taken, by source.")
EVENTS = _counter("jeve.sim.events", "{event}", "Events written, by kind.")
WAIT_DURATION = _histogram(
    "jeve.sim.wait.duration", "s", "Time spent waiting on a model or a budget."
)
# A counter rather than a gauge of the current status: what an operator asks at
# 3am is "when did it start waiting", and only a transition can answer that.
STATUS = _counter(
    "jeve.sim.status.transitions", "{transition}", "sim_meta.status changes."
)

# --- the model path ---------------------------------------------------------

LLM_DURATION = _histogram(
    "gen_ai.client.operation.duration", "s", "Latency of one logical model call."
)
LLM_TOKENS = _histogram(
    "gen_ai.client.token.usage", "{token}", "Tokens per call, by direction."
)
LLM_COST = _counter("jeve.llm.cost", "USD", "Settled cost, by model and purpose.")
LLM_CALLS = _counter("jeve.llm.calls", "{call}", "Logical model calls, by outcome.")
LLM_RETRIES = _counter("jeve.llm.retries", "{retry}", "HTTP attempts beyond the first.")
LLM_CACHE = _counter(
    "jeve.llm.cache.lookups", "{lookup}", "Call-cache lookups, hit or miss."
)

# --- the API ----------------------------------------------------------------

HTTP_DURATION = _histogram(
    "http.server.request.duration", "s", "Time to response start, by route."
)
HTTP_ACTIVE = _updown(
    "http.server.active_requests", "{request}", "Requests currently in flight."
)
DB_DURATION = _histogram(
    "db.client.operation.duration", "s", "Time inside one SQL statement."
)
POOL_WAIT = _histogram(
    "jeve.api.pool.wait", "s", "Time spent waiting for a pooled connection."
)
STREAM_SUBSCRIBERS = _updown(
    "jeve.api.stream.subscribers", "{subscriber}", "Open SSE connections."
)
STREAM_POLL_ERRORS = _counter(
    "jeve.api.stream.poll.errors", "{error}", "Failed fan-out polls, by error type."
)
STREAM_RESYNCS = _counter(
    "jeve.api.stream.resyncs", "{resync}", "Subscribers told to resync after overflow."
)

#: Everything above, for the inventory test. A new instrument that is not in
#: this tuple is not exported and not charted.
ALL: tuple[_Instrument, ...] = (
    TICKS,
    TICK_DURATION,
    TICK_LAG,
    DECISIONS,
    EVENTS,
    WAIT_DURATION,
    STATUS,
    LLM_DURATION,
    LLM_TOKENS,
    LLM_COST,
    LLM_CALLS,
    LLM_RETRIES,
    LLM_CACHE,
    HTTP_DURATION,
    HTTP_ACTIVE,
    DB_DURATION,
    POOL_WAIT,
    STREAM_SUBSCRIBERS,
    STREAM_POLL_ERRORS,
    STREAM_RESYNCS,
)
