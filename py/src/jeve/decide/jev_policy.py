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
import time
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jeve import tracing
from jeve.config import Settings, load_settings
from jeve.core.seed import derive_rng, path_of
from jeve.decide import escalation, gates
from jeve.decide.policy import Decision, DecisionContext, Escalated, Source
from jeve.decide.questions import QUESTION_SETS, Ask, Prepared, Resolved
from jeve.decide.recorder import Recorder, ReplayMissError, StoredCall, call_key
from jeve.decide.sampling import resolve
from jeve.errors import JeveError, ModelVersionDriftError, TransportError
from jeve.llm import (
    DECISION_PIN,
    DECISION_PREFERENCE,
    GENERATIVE_PREFERENCE,
    ChatRequest,
    ChatResponse,
    DecisionRequest,
    Gateway,
    Purpose,
    RawDecision,
)
from jeve.llm.gateway import parse_decision
from jeve.llm.protocol import Answer, Choice, ChoiceAnswer, Noul, Score, Usage

CALL_TIMEOUT_S = 180.0
FAILED = ":failed"
UNRESOLVABLE = ":unresolvable"
MARKS = (FAILED, UNRESOLVABLE)
"""Suffixes of the keys a tier-1 give-up is recorded under (DECIDE-0005)."""
SHADOW_BUDGET_S = 45.0
"""All of a tick's shadow second opinions, every batch and every model tried,
share this. Measurement may slow a tick by this much and no more: it holds up a
world that does not act on it (DECIDE-0005)."""


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
        """Fetch on the gateway's loop, from the engine's thread.

        The calls' spans nest under the caller's batch with nothing passed:
        `run_coroutine_threadsafe` runs in a copy of the caller's context, so
        the span current here is current there (LLM-0009).
        """

        return self.run(self._fetch(requests), timeout=CALL_TIMEOUT_S)

    async def _complete(
        self, requests: Sequence[tuple[ChatRequest, Purpose]]
    ) -> list[ChatResponse | BaseException]:
        return await asyncio.gather(
            *(
                self._gateway.complete(request, purpose=purpose)
                for request, purpose in requests
            ),
            return_exceptions=True,
        )

    def complete(
        self,
        requests: Sequence[tuple[ChatRequest, Purpose]],
        *,
        timeout: float = CALL_TIMEOUT_S,
    ) -> list[ChatResponse | BaseException]:
        """Tier-1 second opinions (DECIDE-0005), concurrently, each under its
        own purpose: shadow work is `explore`, and the first thing the budget
        ladder refuses. Their spans nest under the batch as `fetch`'s do."""

        return self.run(self._complete(requests), timeout=timeout)

    @property
    def generative_models(self) -> tuple[str, ...]:
        return self._gateway.generative_models

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
        tier1: escalation.Config | None = None,
    ) -> None:
        self._root = root_seed
        self._recorder = recorder
        self._model = model
        self._pin = pin
        self._settings = settings
        self._tier1 = tier1 or escalation.Config()
        self._bridge: _Bridge | None = None
        self._tick_escalated = 0
        self._tick_acting = 0
        self._shadow_left = SHADOW_BUDGET_S

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

    def begin_tick(self, sim_time: int) -> None:
        """A tick, or its retry, starts with tier 1's per-tick allowances
        whole (DECIDE-0005): a retried tick then decides exactly as a replay
        of it does, and batches within one share them in the order asked."""

        self._tick_escalated = 0
        self._tick_acting = 0
        self._shadow_left = SHADOW_BUDGET_S

    def decide(self, ctx: DecisionContext) -> Decision:
        return self.decide_many([ctx])[0]

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        if not contexts:
            # Nothing was asked: no lookup, no call, and no span to say so.
            return []
        # LLM-0009: the batch is the fan-in under the tick's span. Identical
        # situations in one tick share a request, so only here are the cache
        # hit rate — the whole cost story — and each decision's settling
        # visible together. A hit never reaches the gateway, so it is a row of
        # this span's output rather than a span of its own; the input is
        # logged up front so a batch that fails still says what it was asked.
        kinds = sorted({ctx.kind for ctx in contexts})
        with tracing.span(
            _batch_name(kinds),
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
                    "kinds": kinds,
                    "contexts": len(contexts),
                    "lookups": lookups,
                    "cache_hits": hits,
                    "distinct_requests": len(requests),
                    "live_calls": len(missing),
                }
            )
            if missing:
                stored |= self._fill(missing, requests)

            calls = [stored[maybe] if maybe else None for maybe in hashes]
            answers = [
                self._answers(item, call) if call is not None else None
                for item, call in zip(prepared, calls, strict=True)
            ]
            opinions = self._second_opinions(contexts, prepared, answers)
            decisions = [
                self._decide_one(ctx, item, call, jev, opinions.get(index))
                for index, (ctx, item, call, jev) in enumerate(
                    zip(contexts, prepared, calls, answers, strict=True)
                )
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
            questions=rotated_questions(item.asks),
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

    @staticmethod
    def _answers(item: Prepared, call: StoredCall) -> dict[str, Answer]:
        return collapse_rotations(item.asks, JevPolicy._raw_answers(item, call))

    @staticmethod
    def _raw_answers(item: Prepared, call: StoredCall) -> dict[str, Answer]:
        return parse_decision(
            call.response,
            expected=set(rotated_questions(item.asks)),
            fallback_model=call.model,
            usage=Usage(
                input_tokens=call.input_tokens,
                output_tokens=0,
                cost_usd=call.cost_usd,
                cost_is_estimated=False,
            ),
        ).answers

    def _decide_one(
        self,
        ctx: DecisionContext,
        item: Prepared,
        call: StoredCall | None,
        jev: dict[str, Answer] | None,
        opinion: _Opinion | None,
    ) -> Decision:
        path = path_of("person", ctx.person_id, "decision", ctx.decision_seq, ctx.kind)
        if call is None or jev is None:
            assert item.gated is not None
            # Settled by a code gate: no model was consulted, so none is credited.
            return Decision(chosen=dict(item.gated), source="rules", prng_path=path)

        used = dict(jev)
        if opinion is not None and opinion.applied:
            for ask in item.asks:
                if ask.key in opinion.answers:
                    used[ask.key] = escalation.applied(
                        ask,
                        jev[ask.key],
                        opinion.answers[ask.key],
                        routed=opinion.routed,
                    )
        # The same path whichever tier answered: a live escalation changes what
        # is drawn from, never the draws themselves.
        rng = derive_rng(self._root, path)
        resolved: dict[str, Resolved] = {
            ask.key: resolve(ask, used[ask.key], rng.random) for ask in item.asks
        }
        outcome = QUESTION_SETS[ctx.kind].interpret(ctx, resolved, rng.random)
        draws = {k: r.draw for k, r in resolved.items() if r.draw is not None}
        return Decision(
            chosen=outcome.chosen,
            source="llm" if opinion is not None and opinion.applied else self.source,
            distributions={k: r.distribution for k, r in resolved.items()},
            draws=draws | outcome.extra_draws,
            prng_path=path,
            model_call=call.hash,
            escalation=opinion.record if opinion is not None else None,
        )

    # -- tier 1 (DECIDE-0005) ------------------------------------------------

    def _second_opinions(
        self,
        contexts: Sequence[DecisionContext],
        prepared: Sequence[Prepared],
        answers: Sequence[dict[str, Answer] | None],
    ) -> dict[int, _Opinion]:
        """Ask tier 1 about the answers Jev was unsure of, within today's room.

        Every model in the preference order is looked up before any is called,
        and a model whose reply is on record, usable or not, is never asked the
        same thing again: nothing is paid for twice, and a replay reads back
        what the recording saw. A second opinion that acts is chosen and
        answered by rules that do not depend on the clock on the wall; shadow's
        may, and its rows are measurement only.
        """

        if self._tier1.mode == "off" and not self._tier1.route:
            return {}
        candidates: list[_Wanted] = []
        routed: list[_Wanted] = []
        for index, (ctx, item, jev) in enumerate(
            zip(contexts, prepared, answers, strict=True)
        ):
            if jev is not None and self._tier1.routes(ctx.kind):
                # DECIDE-0006: every question, whatever Jev said, and outside
                # the day's room — the set is answered by tier 1, not escalated.
                keys = self._tier1.routed_asks(ctx.kind, item.asks)
                if keys:
                    routed.append(
                        _Wanted(index, ctx, item, keys, (escalation.ROUTED,), True)
                    )
                continue
            if (
                jev is None
                or self._tier1.mode == "off"
                or escalation.stakes(ctx.kind) == "low"
            ):
                continue
            fired = escalation.triggers(ctx.kind, item.asks, jev)
            if fired:
                keys = tuple(dict.fromkeys(t.ask for t in fired))
            elif escalation.sampled(
                self._root, ctx.person_id, ctx.decision_seq, ctx.kind
            ):
                high = escalation.stakes(ctx.kind) == "high"
                keys = tuple(a.key for a in item.asks if a.mode == "J" or high)
            else:
                continue
            if keys:
                # Only an answer Jev was unsure of may act: the uniform sample
                # is there to measure where Jev was sure, never to overrule it.
                acts = self._tier1.applies(ctx.kind) and bool(fired)
                candidates.append(_Wanted(index, ctx, item, keys, tuple(fired), acts))
        if not candidates and not routed:
            return {}

        # In the order asked, against what is left of today's room once this
        # tick's earlier batches are counted: one batch of five decides exactly
        # as five batches of one would (the Policy contract).
        chosen: list[_Wanted] = list(routed)
        room = (
            escalation.room(self._recorder.connection(), candidates[0].ctx.sim_time)
            if candidates
            else escalation.Room(any=0, acting=0)
        )
        for want in candidates:
            if want.acts:
                if room.acting - self._tick_acting <= 0:
                    continue
                self._tick_acting += 1
            elif room.any - self._tick_escalated <= 0 or self._shadow_left <= 0:
                continue
            self._tick_escalated += 1
            chosen.append(want)
        if not chosen:
            return {}

        found, heard = self._look_up(chosen)
        unanswered = [w for w in chosen if w.index not in found]
        if unanswered and self._recorder.mode == "record":
            try:
                found |= self._ask_tier1(unanswered, heard)
            except JeveError, TimeoutError:
                # Shadow is measurement: no gateway, no budget or no model is
                # a missing row, never a stopped world. An answer that acts is
                # a decision, and waits like one (SIM-0002).
                if any(w.acts for w in unanswered):
                    raise

        opinions: dict[int, _Opinion] = {}
        for want in chosen:
            if want.index not in found:
                if not want.acts:
                    continue  # shadow is measurement: a missing answer is no row
                if all((want.index, m) in heard for m in GENERATIVE_PREFERENCE):
                    # Every model's reply is on record and none can be read: so
                    # it will be on every retry and every replay, and Jev's
                    # answer stands, the same way each time.
                    continue
                if self._recorder.mode == "replay":
                    raise ReplayMissError(
                        f"strict replay: no tier-1 answer for live set "
                        f"{want.ctx.kind!r}; re-record with `LIVE=1 make e2e`."
                    )
                raise TransportError(
                    f"no tier-1 model gave a usable answer for {want.ctx.kind!r}"
                )
            model, call_hash, llm = found[want.index]
            jev = answers[want.index]
            assert jev is not None
            asks = want.asks
            opinions[want.index] = _Opinion(
                answers=llm,
                applied=want.acts,
                routed=escalation.ROUTED in want.fired,
                record=Escalated(
                    mode="live" if want.acts else "shadow",
                    sampled=not want.fired,
                    triggers=[t.row() for t in want.fired],
                    asks=list(want.keys),
                    jev=escalation.distributions(asks, jev),
                    llm=escalation.distributions(asks, llm),
                    model=model,
                    call_hash=call_hash,
                    agrees=escalation.agrees(asks, jev, llm),
                ),
            )
        return opinions

    def _look_up(
        self, wanted: Sequence[_Wanted], models: Sequence[str] = GENERATIVE_PREFERENCE
    ) -> tuple[dict[int, tuple[str, str, dict[str, Answer]]], set[tuple[int, str]]]:
        """The first usable answer per question in model order, and every
        (question, model) whose reply is on record, usable or not."""

        keys = {
            (want.index, model): want.key(model) for want in wanted for model in models
        }
        stored = self._recorder.lookup(
            [key + mark for key in keys.values() for mark in ("", *MARKS)]
        )
        by_index = {want.index: want for want in wanted}
        heard = {
            slot
            for slot, key in keys.items()
            if key in stored
            or f"{key}{UNRESOLVABLE}" in stored
            # A failure keeps shadow from paying for it again; it never keeps
            # an answer that acts from being asked again.
            or (not by_index[slot[0]].acts and f"{key}{FAILED}" in stored)
        }
        found: dict[int, tuple[str, str, dict[str, Answer]]] = {}
        for want in wanted:
            for model in models:
                call = stored.get(keys[(want.index, model)])
                parsed = _parsed(call, want.asks) if call is not None else None
                if call is not None and parsed is not None:
                    found[want.index] = (model, call.hash, parsed)
                    break
        return found, heard

    def _ask_tier1(
        self, wanted: Sequence[_Wanted], heard: set[tuple[int, str]]
    ) -> dict[int, tuple[str, str, dict[str, Answer]]]:
        """Walk the generative order, a round per model, until each question
        has a usable answer or the models run out.

        Every reply is stored before it is read, as every Jev reply is: it was
        paid for. A shadow question a model failed on is marked as unanswered
        by that model, so it is not paid for again; one that acts is not
        marked, because it failed and its tick will be tried again. A model the
        catalogue cannot resolve is marked for everyone: it is not coming back
        within this run, and a replay has to know it was never an option.
        """

        bridge = self._live()
        reachable = bridge.generative_models
        for want in wanted:
            for model in GENERATIVE_PREFERENCE:
                if model not in reachable and (want.index, model) not in heard:
                    self._mark(want, model, UNRESOLVABLE)
                    heard.add((want.index, model))
        found: dict[int, tuple[str, str, dict[str, Answer]]] = {}
        failure: BaseException | None = None
        remaining = list(wanted)
        for model in reachable:
            pending = [w for w in remaining if (w.index, model) not in heard]
            if not pending:
                continue
            acting = any(w.acts for w in pending)
            if not acting and self._shadow_left <= 0:
                break
            # Two people in the same situation share one call, as they share
            # one Jev call.
            by_key: dict[str, list[_Wanted]] = {}
            for want in pending:
                by_key.setdefault(want.key(model), []).append(want)
            requests: list[tuple[ChatRequest, Purpose]] = [
                (
                    escalation.request_for(group[0].item, group[0].keys, model),
                    "gate" if any(w.acts for w in group) else "explore",
                )
                for group in by_key.values()
            ]
            started = time.monotonic()
            try:
                replies = bridge.complete(
                    requests,
                    timeout=CALL_TIMEOUT_S if acting else self._shadow_left,
                )
            except TimeoutError as error:
                if acting:
                    raise
                # Out of shadow time: the round was given all that was left.
                # What earlier rounds found is kept, and this round's questions
                # stay open for a later tick.
                replies = [error] * len(requests)
                self._shadow_left = 0.0
            finally:
                if not acting:
                    self._shadow_left -= time.monotonic() - started
            for group, (request, _), reply in zip(
                by_key.values(), requests, replies, strict=True
            ):
                if isinstance(reply, ChatResponse):
                    self._keep(request, reply)
                elif any(w.acts for w in group):
                    failure = failure or reply
                elif not isinstance(reply, TimeoutError):
                    for want in group:
                        self._mark(want, model, FAILED)
            now_found, now_heard = self._look_up(pending, (model,))
            found |= now_found
            heard |= now_heard
            remaining = [w for w in remaining if w.index not in found]
        if failure is not None and any(w.acts for w in remaining):
            if isinstance(failure, JeveError | TimeoutError):
                raise failure
            raise TransportError(f"tier-1 call failed: {failure!r}") from failure
        return found

    def _mark(self, want: _Wanted, model: str, why: str) -> None:
        """Beside the answer's own key, never on it: a mark must not stop a
        real answer being stored there later."""

        request = escalation.request_for(want.item, want.keys, model)
        body = request.model_dump(mode="json")
        self._recorder.mark_unanswered(
            escalation.request_key(request) + why,
            kind=escalation.KIND,
            model=model,
            request=body,
            wire=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        )

    def _keep(self, request: ChatRequest, reply: ChatResponse) -> None:
        body = request.model_dump(mode="json")
        self._recorder.store(
            escalation.request_key(request),
            kind=escalation.KIND,
            model=request.model,
            provider=reply.provider,
            request=body,
            wire=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            response={"text": reply.text, "model": reply.model},
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
            cost_usd=reply.usage.cost_usd,
            cost_estimated=reply.usage.cost_is_estimated,
            latency_s=reply.latency_s,
        )


@dataclass(frozen=True, slots=True)
class _Wanted:
    index: int
    ctx: DecisionContext
    item: Prepared
    keys: tuple[str, ...]
    fired: tuple[escalation.Trigger, ...]
    acts: bool
    """Its answer decides: a live set, and a question Jev was unsure of."""

    def key(self, model: str) -> str:
        return escalation.request_key(
            escalation.request_for(self.item, self.keys, model)
        )

    @property
    def asks(self) -> list[Ask]:
        return [ask for ask in self.item.asks if ask.key in self.keys]


@dataclass(frozen=True, slots=True)
class _Opinion:
    answers: dict[str, Answer]
    applied: bool
    record: Escalated
    routed: bool = False


# -- judgements over every order (DECIDE-0007) -----------------------------------

ROTATED = "__r"
"""A judgement's copy in another order of its options: `allocation__r2`."""


def _rotatable(ask: Ask) -> list[str]:
    """The options a judgement over a choice is asked in every cyclic order of:
    all but `other`, which stays last (it is the ontology gap, DECIDE-0001).
    Empty for anything else: a propensity is sampled, and its position bias is
    part of the distribution Jev gives, not a flipped verdict."""

    if ask.mode != "J" or not isinstance(ask.question, Choice):
        return []
    return [o for o in ask.options if o != "other"]


def rotated_questions(asks: Sequence[Ask]) -> dict[str, Noul | Choice | Score]:
    """The questions as Jev is asked them: each once as declared, and each
    judgement over a choice once more for every other cyclic order of its
    options, under a suffixed key, in the same request.

    Reversing a firm-level judgement's options flipped Jev's verdict in 11-22%
    of real states (credit, engineering allocation, founder review). Averaged
    over every rotation — each option in each position once — a verdict held
    under an order it never saw in 96% of 350 states, against 93% for one
    order, bundled in one call as here (`prompt_lab.py orders`,
    `ops/evals/prompt-lab/`)."""

    questions: dict[str, Noul | Choice | Score] = {}
    for ask in asks:
        questions[ask.key] = ask.question
        body = _rotatable(ask)
        if len(body) < 2:
            continue
        assert isinstance(ask.question, Choice)
        criteria = dict(ask.question.criteria)
        tail = {"other": criteria["other"]} if "other" in criteria else {}
        for turn in range(1, len(body)):
            order = body[turn:] + body[:turn]
            questions[f"{ask.key}{ROTATED}{turn}"] = Choice(
                instructions=ask.question.instructions,
                criteria={**{o: criteria[o] for o in order}, **tail},
            )
    return questions


def collapse_rotations(
    asks: Sequence[Ask], answers: dict[str, Answer]
) -> dict[str, Answer]:
    """Each judgement's copies averaged back into one answer under its own
    key; everything else as Jev gave it."""

    out: dict[str, Answer] = {}
    for ask in asks:
        body = _rotatable(ask)
        copies = [answers[ask.key]] + [
            answers[f"{ask.key}{ROTATED}{turn}"]
            for turn in range(1, len(body))
            if f"{ask.key}{ROTATED}{turn}" in answers
        ]
        if len(copies) < 2 or not all(isinstance(c, ChoiceAnswer) for c in copies):
            out[ask.key] = answers[ask.key]
            continue
        mean = {
            option: sum(
                c.distribution().get(option, 0.0)
                for c in copies
                if isinstance(c, ChoiceAnswer)
            )
            / len(copies)
            for option in ask.options
        }
        out[ask.key] = ChoiceAnswer(
            choice=max(ask.options, key=lambda option: mean[option]),
            probabilities=mean,
        )
    return out


def _parsed(call: StoredCall, asks: Sequence[Ask]) -> dict[str, Answer] | None:
    try:
        return escalation.parse(str(call.response.get("text", "")), asks)
    except ValueError:
        return None


type SettledBy = Literal["gated", "cache", "live"]


def _batch_name(kinds: Sequence[str]) -> str:
    """`decide <kind>`, so a trace's children say what was being decided.

    Every call site asks one kind at a time, so the names are bounded by the
    question sets; a mixed batch keeps the generic name rather than minting
    one per combination.
    """

    return f"decide {kinds[0]}" if len(kinds) == 1 else "decide.batch"


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

    row: dict[str, object] = {
        "person_id": ctx.person_id,
        "settled_by": settled_by,
        "chosen": decision.chosen,
        "distributions": decision.distributions,
        "draws": decision.draws,
        "prng_path": decision.prng_path,
        "model_call": decision.model_call,
    }
    second = decision.escalation
    if second is not None:
        # DECIDE-0005: the second opinion, beside the answer it second-guessed.
        row["tier1"] = {
            "mode": second.mode,
            "model": second.model,
            "triggers": second.triggers,
            "sampled": second.sampled,
            "llm": second.llm,
            "agrees": second.agrees,
        }
    return row


def _provider(payload: dict[str, Any]) -> str | None:
    provider = payload.get("provider")
    return str(provider) if provider else None
