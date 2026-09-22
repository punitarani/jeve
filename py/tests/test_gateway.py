"""LLM-0001/0003/0004 at the wire: what the gateway sends, and what it books.

Every test here uses a mock transport. The one real call lives in
`scripts/smoke.py` behind `make smoke`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve.config import Settings
from jeve.errors import (
    BudgetExceededError,
    ProviderBudgetError,
    ResponseShapeError,
    TransportError,
)
from jeve.llm import (
    GENERATIVE_PREFERENCE,
    ChatMessage,
    ChatRequest,
    Choice,
    ChoiceAnswer,
    DecisionRequest,
    Gateway,
    Noul,
    ProviderPrefs,
    Score,
)
from jeve.llm.gateway import MAX_ATTEMPTS, parse_decision
from tests.conftest import RecordingSink
from tests.test_catalog import DECISION_MODELS, DEFAULT_MODELS

JEV = "typesafe/jev-1.13"
GLM = "z-ai/glm-5.3-flash"


@pytest.fixture(autouse=True)
def _clean_ledger(spend_table: Connection[DictRow]) -> None:
    """The ledger is a Postgres table (LLM-0007): every call here books."""


DECISION_BODY: dict[str, Any] = {
    "id": "gen-1",
    "model": "typesafe/jev-1.13-20260917",
    "provider": "TypeSafe",
    "answers": {
        "urgent": {"type": "noul", "noul": 0.91},
        "queue": {
            "type": "choice",
            "choice": "technical",
            "probabilities": {"technical": 0.8, "billing": 0.2},
            "confidence": 0.7,
        },
        "severity": {
            "type": "score",
            "score": 1.8,
            "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8},
            "confidence": 0.75,
        },
    },
    "usage": {"input_tokens": 400, "output_tokens": 30, "cost": 0.0000168},
}

CHAT_BODY: dict[str, Any] = {
    "id": "gen-2",
    "model": GLM,
    "provider": "GMICloud",
    "choices": [{"message": {"content": "Noted."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 37, "completion_tokens": 5, "cost": 0.0000042},
}


class Recorder:
    """Captures what actually went on the wire."""

    def __init__(self, **overrides: Any) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        self._overrides = overrides

    def transport(self) -> httpx.MockTransport:
        import json

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/models"):
                wants = "decisions" in request.url.params.get("output_modalities", "")
                return httpx.Response(
                    200, json=DECISION_MODELS if wants else DEFAULT_MODELS
                )
            if path.endswith("/key"):
                return httpx.Response(200, json={"data": {"usage": 31.4}})

            self.requests.append(request)
            self.bodies.append(json.loads(request.content))
            decisions = "decisions" in path
            override = self._overrides.get("decisions" if decisions else "chat")
            if isinstance(override, Iterator):
                # A scripted sequence: one reply per attempt, or per model in
                # the generative ladder.
                reply: httpx.Response = next(override)
                return reply
            default = DECISION_BODY if decisions else CHAT_BODY
            return override or httpx.Response(200, json=default)

        return httpx.MockTransport(handler)


def _settings(tmp_path: Path) -> Settings:
    return Settings(openrouter_api_key="sk-test", ops_dir=tmp_path)


async def _gateway(
    tmp_path: Path, recorder: Recorder, *, run_cap_usd: float | None = None
) -> Gateway:
    gateway = Gateway(
        settings=_settings(tmp_path),
        transport=recorder.transport(),
        run_cap_usd=run_cap_usd,
        backoff_base_s=0.0,
    )
    await gateway.start()
    return gateway


def _decision_request() -> DecisionRequest:
    return DecisionRequest(
        model=JEV,
        state={"ticket": "exports are failing"},
        questions={
            "urgent": Noul(instructions="Is the customer blocked?"),
            "queue": Choice(
                instructions="Which team?",
                criteria={"technical": "bugs", "billing": "invoices"},
            ),
            "severity": Score(
                instructions="How bad?",
                criteria=["cosmetic", "degraded", "blocked"],
            ),
        },
        provider=ProviderPrefs(sort="throughput", require_parameters=True),
    )


# -- what goes on the wire ------------------------------------------------


async def test_decisions_go_to_the_sibling_path_not_under_v1(tmp_path: Path) -> None:
    """The endpoint is /api/alpha/decisions, beside /api/v1 rather than inside."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    await gateway.decide(_decision_request())
    await gateway.aclose()

    assert recorder.requests[0].url.path == "/api/alpha/decisions"


