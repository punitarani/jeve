"""LLM-0002: slug resolution refuses to guess."""

from __future__ import annotations

import httpx
import pytest

from jeve.errors import ModelResolutionError, TransportError
from jeve.llm.catalog import ModelCatalog

DEFAULT_MODELS = {
    "data": [
        {
            "id": "z-ai/glm-5.3-flash",
            "name": "Z.ai: GLM 5.3 Flash",
            "context_length": 1310720,
            "pricing": {"prompt": "0.00000009", "completion": "0.0000003"},
            "supported_parameters": ["temperature", "seed", "structured_outputs"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "deepseek/deepseek-v4.1-flash",
            "name": "DeepSeek: DeepSeek V4.1 Flash",
            "context_length": 1048576,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
            "supported_parameters": ["temperature", "seed"],
            "architecture": {"output_modalities": ["text"]},
        },
        {
            "id": "openai/gpt-5.6-luna",
            "name": "OpenAI: GPT-5.6 Luna",
            "context_length": 1050000,
            "pricing": {"prompt": "0.0000002", "completion": "0.0000012"},
            "supported_parameters": ["temperature", "seed"],
            "architecture": {"output_modalities": ["text"]},
        },
    ]
}

DECISION_MODELS = {
    "data": [
        {
            "id": "typesafe/jev-1.13",
            "name": "TypeSafe: Jev 1.13",
            "context_length": 32000,
            "pricing": {"prompt": "0.000000042", "completion": "0"},
            "supported_parameters": [],
            "architecture": {"output_modalities": ["decisions"]},
        }
    ]
}


def _client(*, decisions: bool = True, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="upstream is unhappy")
        wants_decisions = "decisions" in request.url.params.get("output_modalities", "")
        if wants_decisions:
            return httpx.Response(
                200, json=DECISION_MODELS if decisions else {"data": []}
            )
        return httpx.Response(200, json=DEFAULT_MODELS)

    return httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1",
        transport=httpx.MockTransport(handler),
    )


async def test_decision_models_need_the_second_listing() -> None:
    """Jev is absent from the default /models response entirely."""

    async with _client() as client:
        catalog = await ModelCatalog.fetch(client)

    assert "typesafe/jev-1.13" in catalog
    assert catalog.get("typesafe/jev-1.13").is_decision_model is True
    assert catalog.get("z-ai/glm-5.3-flash").is_decision_model is False


async def test_a_model_missing_from_the_decisions_listing_is_not_resolvable() -> None:
    async with _client(decisions=False) as client:
        catalog = await ModelCatalog.fetch(client)

    with pytest.raises(ModelResolutionError):
        catalog.get("typesafe/jev-1.13")


async def test_an_unknown_slug_fails_with_near_matches() -> None:
    """A typo must name the alternatives, not fall back to a default."""

    async with _client() as client:
        catalog = await ModelCatalog.fetch(client)

    with pytest.raises(ModelResolutionError) as caught:
        catalog.get("z-ai/glm-5.3-flash-latest")
    assert "z-ai/glm-5.3-flash" in str(caught.value)


async def test_a_model_that_never_existed_still_names_something() -> None:
    """'Qwen 3.8 Next Flash' was supplied from memory and does not exist."""

    async with _client() as client:
        catalog = await ModelCatalog.fetch(client)

    with pytest.raises(ModelResolutionError) as caught:
        catalog.get("qwen/qwen3.8-next-flash")
    assert "catalogue" in str(caught.value)


async def test_prices_come_from_the_catalogue() -> None:
    async with _client() as client:
        catalog = await ModelCatalog.fetch(client)

    cost = catalog.estimate_cost_usd(
        "typesafe/jev-1.13", input_tokens=1_000_000, output_tokens=5_000
    )
    assert cost == pytest.approx(0.042)


async def test_jev_accepts_no_parameters() -> None:
    """require_parameters against an empty list routes to nothing (LLM-0003)."""

    async with _client() as client:
        catalog = await ModelCatalog.fetch(client)

    assert catalog.get("typesafe/jev-1.13").accepts_parameters is False
    assert catalog.get("z-ai/glm-5.3-flash").accepts_parameters is True


async def test_a_failed_listing_is_an_error_not_an_empty_catalogue() -> None:
    async with _client(status=503) as client:
        with pytest.raises(TransportError):
            await ModelCatalog.fetch(client)
