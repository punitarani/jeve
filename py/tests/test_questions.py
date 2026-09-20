"""The question sets, linted (DECIDE-0003).

Each rule here exists because of how Jev behaves, and a set that breaks one
fails quietly in production — a worse distribution, not an exception. So they
are checked where a broken set costs a test run rather than a night.
"""

from __future__ import annotations

import math

import pytest

from jeve.decide.policy import DecisionContext
from jeve.decide.questions import (
    OFFICE_TICKS_PER_DAY,
    QUESTION_SETS,
    Prepared,
    per_tick_hazard,
    trait_level,
)
from jeve.llm.protocol import Choice, Score

# One context per kind that gets past every code gate, so a question is asked.
ASKING: dict[str, dict[str, object]] = {
    "file.ticket": {"module_down": True, "already_open": False},
    "ticket.triage": {"subject": "exports fail", "module_down": True, "backlog": 12},
    "ticket.answer": {"backlog": 12},
    "payment.timing": {"days_until_due": -4, "can_afford": True, "runway_days": 9},
    "cafe.purchase": {"pos_down": True, "queue_length": 3},
}
TRAITS: dict[str, object] = {
    "diligence": 0.41,
    "promptness": 0.8,
    "patience": 0.33,
    "vocality": 0.7,
    "risk_appetite": 0.2,
}


def _prepare(kind: str, facts: dict[str, object] | None = None) -> Prepared:
    return QUESTION_SETS[kind].prepare(
        DecisionContext(
            person_id="p",
            role="r",
            decision_seq=0,
            sim_time=10 * 3600,
            kind=kind,
            facts=ASKING[kind] if facts is None else facts,
            traits=TRAITS,
        )
    )


def _numbers_in(value: object) -> list[object]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers_in(v)]
    if isinstance(value, list | tuple):
        return [n for v in value for n in _numbers_in(v)]
    return []


def test_every_engine_decision_kind_has_a_set() -> None:
    assert set(ASKING) == set(QUESTION_SETS)


@pytest.mark.parametrize("kind", sorted(QUESTION_SETS))
def test_state_is_words_not_numbers(kind: str) -> None:
    """Jev is weak at arithmetic and reads literally. A raw 0.33 in the state
    is noise at best; it is also what would stop identical situations sharing
    a cached call."""

    prepared = _prepare(kind)
    assert prepared.needs_model
    assert _numbers_in(prepared.state) == []


@pytest.mark.parametrize("kind", sorted(QUESTION_SETS))
def test_every_choice_can_decline_and_no_level_is_a_bare_number(kind: str) -> None:
    for ask in _prepare(kind).asks:
        assert ask.mode in ("J", "P", "H")
        if isinstance(ask.question, Choice):
            # Without an exit, a model that finds no option apt is forced to
            # put its mass somewhere, and that mass is then sampled as if meant.
            assert "other" in ask.question.criteria
            assert list(ask.options) == list(ask.question.criteria)
        if isinstance(ask.question, Score):
            for level in ask.question.criteria:
                assert isinstance(level, str) and not level.strip().isdigit()
                assert len(level.split()) >= 3


@pytest.mark.parametrize("kind", sorted(QUESTION_SETS))
def test_the_same_situation_renders_the_same_request(kind: str) -> None:
    """The cache key is a hash of this. Anything unstable in it — a set, a
    timestamp, an id — turns every call into a miss."""

    assert _prepare(kind) == _prepare(kind)


def test_hard_constraints_are_gates_not_questions() -> None:
    """Whether an org can afford an invoice is a ledger fact. A model asked
    about it could pay with money that does not exist."""

    broke = _prepare(
        "payment.timing", {"days_until_due": -4, "can_afford": False, "runway_days": 1}
    )
    assert not broke.needs_model
    assert broke.gated == {"pay": False, "reason": "insufficient_cash"}

    early = _prepare("payment.timing", {"days_until_due": 3, "can_afford": True})
    assert early.gated == {"pay": False, "reason": "not_due"}

    already = _prepare("file.ticket", {"module_down": True, "already_open": True})
    assert already.gated == {"file": False}


def test_traits_are_bucketed_over_the_range_they_are_seeded_in() -> None:
    # patience is seeded over [0.30, 0.90]: 0.45 is low *for this population*.
    assert trait_level("patience", 0.31) == 0
    assert trait_level("patience", 0.45) == 0
    assert trait_level("patience", 0.60) == 1
    assert trait_level("patience", 0.89) == 2
    assert trait_level("vocality", 0.45) == 1


@pytest.mark.parametrize("p_day", [0.05, 0.26, 0.5, 0.9])
def test_a_daily_propensity_asked_every_tick_still_comes_out_daily(
    p_day: float,
) -> None:
    """Sampling a day-level probability every tick compounds: 0.26 a day would
    become 0.9999 by close of business. The per-tick hazard must compound back
    to exactly what Jev said."""

    hazard = per_tick_hazard(p_day)
    assert 0.0 < hazard < p_day
    assert 1 - (1 - hazard) ** OFFICE_TICKS_PER_DAY == pytest.approx(p_day)


def test_without_thinning_a_reluctant_payer_pays_by_lunchtime() -> None:
    """The failure the hazard exists to prevent, stated as a number."""

    naive = 1 - (1 - 0.26) ** OFFICE_TICKS_PER_DAY
    assert naive > 0.9999
    assert not math.isclose(naive, 0.26, abs_tol=0.5)


def test_hazard_handles_certainty_and_impossibility() -> None:
    assert per_tick_hazard(1.0) == 1.0
    assert per_tick_hazard(0.0) == 0.0
    assert per_tick_hazard(1.7) == 1.0
