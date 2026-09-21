"""From an answer to a value: argmax a judgement, sample a propensity.

Pure functions of (question, answer, draw). Nothing here knows whether the
answer arrived over the network a moment ago or out of the cache, and that is
the property replay rests on.
"""

from __future__ import annotations

from jeve.decide.questions import Ask, Draw, Resolved
from jeve.errors import ResponseShapeError
from jeve.llm.protocol import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer


def _ordered(ask: Ask, probabilities: dict[str, float]) -> dict[str, float]:
    """The distribution over the *declared* options, in declared order.

    Normalised, because a provider's probabilities need not sum to one, and
    with any option the response omitted taken as zero.
    """

    raw = [max(0.0, float(probabilities.get(option, 0.0))) for option in ask.options]
    total = sum(raw)
    if total <= 0.0:
        raise ResponseShapeError(
            f"{ask.key}: no probability mass on any declared option "
            f"{list(ask.options)}; got {probabilities}"
        )
    return {
        option: weight / total for option, weight in zip(ask.options, raw, strict=True)
    }


def _sample(distribution: dict[str, float], roll: float) -> str:
    running = 0.0
    last = ""
    for option, weight in distribution.items():
        running += weight
        last = option
        if roll < running:
            return option
    return last  # roll landed in the float dust above the final bucket


def _argmax(distribution: dict[str, float]) -> str:
    # `max` keeps the first of equals, and the dict is in declared order, so a
    # tie resolves the same way on every run.
    return max(distribution, key=lambda option: distribution[option])


def resolve(ask: Ask, answer: Answer, draw: Draw) -> Resolved:
    """Turn one answer into one value. Draws only when the mode calls for it,
    so adding a J question to a set never shifts the draws of the P ones."""

    if isinstance(answer, NoulAnswer):
        p = min(max(float(answer.noul), 0.0), 1.0)
        distribution = {"yes": p, "no": 1.0 - p}
        if ask.mode == "J":
            return Resolved(p >= 0.5, distribution, None)
        roll = draw()
        return Resolved(roll < p, distribution, roll)

    if isinstance(answer, ChoiceAnswer):
        distribution = _ordered(ask, answer.distribution())
        if ask.mode == "J":
            return Resolved(_argmax(distribution), distribution, None)
        roll = draw()
        return Resolved(_sample(distribution, roll), distribution, roll)

    if isinstance(answer, ScoreAnswer):
        if answer.probabilities is None:
            # A score without a distribution is still a judgement we can use;
            # it just cannot be sampled.
            if ask.mode != "J":
                raise ResponseShapeError(
                    f"{ask.key}: score answer has no probabilities to sample"
                )
            level = str(round(answer.score))
            return Resolved(level, {level: 1.0}, None)
        distribution = _ordered(ask, answer.probabilities)
        if ask.mode == "J":
            return Resolved(_argmax(distribution), distribution, None)
        roll = draw()
        return Resolved(_sample(distribution, roll), distribution, roll)

    raise ResponseShapeError(f"{ask.key}: unknown answer type {type(answer).__name__}")
