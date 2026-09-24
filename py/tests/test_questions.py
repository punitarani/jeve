"""The question sets, linted (DECIDE-0003).

Each rule here exists because of how Jev behaves, and a set that breaks one
fails quietly in production — a worse distribution, not an exception. So they
are checked where a broken set costs a test run rather than a night.
"""

from __future__ import annotations

from collections.abc import Callable

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
    "file.ticket": {"module_down": True, "already_open": False},
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
    # matter, already pushed, with a piece of news in their pocket — so `act`,
    # `settled`, `mood` and `mention` are all in the request.
    "episode.round": {
        "org": "halloran",
        "here": "cafe",
        "stake": "invoice",
        "role_in_stake": "holder",
        "days_late": 9,
        "large": True,
        "present": [
            {
                "id": "ledgerline.client_admin.17",
                "org": "ledgerline",
                "role": "client_admin",
            }
        ],
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
        "mind": "outage:invoicing",
        "dealings": {"thirdrail": "they_owe"},
        "horizon": "tick",
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
    # As firms, most relevant first: the vendor to somebody whose software is
    # down, then a firm with a bill between it and theirs (report rec. 4).
    assert here == {
        "the_software_company": "one person from the software company",
        "the_cafe": "one person who works at the cafe; their firm owes that firm money",
    }
    assert "tallybird.sre.4" not in str(prepared.state)
    assert "thirdrail" not in str(prepared.state)
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


def test_a_room_is_firms_not_a_list_of_people() -> None:
    """The roster was the bill: every person present, in load order, so two
    rooms differing only in which barista stood where never shared a call.
    Now the room is at most three firms, and who in a firm is code's to pick."""

    crowd = [
        {"id": f"thirdrail.barista.{i}", "org": "thirdrail", "role": "barista"}
        for i in range(3)
    ] + [
        {"id": "ledgerline.principal.13", "org": "ledgerline", "role": "principal"},
        {"id": "halloran.partner.8", "org": "halloran", "role": "partner"},
        {"id": "halloran.paralegal.11", "org": "halloran", "role": "paralegal"},
        {"id": "tallybird.support.6", "org": "tallybird", "role": "support"},
    ]
    facts = {**ASKING["agent.tick"], "present": crowd, "dealings": {}}
    shuffled = {**facts, "present": list(reversed(crowd))}
    first, second = _prepare("agent.tick", facts), _prepare("agent.tick", shuffled)
    assert first == second
    assert first.state is not None
    here = first.state["who_is_here"]
    assert isinstance(here, dict) and len(here) == 3
    assert next(iter(here)) == "the_software_company"
    with_whom = next(a for a in first.asks if a.key == "with_whom").question
    assert isinstance(with_whom, Choice)
    assert list(with_whom.criteria) == [*here, "other"]


def test_code_picks_the_person_in_the_chosen_firm() -> None:
    from jeve.decide.questions import Resolved

    crowd = [
        {"id": f"thirdrail.barista.{i}", "org": "thirdrail", "role": "barista"}
        for i in range(3)
    ]
    ctx = DecisionContext(
        person_id="p",
        role="partner",
        sim_time=12 * 3600,
        kind="agent.tick",
        facts={
            "org": "halloran",
            "here": "cafe",
            "own_zone": "law_office",
            "present": crowd,
        },
    )
    got = {
        "next_zone": Resolved("stay", {}, None),
        "mood": Resolved("2", {}, None),
        "interact": Resolved(True, {}, 0.1),
        "with_whom": Resolved("the_cafe", {}, 0.1),
        "topic": Resolved("small_talk", {}, 0.1),
    }
    interpret = QUESTION_SETS["agent.tick"].interpret

    def always(roll: float) -> Callable[[], float]:
        return lambda: roll

    picked = {
        interpret(ctx, got, always(roll)).chosen["with"] for roll in (0.0, 0.5, 0.99)
    }
    assert picked == {p["id"] for p in crowd}


def test_every_role_is_a_noun_phrase_with_the_right_article() -> None:
    """The report quoted Jev being sent "a engineer", "a sre" and "a weekend at
    the cafe" (defect 5)."""

    from jeve.core.orgs import ORGS
    from jeve.decide.questions import role_words
    from jeve.world.seed_world import STAFF

    roles = {role for _, role, _ in STAFF} | {
        role for org in ORGS for role in org.headcount
    }
    for role in sorted(roles):
        words = role_words(role)
        article, noun = words.split(" ", 1)
        assert article in ("a", "an", "the"), words
        assert "_" not in noun, words
        if article == "a":
            assert noun[0] not in "aeiou", words
        if article == "an":
            assert noun[0] in "aeiou" or noun.startswith("IT"), words
    assert role_words("weekend") == "a weekend part-timer"
    assert role_words("sre") == "a site reliability engineer"


def test_the_cafe_is_not_somewhere_the_cafe_walks_over_to() -> None:
    facts: dict[str, object] = {
        "org": "thirdrail",
        "here": "cafe",
        "own_zone": "cafe",
        "present": [],
        "horizon": "tick",
    }
    zone = _prepare("agent.tick", facts).asks[0].question
    assert isinstance(zone, Choice)
    assert "cafe" not in zone.criteria
    assert "software_office" in zone.criteria


def test_a_desk_asked_on_the_hour_is_asked_about_the_hour() -> None:
    facts: dict[str, object] = {
        "org": "halloran",
        "here": "law_office",
        "own_zone": "law_office",
        "present": [],
        "horizon": "hour",
    }
    zone = _prepare("agent.tick", facts).asks[0].question
    assert isinstance(zone, Choice)
    assert zone.instructions == "Where does this person go in the next hour?"
    quarter = _prepare("agent.tick", {**facts, "horizon": "tick"}).asks[0].question
    assert isinstance(quarter, Choice)
    assert "fifteen minutes" in quarter.instructions


def test_money_reaches_what_is_on_somebodys_mind() -> None:
    """Findings 4 and 7: four values of `on_their_mind`, all about the outage."""

    from jeve.decide.questions import MIND_WORDS, mind_words

    said = {mind_words(key, None) for key in MIND_WORDS}
    assert len(said) == len(MIND_WORDS)
    assert "wages" in mind_words("unpaid", None)
    assert mind_words("outage:pos", None) == (
        "The pos software has been down and it is disrupting the day."
    )
    for key in ("unpaid", "payday", "short", "nothing"):
        facts = {**ASKING["agent.tick"], "mind": key, "outage": None}
        prepared = _prepare("agent.tick", facts)
        assert prepared.state is not None
        assert prepared.state["on_their_mind"] == MIND_WORDS[key]


def test_catering_sees_the_money_and_a_held_payroll_orders_nothing() -> None:
    """The founder of an insolvent firm ordered $420 of lunch: the question
    said the account was comfortable whatever it held (defect 8)."""

    from jeve.decide.questions import funds_words

    assert funds_words(90) != funds_words(30) != funds_words(5)
    tight = _prepare("catering.order", {**ASKING["catering.order"], "runway_days": 5})
    assert tight.state is not None and "tight" in str(tight.state["funds"])
    held = DecisionContext(
        person_id="p",
        role="founder",
        sim_time=0,
        kind="catering.order",
        facts={"org": "tallybird", "can_afford": True, "payroll_held": True},
    )
    assert gates.settle(held) == {"order": "none"}