async def test_require_parameters_is_stripped_for_jev(tmp_path: Path) -> None:
    """Jev declares no supported parameters; the filter would match nothing."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    await gateway.decide(_decision_request())
    await gateway.aclose()

    provider = recorder.bodies[0]["provider"]
    assert provider["sort"] == "throughput"
    assert "require_parameters" not in provider


async def test_seeds_are_masked_below_2_63(tmp_path: Path) -> None:
    """The gateway rejects larger seeds outright; it killed a 15-day run once."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    await gateway.complete(
        ChatRequest(
            model=GLM,
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=16,
            seed=2**64 - 1,
        )
    )
    await gateway.aclose()

    assert recorder.bodies[0]["seed"] < 2**63


async def test_reasoning_is_omitted_unless_asked_for(tmp_path: Path) -> None:
    """GLM 5.3 Flash rejects `reasoning: {enabled: false}` outright."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    await gateway.complete(
        ChatRequest(
            model=GLM,
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=16,
            seed=1,
        )
    )
    await gateway.aclose()

    assert "reasoning" not in recorder.bodies[0]


# -- answers ---------------------------------------------------------------


async def test_all_three_primitives_parse(tmp_path: Path) -> None:
    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    answer = await gateway.decide(_decision_request())
    await gateway.aclose()

    queue = answer.answers["queue"]
    assert isinstance(queue, ChoiceAnswer)
    assert queue.choice == "technical"
    assert queue.distribution()["technical"] == pytest.approx(0.8)
    assert answer.model == "typesafe/jev-1.13-20260917"


async def test_a_choice_without_probabilities_cannot_be_sampled(
    tmp_path: Path,
) -> None:
    """Silently collapsing to a point mass would fake behavioural diversity."""

    body = dict(DECISION_BODY)
    body["answers"] = {
        **DECISION_BODY["answers"],
        "queue": {"type": "choice", "choice": "technical"},
    }
    recorder = Recorder(decisions=httpx.Response(200, json=body))
    gateway = await _gateway(tmp_path, recorder)
    answer = await gateway.decide(_decision_request())
    await gateway.aclose()

    queue = answer.answers["queue"]
    assert isinstance(queue, ChoiceAnswer)
    with pytest.raises(ResponseShapeError):
        queue.distribution()


async def test_a_missing_answer_is_an_error(tmp_path: Path) -> None:
    body = dict(DECISION_BODY)
    body["answers"] = {"urgent": {"type": "noul", "noul": 0.5}}
    recorder = Recorder(decisions=httpx.Response(200, json=body))
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(ResponseShapeError, match="queue"):
        await gateway.decide(_decision_request())
    await gateway.aclose()


# -- the ledger ------------------------------------------------------------


async def test_real_cost_is_recorded_not_estimated(tmp_path: Path) -> None:
    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert spend.settled_usd == pytest.approx(0.0000168)
    assert spend.estimated_calls == 0
    assert spend.reserved_usd == 0.0


async def test_a_response_without_cost_is_priced_never_free(tmp_path: Path) -> None:
    """OpenRouter marks usage.cost optional; $0 would disable the ceiling."""

    body = {**DECISION_BODY, "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}
    recorder = Recorder(decisions=httpx.Response(200, json=body))
    gateway = await _gateway(tmp_path, recorder)
    await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert spend.settled_usd == pytest.approx(0.042)  # 1M tokens at Jev's price
    assert spend.estimated_calls == 1


async def test_the_key_baseline_is_taken_at_startup(tmp_path: Path) -> None:
    """`/key` is lifetime spend for the credential; only the delta is ours."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert spend.baseline_usd == pytest.approx(31.4)
    assert spend.effective_usd == 0.0


