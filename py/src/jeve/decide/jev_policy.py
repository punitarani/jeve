"""Jev behind the `Policy` seam (WORLD-0001, DECIDE-0003).

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
import threading
from collections.abc import Coroutine, Sequence
from typing import Any

from jeve.config import Settings, load_settings
from jeve.core.seed import derive_rng, path_of
from jeve.decide.policy import Decision, DecisionContext, Source
from jeve.decide.questions import QUESTION_SETS, Prepared, Resolved
from jeve.decide.recorder import Recorder, ReplayMissError, StoredCall, request_hash
from jeve.decide.sampling import resolve
from jeve.errors import JeveError
from jeve.llm import DECISION_PREFERENCE, DecisionRequest, Gateway, RawDecision
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
        self, requests: Sequence[DecisionRequest]
    ) -> list[RawDecision | BaseException]:
        return await asyncio.gather(
            *(self._gateway.decide_raw(request) for request in requests),
            return_exceptions=True,
        )

    def fetch(
        self, requests: Sequence[DecisionRequest]
    ) -> list[RawDecision | BaseException]:
        return self.run(self._fetch(requests), timeout=CALL_TIMEOUT_S)

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
        settings: Settings | None = None,
    ) -> None:
        self._root = root_seed
        self._recorder = recorder
        self._model = model
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
        prepared = [self._prepare(ctx) for ctx in contexts]
        requests: dict[str, tuple[Prepared, DecisionRequest]] = {}
        hashes: list[str | None] = []
        for item in prepared:
            if not item.needs_model:
                hashes.append(None)
                continue
            request = self._request(item)
            digest = request_hash(self._model, request.state, _questions_body(request))
            hashes.append(digest)
            requests.setdefault(digest, (item, request))

        stored = self._recorder.lookup(requests)
        for item, maybe in zip(prepared, hashes, strict=True):
            if maybe is not None:
                self._recorder.note(item.kind, hit=maybe in stored)

        missing = [digest for digest in requests if digest not in stored]
        if missing:
            stored |= self._fill(missing, requests)

        return [
            self._decide_one(ctx, item, stored[maybe] if maybe else None)
            for ctx, item, maybe in zip(contexts, prepared, hashes, strict=True)
        ]

    def _prepare(self, ctx: DecisionContext) -> Prepared:
        try:
            return QUESTION_SETS[ctx.kind].prepare(ctx)
        except KeyError:
            raise KeyError(f"no question set for decision kind {ctx.kind!r}") from None

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
    ) -> dict[str, StoredCall]:
        if self._recorder.mode == "replay":
            kinds = sorted({requests[digest][0].kind for digest in missing})
            raise ReplayMissError(
                f"strict replay: {len(missing)} call(s) not in the cassette, for "
                f"question set(s) {kinds}. First hash {missing[0][:16]}. The "
                "wording or the world changed since it was recorded; re-record "
                "with `LIVE=1 make e2e`."
            )

        results = self._live().fetch([requests[digest][1] for digest in missing])
        failure: BaseException | None = None
        for digest, result in zip(missing, results, strict=True):
            item, request = requests[digest]
            if isinstance(result, BaseException):
                failure = failure or result
                continue
            # Stored before anything interprets it: if parsing fails below, the
            # retry reads this row instead of paying for the call again.
            self._recorder.store(
                digest,
                kind=item.kind,
                model=str(result.payload.get("model") or self._model),
                provider=_provider(result.payload),
                request={
                    "model": self._model,
                    "state": request.state,
                    "questions": _questions_body(request),
                },
                response=result.payload,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
                cost_estimated=result.usage.cost_is_estimated,
                latency_s=result.latency_s,
            )
        if failure is not None:
            # Everything that did come back is already safe in the cache.
            if isinstance(failure, JeveError):
                raise failure
            raise JeveError(f"decision call failed: {failure!r}") from failure
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


def _questions_body(request: DecisionRequest) -> dict[str, object]:
    return {
        key: question.model_dump(mode="json", exclude_none=True, by_alias=True)
        for key, question in request.questions.items()
    }


def _provider(payload: dict[str, Any]) -> str | None:
    provider = payload.get("provider")
    return str(provider) if provider else None
