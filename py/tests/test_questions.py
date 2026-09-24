"""The question sets, linted (DECIDE-0003).

Each rule here exists because of how Jev behaves, and a set that breaks one
fails quietly in production — a worse distribution, not an exception. So they
are checked where a broken set costs a test run rather than a night.
"""

from __future__ import annotations

import pytest

from jeve.decide import gates
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.decide.questions import (
    QUESTION_SETS,
    Prepared,
    lateness_words,
    trait_level,
)
from jeve.llm.protocol import Choice, Score

# One context per kind that gets past every code gate, so a question is asked.
ASKING: dict[str, dict[str, object]] = {
    # Told by somebody who saw it, so the provenance words are in the request.
    "file.ticket": {"module_down": True, "already_open": False, "heard_hops": 1},
    "ticket.triage": {"subject": "exports fail", "module_down": True, "backlog": 12},
    "ticket.answer": {"backlog": 12},
    "payment.timing": {"days_until_due": -4, "can_afford": True, "runway_days": 9},
    "cafe.purchase": {"pos_down": True, "queue_length": 3},
    "ticket.confirm": {"module_down": False, "days_since_answer": 1},
    "chase.invoice": {"org": "halloran", "days_late": 9, "large": True},
    "credit.decision": {
        "customer": "halloran",
        "module": "invoicing",
        "minutes": 1500,
        "escalated": True,
        "blocked_billing": True,
    },
    "close.signoff": {"client": "halloran", "invoices_stuck": True, "overdue_bills": 3},
    "catering.order": {"org": "tallybird", "can_afford": True, "team_mood": 1.2},
    "payroll.release": {
        "employer": "thirdrail",
        "can_afford": True,
        "cash_multiple": 1.4,
        "timesheets_available": False,
    },
    # The richest path through an episode round: somebody who can settle the
    # matter, already pushed, a round in, with a broken promise behind them and
    # a piece of news in their pocket — so `act`, `done`, `mood` and `mention`
    # are all in the request, and so is every word WORLD-0008 added.
    "episode.round": {
        "org": "halloran",
        "here": "cafe",
        "stake": "invoice",
        "role_in_stake": "holder",
        "days_late": 9,
        "large": True,
        "track_record": "broken",
        "present": [
            {
                "id": "ledgerline.client_admin.17",
                "org": "ledgerline",
                "role": "client_admin",
                "last_act": "press",
            }
        ],
        "my_last_act": "explain",
        "rounds_done": 1,
        "raised": True,
        "pressed": True,
        "promised": False,
        "refused": False,
        "tension": 1,
        "tellable_topic": "price_rise",
    },
    "agent.tick": {
        "org": "halloran",
        "here": "cafe",
        "own_zone": "law_office",
        "present": [
            {"id": "tallybird.sre.4", "org": "tallybird", "role": "sre"},
            {"id": "thirdrail.barista.20", "org": "thirdrail", "role": "barista"},
        ],
        "outage": "invoicing",
        "can_raise": True,
    },
}
TRAITS: dict[str, object] = {
    "diligence": 0.41,
    "promptness": 0.8,
    "patience": 0.33,
    "vocality": 0.7,
    "risk_appetite": 0.2,
    "sociability": 0.8,
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
        assert ask.mode in ("J", "P")
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
    about it could pay with money that does not exist. Gates are written once
    (`decide/gates.py`) and both policies ask there first."""

    def ctx(kind: str, facts: dict[str, object]) -> DecisionContext:
        return DecisionContext(
            person_id="p", role="r", sim_time=0, kind=kind, facts=facts
        )

    broke = ctx(
        "payment.timing", {"days_until_due": -4, "can_afford": False, "runway_days": 1}
    )
    assert gates.settle(broke) == {"pay": False, "reason": "insufficient_cash"}
    early = ctx("payment.timing", {"days_until_due": 3, "can_afford": True})
    assert gates.settle(early) == {"pay": False, "reason": "not_due"}
    # Two days out is when a payer starts thinking about it: a real question.
    assert gates.settle(ctx("payment.timing", {"days_until_due": 2})) is None

    already = ctx("file.ticket", {"module_down": True, "already_open": True})
    assert gates.settle(already) == {"file": False}
    still_down = ctx("ticket.confirm", {"module_down": True})
    assert gates.settle(still_down) == {"confirm": False, "reason": "still_down"}
    # Served at once, till working: they bought a coffee. Not worth a question.
    no_line = ctx("cafe.purchase", {"queue_length": 0, "pos_down": False})
    assert gates.settle(no_line) == {"buy": True, "reason": "no_line"}
    assert gates.settle(ctx("cafe.purchase", {"queue_length": 3})) is None


def test_a_gate_costs_neither_policy_any_luck() -> None:
    """The rules twin used to draw before checking the catering gate, so the two
    policies spent different amounts of luck on the same non-decision."""

    ctx = DecisionContext(
        person_id="p",
        role="office_manager",
        sim_time=0,
        kind="catering.order",
        facts={"org": "halloran", "can_afford": False},
    )
    decision = RulesPolicy(1).decide(ctx)
    assert decision.chosen == {"order": "none"}
    assert decision.draws == {}


def test_traits_are_bucketed_over_the_range_they_are_seeded_in() -> None:
    # patience is seeded over [0.30, 0.90]: 0.45 is low *for this population*.
    assert trait_level("patience", 0.31) == 0
    assert trait_level("patience", 0.45) == 0
    assert trait_level("patience", 0.60) == 1
    assert trait_level("patience", 0.89) == 2
    assert trait_level("vocality", 0.45) == 1


def test_a_bill_gets_more_pressing_in_words() -> None:
    """A payer is asked from two days out, so the run-up has to be sayable."""

    said = [lateness_words(d) for d in (2, 1, 0, -2, -8, -20, -45)]
    assert len(set(said)) == len(said)
    assert "two days" in said[0] and "tomorrow" in said[1] and "today" in said[2]


def test_people_in_the_room_are_described_not_named() -> None:
    """A name or an id is noise to Jev, and would stop two identical rooms
    sharing one call. The mapping back to a person lives in code."""

    prepared = _prepare("agent.tick")
    assert prepared.state is not None
    here = prepared.state["who_is_here"]
    assert here == {
        "person_a": "a sre from the software company",
        "person_b": "a barista from the cafe",
    }
    assert "tallybird.sre.4" not in str(prepared.state)
    keys = [ask.key for ask in prepared.asks]
    assert keys == [
        "next_zone",
        "mood",
        "interact",
        "with_whom",
        "topic",
        "raise_outage",
    ]


def test_alone_there_is_nobody_to_ask_about() -> None:
    facts = {**ASKING["agent.tick"], "present": [], "can_raise": False}
    keys = [ask.key for ask in _prepare("agent.tick", facts).asks]
    assert keys == ["next_zone", "mood"]


def test_raising_the_outage_is_only_asked_of_someone_who_can() -> None:
    facts = {**ASKING["agent.tick"], "can_raise": False}
    assert "raise_outage" not in [a.key for a in _prepare("agent.tick", facts).asks]


# -- WORLD-0008: what the words now carry ------------------------------------------


def _round(**changes: object) -> dict[str, object]:
    return {**ASKING["episode.round"], **changes}


def _state(kind: str, facts: dict[str, object] | None = None) -> dict[str, object]:
    prepared = _prepare(kind, facts)
    assert prepared.state is not None, f"{kind} was gated, not asked"
    return prepared.state


def test_the_second_round_is_a_different_question() -> None:
    """Round two used to be round one again whenever the sticky flags had not
    moved, and the answer was a second draw of the same propensity."""

    first = _state("episode.round", _round(rounds_done=0, my_last_act=None))
    second = _state("episode.round", _round())
    assert "just_now" not in first and "how_long" not in first
    assert second["just_now"] == {
        "this_person": "set out their own side of it",
        "person_a": "pushed for it to be dealt with now",
    }
    assert first != second
    longer = _state("episode.round", _round(rounds_done=2))
    assert longer["how_long"] != second["how_long"]


def test_the_question_that_ends_a_conversation_is_about_the_person() -> None:
    """Whether they have had their say, not whether the matter is solved — an
    outage that is still down is never solved, so the old question never let a
    conversation end."""

    asks = {ask.key: ask for ask in _prepare("episode.round").asks}
    assert "done" in asks and "settled" not in asks
    assert "said what they came to say" in asks["done"].question.instructions


def test_a_payer_with_no_record_is_asked_what_they_always_were() -> None:
    about = "what_this_is_about"
    plain = str(_state("episode.round", _round(track_record=None))[about])
    broken = str(_state("episode.round", _round())[about])
    kept = str(_state("episode.round", _round(track_record="kept"))[about])
    assert broken.startswith(plain) and "did not keep it" in broken
    assert "kept their word" in kept


def test_first_hand_is_worded_as_it_always_was_and_hearsay_is_not() -> None:
    seen = _state("file.ticket", {**ASKING["file.ticket"], "heard_hops": 0})
    told = _state("file.ticket")
    rumour = _state("file.ticket", {**ASKING["file.ticket"], "heard_hops": 4})
    assert "how_they_know" not in seen
    assert told["how_they_know"] != rumour["how_they_know"]
    assert {k: v for k, v in told.items() if k != "how_they_know"} == seen


def test_the_rules_twin_acts_on_hearsay_less_than_on_what_it_saw() -> None:
    class Fixed:
        def random(self) -> float:
            return 0.5

    policy = RulesPolicy(1)

    def files(hops: int) -> bool:
        ctx = DecisionContext(
            person_id="p",
            role="subscriber",
            decision_seq=0,
            sim_time=0,
            kind="file.ticket",
            facts={**ASKING["file.ticket"], "heard_hops": hops},
            traits={"vocality": 0.6},
        )
        return bool(policy._file_ticket(ctx, Fixed())[0]["file"])

    assert files(0) and not files(1) and not files(3)