async def test_a_rejected_request_gives_its_reservation_back(tmp_path: Path) -> None:
    recorder = Recorder(decisions=httpx.Response(422, text="bad question"))
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(TransportError):
        await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert spend.effective_usd == 0.0
    assert spend.reserved_usd == 0.0


@pytest.mark.parametrize("status", [500, 520, 529])
async def test_a_server_error_keeps_the_reservation_as_spend(
    tmp_path: Path, status: int
) -> None:
    """A 5xx may still have been billed; assume it was.

    520-529 are here because one 520 ended a 30-day soak (LLM-0006).
    """

    recorder = Recorder(decisions=httpx.Response(status, text="boom"))
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(TransportError):
        await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert spend.settled_usd > 0.0
    # Retried, and every attempt is booked: none of them can be proven free.
    assert len(recorder.requests) == MAX_ATTEMPTS
    assert spend.estimated_calls == MAX_ATTEMPTS
    assert spend.reserved_usd == 0.0


async def test_the_gateway_sends_exactly_the_bytes_that_are_keyed(
    tmp_path: Path,
) -> None:
    """DECIDE-0004: one builder. What the cache hashes is what goes on the wire."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    # As the policy builds it: no routing preferences, which Jev does not accept
    # and which the gateway would otherwise have to adjust before sending.
    request = _decision_request().model_copy(update={"provider": None})

    await gateway.decide(request)
    await gateway.aclose()

    assert recorder.requests[-1].content == request.wire_bytes()
    assert recorder.requests[-1].headers["content-type"] == "application/json"


async def test_a_bug_shaped_5xx_is_not_retried(tmp_path: Path) -> None:
    """501 is a request the server will never serve. Retrying it hides that."""

    recorder = Recorder(decisions=httpx.Response(501, text="not implemented"))
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(TransportError):
        await gateway.decide(_decision_request())
    await gateway.aclose()

    assert len(recorder.requests) == 1


async def test_the_ceiling_refuses_before_issuing(tmp_path: Path) -> None:
    recorder = Recorder()
    settings = Settings(
        openrouter_api_key="sk-test", ops_dir=tmp_path, halt_ceiling_usd=0.000001
    )
    gateway = Gateway(settings=settings, transport=recorder.transport())
    await gateway.start()
    gateway.guard.ledger.reserve("prior", 0.01, purpose="gate", model=JEV)

    with pytest.raises(BudgetExceededError):
        await gateway.decide(_decision_request())
    await gateway.aclose()

    # Nothing reached the wire.
    assert recorder.requests == []


async def test_explore_is_refused_while_gate_work_continues(tmp_path: Path) -> None:
    recorder = Recorder()
    settings = Settings(
        openrouter_api_key="sk-test", ops_dir=tmp_path, explore_ceiling_usd=0.000001
    )
    gateway = Gateway(settings=settings, transport=recorder.transport())
    await gateway.start()
    gateway.guard.ledger.reserve("prior", 0.01, purpose="gate", model=JEV)

    with pytest.raises(BudgetExceededError, match="exploratory"):
        await gateway.decide(_decision_request(), purpose="explore")
    await gateway.decide(_decision_request(), purpose="gate")
    await gateway.aclose()

    assert len(recorder.requests) == 1


async def test_a_429_is_retried_and_books_nothing(tmp_path: Path) -> None:
    """Rate-limited requests never reached inference. Booking worst case for
    each one would invent spend at exactly the moment the run is busiest."""

    recorder = Recorder(
        decisions=iter(
            [
                httpx.Response(429, text="slow down", headers={"retry-after": "0"}),
                httpx.Response(429, text="slow down"),
                httpx.Response(200, json=DECISION_BODY),
            ]
        )
    )
    gateway = await _gateway(tmp_path, recorder)
    response = await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert len(recorder.requests) == 3
    assert response.answers
    assert spend.calls == 1
    assert spend.estimated_calls == 0
    assert spend.reserved_usd == 0.0
    assert spend.settled_usd == pytest.approx(DECISION_BODY["usage"]["cost"])


def test_retry_after_parses_seconds_and_http_dates() -> None:
    """Both legal forms must be honoured (B1/B2 in the deployment audit)."""

    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    from jeve.llm.gateway import Gateway

    assert Gateway._retry_after_seconds("30") == pytest.approx(30.0)
    assert Gateway._retry_after_seconds("0") == 0.0
    assert Gateway._retry_after_seconds("garbage") is None

    in_a_minute = datetime.now(UTC) + timedelta(seconds=60)
    parsed = Gateway._retry_after_seconds(format_datetime(in_a_minute))
    assert parsed is not None and 50 < parsed <= 61
    past = Gateway._retry_after_seconds(
        format_datetime(datetime.now(UTC) - timedelta(seconds=5))
    )
    assert past == 0.0


async def test_a_402_is_budget_not_weather(tmp_path: Path) -> None:
    """A spent account cap is not an outage: never retried, never billed."""

    recorder = Recorder(
        decisions=iter(
            [
                httpx.Response(402, text="insufficient credits"),
                httpx.Response(200, json=DECISION_BODY),
            ]
        )
    )
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(ProviderBudgetError):
        await gateway.decide(_decision_request())
    spend = gateway.guard.state().spend
    await gateway.aclose()

    # One attempt only — a retry cannot refill credit — and it booked
    # nothing, since the request never reached inference.
    assert len(recorder.requests) == 1
    assert spend.effective_usd == 0.0


async def test_rate_limit_headers_hold_the_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`x-ratelimit-remaining: 0` is a promise the next call fails too."""

    reset = 9_999_999_999.0  # far-future epoch: the wait is what we assert
    recorder = Recorder(
        decisions=httpx.Response(
            200,
            json=DECISION_BODY,
            headers={
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": str(reset),
            },
        )
    )
    gateway = await _gateway(tmp_path, recorder)
    await gateway.decide(_decision_request())
    assert gateway._throttle_until == pytest.approx(reset)

    waits: list[float] = []

    async def spy(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", spy)
    await gateway.decide(_decision_request())
    await gateway.aclose()

    # The second call waited out the reset rather than spending a retry.
    assert waits and waits[0] > 60


async def test_retry_after_is_not_clamped_to_the_backoff_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider asking for 30s must not be retried at 8s — it just fails again."""

    import asyncio

    from jeve.llm.gateway import Gateway

    waits: list[float] = []

    async def spy(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", spy)
    gateway = Gateway(
        settings=_settings(tmp_path),
        transport=Recorder().transport(),
        backoff_base_s=0.0,
    )
    try:
        await gateway._backoff(0, "30")
        await gateway._backoff(0, None)
    finally:
        await gateway.aclose()

    assert waits[0] >= 30.0
    # With no Retry-After, the usual sub-second base applies.
    assert waits[1] < 1.0


async def test_the_run_cap_stops_a_process_before_the_ladder_would(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder, run_cap_usd=0.0007)

    await gateway.decide(_decision_request())
    with pytest.raises(BudgetExceededError, match="run cap"):
        # One settled call plus one more worst-case reservation crosses it.
        for _ in range(50):
            await gateway.decide(_decision_request())
    await gateway.aclose()

    assert gateway.guard.state().spend.reserved_usd == 0.0


async def test_a_retired_generative_slug_does_not_block_decisions(
    tmp_path: Path,
) -> None:
    """LLM-0005: prose is a projection. Losing a prose model must not stop Jev."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)

    # The fixture catalogue lacks some of the five escape-hatch models.
    assert set(gateway.generative_models) < set(GENERATIVE_PREFERENCE)
    # LLM-0006: reliability order, so GLM leads and V4.1 Flash is the last resort.
    assert gateway.generative_models[0] == GLM
    assert gateway.generative_models[-1] == "deepseek/deepseek-v4.1-flash"
    response = await gateway.decide(_decision_request())
    await gateway.aclose()
    assert response.answers


async def test_the_raw_response_is_available_before_it_is_parsed(
    tmp_path: Path,
) -> None:
    """A response that was paid for and then fails to parse must still be
    recordable, or every retry pays for it again."""

    broken = {**DECISION_BODY, "answers": {"urgent": {"type": "mystery"}}}
    recorder = Recorder(decisions=httpx.Response(200, json=broken))
    gateway = await _gateway(tmp_path, recorder)

    raw = await gateway.decide_raw(_decision_request())
    assert raw.payload["answers"] == broken["answers"]
    assert raw.usage.cost_usd > 0.0
    assert "__usage" not in raw.payload

    with pytest.raises(ResponseShapeError):
        parse_decision(
            raw.payload,
            expected={"urgent"},
            fallback_model=JEV,
            usage=raw.usage,
        )
    await gateway.aclose()


# -- spans (LLM-0008) ------------------------------------------------------


async def test_a_decision_call_is_one_llm_span_carrying_the_real_cost(
    tmp_path: Path, spans: RecordingSink
) -> None:
    """The trace and the ledger must never disagree about what a call cost."""

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    request = _decision_request().model_copy(update={"provider": None})

    await gateway.decide(request)
    await gateway.aclose()

    span = spans.only("jev.decide")
    assert span.type == "llm"
    # Read from the bytes that were posted, not rebuilt from the request.
    assert span.fields["input"] == json.loads(request.wire_bytes())
    assert span.fields["output"] == DECISION_BODY["answers"]
    assert span.fields["metrics"] == {
        "prompt_tokens": 400,
        "completion_tokens": 30,
        "tokens": 430,
        # OpenRouter's own number, not an estimate from a model registry that
        # has never heard of jev.
        "estimated_cost": DECISION_BODY["usage"]["cost"],
        "latency_s": pytest.approx(span.fields["metrics"]["latency_s"]),
    }
    assert span.fields["metadata"]["served_model"] == DECISION_BODY["model"]
    assert span.fields["metadata"]["provider"] == "TypeSafe"
    assert span.fields["metadata"]["cost_is_estimated"] is False
    assert sorted(span.fields["metadata"]["questions"]) == [
        "queue",
        "severity",
        "urgent",
    ]
    assert [child.name for child in span.children] == ["openrouter.attempt"]


async def test_a_catalogue_priced_call_says_so_on_the_span(
    tmp_path: Path, spans: RecordingSink
) -> None:
    """`usage.cost` is optional upstream. A span must not imply it was there."""

    priced = {**DECISION_BODY, "usage": {"input_tokens": 400, "output_tokens": 30}}
    recorder = Recorder(decisions=httpx.Response(200, json=priced))
    gateway = await _gateway(tmp_path, recorder)

    await gateway.decide(_decision_request())
    await gateway.aclose()

    span = spans.only("jev.decide")
    assert span.fields["metadata"]["cost_is_estimated"] is True
    assert span.fields["metrics"]["estimated_cost"] > 0.0


async def test_retries_are_children_of_one_llm_span_not_four_of_them(
    tmp_path: Path, spans: RecordingSink
) -> None:
    """Four `llm` spans would count the cost four times; none would hide the
    52x weather LLM-0006 exists because of."""

    replies = iter(
        [
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=DECISION_BODY),
        ]
    )
    recorder = Recorder(decisions=replies)
    gateway = await _gateway(tmp_path, recorder)

    await gateway.decide(_decision_request())
    await gateway.aclose()

    call = spans.only("jev.decide")
    attempts = [child for child in call.children if child.name == "openrouter.attempt"]
    assert len(attempts) == 2
    assert attempts[0].fields["metadata"]["outcome"] == "http-503"
    assert attempts[1].fields["metadata"]["outcome"] == "ok"


