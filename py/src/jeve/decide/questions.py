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

from jeve.core.clock import SimTime
from jeve.decide.policy import DecisionContext
from jeve.llm.protocol import Choice, Noul, NoulCriteria, Score

type Mode = Literal["J", "P"]
"""J: judgement, take the argmax. P: propensity, sample the distribution.

There was an H: a day-level propensity thinned to a per-tick hazard, for a
question re-asked every tick until it happened. Nothing is re-asked every tick
any more (WORLD-0005): a question about today is asked once today, at an hour
that belongs to whoever is answering. That also means no constant in here
depends on how long a tick is."""


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
    # Seeded for everyone from the start and rendered nowhere until the
    # decisions it belongs to existed (field report, defect 9).
    "risk_appetite": (
        "cautious; prefers what is safe and known",
        "weighs a risk before taking it",
        "happy to take a chance on something new",
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


def trait_fraction(name: str, value: object) -> float:
    """Where a trait sits in the range it was seeded from: 0 lowest, 1 highest."""

    low, high = _TRAIT_RANGE[name]
    number = float(value) if isinstance(value, int | float) else (low + high) / 2
    return min(1.0, max(0.0, (number - low) / (high - low)))


def trait_words(name: str, value: object) -> str:
    return _TRAIT_WORDS[name][trait_level(name, value)]


TRAIT_PHRASES: frozenset[str] = frozenset(
    phrase for levels in _TRAIT_WORDS.values() for phrase in levels
)
"""Every phrase a trait renders to. A state value that is one of these is the
person's temperament; anything else is their situation (the judge panel's
split between the two)."""


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
    if days >= 2:
        return "the invoice falls due in two days"
    if days == 1:
        return "the invoice falls due tomorrow"
    if days == 0:
        return "the invoice falls due today"
    if days >= -3:
        return "the invoice is a few days overdue"
    if days >= -10:
        return "the invoice is more than a week overdue"
    if days >= -30:
        return "the invoice is several weeks overdue"
    return "the invoice is more than a month overdue"


def chased_words(chased: object, in_person: object, promised: object = False) -> str:
    """How hard this bill has been pushed.

    The `promised` branch is new (WORLD-0006) and is deliberately additive: the
    three older strings are byte-identical to what they were, so every recorded
    call whose payer had not promised anything still hits its cached answer.
    Wording is the cache key, and a state nobody can reach yet costs nothing.
    """

    if promised:
        return "they have given their word to pay it by a set day"
    if in_person:
        return "someone from the firm they owe brought it up with them in person"
    if chased:
        return "the firm they owe has rung them about it"
    return "nobody has chased them about it"


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


_WORKAROUND = Ask(
    "workaround",
    "P",
    Choice(
        instructions="While it is down, how does this person get their work done?",
        criteria={
            "wait": "They wait for it to come back and do something else meanwhile.",
            "by_hand": "They do the work by hand, outside the software.",
            "other_tool": "They use a different product for now.",
            "call_account_manager": (
                "They ring their account manager at the software company."
            ),
            "other": "Something else.",
        },
    ),
)
"""The scenario's behaviour #5 and "the most direct test of the research
question": the same outage, different people, different responses. Asked in
the same request as whether to report it (DECIDE-0001: one request per decision
point carries its whole surface)."""

BLOCKS: dict[str, str] = {
    "invoicing": "They cannot send invoices to their own customers.",
    "timetrack": "They cannot record the hours their people work.",
    "pos": "Their card reader is down, so they can only take cash.",
}
"""What each feature being down stops somebody doing (WORLD-0010). The report
found the situation wording bland and temperament swamping it (finding 5)."""


def _prepare_file_ticket(ctx: DecisionContext) -> Prepared:
    state: dict[str, object] = {
        "person": "a customer who pays for small-business software",
        "temperament": trait_words("vocality", ctx.traits.get("vocality")),
        "situation": _outage_so_far(ctx.facts.get("hours_down")),
    }
    module = str(ctx.facts.get("module", ""))
    if module in BLOCKS:
        state["what_it_stops"] = BLOCKS[module]
    if ctx.facts.get("month_end") and module == "invoicing":
        state["calendar"] = "It is month-end; their invoices are due to go out."
    return Prepared(ctx.kind, asks=(_FILE, _WORKAROUND), state=state)


def _outage_so_far(hours: object) -> str:
    """They are asked when they first notice, and again each day it goes on."""

    h = _number(hours)
    if h < 4:
        return (
            "A feature of the software that they use for work has just "
            "stopped responding. They have not reported it yet."
        )
    if h < 30:
        return (
            "A feature of the software that they use for work has been down "
            "since yesterday. They have not reported it yet."
        )
    return (
        "A feature of the software that they use for work has been down for "
        "days. They have not reported it yet."
    )


def _interpret_file_ticket(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome(
        {"file": bool(got["file"].value), "workaround": str(got["workaround"].value)},
        {},
    )


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


# Asked once per bill per day (WORLD-0005), so the day-level answer is sampled
# as it stands. It used to be asked every tick and thinned to a per-tick hazard;
# that made 1,591 `payment.deferred` events out of a die being rolled.
_PAY = Ask(
    "pay_today",
    "P",
    Noul(
        instructions="Will this person pay this invoice at some point today?",
        criteria=_yes_no(
            "They pay the invoice in full today.",
            "They leave it unpaid today.",
        ),
    ),
)


def _prepare_payment(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_PAY,),
        state={
            "person": "the person who pays the bills for a small business",
            "habit": trait_words("promptness", ctx.traits.get("promptness")),
            "invoice": lateness_words(ctx.facts.get("days_until_due")),
            "cash": runway_words(ctx.facts.get("runway_days")),
            "chased": chased_words(
                ctx.facts.get("chased"),
                ctx.facts.get("reminded_in_person"),
                ctx.facts.get("promised"),
            ),
        },
    )


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
    state: dict[str, object] = {
        "person": "someone who has just walked into a neighbourhood cafe",
        "temperament": trait_words("patience", ctx.traits.get("patience")),
        "line": queue_words(ctx.facts.get("queue_length")),
        "till": (
            "The card reader is broken; the cafe is taking cash only and "
            "service is slow."
            if ctx.facts.get("pos_down")
            else "The cafe is running normally and taking cards."
        ),
    }
    if ctx.facts.get("prices_up"):
        # Additive, so every cafe that has never raised a price still sends
        # the bytes it always sent.
        state["prices"] = "The cafe has recently put its prices up."
    return Prepared(ctx.kind, asks=(_BUY,), state=state)


def _interpret_cafe(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    if not got["buy"].value:
        waiting = _number(ctx.facts.get("queue_length")) > 0
        return Outcome(
            {"buy": False, "reason": "queue" if waiting else "changed_mind"}, {}
        )
    # How much they spend is a till fact, not a judgement: the engine rings it
    # up, keyed by the visit, whichever policy (or gate) said they bought.
    return Outcome({"buy": True, "reason": "bought"}, {})


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


ROLE_WORDS: dict[str, str] = {
    "founder": "the founder",
    "exec": "an executive",
    "eng_lead": "an engineering lead",
    "engineer": "an engineer",
    "sre": "a site reliability engineer",
    "support_lead": "a support team lead",
    "support": "a support agent",
    "account_manager": "an account manager",
    "sales": "a salesperson",
    "product": "a product manager",
    "designer": "a designer",
    "ops": "an operations manager",
    "partner": "a partner",
    "senior_associate": "a senior associate",
    "junior_associate": "a junior associate",
    "paralegal": "a paralegal",
    "office_manager": "an office manager",
    "receptionist": "a receptionist",
    "principal": "a principal",
    "senior_accountant": "a senior accountant",
    "staff_accountant": "a staff accountant",
    "bookkeeper": "a bookkeeper",
    "payroll": "a payroll clerk",
    "client_admin": "a client administrator",
    "it": "an IT administrator",
    "owner": "the owner",
    "manager": "a manager",
    "shift_lead": "a shift lead",
    "barista": "a barista",
    "baker": "a baker",
    "kitchen": "a cook",
    "weekend": "a weekend part-timer",
    "subscriber": "a customer",
    "client": "a client",
    "customer": "a customer",
}
"""A role as a noun phrase, article included. The role column is an identifier,
and pasting it into a sentence sent Jev "a engineer", "a sre", "a account
manager" and "a weekend at the cafe" (field report, defect 5)."""


def role_words(role: str) -> str:
    known = ROLE_WORDS.get(role)
    if known is not None:
        return known
    noun = role.replace("_", " ")
    return f"{'an' if noun[:1] in 'aeiou' else 'a'} {noun}"


def person_words(role: str, org: str) -> str:
    return f"{role_words(role)} at {ORG_WORDS.get(org, 'a local firm')}"


def describe(person: dict[str, object]) -> str:
    return (
        f"{role_words(str(person.get('role', 'employee')))} from "
        f"{ORG_WORDS.get(str(person.get('org')), 'another firm')}"
    )


def _present(ctx: DecisionContext) -> list[dict[str, object]]:
    present = ctx.facts.get("present")
    return (
        [p for p in present if isinstance(p, dict)] if isinstance(present, list) else []
    )


# -- who is here, as groups (field report, recommendation 4) --------------------
#
# The roster was every person present, one line each, in load order. It made
# `agent.tick` the bill: 615 distinct situations became 20,826 distinct
# requests, because two rooms that differed only in which barista stood where
# could never share a call. A room is now described as at most three groups,
# one per firm, with a count in words; `with_whom` chooses a group and code
# picks the person in it.

GROUPS_SHOWN = 3

_GROUP_KEYS: dict[str, str] = {
    "tallybird": "the_software_company",
    "halloran": "the_law_firm",
    "ledgerline": "the_accounting_firm",
    "thirdrail": "the_cafe",
}

_DEALING_WORDS: dict[str, str] = {
    "owes_them": "; that firm owes their firm money",
    "they_owe": "; their firm owes that firm money",
}


@dataclass(frozen=True, slots=True)
class Group:
    key: str
    words: str
    members: tuple[dict[str, object], ...]


def _count_words(n: int) -> tuple[str, str]:
    """How many, and the verb that agrees with it. Two buckets, not three: how
    many of a firm are in the room has never been what anybody decides on, and
    every bucket multiplies the rooms that cannot share a call."""

    return ("one person", "works") if n <= 1 else ("a few people", "work")


def groups(ctx: DecisionContext) -> list[Group]:
    """The people here as firms, most relevant first.

    Relevance is what they could matter for: the vendor, to somebody whose
    software is down; a firm with a live bill between it and theirs; then
    whoever is most numerous. Ties break on the firm, so the order is a function
    of the room and never of who arrived first.
    """

    own = str(ctx.facts.get("org", ""))
    outage = bool(ctx.facts.get("outage"))
    raw = ctx.facts.get("dealings")
    dealing = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    by_org: dict[str, list[dict[str, object]]] = {}
    for person in _present(ctx):
        by_org.setdefault(str(person.get("org", "")), []).append(person)

    def rank(item: tuple[str, list[dict[str, object]]]) -> tuple[int, int, int, str]:
        org, members = item
        return (
            0 if outage and org == "tallybird" and own != "tallybird" else 1,
            0 if org in dealing else 1,
            -len(members),
            org,
        )

    shown: list[Group] = []
    for org, members in sorted(by_org.items(), key=rank)[:GROUPS_SHOWN]:
        count, verb = _count_words(len(members))
        if org == own:
            key, words = "colleagues", f"{count} from their own firm"
        elif org == "thirdrail":
            key, words = _GROUP_KEYS[org], f"{count} who {verb} at the cafe"
        else:
            key = _GROUP_KEYS.get(org, "another_firm")
            words = f"{count} from {ORG_WORDS.get(org, 'another firm')}"
        words += _DEALING_WORDS.get(dealing.get(org, ""), "")
        ordered = tuple(sorted(members, key=lambda p: str(p.get("id", ""))))
        shown.append(Group(key, words, ordered))
    return shown


def who_is_here(ctx: DecisionContext) -> dict[str, str] | str:
    shown = groups(ctx)
    if not shown:
        return "Nobody they would stop to talk to."
    return {group.key: group.words for group in shown}


# -- agent.tick: where next, and whether to stop and talk (WORLD-0003) --------


def _next_zone(org: str, horizon: str) -> Ask:
    """Where next. Asked of somebody alone at their desk on the hour, or of
    anyone else every quarter hour (WORLD-0008), and the question says which:
    "the next fifteen minutes" put to someone asked once an hour would make
    every coffee break four times rarer than the person would take it."""

    span = "hour" if horizon == "hour" else "fifteen minutes"
    criteria: dict[str, str] = {
        "stay": f"Stay where they are for the next {span}.",
        "own_workplace": "Go back to their own workplace and get on with work.",
    }
    if org != "thirdrail":
        criteria["cafe"] = "Walk over to the cafe for a coffee or something to eat."
    criteria["plaza"] = "Step out into the plaza for some air."
    if org != "tallybird":
        criteria["software_office"] = (
            "Walk over to the software company's office to speak to them in person."
        )
    criteria["other"] = "Something else."
    return Ask(
        "next_zone",
        "P",
        Choice(
            instructions=f"Where does this person go in the next {span}?",
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
            "company's people who are here, and press them to get it fixed?"
        ),
        criteria=_yes_no(
            "They raise the outage and push for it to be fixed.",
            "They do not bring it up.",
        ),
    ),
)

MIND_WORDS: dict[str, str] = {
    "nothing": "Nothing unusual; an ordinary working day.",
    "unpaid": (
        "This week's wages have not been paid, and nobody has said when they will be."
    ),
    "short": "Word around the office is that the firm is short of money.",
    "let_down": "Someone who promised to pay the firm what they owe has not paid.",
    "lost_customer": "The firm has just lost a customer.",
    "swamped": "The support queue is overflowing with complaints.",
    "rough_week": "It has been a rough week; things keep going wrong.",
    "payday": "It is payday; the week's wages have just come in.",
    "colleague_left": "A colleague has just quit.",
}
"""What is on somebody's mind, by the typed key `world.space.mind_of` picks. The
report found four values, all about the outage: agents could not perceive
money, and mood could not respond to it (field report, findings 4 and 7)."""


def mind_words(mind: object, outage: object) -> str:
    key = str(mind or "")
    if key.startswith("outage:") or (not key and outage):
        module = key.split(":", 1)[1] if ":" in key else str(outage)
        return f"The {module} software has been down and it is disrupting the day."
    return MIND_WORDS.get(key, MIND_WORDS["nothing"])


def _prepare_agent_tick(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    here = str(ctx.facts.get("here", ""))
    at_own = here == ctx.facts.get("own_zone")
    outage = ctx.facts.get("outage")
    shown = groups(ctx)

    state: dict[str, object] = {
        "person": person_words(ctx.role, org),
        "temperament": trait_words("sociability", ctx.traits.get("sociability")),
        "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        "time": time_of_day_words(ctx.sim_time),
        "where": (
            "at their own workplace" if at_own else f"in {_PLACE_WORDS.get(here, here)}"
        ),
        "on_their_mind": mind_words(ctx.facts.get("mind"), outage),
        "who_is_here": who_is_here(ctx),
    }
    asks: list[Ask] = [_next_zone(org, str(ctx.facts.get("horizon", ""))), _MOOD]
    if shown:
        topics: dict[str, str] = {
            "work": "Their own work and clients.",
            "money": "Bills and invoices; who owes whom.",
            "small_talk": "The weather, the weekend, nothing in particular.",
        }
        if outage:
            topics = {"the_outage": "The software outage.", **topics}
        topics["other"] = "Something else."
        people: dict[str, str] = {
            group.key: group.words[:1].upper() + group.words[1:] + "."
            for group in shown
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
    return Prepared(ctx.kind, asks=tuple(asks), state=state)


def _interpret_agent_tick(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    here = str(ctx.facts.get("here", ""))
    own = str(ctx.facts.get("own_zone", here))
    choice = str(got["next_zone"].value)
    next_zone = {"stay": here, "other": here, "own_workplace": own}.get(choice, choice)

    with_id: str | None = None
    extra: dict[str, float] = {}
    if "interact" in got and got["interact"].value:
        picked = str(got["with_whom"].value)
        members = next((g.members for g in groups(ctx) if g.key == picked), ())
        # The model chose the firm; which of its people is a draw, taken only
        # when there is a choice, so a room of one costs no luck.
        if len(members) == 1:
            with_id = str(members[0]["id"])
        elif members:
            extra["who"] = draw()
            index = min(len(members) - 1, int(extra["who"] * len(members)))
            with_id = str(members[index]["id"])
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
        extra,
    )


# -- credit.decision: what an outage is worth (WORLD-0004) -------------------


def outage_words(minutes: object) -> str:
    m = int(_number(minutes))
    if m < 60:
        return "under an hour"
    if m < 4 * 60:
        return "a few hours"
    if m < 12 * 60:
        return "most of a working day"
    return "more than a day"


_CREDIT = Ask(
    "credit",
    "J",
    Choice(
        instructions=(
            "What service credit does the software company owe this customer "
            "for the outage?"
        ),
        criteria={
            "none": (
                "No credit: the outage was brief and did the customer no real harm."
            ),
            "partial": (
                "A partial credit, a quarter of the month's fee: the outage cost "
                "the customer a meaningful part of a day, or they had to chase it."
            ),
            "full_month": (
                "A full month's credit: the outage ran longer than a day, or it "
                "stopped the customer billing their own clients."
            ),
            "other": "Something else.",
        },
    ),
)


def _prepare_credit(ctx: DecisionContext) -> Prepared:
    customer = str(ctx.facts.get("customer", ""))
    return Prepared(
        ctx.kind,
        asks=(_CREDIT,),
        state={
            "person": "an account manager at a small software company",
            "customer": f"{ORG_WORDS.get(customer, 'a customer')}, a paying subscriber",
            "outage": f"The {ctx.facts.get('module')} feature was down for "
            f"{outage_words(ctx.facts.get('minutes'))}.",
            "how_it_was_raised": (
                "Someone from the customer came and pressed for a fix in person."
                if ctx.facts.get("escalated")
                else "The customer did not chase it."
            ),
            "effect_on_customer": (
                "It stopped the customer sending their own month-end invoices."
                if ctx.facts.get("blocked_billing")
                else "The customer's own billing was not affected."
            ),
        },
    )


def _interpret_credit(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    level = str(got["credit"].value)
    return Outcome({"credit": level if level != "other" else "none"}, {})


# -- payroll.release: Friday's wages (WORLD-0004) ----------------------------

_RELEASE = Ask(
    "release",
    "J",
    Noul(
        instructions="Should this week's payroll for this employer be released now?",
        criteria=_yes_no(
            "Release it: the hours are known and the money is there.",
            "Hold it: the hours worked cannot be confirmed yet.",
        ),
    ),
)


def _prepare_payroll(ctx: DecisionContext) -> Prepared:
    multiple = _number(ctx.facts.get("cash_multiple"), 5.0)
    return Prepared(
        ctx.kind,
        asks=(_RELEASE,),
        state={
            "person": (
                "a payroll clerk at an accounting firm, running a client's payroll"
            ),
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
            "timesheets": (
                "This week's timesheets are complete and approved."
                if ctx.facts.get("timesheets_available")
                else "The time-tracking software is down, but the employer kept "
                "this week's hours on paper."
                if ctx.facts.get("on_paper")
                else "The time-tracking software is down, so this week's timesheets "
                "cannot be retrieved and the hours worked are unknown."
            ),
            "funds": (
                "The employer's account covers this payroll several times over."
                if multiple >= 3
                else "The employer's account covers this payroll, but not by much."
            ),
        },
    )


def _interpret_payroll(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    release = bool(got["release"].value)
    return Outcome(
        {"release": release, "reason": "released" if release else "timesheets"}, {}
    )


# -- close.signoff: can the month be stated yet? (WORLD-0004) ----------------

_READINESS = Ask(
    "readiness",
    "J",
    Score(
        instructions="How ready are this client's books to be closed for the month?",
        criteria=[
            "Not ready: the month's revenue cannot be stated yet.",
            "Ready, with notes: minor items are outstanding but the month can close.",
            "Clean: everything reconciles and the month can close.",
        ],
    ),
)


def _prepare_close(ctx: DecisionContext) -> Prepared:
    overdue = int(_number(ctx.facts.get("overdue_bills")))
    return Prepared(
        ctx.kind,
        asks=(_READINESS, _IF_LATE)
        if ctx.facts.get("invoices_stuck")
        else (_READINESS,),
        state={
            "person": "an accountant closing a client's books for the month",
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
            "client": ORG_WORDS.get(str(ctx.facts.get("client")), "a client firm"),
            "sales_invoices": (
                "The client's month-end invoices have NOT been sent: their invoicing "
                "software is down, so this month's revenue is not yet known."
                if ctx.facts.get("invoices_stuck")
                else "All of the client's invoices for the month have been sent."
            ),
            "bills": (
                "The client has no overdue bills."
                if overdue == 0
                else "The client has one or two overdue bills."
                if overdue <= 2
                else "The client has several overdue bills."
            ),
        },
    )


_IF_LATE = Ask(
    "if_not_ready",
    "J",
    Choice(
        instructions=(
            "If the books cannot be closed because the client's figures are "
            "missing, what does the accountant do?"
        ),
        criteria={
            "wait": "Wait for the client's figures and close when they arrive.",
            "estimate": "Close on an estimate now and correct it next month.",
            "nag": "Chase the client for the figures, and wait.",
            "other": "Something else.",
        },
    ),
)
"""The scenario's Ledgerline row: when a client's data is late, wait, nag, or
estimate and fix later. Asked only when the data is late (WORLD-0010)."""


def _interpret_close(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    chosen: dict[str, object] = {"readiness": int(str(got["readiness"].value))}
    if "if_not_ready" in got:
        chosen["if_not_ready"] = str(got["if_not_ready"].value)
    return Outcome(chosen, {})


# -- catering.order: lunch in, tomorrow? (WORLD-0004) ------------------------

_ORDER = Ask(
    "order",
    "P",
    Choice(
        instructions=(
            "Does this person order lunch in from the neighbourhood cafe for the "
            "team tomorrow?"
        ),
        criteria={
            "none": "No order. People sort out their own lunch as usual.",
            "small": "A small order: sandwiches for a meeting.",
            "large": "A large order: lunch for the whole office.",
            "other": "Something else.",
        },
    ),
)


def mood_words(average: object) -> str:
    value = _number(average, 2.0)
    if value < 1.5:
        return "The team has been stressed and short-tempered this week."
    if value < 2.5:
        return "The team's mood has been ordinary."
    return "The team has been in good spirits."


def funds_words(runway_days: object) -> str:
    """How the firm's account looks to the person spending from it, in weeks of
    running costs. The first string is the one every catering question used to
    carry whatever the balance (field report, defect 8)."""

    days = _number(runway_days, 60.0)
    if days >= 56:
        return "There is comfortably enough in the account for it."
    if days >= 21:
        return "The account can cover it, but money is not plentiful."
    return "Money is tight; the firm has only a few weeks of costs in the bank."


def _prepare_catering(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_ORDER,),
        state={
            "person": (
                "the person who handles office spending at "
                + ORG_WORDS.get(org, "a firm")
            ),
            "temperament": trait_words("sociability", ctx.traits.get("sociability")),
            "team": mood_words(ctx.facts.get("team_mood")),
            "funds": funds_words(ctx.facts.get("runway_days")),
        },
    )


def _interpret_catering(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    order = str(got["order"].value)
    return Outcome({"order": order if order in ("small", "large") else "none"}, {})


# -- ticket.confirm and chase.invoice: the loops that close (WORLD-0005) -------

_CONFIRM = Ask(
    "confirm",
    "P",
    Noul(
        instructions=(
            "Support has told this customer their problem is fixed. Today, do "
            "they check, and reply to confirm so the ticket can be closed?"
        ),
        criteria=_yes_no(
            "They check it works and reply today; the ticket is closed.",
            "They do not get round to replying today.",
        ),
    ),
)


def answered_words(days: object) -> str:
    d = int(_number(days))
    if d <= 0:
        return "support replied earlier today to say it is fixed"
    if d == 1:
        return "support replied yesterday to say it is fixed"
    return "support replied a couple of days ago to say it is fixed"


def _prepare_confirm(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_CONFIRM,),
        state={
            "person": "a customer who pays for small-business software",
            "temperament": trait_words("diligence", ctx.traits.get("diligence")),
            "ticket": answered_words(ctx.facts.get("days_since_answer")),
            "software": "The feature they reported is working again.",
        },
    )


def _interpret_confirm(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    confirm = bool(got["confirm"].value)
    return Outcome(
        {"confirm": confirm, "reason": "confirmed" if confirm else "silent"}, {}
    )


_CHASE = Ask(
    "chase",
    "P",
    Noul(
        instructions=(
            "Today, does this person ring the client about the unpaid invoice?"
        ),
        criteria=_yes_no(
            "They ring or write to the client today and ask for payment.",
            "They leave it another day.",
        ),
    ),
)


def _prepare_chase(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_CHASE,),
        state={
            "person": (
                "the person who looks after the money at "
                + ORG_WORDS.get(org, "a small firm")
            ),
            "temperament": trait_words("vocality", ctx.traits.get("vocality")),
            "invoice": lateness_words(-_number(ctx.facts.get("days_late"), 7.0)),
            "size": (
                "it is one of the larger amounts they are owed"
                if ctx.facts.get("large")
                else "it is a modest amount"
            ),
            "cash": runway_words(ctx.facts.get("runway_days")),
        },
    )


def _interpret_chase(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"chase": bool(got["chase"].value)}, {})


# -- episode.round: one round of a bounded group interaction (WORLD-0006) -----
#
# An encounter is one question about the present moment. An episode is several,
# in sequence, about a matter the people present have between them — and the
# only reason to run one is that round two can see what round one did. Jev
# answers the questions in a request independently, so a round is one request
# per participant and the sequence lives in code.
#
# Three rules shape the set, each from a failure the one-shot encounter cannot
# have:
#
# 1.  **What a person may do depends on whether they can act on the matter.**
#     The firm whose software is down can press; the vendor can promise. Offering
#     `promise` to someone with nothing to promise invites mass on an option the
#     world would have to ignore.
# 2.  **Irreversible acts are asked once.** Telling someone something cannot be
#     untold, so `mention` is asked in the first round it is possible for that
#     speaker and never again — otherwise three rounds thin one propensity into
#     near-certainty, which is the hazard-rate trap (DECIDE-0001) inside an
#     episode instead of across a day.
# 3.  **No round number reaches the model.** Progress is described (`so_far`),
#     never counted: Jev is weak at numbers, and two tables at the same point in
#     the same kind of conversation should share one cached call.

_ACT_WORDS: dict[str, str] = {
    "press": "Push the other side to deal with the matter now.",
    "promise": "Give their word to deal with it, by a definite day.",
    "explain": "Set out their own side of it, without pushing or promising.",
    "decline": "Say plainly that it is not going to happen.",
    "ask": "Ask the others what they know, or what they mean to do.",
    "small_talk": "Let the matter drop and talk about something else.",
    "leave": "Break off and get back to their own day.",
    "other": "Something else.",
}

# Declared order is the sampling order (see `Ask.options`), so it is written
# once here and filtered by role, never rebuilt per call site.
_ACT_ORDER: tuple[str, ...] = (
    "press",
    "promise",
    "explain",
    "decline",
    "ask",
    "small_talk",
    "leave",
    "other",
)

# Who may do what. `holder` can act on the matter, `asker` wants them to, and a
# `bystander` is only in the room.
_ACTS_BY_ROLE: dict[str, frozenset[str]] = {
    "holder": frozenset(
        {"promise", "explain", "decline", "ask", "small_talk", "leave"}
    ),
    "asker": frozenset({"press", "explain", "ask", "small_talk", "leave"}),
    "bystander": frozenset({"ask", "small_talk", "leave"}),
}

STAKE_WORDS: dict[str, str] = {
    "outage": (
        "A feature of the software they use for work has stopped responding, "
        "and the people here are affected by it."
    ),
    "invoice": "A bill between their two firms has not been paid.",
    "news": "Nothing in particular; they have simply ended up together.",
}

TELLABLE_WORDS: dict[str, str] = {
    "outage": "that a feature of the software they all use has stopped working",
    "price_rise": "that the software company is planning to put its prices up",
}
"""The two original sentences, kept byte for byte. Everything a fact can be
about now (WORLD-0010) is worded by `tellable_words`, which names the firm."""

_TOPIC_WORDS: dict[str, str] = {
    "price_rise": "that {org} is putting its prices up",
    "payroll_late": "that {org} has not been able to pay its staff",
    "insolvency": "that {org} is running out of money",
    "churned": "that {org} is losing customers",
    "promise_broken": "that somebody broke their word to pay a bill",
}


def tellable_words(topic: str, about: object = None) -> str:
    if (
        about is None
        or topic not in _TOPIC_WORDS
        or (topic == "price_rise" and about == "tallybird")
    ):
        return TELLABLE_WORDS.get(topic, "a piece of news they have heard")
    return _TOPIC_WORDS[topic].format(org=ORG_WORDS.get(str(about), "a firm in town"))


def stake_words(ctx: DecisionContext) -> str:
    """What the people here have between them, in words.

    The lateness of a bill is bucketed by the same function the payment question
    uses, so "a few days overdue" means the same thing in both — a reader
    comparing an episode with the decision it changed is comparing like with
    like.
    """

    stake = str(ctx.facts.get("stake", "news"))
    if stake == "invoice":
        late = lateness_words(-_number(ctx.facts.get("days_late"), 7.0))
        size = (
            "one of the larger amounts"
            if ctx.facts.get("large")
            else "a fairly modest amount"
        )
        return f"A bill between their two firms is unpaid: {late}, and it is {size}."
    if stake == "outage":
        module = ctx.facts.get("module")
        if module:
            return (
                f"The {module} feature of the software they use for work has "
                "stopped responding, and the people here are affected by it."
            )
    return STAKE_WORDS.get(stake, STAKE_WORDS["news"])


def so_far_words(ctx: DecisionContext) -> str:
    """How the conversation stands. The whole reason a second round differs
    from the first, so it is described rather than counted."""

    if ctx.facts.get("promised"):
        return "Someone has already given their word to deal with it."
    if ctx.facts.get("refused"):
        return "Someone has already said plainly that it will not happen."
    if ctx.facts.get("pressed"):
        return "Someone has already pushed hard for it to be dealt with."
    if ctx.facts.get("raised"):
        return "The matter has been brought up, and nothing is settled yet."
    return "They have only just fallen into conversation."


def tension_words(level: object) -> str:
    value = int(_number(level))
    if value <= 0:
        return "Easy; nobody has taken offence."
    if value == 1:
        return "A little awkward."
    return "Tense; somebody is annoyed."


_SETTLED = Ask(
    "settled",
    "J",
    Noul(
        instructions=(
            "Has the matter these people came together about now been dealt "
            "with, so that there is nothing left to say about it today?"
        ),
        criteria=_yes_no(
            "It is dealt with: someone has agreed to act, or it is plainly "
            "going nowhere and both sides know it.",
            "It is not dealt with; there is more to say.",
        ),
    ),
)


def _mention(topic: str, about: object = None) -> Ask:
    return Ask(
        "mention",
        "P",
        Noul(
            instructions=(
                f"Does this person tell the others {tellable_words(topic, about)}?"
            ),
            criteria=_yes_no(
                "They bring it up and pass it on.",
                "They keep it to themselves for now.",
            ),
        ),
    )


def _act(role: str) -> Ask:
    """The verbs open to this person, in declared order.

    `other` is always last and always present: mass on it is an ontology gap,
    which is the project's primary research measurement (DECIDE-0001).
    """

    allowed = _ACTS_BY_ROLE.get(role, _ACTS_BY_ROLE["bystander"])
    criteria: dict[str, str | dict[str, object] | list[object] | None] = {
        name: _ACT_WORDS[name]
        for name in _ACT_ORDER
        if name in allowed or name == "other"
    }
    return Ask(
        "act",
        "P",
        Choice(
            instructions="What does this person do next in this conversation?",
            criteria=criteria,
        ),
    )


def _prepare_episode_round(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    here = str(ctx.facts.get("here", ""))
    role = str(ctx.facts.get("role_in_stake", "bystander"))

    state: dict[str, object] = {
        "person": person_words(ctx.role, org),
        "temperament": trait_words("sociability", ctx.traits.get("sociability")),
        "speaks_up": trait_words("vocality", ctx.traits.get("vocality")),
        "where": _PLACE_WORDS.get(here, here),
        "time": time_of_day_words(ctx.sim_time),
        "who_is_here": who_is_here(ctx),
        "what_this_is_about": stake_words(ctx),
        "their_part_in_it": _ROLE_WORDS[role],
        "so_far": so_far_words(ctx),
        "mood_of_the_room": tension_words(ctx.facts.get("tension")),
    }
    asks: list[Ask] = [_act(role), _SETTLED, _MOOD]
    topic = ctx.facts.get("tellable_topic")
    if isinstance(topic, str) and topic:
        asks.append(_mention(topic, ctx.facts.get("tellable_about")))
    return Prepared(ctx.kind, asks=tuple(asks), state=state)


_ROLE_WORDS: dict[str, str] = {
    "holder": "They are the one who could actually do something about it.",
    "asker": "It is their work that is held up, and they cannot fix it themselves.",
    "bystander": "It is not their problem either way.",
}


def _interpret_episode_round(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome(
        {
            "act": str(got["act"].value),
            "settled": bool(got["settled"].value),
            "mood": int(str(got["mood"].value)),
            "mention": bool("mention" in got and got["mention"].value),
        },
        {},
    )


# -- the economy has consequences (WORLD-0009) ---------------------------------


def arrears_words(weeks_behind: object) -> str:
    weeks = int(_number(weeks_behind))
    if weeks <= 1:
        return "Their wages are a week late."
    if weeks == 2:
        return "They have not been paid for two weeks."
    return "They have not been paid for three weeks or more."


_LEAVE = Ask(
    "leave",
    "P",
    Noul(
        instructions=(
            "This week, does this person hand in their notice and go to work "
            "somewhere else?"
        ),
        criteria=_yes_no(
            "They quit and take their chances elsewhere.",
            "They stay for now and hope it is sorted out.",
        ),
    ),
)


def _prepare_leave(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_LEAVE,),
        state={
            "person": person_words(ctx.role, org),
            "wages": arrears_words(ctx.facts.get("weeks_behind")),
            "firm": "Everyone at work knows the firm is short of money.",
            "temperament": trait_words("patience", ctx.traits.get("patience")),
            "attitude_to_risk": trait_words(
                "risk_appetite", ctx.traits.get("risk_appetite")
            ),
        },
    )


def _interpret_leave(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    leave = bool(got["leave"].value)
    return Outcome({"leave": leave, "reason": "unpaid" if leave else "stays"}, {})


_REVIEW = Ask(
    "choice",
    "J",
    Choice(
        instructions=(
            "Looking at the firm's money, what does this person decide to do "
            "about it now?"
        ),
        criteria={
            "raise_prices": "Put the firm's prices up by about a tenth.",
            "cut_costs": (
                "Cut spending: no extras, no lunches, no new hires, until "
                "things improve."
            ),
            "chase_debts": "Chase everyone who owes the firm money, sooner and harder.",
            "borrow": "Take a short-term loan from the bank to cover the gap.",
            "hold_course": "Carry on as they are; nothing needs to change.",
            "other": "Something else.",
        },
    ),
)


def trend_words(money_in: object, money_out: object) -> str:
    received, spent = _number(money_in), _number(money_out)
    if received <= 0 and spent <= 0:
        return "Almost nothing has come in or gone out this month."
    if received >= spent * 1.1:
        return "More money has come in this month than has gone out."
    if received >= spent * 0.9:
        return "About as much has gone out this month as has come in."
    return "Far more has gone out this month than has come in."


def owed_words(overdue: object, weekly: object) -> str:
    owed, week = _number(overdue), max(1.0, _number(weekly, 1.0))
    if owed <= 0:
        return "Nobody owes the firm anything overdue."
    if owed < week:
        return "A little is owed to the firm and overdue."
    return "Customers owe the firm a lot of overdue money."


def _prepare_review(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    state: dict[str, object] = {
        "person": person_words(ctx.role, org),
        "attitude_to_risk": trait_words(
            "risk_appetite", ctx.traits.get("risk_appetite")
        ),
        "cash": funds_words(ctx.facts.get("runway_days")),
        "this_month": trend_words(
            ctx.facts.get("money_in"), ctx.facts.get("money_out")
        ),
        "owed_to_the_firm": owed_words(
            ctx.facts.get("overdue_to_them"), ctx.facts.get("weekly_outgoings")
        ),
        "wages": (
            "This week's wages could not be paid."
            if ctx.facts.get("payroll_held")
            else "Wages are being paid on time."
        ),
    }
    if ctx.facts.get("raised_recently"):
        state["prices"] = "The firm put its prices up recently."
    if ctx.facts.get("has_loan"):
        state["borrowing"] = "The firm already owes the bank a loan."
    return Prepared(ctx.kind, asks=(_REVIEW,), state=state)


def _interpret_review(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    choice = str(got["choice"].value)
    return Outcome({"choice": choice if choice != "other" else "hold_course"}, {})


_HIRE = Ask(
    "hire",
    "J",
    Noul(
        instructions="Should the firm hire someone to fill this empty job now?",
        criteria=_yes_no(
            "Hire: the work needs doing and the firm can pay for it.",
            "Leave it empty for now.",
        ),
    ),
)


def _prepare_hire(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_HIRE,),
        state={
            "person": person_words(ctx.role, org),
            "vacancy": "The firm is without "
            f"{role_words(str(ctx.facts.get('vacancy', '')))}.",
            "cash": funds_words(ctx.facts.get("runway_days")),
            "attitude_to_risk": trait_words(
                "risk_appetite", ctx.traits.get("risk_appetite")
            ),
        },
    )


def _interpret_hire(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"hire": bool(got["hire"].value)}, {})


# -- the loops the scenario names (WORLD-0010) ----------------------------------


def debt_words(level: object) -> str:
    value = _number(level, 1.0)
    if value < 0.6:
        return "The codebase is in good shape."
    if value < 1.2:
        return "The codebase carries shortcuts that slow the team down."
    return "The codebase is fragile; things break often."


def incidents_words(count: object) -> str:
    n = int(_number(count))
    if n == 0:
        return "Nothing broke last week."
    if n == 1:
        return "Something broke once last week."
    return "Things broke several times last week."


_ALLOCATION = Ask(
    "allocation",
    "J",
    Choice(
        instructions="How should the engineering team spend this week?",
        criteria={
            "roadmap": "Build the features customers are asking for.",
            "debt": "Pay down technical debt so things break less often.",
            "firefight": "Drop everything else and deal with what is on fire.",
            "other": "Something else.",
        },
    ),
)


def _prepare_allocation(ctx: DecisionContext) -> Prepared:
    churned = int(_number(ctx.facts.get("churned_last_month")))
    return Prepared(
        ctx.kind,
        asks=(_ALLOCATION,),
        state={
            "person": person_words(ctx.role, "tallybird"),
            "codebase": debt_words(ctx.facts.get("debt_level")),
            "last_week": incidents_words(ctx.facts.get("incidents_last_week")),
            "support_queue": backlog_words(ctx.facts.get("backlog")),
            "customers": (
                "Customers have been cancelling their subscriptions."
                if churned
                else "Customers are asking for new features."
            ),
            "cash": funds_words(ctx.facts.get("runway_days")),
        },
    )


def _interpret_allocation(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    choice = str(got["allocation"].value)
    return Outcome({"allocation": choice if choice != "other" else "roadmap"}, {})


_DEPLOY = Ask(
    "deploy",
    "P",
    Noul(
        instructions="Does the team release this week's changes to customers today?",
        criteria=_yes_no(
            "They ship the changes today.",
            "They hold the changes back for now.",
        ),
    ),
)


def _prepare_deploy(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_DEPLOY,),
        state={
            "person": person_words(ctx.role, "tallybird"),
            "attitude_to_risk": trait_words(
                "risk_appetite", ctx.traits.get("risk_appetite")
            ),
            "codebase": debt_words(ctx.facts.get("debt_level")),
            "last_week": incidents_words(ctx.facts.get("incidents_last_week")),
        },
    )


def _interpret_deploy(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"deploy": bool(got["deploy"].value)}, {})


TRUST_LEVELS: tuple[str, ...] = (
    "They no longer trust it at all and are looking elsewhere.",
    "They doubt it; one more problem and they will look elsewhere.",
    "They are uneasy about it but not looking elsewhere yet.",
    "They are reasonably confident in it.",
    "They trust it completely.",
)
"""A customer's trust in the vendor: MEM-0001's "reliability" slot, the first
typed belief in the world."""

_TRUST = Ask(
    "trust",
    "J",
    Score(
        instructions=(
            "After this, how far does the customer trust the software company "
            "to keep the product working?"
        ),
        criteria=list(TRUST_LEVELS),
    ),
)


def trust_words(level: object) -> str:
    index = int(_number(level, 3.0))
    return TRUST_LEVELS[max(0, min(len(TRUST_LEVELS) - 1, index))]


def _prepare_trust(ctx: DecisionContext) -> Prepared:
    if ctx.facts.get("reported"):
        handled = (
            "They reported it and support has replied."
            if ctx.facts.get("answered")
            else "They reported it and have heard nothing back."
        )
    else:
        handled = "They did not report it."
    state: dict[str, object] = {
        "person": "a customer who pays for small-business software",
        "temperament": trait_words("patience", ctx.traits.get("patience")),
        "before": trust_words(ctx.facts.get("trust")),
        "outage": f"The {ctx.facts.get('module')} feature was down for "
        f"{outage_words(ctx.facts.get('minutes'))}.",
        "handled": handled,
        "history": (
            "It is the second time this month."
            if ctx.facts.get("repeat")
            else "It is the first problem in a while."
        ),
    }
    if ctx.facts.get("tried_another_tool"):
        state["meanwhile"] = "While it was down they tried a competitor's product."
    return Prepared(ctx.kind, asks=(_TRUST,), state=state)


def _interpret_trust(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"trust": int(str(got["trust"].value))}, {})


_RENEW = Ask(
    "renew",
    "P",
    Noul(
        instructions=(
            "Does this customer keep paying for the software for another month?"
        ),
        criteria=_yes_no(
            "They keep their subscription.",
            "They cancel it and move to another product.",
        ),
    ),
)


def _prepare_renew(ctx: DecisionContext) -> Prepared:
    state: dict[str, object] = {
        "person": "a customer who pays for small-business software",
        "temperament": trait_words("patience", ctx.traits.get("patience")),
        "trust": trust_words(ctx.facts.get("trust")),
        "reliance": (
            "Their whole business runs on it; moving would be a lot of work."
            if ctx.facts.get("relies_on_it")
            else "Only a few of their people use it; moving would be easy."
        ),
    }
    if ctx.facts.get("heard_bad_news"):
        state["heard"] = "They have heard the software company is in trouble."
    if ctx.facts.get("price_rise"):
        state["price"] = "The software company has put its prices up."
    if ctx.facts.get("offered_discount"):
        state["offer"] = "The account manager has offered them a month at a discount."
    return Prepared(ctx.kind, asks=(_RENEW,), state=state)


def _interpret_renew(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"renew": bool(got["renew"].value)}, {})


_RETAIN = Ask(
    "offer",
    "J",
    Noul(
        instructions=(
            "Should the account manager offer this unhappy customer a month at a "
            "quarter off, to keep them?"
        ),
        criteria=_yes_no(
            "Offer the discount.",
            "Do not; let them decide on their own.",
        ),
    ),
)


def _prepare_retain(ctx: DecisionContext) -> Prepared:
    state: dict[str, object] = {
        "person": person_words(ctx.role, "tallybird"),
        "customer": (
            "One of the larger customers."
            if ctx.facts.get("large")
            else "A mid-sized customer."
        ),
        "trust": trust_words(ctx.facts.get("trust")),
        "cash": funds_words(ctx.facts.get("runway_days")),
    }
    if ctx.facts.get("heard_bad_news"):
        state["heard"] = "The customer has heard the company is in trouble."
    return Prepared(ctx.kind, asks=(_RETAIN,), state=state)


def _interpret_retain(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"offer": bool(got["offer"].value)}, {})


_DISPUTE = Ask(
    "dispute",
    "P",
    Noul(
        instructions="Does this person query the bill instead of accepting it?",
        criteria=_yes_no(
            "They write back and dispute part of it.",
            "They accept it as it stands.",
        ),
    ),
)


def _prepare_dispute(ctx: DecisionContext) -> Prepared:
    issuer = str(ctx.facts.get("issuer", ""))
    state: dict[str, object] = {
        "person": (
            "the person who pays the bills for a small business"
            if ctx.facts.get("firm")
            else "a client of a professional firm"
        ),
        "temperament": trait_words("patience", ctx.traits.get("patience")),
        "bill": f"A bill has just arrived from {ORG_WORDS.get(issuer, 'a firm')}.",
        "size": (
            "It is larger than they expected."
            if ctx.facts.get("large")
            else "It is about what they expected."
        ),
    }
    if ctx.facts.get("price_rise"):
        state["prices"] = "The firm has recently put its prices up."
    return Prepared(ctx.kind, asks=(_DISPUTE,), state=state)


def _interpret_dispute(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"dispute": bool(got["dispute"].value)}, {})


_RESOLUTION = Ask(
    "resolution",
    "J",
    Choice(
        instructions="A client has disputed a bill. What does the firm do?",
        criteria={
            "stand_firm": "Stand by the bill and ask for it in full.",
            "discount": "Take a sixth off to settle it.",
            "write_off": "Drop the bill entirely to keep the client.",
            "other": "Something else.",
        },
    ),
)


def _prepare_resolution(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_RESOLUTION,),
        state={
            "person": person_words(ctx.role, org),
            "bill": (
                "It is one of the larger bills the firm sends."
                if ctx.facts.get("large")
                else "It is a modest bill."
            ),
            "client": (
                "The client is another firm in town."
                if ctx.facts.get("client_firm")
                else "The client is an outside customer."
            ),
            "cash": funds_words(ctx.facts.get("runway_days")),
        },
    )


