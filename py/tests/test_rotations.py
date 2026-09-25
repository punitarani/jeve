"""A judgement is asked over every order of its options (DECIDE-0007)."""

from __future__ import annotations

from jeve.decide.jev_policy import ROTATED, collapse_rotations, rotated_questions
from jeve.decide.questions import Ask
from jeve.llm.protocol import Answer, Choice, ChoiceAnswer, Noul, NoulCriteria

VERDICT = Ask(
    "allocation",
    "J",
    Choice(
        instructions="Where does the week go?",
        criteria={
            "features": "New features.",
            "debt": "Paying down debt.",
            "reliability": "Reliability.",
            "other": "Something else.",
        },
    ),
)
PROPENSITY = Ask(
    "next_zone",
    "P",
    Choice(instructions="Where next?", criteria={"stay": "Stay.", "other": "Else."}),
)
YES_NO = Ask(
    "done",
    "J",
    Noul(
        instructions="Done?",
        criteria=NoulCriteria.model_validate({"true": "Yes.", "false": "No."}),
    ),
)


def test_only_a_judgement_over_a_choice_is_rotated_and_other_stays_last() -> None:
    questions = rotated_questions([VERDICT, PROPENSITY, YES_NO])
    assert list(questions) == [
        "allocation",
        f"allocation{ROTATED}1",
        f"allocation{ROTATED}2",
        "next_zone",
        "done",
    ]
    orders = [
        list(q.criteria)
        for k, q in questions.items()
        if k.startswith("allocation") and isinstance(q, Choice)
    ]
    assert orders == [
        ["features", "debt", "reliability", "other"],
        ["debt", "reliability", "features", "other"],
        ["reliability", "features", "debt", "other"],
    ]


def _primacy(truth: dict[str, float], order: list[str]) -> ChoiceAnswer:
    """A model that adds weight to whatever it reads first."""

    biased = {o: truth[o] + (0.25 if i == 0 else 0.0) for i, o in enumerate(order)}
    total = sum(biased.values())
    probs = {o: p / total for o, p in biased.items()}
    return ChoiceAnswer(choice=max(probs, key=lambda o: probs[o]), probabilities=probs)


def test_averaging_every_rotation_undoes_a_position_bias() -> None:
    truth = {"features": 0.30, "debt": 0.38, "reliability": 0.27, "other": 0.05}
    questions = rotated_questions([VERDICT])
    answers: dict[str, Answer] = {
        key: _primacy(truth, list(q.criteria))
        for key, q in questions.items()
        if isinstance(q, Choice)
    }
    # One order alone: the first-listed option wins though it is not the best.
    assert answers["allocation"].choice == "features"  # type: ignore[union-attr]
    collapsed = collapse_rotations([VERDICT], answers)["allocation"]
    assert isinstance(collapsed, ChoiceAnswer) and collapsed.choice == "debt"
    assert abs(sum(collapsed.distribution().values()) - 1.0) < 1e-9


def test_a_response_recorded_before_rotations_is_read_as_it_was() -> None:
    only = ChoiceAnswer(
        choice="debt",
        probabilities={"features": 0.2, "debt": 0.5, "reliability": 0.2, "other": 0.1},
    )
    assert collapse_rotations([VERDICT], {"allocation": only}) == {"allocation": only}