async def test_a_failed_call_records_the_failure_and_still_raises(
    tmp_path: Path, spans: RecordingSink
) -> None:
    recorder = Recorder(decisions=httpx.Response(501, text="not implemented"))
    gateway = await _gateway(tmp_path, recorder)

    with pytest.raises(TransportError):
        await gateway.decide(_decision_request())
    await gateway.aclose()

    assert "TransportError" in (spans.only("jev.decide").error or "")


async def test_prose_is_a_chat_span_with_the_messages_as_input(
    tmp_path: Path, spans: RecordingSink
) -> None:
    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)

    await gateway.complete(
        ChatRequest(
            model=GLM,
            messages=[ChatMessage(role="user", content="Say something.")],
            max_tokens=64,
            seed=7,
        ),
        purpose="explore",
    )
    await gateway.aclose()

    span = spans.only("chat.completion")
    assert span.type == "llm"
    assert span.fields["input"] == [{"role": "user", "content": "Say something."}]
    assert span.fields["output"] == "Noted."
    assert span.fields["metadata"]["purpose"] == "explore"
    assert span.fields["metrics"]["prompt_tokens"] == 37
    assert span.fields["metrics"]["estimated_cost"] == CHAT_BODY["usage"]["cost"]


async def test_tracing_off_changes_neither_the_bytes_nor_the_booking(
    tmp_path: Path,
) -> None:
    """CORE-0005/DECIDE-0004: a span is a side effect or it is a bug.

    No `spans` fixture here — this is the default path, the one CI and a clean
    clone take.
    """

    recorder = Recorder()
    gateway = await _gateway(tmp_path, recorder)
    request = _decision_request().model_copy(update={"provider": None})

    reply = await gateway.decide(request)
    spend = gateway.guard.state().spend
    await gateway.aclose()

    assert recorder.requests[-1].content == request.wire_bytes()
    assert reply.usage.cost_usd == DECISION_BODY["usage"]["cost"]
    assert spend.settled_usd == pytest.approx(DECISION_BODY["usage"]["cost"])


