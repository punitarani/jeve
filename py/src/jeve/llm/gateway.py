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
import time
from types import TracebackType
from typing import Any, Self

import httpx

from jeve.config import Settings, load_settings
from jeve.errors import ResponseShapeError, TransportError
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
# we cannot prove we were not billed.
UNBILLED_STATUSES = frozenset({400, 401, 403, 404, 422})


def _approx_tokens(payload: object) -> int:
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
    ) -> None:
        self._settings = settings or load_settings()
        self._ledger = SpendLedger(
            self._settings.ledger_path, checkpoint=self._settings.spend_path
        )
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
        """Resolve slugs and take a spend baseline. Fails loudly, early."""

        catalog = await ModelCatalog.fetch(self._client)
        catalog.resolve_all(GENERATIVE_PREFERENCE)
        catalog.resolve_all(DECISION_PREFERENCE)
        self._catalog = catalog
        await self._sync_remote(force=True)
        return catalog

    async def aclose(self) -> None:
        await self._client.aclose()

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
        path = self._settings.ops_dir / "discrepancies.jsonl"
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
                        "note": "remote is authoritative when higher; local is a floor",
                    },
                    sort_keys=True,
                )
                + "\n"
            )

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

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        call_id: str,
        model: str,
        worst_case_usd: float,
        purpose: Purpose,
    ) -> tuple[dict[str, Any], float]:
        """Reserve, issue, settle. Returns the payload and its latency."""

        await self._sync_remote()
        self._guard.authorise(
            call_id, worst_case_usd=worst_case_usd, purpose=purpose, model=model
        )

        started = time.perf_counter()
        try:
            async with self._permits:
                response = await self._client.post(path, json=body)
        except httpx.HTTPError as error:
            # Unknown whether it was billed. Keep the reservation as spend.
            self._ledger.settle(
                call_id,
                worst_case_usd,
                estimated=True,
                model=model,
                outcome=f"transport-error: {type(error).__name__}",
            )
            raise TransportError(f"{path} failed: {error}") from error

        latency = time.perf_counter() - started

        if response.status_code != 200:
            if response.status_code in UNBILLED_STATUSES:
                self._ledger.release(
                    call_id, reason=f"http-{response.status_code}-unbilled"
                )
            else:
                self._ledger.settle(
                    call_id,
                    worst_case_usd,
                    estimated=True,
                    model=model,
                    outcome=f"http-{response.status_code}",
                    latency_s=latency,
                )
            raise TransportError(
                f"{path} returned {response.status_code}: {response.text[:400]}"
            )

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
        payload["__usage"] = usage
        payload["__latency"] = latency
        return payload, latency

    async def decide(
        self, request: DecisionRequest, *, purpose: Purpose = "gate"
    ) -> DecisionResponse:
        """Ask Jev a set of typed questions about one state."""

        card = self.catalog.get(request.model)
        body: dict[str, Any] = {
            "model": request.model,
            "state": request.state,
            "questions": {
                key: question.model_dump(mode="json", exclude_none=True, by_alias=True)
                for key, question in request.questions.items()
            },
        }
        provider = request.provider
        if provider is not None and not card.accepts_parameters:
            # Jev lists no supported parameters; require_parameters would route
            # the request to nothing at all.
            provider = provider.model_copy(update={"require_parameters": None})
        if provider is not None:
            body["provider"] = provider.to_body()

        tokens = _approx_tokens(body)
        worst_case = max(
            MIN_RESERVATION_USD,
            tokens * card.prompt_usd_per_token * 1.5,
        )
        call_id = self._next_call_id("decide")
        payload, latency = await self._post(
            self._decisions_url,
            body,
            call_id=call_id,
            model=request.model,
            worst_case_usd=worst_case,
            purpose=purpose,
        )

        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict) or not raw_answers:
            raise ResponseShapeError(
                f"decisions response carried no answers: {str(payload)[:300]}"
            )
        answers: dict[str, Answer] = {}
        for key, value in raw_answers.items():
            answers[key] = _parse_answer(value)
        missing = set(request.questions) - set(answers)
        if missing:
            raise ResponseShapeError(f"no answer for questions: {sorted(missing)}")

        usage: Usage = payload["__usage"]
        return DecisionResponse(
            model=str(payload.get("model") or request.model),
            answers=answers,
            usage=usage,
            provider=payload.get("provider"),
            request_id=payload.get("id"),
            latency_s=latency,
        )

    async def complete(
        self, request: ChatRequest, *, purpose: Purpose = "gate"
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
        payload, latency = await self._post(
            CHAT_PATH,
            body,
            call_id=call_id,
            model=request.model,
            worst_case_usd=worst_case,
            purpose=purpose,
        )

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ResponseShapeError(f"no choices in response: {str(payload)[:300]}")
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not text:
            raise ResponseShapeError(
                f"empty completion (finish_reason="
                f"{choices[0].get('finish_reason', 'unknown')})"
            )

        usage: Usage = payload["__usage"]
        return ChatResponse(
            model=str(payload.get("model") or request.model),
            text=str(text),
            usage=usage,
            provider=payload.get("provider"),
            request_id=payload.get("id"),
            latency_s=latency,
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
