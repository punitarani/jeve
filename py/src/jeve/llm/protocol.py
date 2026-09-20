"""Wire types for the two things we ask OpenRouter for.

Typed decisions (noul / choice / score) come from the Decisions endpoint and
drive the simulation. Chat completions render prose and are the exception.

The decision shapes follow OpenRouter's published schema for
`POST /api/alpha/decisions`, in which `probabilities` and `confidence` are
*optional* on an answer. Code that needs a distribution must say so.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from jeve.errors import ResponseShapeError

type Purpose = Literal["gate", "explore"]
"""Why a call is being made. `explore` is refused once spend passes $12."""

# Instructions and criteria accept structure, not just strings (TypeSafe's
# "advanced structure"): a dict puts the question in one field and the data it
# refers to in others.
type Prose = str | dict[str, object] | list[object]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------
# Questions
# --------------------------------------------------------------------------


class NoulCriteria(_Frozen):
    # OpenRouter requires both keys when criteria is present at all.
    true_: Prose = Field(alias="true")
    false_: Prose = Field(alias="false")

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Noul(_Frozen):
    """Yes/no. The answer is P(yes) — there is no separate confidence."""

    type: Literal["noul"] = "noul"
    instructions: Prose
    criteria: NoulCriteria | None = None


class Choice(_Frozen):
    """One option from a fixed set. Max 255 options."""

    type: Literal["choice"] = "choice"
    instructions: Prose
    criteria: dict[str, Prose | None] = Field(min_length=2, max_length=255)


class Score(_Frozen):
    """A position on ordered, *described* levels. Numerals as levels perform badly."""

    type: Literal["score"] = "score"
    instructions: Prose
    criteria: list[Prose] = Field(min_length=2, max_length=10)


type Question = Annotated[Noul | Choice | Score, Field(discriminator="type")]


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------


class NoulAnswer(_Frozen):
    type: Literal["noul"] = "noul"
    noul: float

    def probability(self) -> float:
        return self.noul


class ChoiceAnswer(_Frozen):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float] | None = None
    confidence: float | None = None

    def distribution(self) -> dict[str, float]:
        """The full distribution, or a clear failure.

        Sampling a propensity needs real probabilities. A provider that returns
        only the argmax cannot drive an agent, and silently collapsing to a
        point mass would fake diversity.
        """

        if self.probabilities is None:
            raise ResponseShapeError(
                "choice answer carried no probabilities; sampling is impossible"
            )
        return self.probabilities


class ScoreAnswer(_Frozen):
    type: Literal["score"] = "score"
    score: float
    legend: dict[str, Prose] | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


type Answer = Annotated[
    NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")
]


# --------------------------------------------------------------------------
# Requests and responses
# --------------------------------------------------------------------------


class ProviderPrefs(_Frozen):
    """Per-request provider routing (LLM-0003).

    Never sent to a model that declares no supported parameters: Jev lists
    `supported_parameters: []`, and `require_parameters` against it would
    route the request to nothing.
    """

    order: list[str] | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None
    sort: Literal["price", "throughput", "latency"] | None = None
    allow_fallbacks: bool = True
    require_parameters: bool | None = None

    def to_body(self) -> dict[str, object]:
        body: dict[str, object] = {"allow_fallbacks": self.allow_fallbacks}
        for key in ("order", "only", "ignore", "sort", "require_parameters"):
            value = getattr(self, key)
            if value is not None:
                body[key] = value
        return body


class Usage(_Frozen):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_is_estimated: bool = False
    """True when the response omitted `usage.cost` and we priced it ourselves."""


class DecisionRequest(_Frozen):
    model: str
    state: str | dict[str, object] | list[object]
    questions: dict[str, Question] = Field(min_length=1)
    provider: ProviderPrefs | None = None


class DecisionResponse(_Frozen):
    model: str
    answers: dict[str, Answer]
    usage: Usage
    provider: str | None = None
    request_id: str | None = None
    latency_s: float = 0.0


class ChatMessage(_Frozen):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(_Frozen):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    seed: int = Field(ge=0)
    temperature: float | None = None
    response_schema: dict[str, object] | None = None
    provider: ProviderPrefs | None = None
    reasoning: dict[str, object] | None = None
    """Sent verbatim when set, omitted otherwise.

    Disabling reasoning outright looks attractive — a model that spends its
    whole budget thinking returns empty content — but several current models
    reject it: GLM 5.3 Flash answers `reasoning is mandatory for this endpoint
    and cannot be disabled`. So the default is to say nothing and to size
    `max_tokens` with room for thinking.
    """


class ChatResponse(_Frozen):
    model: str
    text: str
    usage: Usage
    provider: str | None = None
    request_id: str | None = None
    latency_s: float = 0.0