async def test_closing_the_gateway_flushes(
    tmp_path: Path, spans: RecordingSink
) -> None:
    """A script or an API shutdown must not lose its last spans."""

    gateway = await _gateway(tmp_path, Recorder())
    await gateway.aclose()

    assert spans.flushes == 1


# -- traces and metrics (OBS-0001) -----------------------------------------


def test_a_decision_call_is_a_span_with_its_cost_and_tokens(
    tmp_path: Path,
) -> None:
    """OBS-0001: the money path is the one worth tracing.

    One logical call is one span with the retries as children, and the cost
    and token counts come off the same `Usage` the ledger settles against —
    so a chart of spend and the ledger cannot disagree.
    """

    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from jeve import obs
    from tests.conftest import counter_points

    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    obs.shutdown()
    obs.start(
        "jeve-test",
        settings=Settings(axiom_token="test-token"),
        span_exporter=spans,
        metric_reader=reader,
        log_exporter=InMemoryLogRecordExporter(),  # type: ignore[no-untyped-call]
    )
    try:
        recorder = Recorder()

        async def run() -> None:
            gateway = await _gateway(tmp_path, recorder)
            await gateway.decide(_decision_request())
            await gateway.aclose()

        asyncio.run(run())
        data = reader.get_metrics_data()
        obs.shutdown()

        finished = {s.name: s for s in spans.get_finished_spans()}
        call = finished[f"decide {JEV}"]
        attributes = call.attributes or {}
        assert attributes["gen_ai.operation.name"] == "decide"
        assert attributes["gen_ai.provider.name"] == "openrouter"
        assert attributes["gen_ai.request.model"] == JEV
        assert attributes["gen_ai.response.model"] == DECISION_BODY["model"]
        assert attributes["jeve.attempts"] == 1
        # The prompt is never recorded: generated text does not leave the
        # process, and the state we send is the simulation's own (GEN-0001).
        assert not [k for k in attributes if "messages" in k or "prompt" in k]

        # The HTTP round trip is a child, so a retry is visible as a second
        # child rather than as a second call.
        attempt = finished["gen_ai.attempt"]
        assert (attempt.attributes or {})["http.response.status_code"] == 200
        assert attempt.parent is not None
        assert attempt.parent.span_id == call.context.span_id

        calls = counter_points(data, "jeve.llm.calls")
        assert list(calls.values()) == [1]
        assert "jeve.outcome=ok" in next(iter(calls))

        cost = counter_points(data, "jeve.llm.cost")
        assert sum(cost.values()) == pytest.approx(
            float(str(attributes["jeve.cost_usd"]))
        )
    finally:
        obs.shutdown()
