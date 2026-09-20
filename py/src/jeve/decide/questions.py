"""The question sets: what each decision point asks Jev (DECIDE-0003).

One set per decision kind. Three rules shape every one of them, and each comes
from how Jev behaves rather than from taste:

1.  **Words, not numbers.** Jev reads literally and is weak at arithmetic, so a
    trait of 0.31 is sent as "impatient; hates waiting in line" and a backlog
    of 14 as "deep". Bucketing is also what lets identical situations share one
    cached call.
2.  **Hard constraints stay in code.** Whether an org can afford an invoice is
    a ledger fact; asking a model would let it move money it does not have.
    Those are *gates*: settled here, no call made, recorded as decided by rules.
3.  **Every question is tagged J or P.** A judgement has a right answer, so it
    takes the argmax. A propensity is a disposition, so it is *sampled* — taking
    the argmax of a propensity makes every impatient customer the same person.

Wording is frozen once recorded: the cache key is the content hash of what is
sent, so editing a sentence here re-records every call that contained it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from jeve.core.clock import TICK, WORK_END, WORK_START, SimTime
from jeve.decide.policy import DecisionContext
from jeve.llm.protocol import Choice, Noul, NoulCriteria, Score

type Mode = Literal["J", "P", "H"]
"""J: judgement, take the argmax. P: propensity, sample the distribution.
H: a propensity asked at day scale and thinned to a per-tick hazard — for
irreversible actions that are re-asked every tick until they happen."""

OFFICE_TICKS_PER_DAY = (WORK_END - WORK_START) // TICK


@dataclass(frozen=True, slots=True)
class Ask:
    key: str
    mode: Mode
    question: Noul | Choice | Score

    @property
    def options(self) -> tuple[str, ...]:
        """Declared order. Sampling iterates this, never a response dict: JSONB
        reorders keys, so a stored response and a fresh one would otherwise
        walk the same distribution in different orders and draw differently."""

        if isinstance(self.question, Choice):
            return tuple(self.question.criteria)
        if isinstance(self.question, Score):
            return tuple(str(i) for i in range(len(self.question.criteria)))
        return ("yes", "no")


@dataclass(frozen=True, slots=True)
class Prepared:
    """One decision, ready to send — or already settled by a code gate."""

    kind: str
    asks: tuple[Ask, ...] = ()
    state: dict[str, object] | None = None
    gated: dict[str, object] | None = None

    @property
    def needs_model(self) -> bool:
        return self.gated is None


@dataclass(frozen=True, slots=True)
class Resolved:
    """An answer after J/P resolution."""

    value: object
    distribution: dict[str, float]
    draw: float | None


type Draw = Callable[[], float]
type Interpreter = Callable[[DecisionContext, dict[str, Resolved], Draw], "Outcome"]


@dataclass(frozen=True, slots=True)
class Outcome:
    chosen: dict[str, object]
    extra_draws: dict[str, float]


@dataclass(frozen=True, slots=True)
class QuestionSet:
    kind: str
    prepare: Callable[[DecisionContext], Prepared]
    interpret: Interpreter


# --------------------------------------------------------------------------
# Rendering: numbers become words
# --------------------------------------------------------------------------

# The range each trait is seeded over (world/seed_world.py). Tertiles of the
# *actual* range, so "low" means low for this population, not low in [0, 1].
_TRAIT_RANGE: dict[str, tuple[float, float]] = {
    "diligence": (0.35, 0.85),
    "promptness": (0.30, 0.85),
    "patience": (0.30, 0.90),
    "vocality": (0.15, 0.75),
    "risk_appetite": (0.15, 0.75),
    "sociability": (0.15, 0.85),
}

_TRAIT_WORDS: dict[str, tuple[str, str, str]] = {
    "diligence": (
        "easily distracted; lets work sit in the queue",
        "a steady worker; gets to things in reasonable time",
        "conscientious; clears work as soon as it arrives",
    ),
    "promptness": (
        "pays bills late as a habit and waits to be chased",
        "pays bills around the due date",
        "pays bills the moment they fall due",
    ),
    "patience": (
        "impatient; hates waiting in line",
        "will wait a few minutes, but not long",
        "patient; does not mind waiting",
    ),
    "vocality": (
        "rarely complains; waits for problems to fix themselves",
        "speaks up when something blocks their work",
        "quick to complain and to report any problem",
    ),
    "sociability": (
        "keeps to themselves; avoids small talk",
        "friendly enough; chats when there is a reason to",
        "talkative; stops to chat with anyone nearby",
    ),
}


def trait_level(name: str, value: object) -> int:
    """0, 1 or 2: which tertile of the seeded range this value falls in."""

    low, high = _TRAIT_RANGE[name]
    number = float(value) if isinstance(value, int | float) else (low + high) / 2
    third = (high - low) / 3
    if number < low + third:
        return 0
    if number < low + 2 * third:
        return 1
    return 2


def trait_words(name: str, value: object) -> str:
    return _TRAIT_WORDS[name][trait_level(name, value)]


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def backlog_words(count: object) -> str:
    n = int(_number(count))
    if n <= 2:
        return "nearly empty"
    if n <= 8:
        return "a handful of open tickets"
    if n <= 20:
        return "busy; a long list of open tickets"
    return "deep; far more open tickets than the team can clear today"


def queue_words(length: object) -> str:
    n = int(_number(length))
    if n <= 0:
        return "nobody is waiting; they can be served at once"
    if n <= 2:
        return "one or two people are ahead of them"
    return "several people are ahead of them and the line is slow"


def lateness_words(days_until_due: object) -> str:
    days = int(_number(days_until_due))
    if days >= 0:
        return "the invoice falls due today"
    if days >= -3:
        return "the invoice is a few days overdue"
    if days >= -10:
        return "the invoice is more than a week overdue"
    return "the invoice is several weeks overdue and has been chased"


def runway_words(days: object) -> str:
    return (
        "cash is tight; paying this leaves little in the account"
        if _number(days, 30.0) < 14
        else "there is comfortably enough cash to pay it"
    )


def time_of_day_words(sim_time: int) -> str:
    hour = SimTime(sim_time).time_of_day // 3600
    if hour < 9:
        return "early morning, before the offices open"
    if hour < 12:
        return "mid-morning"
    if hour < 14:
        return "lunchtime"
    if hour < 16:
        return "mid-afternoon"
    return "late afternoon, near the end of the working day"


# --------------------------------------------------------------------------
# The sets
# --------------------------------------------------------------------------


def _yes_no(yes: str, no: str) -> NoulCriteria:
    # The wire names are `true` and `false`, which Python will not take as
    # keyword arguments.
    return NoulCriteria.model_validate({"true": yes, "false": no})


_FILE = Ask(
    "file",
    "P",
    Noul(
        instructions=(
            "Does this person contact the software vendor's support desk about "
            "the problem right now?"
        ),
        criteria=_yes_no(
            "They stop what they are doing and report the problem now.",
            "They do not report it now; they wait, or work around it.",
        ),
    ),
)


def _prepare_file_ticket(ctx: DecisionContext) -> Prepared:
    if not ctx.facts.get("module_down") or ctx.facts.get("already_open"):
        # Nothing is broken, or they already have a ticket open: not a choice.
        return Prepared(ctx.kind, gated={"file": False})
    return Prepared(
        ctx.kind,
        asks=(_FILE,),
        state={
            "person": "a customer who pays for small-business software",
            "temperament": trait_words("vocality", ctx.traits.get("vocality")),
            "situation": (
                "A feature of the software that they use for work has just "
                "stopped responding. They have not reported it yet."
            ),
        },
    )


def _interpret_file_ticket(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"file": bool(got["file"].value)}, {})


_TRIAGE_QUEUE = Ask(
    "queue",
    "J",
    Choice(
        instructions="Which support queue should this new ticket be routed to?",
        criteria={
            "technical": "The product is broken, slow, or not responding.",
            "billing": "A question or dispute about a charge, invoice or refund.",
            "account": "Login, access, users, or plan changes.",
            "other": "None of the above.",
        },
    ),
)
_TRIAGE_SEVERITY = Ask(
    "severity",
    "J",
    Score(
        instructions="How severe is this ticket for the customer?",
        criteria=[
            "A question or a cosmetic issue; nobody is blocked.",
            "Degraded: the customer is slowed down but has a workaround.",
            "Blocked: the customer cannot do their work until this is fixed.",
        ],
    ),
)


def _prepare_triage(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_TRIAGE_QUEUE, _TRIAGE_SEVERITY),
        state={
            "ticket_subject": str(ctx.facts.get("subject", "")),
            "status_page": (
                "The status page shows this feature is DOWN right now."
                if ctx.facts.get("module_down")
                else "The status page shows every feature operating normally."
            ),
        },
    )


def _interpret_triage(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    level = int(str(got["severity"].value))
    return Outcome({"queue": str(got["queue"].value), "severity": float(level)}, {})


_ANSWER = Ask(
    "answer_now",
    "P",
    Noul(
        instructions=(
            "In the next fifteen minutes, does this support agent pick up the "
            "next waiting ticket and answer it?"
        ),
        criteria=_yes_no(
            "They pick up the next ticket and answer it in this window.",
            "They do not get to it in this window.",
        ),
    ),
)


def _prepare_answer(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_ANSWER,),
        state={
            "person": "a customer support agent at a small software company",
            "temperament": trait_words("diligence", ctx.traits.get("diligence")),
            "queue": backlog_words(ctx.facts.get("backlog")),
            "time": time_of_day_words(ctx.sim_time),
        },
    )


def _interpret_answer(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"answer_now": bool(got["answer_now"].value)}, {})


_PAY = Ask(
    "pay_today",
    "H",
    Noul(
        instructions="Will this person pay this invoice at some point today?",
        criteria=_yes_no(
            "They pay the invoice in full today.",
            "They leave it unpaid today.",
        ),
    ),
)


def _prepare_payment(ctx: DecisionContext) -> Prepared:
    if not ctx.facts.get("can_afford", True):
        return Prepared(ctx.kind, gated={"pay": False, "reason": "insufficient_cash"})
    if _number(ctx.facts.get("days_until_due")) > 0:
        return Prepared(ctx.kind, gated={"pay": False, "reason": "not_due"})
    return Prepared(
        ctx.kind,
        asks=(_PAY,),
        state={
            "person": "the person who pays the bills for a small business",
            "habit": trait_words("promptness", ctx.traits.get("promptness")),
            "invoice": lateness_words(ctx.facts.get("days_until_due")),
            "cash": runway_words(ctx.facts.get("runway_days")),
        },
    )


def per_tick_hazard(p_day: float) -> float:
    """Thin a day-level probability to one fifteen-minute tick.

    The question is about *today* because that is a scale Jev can reason at.
    It is asked every tick, and sampling a day-level p every tick compounds to
    near-certainty by lunchtime: 1 - (1 - p)^32. Jev cannot do that arithmetic,
    so code does: the hazard h with 1 - (1 - h)^ticks = p.
    """

    p = min(max(p_day, 0.0), 1.0)
    if p >= 1.0:
        return 1.0
    return float(1.0 - (1.0 - p) ** (1.0 / OFFICE_TICKS_PER_DAY))


def _interpret_payment(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    pay = bool(got["pay_today"].value)
    return Outcome({"pay": pay, "reason": "due" if pay else "deferred"}, {})


_BUY = Ask(
    "buy",
    "P",
    Noul(
        instructions="Does this customer stay and buy something?",
        criteria=_yes_no(
            "They wait their turn and buy a drink or something to eat.",
            "They give up and leave without buying anything.",
        ),
    ),
)


def _prepare_cafe(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_BUY,),
        state={
            "person": "someone who has just walked into a neighbourhood cafe",
            "temperament": trait_words("patience", ctx.traits.get("patience")),
            "line": queue_words(ctx.facts.get("queue_length")),
            "till": (
                "The card reader is broken; the cafe is taking cash only and "
                "service is slow."
                if ctx.facts.get("pos_down")
                else "The cafe is running normally and taking cards."
            ),
        },
    )


def _interpret_cafe(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    if not got["buy"].value:
        waiting = _number(ctx.facts.get("queue_length")) > 0
        return Outcome(
            {"buy": False, "reason": "queue" if waiting else "changed_mind"}, {}
        )
    # How much they spend is a till fact, not a judgement: same draw the rules
    # twin uses, so the two policies differ only in whether they buy.
    roll = draw()
    return Outcome(
        {"buy": True, "amount_cents": 350 + int(roll * 600)}, {"amount": roll}
    )


# -- agent.tick: where next, and whether to stop and talk (WORLD-0003) --------

ORG_WORDS: dict[str, str] = {
    "tallybird": "the software company",
    "halloran": "the law firm",
    "ledgerline": "the accounting firm",
    "thirdrail": "the cafe",
}
_PLACE_WORDS: dict[str, str] = {
    "software_office": "the software company's office",
    "law_office": "the law firm's office",
    "accounting_office": "the accounting firm's office",
    "cafe": "the neighbourhood cafe",
    "plaza": "the plaza outside, by the fountain",
}
MOODS: tuple[str, ...] = (
    "Stressed and short-tempered.",
    "Flat; just getting through the day.",
    "Content and settled.",
    "Upbeat and energetic.",
)


def slot(index: int) -> str:
    """A neutral label for someone present. Names and ids are noise to Jev,
    and would stop two identical rooms sharing a call."""

    return f"person_{chr(ord('a') + index)}"


def describe(person: dict[str, object]) -> str:
    role = str(person.get("role", "employee")).replace("_", " ")
    return f"a {role} from {ORG_WORDS.get(str(person.get('org')), 'another firm')}"


def _present(ctx: DecisionContext) -> list[dict[str, object]]:
    present = ctx.facts.get("present")
    return (
        [p for p in present if isinstance(p, dict)] if isinstance(present, list) else []
    )


def _next_zone(org: str) -> Ask:
    criteria: dict[str, str] = {
        "stay": "Stay where they are for the next fifteen minutes.",
        "own_workplace": "Go back to their own workplace and get on with work.",
        "cafe": "Walk over to the cafe for a coffee or something to eat.",
        "plaza": "Step out into the plaza for some air.",
    }
    if org != "tallybird":
        criteria["software_office"] = (
            "Walk over to the software company's office to speak to them in person."
        )
    criteria["other"] = "Something else."
    return Ask(
        "next_zone",
        "P",
        Choice(
            instructions="Where does this person go in the next fifteen minutes?",
            criteria=dict(criteria),
        ),
    )


_INTERACT = Ask(
    "interact",
    "P",
    Noul(
        instructions=(
            "In the next fifteen minutes, does this person stop and have a "
            "conversation with one of the people listed as being here?"
        ),
        criteria=_yes_no(
            "They stop and talk with someone who is here.",
            "They keep to themselves.",
        ),
    ),
)
_MOOD = Ask(
    "mood",
    "J",
    Score(instructions="What is this person's mood right now?", criteria=list(MOODS)),
)
_RAISE = Ask(
    "raise_outage",
    "P",
    Noul(
        instructions=(
            "Does this person bring up the broken software with the software "
            "company's employee who is here, and press them to get it fixed?"
        ),
        criteria=_yes_no(
            "They raise the outage and push for it to be fixed.",
            "They do not bring it up.",
        ),
    ),
)


def _prepare_agent_tick(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    here = str(ctx.facts.get("here", ""))
    at_own = here == ctx.facts.get("own_zone")
    present = _present(ctx)
    outage = ctx.facts.get("outage")

    state: dict[str, object] = {
        "person": f"a {ctx.role.replace('_', ' ')} at {ORG_WORDS.get(org, 'a firm')}",
        "temperament": trait_words("sociability", ctx.traits.get("sociability")),
        "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        "time": time_of_day_words(ctx.sim_time),
        "where": (
            "at their own workplace" if at_own else f"in {_PLACE_WORDS.get(here, here)}"
        ),
        "on_their_mind": (
            f"The {outage} software has been down and it is disrupting the day."
            if outage
            else "Nothing unusual; an ordinary working day."
        ),
    }
    asks: list[Ask] = [_next_zone(org), _MOOD]
    if present:
        state["who_is_here"] = {slot(i): describe(p) for i, p in enumerate(present)}
        topics: dict[str, str] = {
            "work": "Their own work and clients.",
            "money": "Bills and invoices; who owes whom.",
            "small_talk": "The weather, the weekend, nothing in particular.",
        }
        if outage:
            topics = {"the_outage": "The software outage.", **topics}
        topics["other"] = "Something else."
        people: dict[str, str] = {
            slot(i): describe(p).capitalize() + "." for i, p in enumerate(present)
        }
        people["other"] = "Nobody in particular."
        asks += [
            _INTERACT,
            Ask(
                "with_whom",
                "P",
                Choice(
                    instructions=(
                        "If this person talks to someone here, who is it most "
                        "likely to be?"
                    ),
                    criteria=dict(people),
                ),
            ),
            Ask(
                "topic",
                "P",
                Choice(
                    instructions="If they talk, what is it most likely about?",
                    criteria=dict(topics),
                ),
            ),
        ]
        if ctx.facts.get("can_raise"):
            asks.append(_RAISE)
    else:
        state["who_is_here"] = "Nobody they would stop to talk to."
    return Prepared(ctx.kind, asks=tuple(asks), state=state)


def _interpret_agent_tick(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    here = str(ctx.facts.get("here", ""))
    own = str(ctx.facts.get("own_zone", here))
    choice = str(got["next_zone"].value)
    next_zone = {"stay": here, "other": here, "own_workplace": own}.get(choice, choice)

    present = _present(ctx)
    with_id: str | None = None
    if "interact" in got and got["interact"].value:
        picked = str(got["with_whom"].value)
        for index, person in enumerate(present):
            if slot(index) == picked:
                with_id = str(person["id"])
    return Outcome(
        {
            "next_zone": next_zone,
            "interact": with_id is not None,
            "with": with_id,
            "topic": str(got["topic"].value) if with_id and "topic" in got else None,
            "mood": int(str(got["mood"].value)),
            "raise_outage": bool(
                with_id and "raise_outage" in got and got["raise_outage"].value
            ),
        },
        {},
    )


QUESTION_SETS: dict[str, QuestionSet] = {
    s.kind: s
    for s in (
        QuestionSet("file.ticket", _prepare_file_ticket, _interpret_file_ticket),
        QuestionSet("ticket.triage", _prepare_triage, _interpret_triage),
        QuestionSet("ticket.answer", _prepare_answer, _interpret_answer),
        QuestionSet("payment.timing", _prepare_payment, _interpret_payment),
        QuestionSet("cafe.purchase", _prepare_cafe, _interpret_cafe),
        QuestionSet("agent.tick", _prepare_agent_tick, _interpret_agent_tick),
    )
}
