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
from jeve.core.orgs import ORGS, role_words
from jeve.decide.policy import DecisionContext
from jeve.llm.protocol import Choice, Noul, NoulCriteria, Score
from jeve.memory.beliefs import SLOTS as BELIEF_SLOTS
from jeve.memory.beliefs import words as belief_words

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
    "risk_appetite": (
        "cautious with money; would rather go without than borrow",
        "borrows when there is a clear need and a way to repay",
        "comfortable with debt; borrows early to keep options open",
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


def _prepare_file_ticket(ctx: DecisionContext) -> Prepared:
    return Prepared(
        ctx.kind,
        asks=(_FILE,),
        state={
            "person": "a customer who pays for small-business software",
            "temperament": trait_words("vocality", ctx.traits.get("vocality")),
            "situation": _outage_so_far(ctx.facts.get("hours_down")),
        },
    )


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


def _prepare_retail(ctx: DecisionContext) -> Prepared:
    place = PLACE_WORDS.get(str(ctx.facts.get("org", "")), "a neighbourhood shop")
    return Prepared(
        ctx.kind,
        asks=(_BUY,),
        state={
            "person": f"someone who has just walked into {place}",
            "temperament": trait_words("patience", ctx.traits.get("patience")),
            "line": queue_words(ctx.facts.get("queue_length")),
            "till": (
                "The card reader is broken; they are taking cash only and "
                "service is slow."
                if ctx.facts.get("till_down")
                else "The place is running normally and taking cards."
            ),
        },
    )


def _interpret_retail(
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

# How a question set names a firm and being there: from the roster
# (CORE-0012), never the brand. Wording is a cache key, so these are data
# that changes rarely, not prose that is tidied.
ORG_WORDS: dict[str, str] = {org.id: org.words for org in ORGS}
PLACE_WORDS: dict[str, str] = {org.id: org.place_words for org in ORGS} | {
    "plaza": "the plaza outside, by the fountain",
}
_SOCIAL_WORDS: dict[str, str] = {
    "cafe": "Walk over to the cafe for a coffee or something to eat.",
    "gym": "Go to the gym for a workout.",
}
MOODS: tuple[str, ...] = (
    "Stressed and short-tempered.",
    "Flat; just getting through the day.",
    "Content and settled.",
    "Upbeat and energetic.",
)


CANDIDATES = 6
"""How many of the people here are offered as somebody to talk to."""
GROUPS = 5
"""How many firms' worth of people are named when the room is described."""
_NUMBERS = (
    "no", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten",
)  # fmt: skip


def slot(index: int) -> str:
    """A neutral label for someone present. Names and ids are noise to Jev,
    and would stop two identical rooms sharing a call."""

    return f"person_{chr(ord('a') + index)}"


def _article(words: str) -> str:
    return "an" if words[:1] in "aeiou" else "a"


def describe(person: dict[str, object]) -> str:
    role = role_words(str(person.get("role", "employee")))
    firm = ORG_WORDS.get(str(person.get("org")), "another firm")
    return f"{_article(role)} {role} from {firm}"


def count_words(n: int, words: str) -> str:
    """`a paralegal`, `two engineers`, `fourteen support agents`."""

    if n == 1:
        return f"{_article(words)} {words}"
    plural = words if words.endswith("s") else f"{words}s"
    return f"{_NUMBERS[n] if n < len(_NUMBERS) else n} {plural}"


def _present(ctx: DecisionContext) -> list[dict[str, object]]:
    present = ctx.facts.get("present")
    return (
        [p for p in present if isinstance(p, dict)] if isinstance(present, list) else []
    )


def _priority(person: dict[str, object], *, own_org: str, vendor: object) -> int:
    """Whom it matters most to notice: the vendor whose product is down,
    then colleagues from other floors, then everybody else."""

    org = str(person.get("org"))
    if vendor is not None and org == vendor:
        return 0
    return 1 if org == own_org else 2


def candidates(
    present: list[dict[str, object]],
    *,
    own_org: str,
    vendor: object,
    strengths: dict[str, int] | None = None,
) -> list[str]:
    """Who is offered as somebody to talk to: at most `CANDIDATES` of the
    people here, the vendor's staff first, then colleagues, then the people
    they know best (MEM-0003), then the rest in a stable order. The one
    function both policies and the world use, so the labels a model chooses
    from and the people the rules twin picks among are the same short list
    (DECIDE-0005)."""

    known = strengths or {}
    ranked = sorted(
        present,
        key=lambda p: (
            _priority(p, own_org=own_org, vendor=vendor),
            -known.get(str(p.get("id")), 0),
            str(p.get("id")),
        ),
    )
    return [str(p["id"]) for p in ranked[:CANDIDATES] if "id" in p]


def _offered(ctx: DecisionContext) -> list[dict[str, object]]:
    """The people behind the labels, in label order."""

    present = _present(ctx)
    ids = ctx.facts.get("candidates")
    if not isinstance(ids, list):
        known = ctx.facts.get("strengths")
        ids = candidates(
            present,
            own_org=str(ctx.facts.get("org", "")),
            vendor=ctx.facts.get("vendor"),
            strengths=(
                {str(k): int(str(v)) for k, v in known.items()}
                if isinstance(known, dict)
                else None
            ),
        )
    by_id = {str(p.get("id")): p for p in present}
    return [by_id[str(i)] for i in ids if str(i) in by_id]


def roster_words(
    present: list[dict[str, object]], *, own_org: str, vendor: object
) -> str:
    """Who is here, counted rather than listed (DECIDE-0005): `two engineers
    and a salesperson from the software company; a paralegal from the law
    firm; and three others`. Bounded however crowded the floor, and the same
    words for any two rooms with the same people in them by role and firm."""

    by_org: dict[str, dict[str, int]] = {}
    for person in present:
        roles = by_org.setdefault(str(person.get("org")), {})
        role = str(person.get("role", "employee"))
        roles[role] = roles.get(role, 0) + 1
    ordered = sorted(
        by_org,
        key=lambda org: (
            0 if org == vendor else 1 if org == own_org else 2,
            -sum(by_org[org].values()),
            org,
        ),
    )
    parts: list[str] = []
    for org in ordered[:GROUPS]:
        counted = [
            count_words(n, role_words(role)) for role, n in sorted(by_org[org].items())
        ]
        people = (
            counted[0]
            if len(counted) == 1
            else ", ".join(counted[:-1]) + f" and {counted[-1]}"
        )
        parts.append(f"{people} from {ORG_WORDS.get(org, 'another firm')}")
    rest = sum(sum(by_org[org].values()) for org in ordered[GROUPS:])
    if rest:
        parts.append(f"and {count_words(rest, 'other')}")
    return "; ".join(parts) + "."


def _social(ctx: DecisionContext) -> dict[str, str]:
    """Where the staff of other firms go on their own time: kind -> firm id."""

    social = ctx.facts.get("social")
    return (
        {str(k): str(v) for k, v in social.items()} if isinstance(social, dict) else {}
    )


def destination(ctx: DecisionContext) -> Ask:
    """Where next. The options are the places this person could go from here:
    their desk, their building's lobby, the district's cafe or gym, the plaza,
    and — only when their software is down — the vendor that sells it."""

    org = str(ctx.facts.get("org", ""))
    here = str(ctx.facts.get("here", ""))
    vendor = ctx.facts.get("vendor")
    criteria: dict[str, str] = {
        "stay": "Stay where they are for now.",
        "own_workplace": "Go back to their own workplace and get on with work.",
    }
    if ctx.facts.get("lobby"):
        criteria["lobby"] = (
            "Go down to the lobby of their own building, by the kitchenette."
        )
    for kind in _social(ctx):
        if kind in _SOCIAL_WORDS:
            criteria[kind] = _SOCIAL_WORDS[kind]
    criteria["plaza"] = "Step out into the plaza for some air."
    if isinstance(vendor, str) and vendor not in (org, here):
        criteria["visit"] = (
            f"Walk over to {ORG_WORDS.get(vendor, 'the vendor')}'s office to "
            "speak to them in person about the outage."
        )
    criteria["other"] = "Something else."
    return Ask(
        "next_zone",
        "P",
        Choice(
            instructions="Where does this person go next?",
            criteria=dict(criteria),
        ),
    )


# Beliefs are revised by a score inside a request already being made
# (MEM-0003): never a call of their own.
_RELIABILITY = Ask(
    "vendor_reliability",
    "J",
    Score(
        instructions=(
            "Having lived with this outage, how reliable does this person now "
            "think the software is?"
        ),
        criteria=list(BELIEF_SLOTS["vendor_reliability"]),
    ),
)
_STRAIN = Ask(
    "employer_strain",
    "J",
    Score(
        instructions=(
            "From what they have seen at work lately, how is this person's "
            "employer doing?"
        ),
        criteria=list(BELIEF_SLOTS["employer_strain"]),
    ),
)
_TRUST = Ask(
    "counterparty_trust",
    "J",
    Score(
        instructions=(
            "After this, how does the person chasing the bill rate this "
            "customer as a payer?"
        ),
        criteria=list(BELIEF_SLOTS["counterparty_trust"]),
    ),
)

_INTERACT = Ask(
    "interact",
    "P",
    Noul(
        instructions=(
            "Does this person stop and have a conversation with one of the "
            "people who are here?"
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


def where_words(ctx: DecisionContext) -> str:
    here = str(ctx.facts.get("here", ""))
    if ctx.facts.get("at_workplace"):
        return "at their own workplace"
    if here == ctx.facts.get("own_zone"):
        return "in the lobby of their own building, by the kitchenette"
    return f"in {PLACE_WORDS.get(here, here)}"


def _prepare_agent_tick(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    present = _present(ctx)
    offered = _offered(ctx)
    outage = ctx.facts.get("outage")

    minds: list[str] = []
    if outage:
        minds.append(
            "A piece of software the firm depends on has been down and it is "
            "disrupting the day."
        )
    strain = ctx.facts.get("employer_strain")
    if strain is not None and int(_number(strain)) >= 2:
        minds.append(belief_words("employer_strain", strain))
    state: dict[str, object] = {
        "person": f"a {role_words(ctx.role)} at {ORG_WORDS.get(org, 'a firm')}",
        "temperament": trait_words("sociability", ctx.traits.get("sociability")),
        "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
        "time": time_of_day_words(ctx.sim_time),
        "where": where_words(ctx),
        "on_their_mind": (
            " ".join(minds) if minds else "Nothing unusual; an ordinary working day."
        ),
    }
    asks: list[Ask] = [destination(ctx), _MOOD]
    if offered:
        state["who_is_here"] = roster_words(
            present, own_org=org, vendor=ctx.facts.get("vendor")
        )
        topics: dict[str, str] = {
            "work": "Their own work and clients.",
            "money": "Bills and invoices; who owes whom.",
            "small_talk": "The weather, the weekend, nothing in particular.",
        }
        if outage:
            topics = {"the_outage": "The software outage.", **topics}
        topics["other"] = "Something else."
        people: dict[str, str] = {
            slot(i): describe(p).capitalize() + "." for i, p in enumerate(offered)
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
    # The belief revisions ride at the end: the request is being made anyway,
    # and the questions that move the world keep their order (MEM-0003).
    if outage:
        asks.append(_RELIABILITY)
    if ctx.facts.get("strained"):
        asks.append(_STRAIN)
    return Prepared(ctx.kind, asks=tuple(asks), state=state)


def _interpret_agent_tick(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    next_zone, next_floor = resolve_destination(ctx, str(got["next_zone"].value))

    with_id: str | None = None
    if "interact" in got and got["interact"].value:
        picked = str(got["with_whom"].value)
        for index, person in enumerate(_offered(ctx)):
            if slot(index) == picked:
                with_id = str(person["id"])
    chosen: dict[str, object] = {
        "next_zone": next_zone,
        "next_floor": next_floor,
        "interact": with_id is not None,
        "with": with_id,
        "topic": str(got["topic"].value) if with_id and "topic" in got else None,
        "mood": int(str(got["mood"].value)),
        "raise_outage": bool(
            with_id and "raise_outage" in got and got["raise_outage"].value
        ),
    }
    for belief in ("vendor_reliability", "employer_strain"):
        if belief in got:
            chosen[belief] = int(str(got[belief].value))
    return Outcome(chosen, {})


def resolve_destination(ctx: DecisionContext, choice: str) -> tuple[str, int]:
    """A destination's key, as chosen, to the zone and floor it means. Both
    policies use this, so a place is a place whoever decided."""

    here = str(ctx.facts.get("here", ""))
    floor = int(_number(ctx.facts.get("floor")))
    own = str(ctx.facts.get("own_zone", here))
    own_floor = int(_number(ctx.facts.get("own_floor")))
    social = _social(ctx)
    vendor = ctx.facts.get("vendor")
    if choice == "own_workplace":
        return own, own_floor
    if choice == "lobby":
        return own, 0
    if choice == "plaza":
        return "plaza", 0
    if choice in social:
        return social[choice], 0
    if choice == "visit" and isinstance(vendor, str):
        return vendor, 0
    return here, floor


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
                "the person who runs payroll at a small firm, for its own staff"
                if ctx.facts.get("own_books")
                else "a payroll clerk at an accounting firm, running a client's payroll"
            ),
            "work_habit": trait_words("diligence", ctx.traits.get("diligence")),
            "timesheets": (
                "This week's timesheets are complete and approved."
                if ctx.facts.get("timesheets_available")
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
        asks=(_READINESS,),
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


def _interpret_close(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"readiness": int(str(got["readiness"].value))}, {})


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
            "funds": "There is comfortably enough in the account for it.",
        },
    )


def _interpret_catering(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    order = str(got["order"].value)
    return Outcome({"order": order if order in ("small", "large") else "none"}, {})


# -- supply.order, credit.draw, credit.approve: the archetype flows (WORLD-0010)

_STOCK_WORDS = (
    "The shelves are bare; there is nothing left to sell.",
    "Stock is low: a couple of days' worth at most.",
    "Stock is fine for the week.",
    "The store room is full.",
)


def stock_words(level: object) -> str:
    return _STOCK_WORDS[max(0, min(3, int(_number(level))))]


def debt_words(debt_cents: object, weekly_wages_cents: object) -> str:
    debt = _number(debt_cents)
    weekly = max(1.0, _number(weekly_wages_cents, 1.0))
    if debt <= 0:
        return "The firm has no debt."
    if debt < 2 * weekly:
        return "The firm already owes the bank a little."
    return "The firm already carries a heavy line of credit."


_SUPPLY = Ask(
    "order",
    "P",
    Choice(
        instructions=(
            "Does this person place an order with the supplier today, and how large?"
        ),
        criteria={
            "none": "No order this week; what is on the shelves will do.",
            "small": "A small order: a few days' worth.",
            "large": "A large order: more than a week's worth, to be safe.",
            "other": "Something else.",
        },
    ),
)


def _prepare_supply(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_SUPPLY,),
        state={
            "person": "the person who does the buying at "
            + ORG_WORDS.get(org, "a shop"),
            "temperament": trait_words("promptness", ctx.traits.get("promptness")),
            "stock": stock_words(ctx.facts.get("stock_level")),
            "cash": runway_words(ctx.facts.get("runway_days")),
            "prices": (
                "The supplier has just put its prices up."
                if ctx.facts.get("price_up")
                else "The supplier's prices are as usual."
            ),
        },
    )


def _interpret_supply(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    order = str(got["order"].value)
    return Outcome({"order": order if order in ("small", "large") else "none"}, {})


_DRAW = Ask(
    "draw",
    "P",
    Noul(
        instructions=(
            "With the firm's cash running short, does this person apply to the "
            "credit union for a line of credit today?"
        ),
        criteria=_yes_no(
            "They apply for a line of credit.",
            "They hold off and try to get by.",
        ),
    ),
)


def _prepare_draw(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    return Prepared(
        ctx.kind,
        asks=(_DRAW,),
        state={
            "person": "the person who pays the bills at "
            + ORG_WORDS.get(org, "a firm"),
            "temperament": trait_words(
                "risk_appetite", ctx.traits.get("risk_appetite")
            ),
            "cash": runway_words(ctx.facts.get("runway_days")),
            "debt": debt_words(
                ctx.facts.get("debt_cents"), ctx.facts.get("weekly_wages_cents")
            ),
        },
    )


def _interpret_draw(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"draw": bool(got["draw"].value)}, {})


_APPROVE = Ask(
    "approve",
    "J",
    Noul(
        instructions=(
            "Does the credit union approve this firm's application for a line "
            "of credit worth a month of its payroll?"
        ),
        criteria=_yes_no(
            "Approve the line: the firm is short of cash but sound.",
            "Decline: the firm is not paying its way; the line would not be repaid.",
        ),
    ),
)


def _prepare_approve(ctx: DecisionContext) -> Prepared:
    applicant = str(ctx.facts.get("applicant", ""))
    overdue = int(_number(ctx.facts.get("overdue_bills")))
    return Prepared(
        ctx.kind,
        asks=(_APPROVE,),
        state={
            "applicant": ORG_WORDS.get(applicant, "a local firm"),
            "cash": runway_words(ctx.facts.get("runway_days")),
            "bills": (
                "They pay their bills on time."
                if overdue == 0
                else f"They have {count_words(overdue, 'bill')} overdue."
            ),
            "payroll": (
                "They have held payroll in the last month."
                if ctx.facts.get("payroll_held")
                else "They have met every payroll."
            ),
            "debt": debt_words(
                ctx.facts.get("debt_cents"), ctx.facts.get("amount_cents")
            ),
        },
    )


def _interpret_approve(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"decision": "approve" if got["approve"].value else "decline"}, {})


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
        asks=(_CONFIRM, _RELIABILITY),
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
    chosen: dict[str, object] = {
        "confirm": confirm,
        "reason": "confirmed" if confirm else "silent",
    }
    if "vendor_reliability" in got:
        chosen["vendor_reliability"] = int(str(got["vendor_reliability"].value))
    return Outcome(chosen, {})


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
    trust = ctx.facts.get("trust_level")
    return Prepared(
        ctx.kind,
        asks=(_CHASE, _TRUST),
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
            "customer": (
                belief_words("counterparty_trust", trust)
                if trust is not None
                else "They have no history with this customer's payments."
            ),
        },
    )


def _interpret_chase(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    chosen: dict[str, object] = {"chase": bool(got["chase"].value)}
    if "counterparty_trust" in got:
        chosen["counterparty_trust"] = int(str(got["counterparty_trust"].value))
    return Outcome(chosen, {})


# -- subscription.switch: churn (MEM-0003) --------------------------------------

_SWITCH = Ask(
    "switch",
    "P",
    Noul(
        instructions=(
            "The month's bill for the software has come. Does this firm move "
            "to the competing product instead of renewing?"
        ),
        criteria=_yes_no(
            "They switch to the competitor this month.",
            "They renew where they are.",
        ),
    ),
)


def _prepare_switch(ctx: DecisionContext) -> Prepared:
    org = str(ctx.facts.get("org", ""))
    competitor = str(ctx.facts.get("competitor", ""))
    return Prepared(
        ctx.kind,
        asks=(_SWITCH,),
        state={
            "person": (
                "the person who pays the bills at " + ORG_WORDS.get(org, "a firm")
                if org
                else "a customer who pays for small-business software"
            ),
            "temperament": trait_words("promptness", ctx.traits.get("promptness")),
            "software": belief_words(
                "vendor_reliability", ctx.facts.get("reliability")
            ),
            "alternative": (
                f"{ORG_WORDS.get(competitor, 'another vendor').capitalize()} sells a "
                "comparable product at a similar price."
            ),
        },
    )


def _interpret_switch(
    ctx: DecisionContext, got: dict[str, Resolved], draw: Draw
) -> Outcome:
    return Outcome({"switch": bool(got["switch"].value)}, {})


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


def _mention(topic: str) -> Ask:
    return Ask(
        "mention",
        "P",
        Noul(
            instructions=(
                "Does this person tell the others "
                f"{TELLABLE_WORDS.get(topic, 'a piece of news they have heard')}?"
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
    present = _present(ctx)

    state: dict[str, object] = {
        "person": f"a {ctx.role.replace('_', ' ')} at {ORG_WORDS.get(org, 'a firm')}",
        "temperament": trait_words("sociability", ctx.traits.get("sociability")),
        "speaks_up": trait_words("vocality", ctx.traits.get("vocality")),
        "where": PLACE_WORDS.get(here, here),
        "time": time_of_day_words(ctx.sim_time),
        "who_is_here": {slot(i): describe(p) for i, p in enumerate(present)},
        "what_this_is_about": stake_words(ctx),
        "their_part_in_it": _ROLE_WORDS[role],
        "so_far": so_far_words(ctx),
        "mood_of_the_room": tension_words(ctx.facts.get("tension")),
    }
    asks: list[Ask] = [_act(role), _SETTLED, _MOOD]
    topic = ctx.facts.get("tellable_topic")
    if isinstance(topic, str) and topic:
        asks.append(_mention(topic))
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


QUESTION_SETS: dict[str, QuestionSet] = {
    s.kind: s
    for s in (
        QuestionSet("file.ticket", _prepare_file_ticket, _interpret_file_ticket),
        QuestionSet("ticket.triage", _prepare_triage, _interpret_triage),
        QuestionSet("ticket.answer", _prepare_answer, _interpret_answer),
        QuestionSet("payment.timing", _prepare_payment, _interpret_payment),
        QuestionSet("retail.purchase", _prepare_retail, _interpret_retail),
        QuestionSet("agent.tick", _prepare_agent_tick, _interpret_agent_tick),
        QuestionSet("credit.decision", _prepare_credit, _interpret_credit),
        QuestionSet("payroll.release", _prepare_payroll, _interpret_payroll),
        QuestionSet("close.signoff", _prepare_close, _interpret_close),
        QuestionSet("catering.order", _prepare_catering, _interpret_catering),
        QuestionSet("ticket.confirm", _prepare_confirm, _interpret_confirm),
        QuestionSet("chase.invoice", _prepare_chase, _interpret_chase),
        QuestionSet("supply.order", _prepare_supply, _interpret_supply),
        QuestionSet("credit.draw", _prepare_draw, _interpret_draw),
        QuestionSet("credit.approve", _prepare_approve, _interpret_approve),
        QuestionSet("subscription.switch", _prepare_switch, _interpret_switch),
        QuestionSet("episode.round", _prepare_episode_round, _interpret_episode_round),
    )
}
