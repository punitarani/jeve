"""Judgement takes the argmax, propensity is sampled — and both are stable.

These are tests of arithmetic, so the answers are written by hand: a
distribution chosen to make the property visible. That is not a stand-in for
Jev (nothing here pretends to be a model); what Jev actually says is exercised
from the recorded cassette in `test_jev_policy.py`.
"""

from __future__ import annotations

import itertools

import pytest

from jeve.decide.questions import Ask, per_tick_hazard
from jeve.decide.sampling import resolve
from jeve.errors import ResponseShapeError
from jeve.llm.protocol import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
)

QUEUES = {"technical": "broken", "billing": "money", "account": "login", "other": "?"}


def _choice(mode: str) -> Ask:
    return Ask("queue", mode, Choice(instructions="Which?", criteria=QUEUES))  # type: ignore[arg-type]


def _noul(mode: str) -> Ask:
    return Ask("yes", mode, Noul(instructions="Well?"))  # type: ignore[arg-type]


def _never() -> float:
    raise AssertionError("a judgement must not consume a draw")


def test_a_judgement_takes_the_argmax_and_draws_nothing() -> None:
    answer = ChoiceAnswer(
        choice="billing",
        probabilities={"technical": 0.2, "billing": 0.7, "account": 0.1, "other": 0.0},
    )
    got = resolve(_choice("J"), answer, _never)
    assert got.value == "billing"
    assert got.draw is None


def test_a_propensity_is_sampled_not_argmaxed() -> None:
    """The point of the whole design. Argmax would send every customer with
    P(buy)=0.4 out of the door; sampling sends four in ten to the till."""

    answer = NoulAnswer(noul=0.4)

    def at(roll: float) -> object:
        return resolve(_noul("P"), answer, lambda: roll).value

    bought = [at(i / 1000) for i in range(1000)].count(True)
    assert bought == 400
    assert resolve(_noul("J"), answer, _never).value is False


def test_sampling_does_not_depend_on_the_order_a_response_lists_options() -> None:
    """Postgres JSONB reorders keys, and so may a provider. If sampling walked
    the response's own order, a replayed call would draw differently from the
    live call it recorded. It walks the declared order."""

    weights = {"technical": 0.4, "billing": 0.3, "account": 0.2, "other": 0.1}
    outcomes = set()
    for order in itertools.permutations(weights):
        shuffled = {key: weights[key] for key in order}
        answer = ChoiceAnswer(choice="technical", probabilities=shuffled)
        got = resolve(_choice("P"), answer, lambda: 0.65)
        outcomes.add(got.value)
        assert list(got.distribution) == list(QUEUES)
    # 0.65 falls in billing's slice of the *declared* order: [0.4, 0.7).
    assert outcomes == {"billing"}


def test_a_distribution_that_does_not_sum_to_one_is_normalised() -> None:
    answer = ChoiceAnswer(
        choice="technical", probabilities={"technical": 2.0, "billing": 2.0}
    )
    got = resolve(_choice("P"), answer, lambda: 0.75)
    assert got.distribution["technical"] == pytest.approx(0.5)
    assert got.distribution["other"] == 0.0
    assert got.value == "billing"


def test_a_roll_in_the_float_dust_above_the_last_bucket_still_lands() -> None:
    answer = ChoiceAnswer(
        choice="other",
        probabilities={"technical": 0.1, "billing": 0.2, "account": 0.3, "other": 0.4},
    )
    assert resolve(_choice("P"), answer, lambda: 0.9999999999999999).value == "other"


def test_no_mass_on_any_declared_option_is_an_error_not_a_guess() -> None:
    answer = ChoiceAnswer(choice="refund", probabilities={"refund": 1.0})
    with pytest.raises(ResponseShapeError, match="no probability mass"):
        resolve(_choice("P"), answer, lambda: 0.5)


def test_a_choice_without_probabilities_cannot_be_sampled() -> None:
    with pytest.raises(ResponseShapeError, match="no probabilities"):
        resolve(_choice("P"), ChoiceAnswer(choice="billing"), lambda: 0.5)


def test_a_hazard_question_is_thinned_before_it_is_sampled() -> None:
    answer = NoulAnswer(noul=0.5)
    hazard = per_tick_hazard(0.5)
    below = resolve(_noul("H"), answer, lambda: hazard * 0.99)
    above = resolve(_noul("H"), answer, lambda: hazard * 1.01)
    assert (below.value, above.value) == (True, False)
    # What is stored is what Jev said, not the thinned figure.
    assert below.distribution == {"yes": 0.5, "no": 0.5}


def test_a_score_judgement_is_its_most_likely_level() -> None:
    ask = Ask(
        "severity",
        "J",
        Score(
            instructions="How bad?", criteria=["fine really", "slowed down", "stuck"]
        ),
    )
    answer = ScoreAnswer(score=1.4, probabilities={"2": 0.35, "0": 0.05, "1": 0.6})
    got = resolve(ask, answer, _never)
    assert got.value == "1"
    assert list(got.distribution) == ["0", "1", "2"]