def _interpret_resolution(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    choice = str(got["resolution"].value)
    return Outcome({"resolution": choice if choice != "other" else "stand_firm"}, {})


_HANDOFF = Ask(
    "relay",
    "P",
    Noul(
        instructions=(
            "A customer has complained about the outage to this person. Do they "
            "take it straight to the engineers?"
        ),
        criteria=_yes_no(
            "They go and tell the engineers at once.",
            "They log it and leave it in the queue.",
        ),
    ),
)


def _prepare_handoff(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_HANDOFF,),
        state={
            "person": person_words(ctx.role, "tallybird"),
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
            "how": (
                "The customer rang them."
                if ctx.facts.get("by_phone")
                else "The customer cornered them in person."
            ),
            "queue": backlog_words(ctx.facts.get("backlog")),
        },
    )


def _interpret_handoff(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"relay": bool(got["relay"].value)}, {})


_LOG = Ask(
    "log",
    "P",
    Noul(
        instructions="Before going home, does this person log their billable hours?",
        criteria=_yes_no(
            "They log their hours now.",
            "They leave it for later.",
        ),
    ),
)


def pending_words(days: object) -> str:
    n = int(_number(days))
    if n <= 1:
        return "Only today's hours are unlogged."
    if n <= 3:
        return "They have a few days of hours still to log."
    return "They have not logged their hours for about a week."


