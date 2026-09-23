"""The question sets, linted (DECIDE-0003).

Each rule here exists because of how Jev behaves, and a set that breaks one
fails quietly in production — a worse distribution, not an exception. So they
are checked where a broken set costs a test run rather than a night.
"""

from __future__ import annotations

import pytest

from jeve.decide import gates, questions
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
    "retail.purchase": {"org": "thirdrail", "till_down": True, "queue_length": 3},
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
    "supply.order": {
        "org": "thirdrail",
        "stock_level": 1,
        "runway_days": 21,
        "price_up": True,
        "can_afford": True,
    },
    "credit.draw": {
        "org": "thirdrail",
        "runway_days": 9,
        "debt_cents": 0,
        "weekly_wages_cents": 900_000,
    },
    "credit.approve": {
        "applicant": "thirdrail",
        "runway_days": 9,
        "overdue_bills": 2,
        "payroll_held": True,
        "debt_cents": 0,
        "amount_cents": 3_600_000,
        "bank_can_lend": True,
    },
    "subscription.switch": {
        "org": "ironworks",
        "competitor": "tallybird",
        "reliability": 1,
    },
    # The richest path through an episode round: somebody who can settle the
    # matter, already pushed, with a piece of news in their pocket — so `act`,
    # `settled`, `mood` and `mention` are all in the request.
    "episode.round": {
        "org": "halloran",
        "here": "thirdrail",
        "stake": "invoice",
        "role_in_stake": "holder",
        "days_late": 9,
        "large": True,
        "present": [
            {
                "id": "ledgerline.client_services.client_admin.1",
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
        "team": "halloran.partners",
        "here": "thirdrail",
        "floor": 0,
        "own_zone": "halloran",
        "own_floor": 2,
        "at_workplace": False,
        "present": [
            {"id": "tallybird.engineering.sre.1", "org": "tallybird", "role": "sre"},
            {
                "id": "thirdrail.front_of_house.barista.3",
                "org": "thirdrail",
                "role": "barista",
            },
        ],
        "outage": "invoicing",
        "vendor": "tallybird",
        "can_raise": True,
        "lobby": True,
        "social": {"cafe": "thirdrail", "gym": "ironworks"},
        "minds_counter": False,
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
    no_line = ctx("retail.purchase", {"queue_length": 0, "till_down": False})
    assert gates.settle(no_line) == {"buy": True, "reason": "no_line"}
    assert gates.settle(ctx("retail.purchase", {"queue_length": 3})) is None


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
    assert here == (
        "a site reliability engineer from the software company; "
        "a barista from the cafe."
    )
    assert "tallybird.engineering.sre.1" not in str(prepared.state)
    whom = next(ask for ask in prepared.asks if ask.key == "with_whom")
    assert isinstance(whom.question, Choice)
    assert whom.question.criteria == {
        "person_a": "A site reliability engineer from the software company.",
        "person_b": "A barista from the cafe.",
        "other": "Nobody in particular.",
    }
    keys = [ask.key for ask in prepared.asks]
    # With an outage on their mind, what they now think of the vendor is
    # asked last, after everything that moves the world (MEM-0003).
    assert keys == [
        "next_zone",
        "mood",
        "interact",
        "with_whom",
        "topic",
        "raise_outage",
        "vendor_reliability",
    ]


def test_alone_there_is_nobody_to_ask_about() -> None:
    facts = {**ASKING["agent.tick"], "present": [], "can_raise": False}
    keys = [ask.key for ask in _prepare("agent.tick", facts).asks]
    assert keys == ["next_zone", "mood", "vendor_reliability"]
    quiet = {**facts, "outage": None}
    keys = [ask.key for ask in _prepare("agent.tick", quiet).asks]
    assert keys == ["next_zone", "mood"]


def test_raising_the_outage_is_only_asked_of_someone_who_can() -> None:
    facts = {**ASKING["agent.tick"], "can_raise": False}
    assert "raise_outage" not in [a.key for a in _prepare("agent.tick", facts).asks]


def _crowd(spec: dict[str, tuple[str, int]]) -> list[dict[str, object]]:
    """`{"tallybird": ("engineer", 3)}` -> three engineers from Tallybird."""

    return [
        {"id": f"{org}.x.{role}.{i}", "org": org, "role": role}
        for org, (role, n) in spec.items()
        for i in range(n)
    ]


def test_a_crowded_floor_is_counted_not_listed() -> None:
    """DECIDE-0005: the state is bounded however many people are here, and
    the vendor whose product is down is named first, colleagues second."""

    present = _crowd(
        {
            "halloran": ("paralegal", 2),
            "tallybird": ("engineer", 3),
            "ledgerline": ("bookkeeper", 4),
            "thirdrail": ("barista", 1),
            "meridian": ("architect", 2),
            "quill": ("support", 1),
            "ironworks": ("trainer", 5),
        }
    )
    present.append({"id": "tallybird.x.sales.9", "org": "tallybird", "role": "sales"})
    facts = {**ASKING["agent.tick"], "present": present, "candidates": None}
    prepared = _prepare("agent.tick", facts)
    assert prepared.state is not None
    here = prepared.state["who_is_here"]
    assert here == (
        "three engineers and a salesperson from the software company; "
        "two paralegals from the law firm; five personal trainers from the gym; "
        "four bookkeepers from the accounting firm; two architects from the "
        "architecture studio; and two others."
    )
    whom = next(ask for ask in prepared.asks if ask.key == "with_whom")
    assert isinstance(whom.question, Choice)
    labels = [k for k in whom.question.criteria if k != "other"]
    assert len(labels) == 6
    # The vendor's people, then colleagues, then the rest: the order the
    # interpretation maps the labels back in.
    offered = questions._offered(
        DecisionContext(
            person_id="p",
            role="r",
            decision_seq=0,
            sim_time=0,
            kind="agent.tick",
            facts=facts,
            traits=TRAITS,
        )
    )
    assert [str(p["org"]) for p in offered] == ["tallybird"] * 4 + ["halloran"] * 2
    assert not any(str(p["id"]) in str(prepared.state) for p in present)


def test_two_rooms_with_the_same_people_in_them_share_a_call() -> None:
    """Different ids, same roles and firms: the same bytes go out, so the
    call is shared (DECIDE-0004)."""

    one = _prepare(
        "agent.tick",
        {**ASKING["agent.tick"], "present": _crowd({"tallybird": ("engineer", 2)})},
    )
    other = _prepare(
        "agent.tick",
        {
            **ASKING["agent.tick"],
            "present": [
                {
                    "id": "tallybird.x.engineer.7",
                    "org": "tallybird",
                    "role": "engineer",
                },
                {
                    "id": "tallybird.x.engineer.8",
                    "org": "tallybird",
                    "role": "engineer",
                },
            ],
        },
    )
    assert one.state == other.state
    assert [a.question for a in one.asks] == [a.question for a in other.asks]
