"""LLM-0001/0003/0004 at the wire: what the gateway sends, and what it books.

Every test here uses a mock transport. The one real call lives in
`scripts/smoke.py` behind `make smoke`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from jeve.config import Settings
from jeve.errors import BudgetExceededError, ResponseShapeError, TransportError
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
from tests.test_catalog import DECISION_MODELS, DEFAULT_MODELS

JEV = "typesafe/jev-1.13"
GLM = "z-ai/glm-5.3-flash"

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
            if "decisions" in path:
                override = self._overrides.get("decisions")
                if isinstance(override, Iterator):
                    # A scripted sequence: one reply per attempt.
                    reply: httpx.Response = next(override)
                    return reply
                return override or httpx.Response(200, json=DECISION_BODY)
            override = self._overrides.get("chat")
            return override or httpx.Response(200, json=CHAT_BODY)

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
