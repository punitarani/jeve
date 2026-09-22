"""The gateway. Every model call in this project goes through here.

Nothing else may import httpx (ruff TID251 bans it elsewhere, and a test walks
the tree to catch a stray raw request). One module means one place that knows
about keys, retries, provider routing, and — the point — the ceiling.

Per call: reserve worst-case cost, issue, settle at the real cost reported by
OpenRouter. A response that omits `usage.cost` is priced from the catalogue and
flagged `estimated`; it is never booked as free.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

from jeve import tracing
from jeve.config import Settings, load_settings
from jeve.errors import (
    BudgetExceededError,
    ModelResolutionError,
    ProviderBudgetError,
    ResponseShapeError,
    TransportError,
)
from jeve.llm.budget import BudgetGuard
from jeve.llm.catalog import (
    DECISION_PREFERENCE,
    GENERATIVE_PREFERENCE,
    ModelCatalog,
)
from jeve.llm.ledger import SpendLedger
from jeve.llm.protocol import (
    Answer,
    ChatRequest,
    ChatResponse,
    DecisionRequest,
    DecisionResponse,
    Purpose,
    Usage,
)

CHAT_PATH = "/chat/completions"


def decisions_url(base_url: str) -> str:
    """Absolute URL for the Decisions endpoint.

    It is a *sibling* of `/api/v1`, not a child: the chat path lives at
    `.../api/v1/chat/completions` but decisions live at
    `.../api/alpha/decisions`. Resolving it against the client's base URL
    silently produces `/api/v1/api/alpha/decisions`, which 404s.
    """

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root}/alpha/decisions"


# Conservative: over-estimating tokens over-reserves, which is the safe
# direction for a ceiling.
CHARS_PER_TOKEN = 3.0
MIN_RESERVATION_USD = 0.0005

# Statuses where the request was rejected before any inference happened, so the
# reservation can be given back. Anything else settles at the reserved amount:
# we cannot prove we were not billed. 402 belongs here — OpenRouter refuses
# before inference when the account cap is spent — and it gets its own raise.
UNBILLED_STATUSES = frozenset({400, 401, 402, 403, 404, 422, 429})

# Worth another attempt. 429 is rejected before inference, so its reservation is
# released; a 5xx or a dropped connection may have been billed, so that attempt
# settles at worst case and the retry reserves afresh. 520-529 are the edge
# saying the origin hiccuped: one 520 ended a 30-day soak before they were here
# (LLM-0006). 501 and 505 stay fatal; those are bugs, not weather.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, *range(520, 530)})
MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 8.0
# How long a server's own "wait this long" is honoured inside the gateway.
# Past this, the call surfaces as weather and the daemon's minutes-scale
# retry takes over (SIM-0002) — matching its cap means neither loop lies.
RETRY_AFTER_CAP_S = 120.0


def _metrics(usage: Usage, latency_s: float) -> dict[str, float]:
    """What a span charts. `estimated_cost` is OpenRouter's own number.

    Braintrust prices a span from its model registry when that field is absent,
    and the registry has never heard of `typesafe/jev-1.13`. An explicitly
    logged cost wins, so the trace and the ledger never disagree.
    """

    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "tokens": usage.input_tokens + usage.output_tokens,
        "estimated_cost": usage.cost_usd,
        "latency_s": latency_s,
    }


def _served(payload: dict[str, Any], usage: Usage) -> dict[str, Any]:
    """Who actually answered, and whether the price is theirs or ours."""

    return {
        "served_model": payload.get("model"),
        "provider": payload.get("provider"),
        "request_id": payload.get("id"),
        "cost_is_estimated": usage.cost_is_estimated,
    }


def _approx_tokens(payload: object) -> int:
    if isinstance(payload, bytes):
        payload = payload.decode()
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return max(1, int(len(text) / CHARS_PER_TOKEN))


class Gateway:
    """Budget-guarded access to OpenRouter."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 60.0,
        max_concurrency: int = 8,
        run_cap_usd: float | None = None,
        backoff_base_s: float = BACKOFF_BASE_S,
    ) -> None:
        self._settings = settings or load_settings()
        self._run_cap_usd = (
            self._settings.run_cap_usd if run_cap_usd is None else run_cap_usd
        )
        self._run_spent_usd = 0.0
        self._run_reserved_usd = 0.0
        self._backoff_base_s = backoff_base_s
        self._generative: tuple[str, ...] = ()
        self._ledger = SpendLedger(checkpoint=self._settings.spend_path)
        self._guard = BudgetGuard(self._settings, self._ledger)
        self._client = httpx.AsyncClient(
            base_url=self._settings.openrouter_base_url,
            headers={
                "Authorization": f"Bearer {self._settings.require_api_key()}",
                "HTTP-Referer": "https://github.com/punitarani/jeve",
                "X-Title": "jeve",
            },
            timeout=timeout_s,
            transport=transport,
        )
        self._decisions_url = decisions_url(self._settings.openrouter_base_url)
        self._permits = asyncio.Semaphore(max_concurrency)
        self._catalog: ModelCatalog | None = None
        self._call_seq = 0
        self._remote_lock = asyncio.Lock()
        self._throttle_until = 0.0
        self._discrepancy_log_disabled = False

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def start(self) -> ModelCatalog:
        """Resolve slugs and take a spend baseline. Fails loudly, early.

        Resolution is per path (LLM-0005). The decision model is the product,
        so an unknown decision slug is fatal here. Prose is a projection: a
        retired generative slug drops out of the preference list, and only a
        list that resolves to nothing is an error — raised by `complete`, when
        prose is actually asked for, not at startup where it would take the
        decision path down with it.
        """

        catalog = await ModelCatalog.fetch(self._client)
        catalog.resolve_all(DECISION_PREFERENCE)
        self._generative = tuple(s for s in GENERATIVE_PREFERENCE if s in catalog)
        self._catalog = catalog
        await self._sync_remote(force=True)
        return catalog

    @property
    def generative_models(self) -> tuple[str, ...]:
        """The escape-hatch models that exist right now, in preference order."""

        if not self._generative:
            raise ModelResolutionError(
                "no generative model resolved; tried: "
                + ", ".join(GENERATIVE_PREFERENCE)
            )
        return self._generative

    @property
    def run_spent_usd(self) -> float:
        return self._run_spent_usd

    async def aclose(self) -> None:
        await self._client.aclose()
        self._ledger.close()
        # The last spans of a script or an API shutdown, before the process
        # has any reason to still be alive.
        tracing.flush()

    @property
    def guard(self) -> BudgetGuard:
        return self._guard

    @property
    def catalog(self) -> ModelCatalog:
        if self._catalog is None:
            raise RuntimeError("Gateway.start() has not run")
        return self._catalog

    # -- spend cross-check -------------------------------------------------

    async def _sync_remote(self, *, force: bool = False) -> float | None:
        """Reconcile the local ledger against `GET /api/v1/key`.

        `/key` reports this credential's lifetime spend; `/credits` reports the
        whole account, so on a shared key another project's traffic would land
        in ours. The first reading is the baseline and only the delta counts.
        """

        if not force and not self._guard.needs_remote_check():
            return None
        async with self._remote_lock:
            try:
                response = await self._client.get("/key")
            except httpx.HTTPError as error:
                raise TransportError(f"could not read key usage: {error}") from error
            if response.status_code != 200:
                raise TransportError(
                    f"/key returned {response.status_code}: {response.text[:200]}"
                )
            data = response.json().get("data") or {}
            usage = float(data.get("usage") or 0.0)
            _, divergence = self._guard.apply_remote(usage)
            if divergence is not None:
                self._log_discrepancy(usage, divergence)
            return usage

    def _log_discrepancy(self, remote_usage: float, divergence: float) -> None:
        if self._discrepancy_log_disabled:
            return
        path = self._settings.ops_dir / "discrepancies.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            spend = self._ledger.read()
            with open(path, "a") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "remote_usage_usd": remote_usage,
                            "remote_delta_usd": spend.remote_delta_usd,
                            "local_usd": spend.local_usd,
                            "divergence": round(divergence, 4),
                            "effective_usd": spend.effective_usd,
                            "note": "remote is authoritative when higher; "
                            "local is a floor",
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        except OSError as error:
            # Same class of failure as the spend checkpoint: an unwritable
            # ops dir must not take the call path down with it — this one
            # did, as a PermissionError inside a decision call on Fly.
            print(f"discrepancy log disabled: {error}", file=sys.stderr)
            self._discrepancy_log_disabled = True

    # -- the two call paths ------------------------------------------------

    def _next_call_id(self, kind: str) -> str:
        self._call_seq += 1
        return f"{kind}-{int(time.time() * 1000)}-{self._call_seq}"

    def _usage_from(self, model: str, raw: dict[str, Any]) -> Usage:
        input_tokens = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
        output_tokens = int(
            raw.get("output_tokens") or raw.get("completion_tokens") or 0
        )
        cost = raw.get("cost")
        if cost is None:
            # OpenRouter marks `usage.cost` optional. Pricing it ourselves keeps
            # the ledger honest; booking $0 would quietly disable the ceiling.
            estimated = self.catalog.estimate_cost_usd(
                model, input_tokens=input_tokens, output_tokens=output_tokens
            )
            return Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimated,
                cost_is_estimated=True,
            )
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=float(cost),
            cost_is_estimated=False,
        )

    def _check_run_cap(self, worst_case_usd: float) -> None:
        """Refuse a call that could take this process past its own cap.

        The ladder protects the night; this protects one run from a loop. It
        counts in-flight reservations for the same reason the ladder does.
        A cap of zero means none — the deployed daemon is governed by the
        daily budget and OpenRouter's own ceiling instead (LLM-0007).
        """

        if self._run_cap_usd <= 0:
            return
        projected = self._run_spent_usd + self._run_reserved_usd + worst_case_usd
        if projected > self._run_cap_usd:
            raise BudgetExceededError(
                f"run cap reached: ${self._run_spent_usd:.4f} spent by this "
                f"process, cap ${self._run_cap_usd:.2f} (JEVE_RUN_CAP_USD)."
            )

    def _note_rate_limit(self, headers: httpx.Headers) -> None:
        """Believe a provider that says the account is out of requests.

        `x-ratelimit-remaining: 0` with a reset time is a promise the next
        call fails too; holding it here means the throttled call waits rather
        than spending one of its retries discovering that.
        """

        remaining = headers.get("x-ratelimit-remaining")
        reset = headers.get("x-ratelimit-reset")
        if remaining is None or reset is None:
            return
        try:
            remaining_n = float(remaining)
            reset_at = float(reset)
        except ValueError:
            return
        if remaining_n > 0:
            return
        # Epoch seconds or milliseconds, depending on the provider.
        if reset_at > 1e12:
            reset_at /= 1000.0
        self._throttle_until = max(self._throttle_until, reset_at)

    @staticmethod
    def _retry_after_seconds(value: str) -> float | None:
        """Parse Retry-After: delta-seconds or an HTTP-date."""

        try:
            return float(value)
        except ValueError:
            pass
        try:
            from email.utils import parsedate_to_datetime

            when = parsedate_to_datetime(value)
        # ruff 0.16.8's formatter rewrites this tuple to `except A, B:` — a
        # SyntaxError, and how all three of these got into the tree in the
        # first place. The skip is what keeps the package importable.
        except (TypeError, ValueError):  # fmt: skip
            return None
        return max(0.0, when.timestamp() - time.time())

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = min(BACKOFF_CAP_S, self._backoff_base_s * (2**attempt))
        if retry_after is not None:
            asked = self._retry_after_seconds(retry_after)
            if asked is not None:
                # The server's word outranks our schedule. Capped at the
                # daemon's own patience: past that the tick retries under
                # waiting_on_model, which is honest about what's happening.
                delay = max(delay, min(RETRY_AFTER_CAP_S, asked))
        # Full jitter on top: eight workers hitting a limit together must not
        # come back together.
        await asyncio.sleep(delay + random.uniform(0.0, delay))

    async def _post(
        self,
        path: str,
        body: dict[str, Any] | bytes,
        *,
        call_id: str,
        model: str,
        worst_case_usd: float,
        purpose: Purpose,
    ) -> tuple[dict[str, Any], float]:
        """Reserve, issue, settle — with bounded retries.

        Each attempt is its own reservation, so every attempt is accounted for
        on its own terms and the ledger never shows one id settling twice.
        """

        last_error: TransportError | None = None
        for attempt in range(MAX_ATTEMPTS):
            attempt_id = call_id if attempt == 0 else f"{call_id}-r{attempt}"
            try:
                return await self._attempt(
                    path,
                    body,
                    call_id=attempt_id,
                    model=model,
                    worst_case_usd=worst_case_usd,
                    purpose=purpose,
                )
            except _Retryable as retry:
                last_error = retry.error
                if attempt + 1 < MAX_ATTEMPTS:
                    await self._backoff(attempt, retry.retry_after)
        assert last_error is not None
        raise last_error

    async def _attempt(
        self,
        path: str,
        body: dict[str, Any] | bytes,
        *,
        call_id: str,
        model: str,
        worst_case_usd: float,
        purpose: Purpose,
    ) -> tuple[dict[str, Any], float]:
        await self._sync_remote()
        self._check_run_cap(worst_case_usd)
        throttled_for = self._throttle_until - time.time()
        if throttled_for > 0:
            await asyncio.sleep(min(RETRY_AFTER_CAP_S, throttled_for))
        self._guard.authorise(
            call_id, worst_case_usd=worst_case_usd, purpose=purpose, model=model
        )
        self._run_reserved_usd += worst_case_usd

        started = time.perf_counter()
        try:
            # One span per HTTP try, under the call's own span. Folding the
            # retries into the parent would hide the 52x weather LLM-0006
            # exists because of; a separate `llm` span each would count the
            # cost four times.
            with tracing.span(
                "openrouter.attempt",
                type="function",
                metadata={"call_id": call_id, "model": model, "path": path},
            ) as attempt:
                try:
                    async with self._permits:
                        if isinstance(body, bytes):
                            # Already serialised: these exact bytes are the
                            # cache key (DECIDE-0004), so they must be what is
                            # sent.
                            response = await self._client.post(
                                path,
                                content=body,
                                headers={"content-type": "application/json"},
                            )
                        else:
                            response = await self._client.post(path, json=body)
                except httpx.HTTPError as error:
                    # Unknown whether it was billed. Keep the reservation as
                    # spend.
                    outcome = f"transport-error: {type(error).__name__}"
                    self._ledger.settle(
                        call_id,
                        worst_case_usd,
                        estimated=True,
                        model=model,
                        outcome=outcome,
                    )
                    self._run_spent_usd += worst_case_usd
                    attempt.log(metadata={"outcome": outcome})
                    raise _Retryable(
                        TransportError(f"{path} failed: {error}"), None
                    ) from error

                latency = time.perf_counter() - started

                self._note_rate_limit(response.headers)

                if response.status_code != 200:
                    status = response.status_code
                    attempt.log(
                        metadata={"http_status": status, "outcome": f"http-{status}"},
                        metrics={"latency_s": latency},
                    )
                    if status in UNBILLED_STATUSES:
                        self._ledger.release(call_id, reason=f"http-{status}-unbilled")
                    else:
                        self._ledger.settle(
                            call_id,
                            worst_case_usd,
                            estimated=True,
                            model=model,
                            outcome=f"http-{status}",
                            latency_s=latency,
                        )
                        self._run_spent_usd += worst_case_usd
                    if status == 402:
                        # LLM-0007: the account cap is spent. Retrying inside
                        # the gateway is pointless — the daemon waits out the
                        # window.
                        raise ProviderBudgetError(
                            f"{path} returned 402: {response.text[:400]}"
                        )
                    failure = TransportError(
                        f"{path} returned {status}: {response.text[:400]}"
                    )
                    if status in RETRYABLE_STATUSES:
                        raise _Retryable(failure, response.headers.get("retry-after"))
                    raise failure

                payload: dict[str, Any] = response.json()
                usage = self._usage_from(model, payload.get("usage") or {})
                self._ledger.settle(
                    call_id,
                    usage.cost_usd,
                    estimated=usage.cost_is_estimated,
                    model=payload.get("model") or model,
                    outcome="ok",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    latency_s=latency,
                    provider=payload.get("provider"),
                )
                self._run_spent_usd += usage.cost_usd
                attempt.log(
                    metadata={"http_status": 200, "outcome": "ok"}
                    | _served(payload, usage),
                    metrics=_metrics(usage, latency),
                )
                payload["__usage"] = usage
                payload["__latency"] = latency
                return payload, latency
        finally:
            self._run_reserved_usd -= worst_case_usd

    async def decide_raw(
        self,
        request: DecisionRequest,
        *,
        purpose: Purpose = "gate",
        parent: str | None = None,
    ) -> RawDecision:
        """Issue a decision request and return the response *unparsed*.

        The recorder stores this before anyone interprets it. A response we
        paid for and then failed to parse must not be paid for again on retry,
        and the stored bytes are what a replay reads back.
        """

        card = self.catalog.get(request.model)
        provider = request.provider
        if provider is not None and not card.accepts_parameters:
            # Jev lists no supported parameters; require_parameters would route
            # the request to nothing at all.
            request = request.model_copy(
                update={
                    "provider": provider.model_copy(update={"require_parameters": None})
                }
            )
        body = request.wire_bytes()

        tokens = _approx_tokens(body)
        worst_case = max(
            MIN_RESERVATION_USD,
            tokens * card.prompt_usd_per_token * 1.5,
        )
        call_id = self._next_call_id("decide")
        with tracing.span(
            "jev.decide",
            type="llm",
            parent=parent,
            # Parsed from the bytes that go on the wire, never rebuilt from the
            # request: what is logged has to be what was asked (DECIDE-0004).
            input=json.loads(body),
            metadata={
                "endpoint": "decisions",
                "model": request.model,
                "purpose": purpose,
                "call_id": call_id,
                "questions": list(request.questions),
            },
        ) as span:
            payload, latency = await self._post(
                self._decisions_url,
                body,
                call_id=call_id,
                model=request.model,
                worst_case_usd=worst_case,
                purpose=purpose,
            )
            usage: Usage = payload.pop("__usage")
            payload.pop("__latency", None)
            span.log(
                output=payload.get("answers"),
                metrics=_metrics(usage, latency),
                metadata=_served(payload, usage),
            )
            return RawDecision(payload=payload, usage=usage, latency_s=latency)

    async def decide(
        self,
        request: DecisionRequest,
        *,
        purpose: Purpose = "gate",
        parent: str | None = None,
    ) -> DecisionResponse:
        """Ask Jev a set of typed questions about one state."""

        raw = await self.decide_raw(request, purpose=purpose, parent=parent)
        return parse_decision(
            raw.payload,
            expected=set(request.questions),
            fallback_model=request.model,
            usage=raw.usage,
            latency_s=raw.latency_s,
        )

    async def complete(
        self,
        request: ChatRequest,
        *,
        purpose: Purpose = "gate",
        parent: str | None = None,
    ) -> ChatResponse:
        """Generate prose. The exception, not the default path."""

        card = self.catalog.get(request.model)
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [m.model_dump(mode="json") for m in request.messages],
            "max_tokens": request.max_tokens,
            # The gateway rejects seeds at or above 2**63 outright, and an
            # unmasked derived seed is above it about half the time. Masking
            # here, at the wire, keeps the caller's seed intact.
            "seed": request.seed % (2**63),
        }
        if request.reasoning is not None:
            body["reasoning"] = request.reasoning
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        if request.provider is not None:
            body["provider"] = request.provider.to_body()

        worst_case = max(
            MIN_RESERVATION_USD,
            _approx_tokens(body) * card.prompt_usd_per_token
            + request.max_tokens * card.completion_usd_per_token,
        )
        call_id = self._next_call_id("chat")
        with tracing.span(
            "chat.completion",
            type="llm",
            parent=parent,
            input=body["messages"],
            metadata={
                "endpoint": "chat",
                "model": request.model,
                "purpose": purpose,
                "call_id": call_id,
                "max_tokens": request.max_tokens,
            },
        ) as span:
            payload, latency = await self._post(
                CHAT_PATH,
                body,
                call_id=call_id,
                model=request.model,
                worst_case_usd=worst_case,
                purpose=purpose,
            )

            usage: Usage = payload["__usage"]
            # Logged before the shape is checked: a reply we paid for and could
            # not read is exactly the one worth looking at afterwards.
            span.log(metrics=_metrics(usage, latency), metadata=_served(payload, usage))

            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ResponseShapeError(
                    f"no choices in response: {str(payload)[:300]}"
                )
            message = choices[0].get("message") or {}
            text = message.get("content")
            if not text:
                raise ResponseShapeError(
                    f"empty completion (finish_reason="
                    f"{choices[0].get('finish_reason', 'unknown')})"
                )

            span.log(output=text)
            return ChatResponse(
                model=str(payload.get("model") or request.model),
                text=str(text),
                usage=usage,
                provider=payload.get("provider"),
                request_id=payload.get("id"),
                latency_s=latency,
            )


