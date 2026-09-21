"""Model slug resolution (LLM-0002).

Wrong model slugs are the quiet failure in this kind of build: the request is
accepted, something answers, and the run is measuring a model nobody chose. So
every name is resolved against OpenRouter's live catalogue at startup and an
unresolved name is fatal, with near-matches printed.

Two listings are needed. Decision models do not appear in the default
`/models` response at all — they only show up under
`?output_modalities=decisions`.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

import httpx

from jeve.errors import ModelResolutionError, TransportError

# LLM-0006: ordered by measured reliability, cheapest-that-works first. V4.1
# Flash was first on price until it failed 8 of 12 *billed* dialogue attempts,
# which made it about seven times the cost of GLM; it is now the last resort.
# Qwen is deliberately absent. `deepseek-v4-pro-0813` is the dated August build;
# the undated `deepseek/deepseek-v4-pro` still resolves, but to the April weights.
GENERATIVE_PREFERENCE: tuple[str, ...] = (
    "z-ai/glm-5.3-flash",
    "google/gemini-3.8-flash",
    "openai/gpt-5.6-luna",
    "deepseek/deepseek-v4-pro-0813",
    "deepseek/deepseek-v4.1-flash",
)
DECISION_PREFERENCE: tuple[str, ...] = ("typesafe/jev-1.13",)

DECISION_PIN = "typesafe/jev-1.13-20260917"
"""The dated build the cassette was recorded against (DECIDE-0004).

The slug above is undated and the response names the build that answered. A
different build is a different model: its answers are cached under its own
name, and the run halts rather than quietly mixing two models in one world.
Moving this is a decision about the experiment; follow it with
`LIVE=1 make e2e` and commit the cassette."""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """What the gateway needs to know about a model to price and route it."""

    slug: str
    name: str
    context_length: int
    prompt_usd_per_token: float
    completion_usd_per_token: float
    supported_parameters: frozenset[str]
    output_modalities: frozenset[str]

    @property
    def is_decision_model(self) -> bool:
        return "decisions" in self.output_modalities

    @property
    def accepts_parameters(self) -> bool:
        """Jev declares no supported parameters; never send it routing filters."""

        return bool(self.supported_parameters)


def _to_float(value: object) -> float:
    try:
        return float(str(value))
    except TypeError, ValueError:
        return 0.0


def _card(payload: dict[str, object]) -> ModelCard:
    pricing = payload.get("pricing")
    pricing = pricing if isinstance(pricing, dict) else {}
    architecture = payload.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    modalities = architecture.get("output_modalities")
    params = payload.get("supported_parameters")
    return ModelCard(
        slug=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        context_length=int(_to_float(payload.get("context_length") or 0)),
        prompt_usd_per_token=_to_float(pricing.get("prompt")),
        completion_usd_per_token=_to_float(pricing.get("completion")),
        supported_parameters=frozenset(
            str(p) for p in (params if isinstance(params, list) else [])
        ),
        output_modalities=frozenset(
            str(m) for m in (modalities if isinstance(modalities, list) else ["text"])
        ),
    )


class ModelCatalog:
    """Resolved, priced models. Built once per process."""

    def __init__(self, cards: dict[str, ModelCard]) -> None:
        self._cards = cards

    @classmethod
    async def fetch(cls, client: httpx.AsyncClient) -> ModelCatalog:
        cards: dict[str, ModelCard] = {}
        for params in ({}, {"output_modalities": "decisions"}):
            try:
                response = await client.get("/models", params=params)
            except httpx.HTTPError as error:
                raise TransportError(f"could not list models: {error}") from error
            if response.status_code != 200:
                raise TransportError(
                    f"listing models returned {response.status_code}: "
                    f"{response.text[:300]}"
                )
            payload = response.json()
            for item in payload.get("data", []):
                if isinstance(item, dict):
                    card = _card(item)
                    if card.slug:
                        cards[card.slug] = card
        if not cards:
            raise TransportError("OpenRouter returned an empty model catalogue")
        return cls(cards)

    def __contains__(self, slug: str) -> bool:
        return slug in self._cards

    def __len__(self) -> int:
        return len(self._cards)

    def get(self, slug: str) -> ModelCard:
        try:
            return self._cards[slug]
        except KeyError:
            near = difflib.get_close_matches(slug, self._cards, n=5, cutoff=0.4)
            if not near:
                # Fall back to substring matching: difflib is poor at long
                # slugs that share only a vendor prefix.
                stem = slug.split("/")[-1].split("-")[0]
                near = sorted(s for s in self._cards if stem and stem in s)[:5]
            raise ModelResolutionError(
                f"model {slug!r} is not in OpenRouter's catalogue "
                f"({len(self._cards)} models listed). "
                f"Near matches: {', '.join(near) if near else 'none'}"
            ) from None

    def resolve_all(self, slugs: tuple[str, ...]) -> tuple[ModelCard, ...]:
        """Resolve a preference list, failing on the first unknown name."""

        return tuple(self.get(slug) for slug in slugs)

    def estimate_cost_usd(
        self, slug: str, *, input_tokens: int, output_tokens: int
    ) -> float:
        card = self.get(slug)
        return (
            input_tokens * card.prompt_usd_per_token
            + output_tokens * card.completion_usd_per_token
        )
