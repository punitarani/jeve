"""Jev behind the `Policy` seam (WORLD-0001, DECIDE-0004).

The engine is synchronous and owns a database transaction; the gateway is
asynchronous and owns a socket. They meet here, and the rule that keeps the
meeting safe is a strict division of labour:

- The **main thread** does everything that touches Postgres: render the
  question set, look the hash up, store a response, read the row back, decide.
- A **background event loop** does everything that touches the network. The
  `Gateway` is constructed, started and closed *on that loop*, because its HTTP
  client, its semaphore and its lock all bind to the loop they were made on.

A batch therefore goes: hash every context -> one lookup -> send only the
distinct misses, concurrently -> store each -> read back -> decide every
context from stored rows. Identical situations in one batch share one call.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine, Sequence
from typing import Any, Literal

from jeve import tracing
from jeve.config import Settings, load_settings
from jeve.core.seed import derive_rng, path_of
from jeve.decide import gates
from jeve.decide.policy import Decision, DecisionContext, Source
from jeve.decide.questions import QUESTION_SETS, Prepared, Resolved
from jeve.decide.recorder import Recorder, ReplayMissError, StoredCall, call_key
from jeve.decide.sampling import resolve
from jeve.errors import JeveError, ModelVersionDriftError, TransportError
from jeve.llm import (
    DECISION_PIN,
    DECISION_PREFERENCE,
    DecisionRequest,
    Gateway,
    RawDecision,
)
from jeve.llm.gateway import parse_decision
from jeve.llm.protocol import Usage

CALL_TIMEOUT_S = 180.0


class _Bridge:
    """One event loop on one daemon thread, and the gateway that lives on it."""

    def __init__(self, settings: Settings) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="jev-gateway", daemon=True
        )
        self._thread.start()
        self._gateway: Gateway = self.run(self._open(settings), timeout=90.0)

    @staticmethod
    async def _open(settings: Settings) -> Gateway:
        gateway = Gateway(settings=settings)
        await gateway.start()
        return gateway

    def run[T](self, coro: Coroutine[Any, Any, T], *, timeout: float) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    async def _fetch(
        self, requests: Sequence[DecisionRequest], parent: str | None
    ) -> list[RawDecision | BaseException]:
        return await asyncio.gather(
            *(self._gateway.decide_raw(request, parent=parent) for request in requests),
            return_exceptions=True,
        )

    def fetch(
        self, requests: Sequence[DecisionRequest], *, parent: str | None = None
    ) -> list[RawDecision | BaseException]:
        """`parent` is passed, not inherited.

        `run_coroutine_threadsafe` schedules onto this loop, which copies the
        context on *this* thread — so the batch span open on the caller's
        thread is not the current span here, and a call would otherwise land
        at the root of its own trace (LLM-0009).
        """

        return self.run(self._fetch(requests, parent), timeout=CALL_TIMEOUT_S)

    @property
    def run_spent_usd(self) -> float:
        return self._gateway.run_spent_usd

    def close(self) -> None:
        try:
            self.run(self._gateway.aclose(), timeout=30.0)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)


class JevPolicy:
    """Typed questions in, a sampled draw out."""

    source: Source = "jev"

    def __init__(
        self,
        root_seed: int,
        recorder: Recorder,
        *,
        model: str = DECISION_PREFERENCE[0],
        pin: str = DECISION_PIN,
        settings: Settings | None = None,
    ) -> None:
        self._root = root_seed
        self._recorder = recorder
        self._model = model
        self._pin = pin
        self._settings = settings
        self._bridge: _Bridge | None = None

    # -- lifecycle ---------------------------------------------------------

    def _live(self) -> _Bridge:
        """The gateway, opened on first need.

        Lazily, because a replay never needs it — and constructing a `Gateway`
        demands an API key, which a clean clone does not have.
        """

        if self._bridge is None:
            self._bridge = _Bridge(self._settings or load_settings())
        return self._bridge

    def close(self) -> None:
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None
        self._recorder.close()

    @property
    def recorder(self) -> Recorder:
        return self._recorder

    # -- deciding ----------------------------------------------------------

    def decide(self, ctx: DecisionContext) -> Decision:
        return self.decide_many([ctx])[0]

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        # LLM-0009: the batch is the fan-in under the tick's span. Identical
        # situations in one tick share a request, so only here are the cache
        # hit rate — the whole cost story — and each decision's settling
        # visible together. A hit never reaches the gateway, so it is a row of
        # this span's output rather than a span of its own; the input is
        # logged up front so a batch that fails still says what it was asked.
        with tracing.span(
            _batch_name(contexts),
            type="task",
            input=[_asked(ctx) for ctx in contexts],
            metadata={"mode": self._recorder.mode},
        ) as span:
            prepared = [self._prepare(ctx) for ctx in contexts]
            requests: dict[str, tuple[Prepared, DecisionRequest]] = {}
            hashes: list[str | None] = []
            for item in prepared:
                if not item.needs_model:
                    hashes.append(None)
                    continue
                request = self._request(item)
                # Looked up under the build we are pinned to (DECIDE-0004).
                digest = call_key(self._pin, request.wire_bytes())
                hashes.append(digest)
                requests.setdefault(digest, (item, request))

            stored = self._recorder.lookup(requests)
            lookups = 0
            hits = 0
            for item, maybe in zip(prepared, hashes, strict=True):
                if maybe is not None:
                    hit = maybe in stored
                    lookups += 1
                    hits += 1 if hit else 0
                    self._recorder.note(item.kind, hit=hit)

            missing = [digest for digest in requests if digest not in stored]
            span.log(
                metadata={
                    "kinds": sorted({item.kind for item in prepared}),
                    "contexts": len(contexts),
                    "lookups": lookups,
                    "cache_hits": hits,
                    "distinct_requests": len(requests),
                    "live_calls": len(missing),
                }
            )
            if missing:
                # Exported on this thread, because the gateway is not on it.
                stored |= self._fill(missing, requests, parent=span.export() or None)

            decisions = [
                self._decide_one(ctx, item, stored[maybe] if maybe else None)
                for ctx, item, maybe in zip(contexts, prepared, hashes, strict=True)
            ]
            live = set(missing)
            span.log(
                output=[
                    _settled(ctx, decision, _settled_by(maybe, live))
                    for ctx, decision, maybe in zip(
                        contexts, decisions, hashes, strict=True
                    )
                ]
            )
            return decisions

    def _prepare(self, ctx: DecisionContext) -> Prepared:
        if ctx.kind not in QUESTION_SETS:
            raise KeyError(f"no question set for decision kind {ctx.kind!r}")
        settled = gates.settle(ctx)
        if settled is not None:
            # The world has already decided (WORLD-0005): no model is asked.
            return Prepared(ctx.kind, gated=settled)
        return QUESTION_SETS[ctx.kind].prepare(ctx)

    def _request(self, item: Prepared) -> DecisionRequest:
        assert item.state is not None
        return DecisionRequest(
            model=self._model,
            state=item.state,
            questions={ask.key: ask.question for ask in item.asks},
        )

    def _fill(
        self,
        missing: list[str],
        requests: dict[str, tuple[Prepared, DecisionRequest]],
        *,
        parent: str | None = None,
    ) -> dict[str, StoredCall]:
        if self._recorder.mode == "replay":
            kinds = sorted({requests[digest][0].kind for digest in missing})
            raise ReplayMissError(
                f"strict replay: {len(missing)} call(s) not in the cassette, for "
                f"question set(s) {kinds}. First hash {missing[0][:16]}. The "
                "wording or the world changed since it was recorded; re-record "
                "with `LIVE=1 make e2e`."
            )

        results = self._live().fetch(
            [requests[digest][1] for digest in missing], parent=parent
        )
        failure: BaseException | None = None
        drifted: set[str] = set()
        for digest, result in zip(missing, results, strict=True):
            item, request = requests[digest]
            if isinstance(result, BaseException):
                failure = failure or result
                continue
            wire = request.wire_bytes()
            served = str(result.payload.get("model") or self._pin)
            if served != self._pin:
                drifted.add(served)
            # Stored before anything interprets it: if parsing fails below, the
            # retry reads this row instead of paying for the call again. And
            # stored under the build that *served* it, so an answer from another
            # build is kept (it was paid for) but can never be read back as the
            # pinned build's.
            self._recorder.store(
                call_key(served, wire),
                kind=item.kind,
                model=served,
                provider=_provider(result.payload),
                request=json.loads(wire),
                wire=wire.decode(),
                response=result.payload,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
                cost_estimated=result.usage.cost_is_estimated,
                latency_s=result.latency_s,
            )
        if drifted:
            # Not a miss to be quietly re-recorded: with first-writer-wins
            # storage that would pay for every call on every run and never hit,
            # and it would change the world's behaviour without anyone deciding
            # to. Halt, and let a person move the pin.
            raise ModelVersionDriftError(
                f"pinned to {self._pin} but {sorted(drifted)} answered. The "
                "responses are kept under the build that served them. To adopt "
                "the new build, move DECISION_PIN in jeve/llm/catalog.py, then "
                "`LIVE=1 make e2e` and commit the cassette."
            )
        if failure is not None:
            # Everything that did come back is already safe in the cache.
            if isinstance(failure, JeveError):
                raise failure
            # Anything else that escaped the gateway is still the road to the
            # model, and the daemon waits for that (SIM-0002) rather than dying.
            raise TransportError(f"decision call failed: {failure!r}") from failure
        return self._recorder.lookup(missing)

    def _decide_one(
        self, ctx: DecisionContext, item: Prepared, call: StoredCall | None
    ) -> Decision:
        path = path_of("person", ctx.person_id, "decision", ctx.decision_seq, ctx.kind)
        if call is None:
            assert item.gated is not None
            # Settled by a code gate: no model was consulted, so none is credited.
            return Decision(chosen=dict(item.gated), source="rules", prng_path=path)

        response = parse_decision(
            call.response,
            expected={ask.key for ask in item.asks},
            fallback_model=call.model,
            usage=Usage(
                input_tokens=call.input_tokens,
                output_tokens=0,
                cost_usd=call.cost_usd,
                cost_is_estimated=False,
            ),
        )
        rng = derive_rng(self._root, path)
        resolved: dict[str, Resolved] = {
            ask.key: resolve(ask, response.answers[ask.key], rng.random)
            for ask in item.asks
        }
        outcome = QUESTION_SETS[ctx.kind].interpret(ctx, resolved, rng.random)
        draws = {k: r.draw for k, r in resolved.items() if r.draw is not None}
        return Decision(
            chosen=outcome.chosen,
            source=self.source,
            distributions={k: r.distribution for k, r in resolved.items()},
            draws=draws | outcome.extra_draws,
            prng_path=path,
            model_call=call.hash,
        )


type SettledBy = Literal["gated", "cache", "live"]


def _batch_name(contexts: Sequence[DecisionContext]) -> str:
    """`decide <kind>`, so a trace's children say what was being decided.

    Every call site asks one kind at a time, so the names are bounded by the
    question sets; a mixed batch keeps the generic name rather than minting
    one per combination.
    """

    kinds = {ctx.kind for ctx in contexts}
    return f"decide {kinds.pop()}" if len(kinds) == 1 else "decide.batch"


def _asked(ctx: DecisionContext) -> dict[str, object]:
    """One decision's input, as the world handed it over. Read, never copied:
    the span serialises it, and nothing here may touch what is hashed."""

    return {
        "person_id": ctx.person_id,
        "role": ctx.role,
        "kind": ctx.kind,
        "decision_seq": ctx.decision_seq,
        "sim_time": ctx.sim_time,
        "facts": ctx.facts,
        "traits": ctx.traits,
    }


def _settled_by(digest: str | None, live: set[str]) -> SettledBy:
    """How one decision was settled. Rows count decisions, not calls: two
    people in the same situation share one live request, so both rows say
    `live` with the same `model_call`, and `live_calls` counts it once."""

    if digest is None:
        return "gated"
    return "live" if digest in live else "cache"


def _settled(
    ctx: DecisionContext, decision: Decision, settled_by: SettledBy
) -> dict[str, object]:
    """One decision's output: what was chosen and what it was chosen from."""

    return {
        "person_id": ctx.person_id,
        "settled_by": settled_by,
        "chosen": decision.chosen,
        "distributions": decision.distributions,
        "draws": decision.draws,
        "prng_path": decision.prng_path,
        "model_call": decision.model_call,
    }


def _provider(payload: dict[str, Any]) -> str | None:
    provider = payload.get("provider")
    return str(provider) if provider else None