def _prepare_log(ctx: DecisionContext) -> Prepared:
    state: dict[str, object] = {
        "person": person_words(ctx.role, "halloran"),
        "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        "backlog": pending_words(ctx.facts.get("pending_days")),
    }
    if ctx.facts.get("on_paper"):
        state["software"] = (
            "The time-tracking software is down; they keep a paper note."
        )
    return Prepared(ctx.kind, asks=(_LOG,), state=state)


def _interpret_log(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"log": bool(got["log"].value)}, {})


_COVER = Ask(
    "cover",
    "J",
    Choice(
        instructions="Someone behind the counter is off sick. What does the owner do?",
        criteria={
            "cover_it": "Work the shift themselves.",
            "call_in": "Call in the weekend part-timer.",
            "run_short": "Run the cafe one person short.",
            "other": "Something else.",
        },
    ),
)


def _prepare_cover(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_COVER,),
        state={
            "person": person_words(ctx.role, "thirdrail"),
            "absent": f"{role_words(str(ctx.facts.get('absent_role', 'barista')))} "
            "is off sick.",
            "cash": funds_words(ctx.facts.get("runway_days")),
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        },
    )


def _interpret_cover(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    choice = str(got["cover"].value)
    return Outcome({"cover": choice if choice != "other" else "run_short"}, {})


_STOCK = Ask(
    "order",
    "J",
    Choice(
        instructions="How much stock does the cafe order for the coming week?",
        criteria={
            "usual": "The usual amount.",
            "more": "More than usual.",
            "less": "Less than usual.",
            "other": "Something else.",
        },
    ),
)


def _prepare_stock(ctx: DecisionContext) -> Prepared:
    trend = _number(ctx.facts.get("trend"), 1.0)
    return Prepared(
        ctx.kind,
        asks=(_STOCK,),
        state={
            "person": person_words(ctx.role, "thirdrail"),
            "sales": (
                "The till's records are unavailable, so last week's sales are a guess."
                if ctx.facts.get("pos_down")
                else "Last week was busier than the week before."
                if trend > 1.1
                else "Last week was quieter than the week before."
                if trend < 0.9
                else "Last week was much like the week before."
            ),
            "cash": funds_words(ctx.facts.get("runway_days")),
        },
    )


def _interpret_stock(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    choice = str(got["order"].value)
    return Outcome({"order": choice if choice != "other" else "usual"}, {})


_ACCEPT = Ask(
    "accept",
    "P",
    Noul(
        instructions="Does the cafe take on this catering order for tomorrow?",
        criteria=_yes_no(
            "They accept it.",
            "They turn it down.",
        ),
    ),
)


def _prepare_accept(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_ACCEPT,),
        state={
            "person": person_words(ctx.role, "thirdrail"),
            "order": (
                "Lunch for a whole office."
                if ctx.facts.get("size") == "large"
                else "Sandwiches for a meeting."
            ),
            "staff": (
                "They are short-handed behind the counter."
                if ctx.facts.get("short_staffed")
                else "They have the usual people on."
            ),
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        },
    )


def _interpret_accept(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"accept": bool(got["accept"].value)}, {})


