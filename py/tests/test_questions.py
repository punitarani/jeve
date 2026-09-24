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
    # Told by somebody who saw it, so the provenance words are in the request.
    "file.ticket": {
        "module_down": True,
        "already_open": False,
        "module": "invoicing",
        "month_end": True,
        "heard_hops": 1,
    },
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
    "close.signoff": {
        "client": "halloran",
        "invoices_stuck": True,
        "overdue_bills": 3,
        "attempt": 2,
    },
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
    "leave.consider": {"org": "tallybird", "weeks_behind": 2},
    "career.review": {
        "org": "tallybird",
        "mood": 1,
        "friends_at_work": 1,
        "fallen_out_at_work": 1,
        "pay_late": True,
        "firm_struggling": False,
        "swamped": True,
    },
    "eng.allocation": {
        "debt_level": 1.3,
        "incidents_last_week": 2,
        "backlog": 25,
        "churned_last_month": 1,
        "runway_days": 30,
    },
    "deploy.decision": {"debt_level": 1.0, "incidents_last_week": 0},
    "vendor.trust": {
        "trust": 3,
        "module": "invoicing",
        "minutes": 300,
        "reported": True,
        "answered": False,
        "escalated": False,
        "repeat": True,
        "tried_another_tool": True,
    },
    "subscription.renew": {
        "trust": 1,
        "heard_bad_news": True,
        "price_rise": True,
        "offered_discount": True,
        "relies_on_it": True,
    },
    "retention.offer": {
        "trust": 1,
        "large": True,
        "runway_days": 40,
        "heard_bad_news": True,
    },
    "invoice.dispute": {
        "issuer": "halloran",
        "larger_than_expected": True,
        "price_rise": True,
        "firm": False,
    },
    "dispute.resolution": {
        "org": "halloran",
        "large": True,
        "runway_days": 40,
        "client_firm": False,
    },
    "escalation.handoff": {"by_phone": True, "backlog": 12},
    "time.log": {"pending_days": 3, "timetrack_down": True, "on_paper": True},
    "cover.shift": {"absent_role": "barista", "runway_days": 20},
    "close.order": {
        "clients": {
            "halloran": {"stuck": False, "overdue_bills": 0, "fee_rank": 0},
            "tallybird": {"stuck": True, "overdue_bills": 2, "fee_rank": 1},
            "thirdrail": {"stuck": False, "overdue_bills": 0, "fee_rank": 2},
        }
    },
    "supplier.order": {"trend": 1.3, "pos_down": False, "runway_days": 20},
    "catering.accept": {"size": "large", "short_staffed": True},
    "founder.review": {
        "org": "tallybird",
        "runway_days": 10,
        "money_in": 100,
        "money_out": 250,
        "overdue_to_them": 50,
        "weekly_outgoings": 100,
        "payroll_held": True,
        "raised_recently": True,
        "has_loan": True,
    },
    "hire.decision": {
        "org": "ledgerline",
        "vacancy": "staff_accountant",
        "runway_days": 60,
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


def test_the_same_outage_offers_every_way_of_working_around_it() -> None:
    """The scenario's behaviour #5, "the most direct test of the research
    question": one request asks both whether to report it and how to get the
    work done meanwhile (DECIDE-0001)."""

    prepared = _prepare("file.ticket")
    assert [ask.key for ask in prepared.asks] == ["file", "workaround"]
    workaround = prepared.asks[1].question
    assert isinstance(workaround, Choice)
    assert set(workaround.criteria) >= {"wait", "by_hand", "call_account_manager"}
    assert prepared.state is not None
    assert "invoices" in str(prepared.state["what_it_stops"])
    assert "month-end" in str(prepared.state["calendar"])
    quiet = _prepare("file.ticket", {"module_down": True, "module": "pos"})
    assert quiet.state is not None and "calendar" not in quiet.state


def test_a_late_close_asks_what_to_do_about_it_only_when_it_is_late() -> None:
    late = _prepare("close.signoff")
    assert [ask.key for ask in late.asks] == ["readiness", "if_not_ready"]
    on_time = _prepare(
        "close.signoff", {**ASKING["close.signoff"], "invoices_stuck": False}
    )
    assert [ask.key for ask in on_time.asks] == ["readiness"]


def test_news_about_a_firm_names_the_firm() -> None:
    from jeve.decide.questions import TELLABLE_WORDS, tellable_words

    # The two sentences recorded before WORLD-0011 are unchanged.
    assert tellable_words("price_rise", "tallybird") == TELLABLE_WORDS["price_rise"]
    assert tellable_words("outage", None) == TELLABLE_WORDS["outage"]
    assert "the software company" in tellable_words("insolvency", "tallybird")
    assert "the cafe" in tellable_words("payroll_late", "thirdrail")


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
        "the_accounting_firm": "pushed for it to be dealt with now",
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