@dataclass(frozen=True, slots=True)
class RawDecision:
    """A decisions response exactly as it arrived, plus what it cost."""

    payload: dict[str, Any]
    usage: Usage
    latency_s: float


class _Retryable(Exception):
    """Internal: this attempt failed in a way worth repeating."""

    def __init__(self, error: TransportError, retry_after: str | None) -> None:
        super().__init__(str(error))
        self.error = error
        self.retry_after = retry_after


def parse_decision(
    payload: dict[str, Any],
    *,
    expected: set[str],
    fallback_model: str,
    usage: Usage,
    latency_s: float = 0.0,
) -> DecisionResponse:
    """Interpret a stored or fresh decisions payload. Pure: no I/O, no spend."""

    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict) or not raw_answers:
        raise ResponseShapeError(
            f"decisions response carried no answers: {str(payload)[:300]}"
        )
    answers: dict[str, Answer] = {
        key: _parse_answer(value) for key, value in raw_answers.items()
    }
    missing = expected - set(answers)
    if missing:
        raise ResponseShapeError(f"no answer for questions: {sorted(missing)}")
    return DecisionResponse(
        model=str(payload.get("model") or fallback_model),
        answers=answers,
        usage=usage,
        provider=payload.get("provider"),
        request_id=payload.get("id"),
        latency_s=latency_s,
    )


def _parse_answer(value: object) -> Answer:
    if not isinstance(value, dict):
        raise ResponseShapeError(f"answer is not an object: {value!r}")
    from jeve.llm.protocol import ChoiceAnswer, NoulAnswer, ScoreAnswer

    kind = value.get("type")
    match kind:
        case "noul":
            return NoulAnswer.model_validate(value)
        case "choice":
            return ChoiceAnswer.model_validate(value)
        case "score":
            return ScoreAnswer.model_validate(value)
        case _:
            raise ResponseShapeError(f"unknown answer type {kind!r}")