QUESTION_SETS: dict[str, QuestionSet] = {
    s.kind: s
    for s in (
        QuestionSet("file.ticket", _prepare_file_ticket, _interpret_file_ticket),
        QuestionSet("ticket.triage", _prepare_triage, _interpret_triage),
        QuestionSet("ticket.answer", _prepare_answer, _interpret_answer),
        QuestionSet("payment.timing", _prepare_payment, _interpret_payment),
        QuestionSet("cafe.purchase", _prepare_cafe, _interpret_cafe),
        QuestionSet("agent.tick", _prepare_agent_tick, _interpret_agent_tick),
        QuestionSet("credit.decision", _prepare_credit, _interpret_credit),
        QuestionSet("payroll.release", _prepare_payroll, _interpret_payroll),
        QuestionSet("close.signoff", _prepare_close, _interpret_close),
        QuestionSet("catering.order", _prepare_catering, _interpret_catering),
        QuestionSet("ticket.confirm", _prepare_confirm, _interpret_confirm),
        QuestionSet("chase.invoice", _prepare_chase, _interpret_chase),
        QuestionSet("episode.round", _prepare_episode_round, _interpret_episode_round),
        QuestionSet("leave.consider", _prepare_leave, _interpret_leave),
        QuestionSet("founder.review", _prepare_review, _interpret_review),
        QuestionSet("hire.decision", _prepare_hire, _interpret_hire),
        QuestionSet("eng.allocation", _prepare_allocation, _interpret_allocation),
        QuestionSet("deploy.decision", _prepare_deploy, _interpret_deploy),
        QuestionSet("vendor.trust", _prepare_trust, _interpret_trust),
        QuestionSet("subscription.renew", _prepare_renew, _interpret_renew),
        QuestionSet("retention.offer", _prepare_retain, _interpret_retain),
        QuestionSet("invoice.dispute", _prepare_dispute, _interpret_dispute),
        QuestionSet("dispute.resolution", _prepare_resolution, _interpret_resolution),
        QuestionSet("escalation.handoff", _prepare_handoff, _interpret_handoff),
        QuestionSet("time.log", _prepare_log, _interpret_log),
        QuestionSet("cover.shift", _prepare_cover, _interpret_cover),
        QuestionSet("supplier.order", _prepare_stock, _interpret_stock),
        QuestionSet("catering.accept", _prepare_accept, _interpret_accept),
    )
}
