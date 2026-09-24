"""Episodes: an encounter that gets more than one round (WORLD-0006).

`space.py` decides who is standing where and who stops to talk. This module
decides what a meeting *changes*, at two resolutions:

* the **one-shot encounter** — one question about the present moment, resolved
  once, which is what happens to everybody (WORLD-0003). It is also the cheap
  proxy, and `escalate` below is the whole of its consequence;
* the **episode** — a bounded, multi-round interaction among people who are
  together *and have something between them*, which is what happens when the
  stake is worth the extra calls.

An episode is only worth running if round two can do something round one could
not. That is the entire hypothesis, and it is why the design is shaped this way:

* **There must be a stake.** A broken module one of them can fix, an unpaid bill
  between their firms, or news one holds and another lacks. No stake and the
  one-shot encounter stands — this is the multiscale rule of thumb that you
  refine only where the coarse model has nothing to say.
* **Rounds are sequential; questions inside a round are not.** Jev answers the
  questions in one request independently, so a round is one request per
  participant and the ordering lives here. All of them read the state as it
  stood at the start of the round and their acts are folded in seat order —
  influences, then one reaction — so two people cannot both be the first to
  press.
* **Nothing is written until it closes.** Every effect on the world happens once,
  at the end, in `_close`. A round that changed the room's mood has changed
  nothing in the economy yet. This is what keeps an episode atomic to the tick
  that spawned it: it reads a frozen world and writes once.
* **It has to end.** A settled question, an empty room, or the round cap —
  whichever comes first. `exit_reason` says which, because "it ran out of
  rounds" and "they agreed" are different findings.

Three things fold back, and each was chosen because it reaches money by a path
the tests already follow:

* **press** shortens an outage, exactly as the one-shot encounter does;
* **mention** moves a fact, and someone who hears that the software they use is
  down notices it *now* instead of whenever their own draw said — so word of
  mouth reaches a ticket, and a ticket reaches billing;
* **promise** records a commitment, which raises the pressure on the promiser's
  next decision about that bill and is later kept or broken.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from jeve import db, memory
from jeve.core.clock import DAY, TICK, SimTime
from jeve.core.seed import derive_rng
from jeve.decide.gates import ASK_FROM_DAYS_BEFORE_DUE
from jeve.decide.policy import DecisionContext
from jeve.world import scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport
    from jeve.world.space import Agent

# What an escalation buys: the vendor drops everything, and the time left to
# fix is cut to a quarter — never to less than half an hour, and only once per
# incident however many people complain.
ESCALATION_KEEPS = 4
ESCALATION_FLOOR = 2 * TICK

MAX_PARTICIPANTS = 4
"""Two to four. Above that the state stops being small, which is the one thing
Jev is documented to degrade on, and a room that size is not one conversation."""

MAX_ROUNDS = 3
"""Smallville allows eight turns, Concordia twenty. Three is deliberately mean:
the evidence that extra rounds earn their cost is exactly what `ops/episodes.md`
is for, and a cap that binds shows up in `exit_reason` rather than hiding."""

MAX_DEPTH = 1
"""A side conversation may be carved out of an episode; nothing may be carved
out of the side conversation. Unbounded nesting is what the multi-resolution
literature calls chain disaggregation, and the schema holds this too."""

COOLDOWN = 8 * TICK
"""Two sim-hours before the same person is in another episode. Without it a
group that enjoys each other's company holds one conversation per tick for ever
— Smallville met this and answered it the same way, with a per-pair buffer."""

PER_DAY = 12
"""Episodes opened per sim-day, counting side conversations. A ceiling on the
extra calls, in the spirit of the budget governor: spend is a decision, not a
surprise."""

PROMISE_HORIZON = 2 * DAY
"""How long "by a definite day" means. A rule, not a draw: a promise whose
deadline was random would make the same promise a different obligation."""

type StakeKind = Literal["outage", "invoice", "news"]
type Role = Literal["holder", "asker", "bystander"]
type Exit = Literal["settled", "emptied", "rounds"]


@dataclass(frozen=True, slots=True)
class Stake:
    """What the people here have between them, and who can act on it.

    `holder` is the one person who could settle it — the vendor with the broken
    module, the clerk who pays the bill. `askers` want them to. Everyone else is
    in the room. An episode with no holder is still a real conversation; it just
    cannot produce a promise.
    """

    kind: StakeKind
    ref: str
    holder: str | None
    askers: frozenset[str]
    causes: tuple[int, ...] = ()
    module_id: str | None = None
    incident_id: int | None = None
    invoice_id: int | None = None
    days_late: int = 0
    large: bool = False

    def role_of(self, person_id: str) -> Role:
        if person_id == self.holder:
            return "holder"
        return "asker" if person_id in self.askers else "bystander"


@dataclass(frozen=True, slots=True)
class Seat:
    """A participant in speaking order. Drawn once when the episode opens."""

    agent: Agent
    seat: int


@dataclass(slots=True)
class Local:
    """The episode's own state — not a re-read of the world.

    Small on purpose: it is rendered into words for every request, and it is the
    only thing that makes round two differ from round one.
    """

    raised: bool = False
    pressed: bool = False
    promised_by: str | None = None
    refused: bool = False
    tension: int = 0
    left: set[str] = field(default_factory=set)
    told: dict[str, memory.Tellable] = field(default_factory=dict)
    asked_mention: set[str] = field(default_factory=set)
    moods: dict[str, int] = field(default_factory=dict)
    other_acts: int = 0
    """Mass that landed on `other`: the ontology-gap signal, per DECIDE-0001."""
    rounds: int = 0
    """How many rounds were actually run. The outcome used to carry the exit
    reason under this name, so "how long did it last" could not be read back
    (field report, defect 3)."""

    @property
    def promised(self) -> bool:
        return self.promised_by is not None


# -- what an outage is, and who can hear about it -------------------------------


def known_outage(engine: Engine, org: str, down: list[str]) -> str | None:
    """A broken module this person has reason to know about.

    The vendor's own staff know about anything that is down. Everyone else
    knows only about what their firm subscribes to.
    """

    if not down:
        return None
    if org == "tallybird":
        return down[0]
    rows = engine.conn.execute(
        "SELECT module_id FROM subscriptions WHERE org_id = %s AND active "
        "AND module_id = ANY(%s) ORDER BY module_id",
        (org, down),
    ).fetchall()
    return str(rows[0]["module_id"]) if rows else None


def open_incident(engine: Engine, down: list[str]) -> dict[str, Any] | None:
    if not down:
        return None
    row = engine.conn.execute(
        "SELECT id, module_id, cause_event_seq, escalated_sim FROM incidents "
        "WHERE ended_sim IS NULL AND module_id = ANY(%s) ORDER BY id LIMIT 1",
        (down,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "module": str(row["module_id"]),
        "cause": int(row["cause_event_seq"]) if row["cause_event_seq"] else None,
        "escalated": row["escalated_sim"] is not None,
    }


ENGINEERING_ROLES = frozenset({"founder", "eng_lead", "engineer", "sre"})
"""People who can act on an outage themselves. Anyone else at the vendor has to
pass a complaint on (WORLD-0012)."""


def escalate(
    engine: Engine,
    report: TickReport,
    *,
    raised_by: str,
    org_id: str,
    raised_with: str,
    zone: str,
    cause_seq: int | None,
    decision_id: int | None,
    decided_by: str,
    module: str | None = None,
    routed: bool = False,
) -> int | None:
    """A customer has cornered the vendor. The fix gets priority — if the
    complaint reaches somebody who can fix it.

    The one consequence a meeting has always had (WORLD-0003), reached now from
    either resolution: `cause_seq` is the encounter for a one-shot and the
    episode's closing event for an episode, so the cascade query walks through
    whichever ran.

    Whom it was raised with matters (WORLD-0012). The field report found
    escalation was social — it landed on whoever from the vendor happened to be
    in the cafe, and every one of them could shorten an outage on the spot. An
    engineer can; a support agent or the account manager decides whether to
    take it to the engineers (`escalation.handoff`), a quarter of an hour
    later, and may leave it in the queue instead.
    """

    if module is None:
        module = known_outage(
            engine,
            org_id,
            [
                str(r["id"])
                for r in engine.conn.execute(
                    "SELECT id FROM modules WHERE status = 'down' ORDER BY id"
                ).fetchall()
            ],
        )
    if module is None:
        return None
    if not routed:
        holder = engine.conn.execute(
            "SELECT role FROM persons WHERE id = %s", (raised_with,)
        ).fetchone()
        if holder is not None and str(holder["role"]) not in ENGINEERING_ROLES:
            engine.schedule(
                report.sim_time + TICK,
                "escalation.handoff",
                raised_with,
                {
                    "raised_by": raised_by,
                    "org_id": org_id,
                    "zone": zone,
                    "cause": cause_seq,
                    "module": module,
                },
            )
            return None
    incident = open_incident(engine, [module])
    if incident is None or incident["escalated"]:
        return None
    pending = engine.conn.execute(
        "SELECT id, due_sim_time FROM scheduled WHERE kind = 'incident.end' "
        "AND subject_id = %s ORDER BY id LIMIT 1",
        (module,),
    ).fetchone()
    if pending is None:
        return None

    due = int(pending["due_sim_time"])
    remaining = max(0, due - report.sim_time)
    keep = max(ESCALATION_FLOOR, remaining // ESCALATION_KEEPS)
    # Whole ticks: the scheduler only looks once a tick.
    new_due = min(due, report.sim_time + -(-keep // TICK) * TICK)

    seq = engine.emit(
        report,
        "ticket.escalated",
        actor_id=raised_by,
        org_id=org_id,
        decision_id=decision_id,
        causes=([cause_seq] if cause_seq else [])
        + ([incident["cause"]] if incident["cause"] else []),
        payload={
            "module_id": module,
            "incident_id": incident["id"],
            "raised_by": raised_by,
            "raised_with": raised_with,
            "zone": zone,
            "minutes_saved": (due - new_due) // 60,
            "decided_by": decided_by,
        },
    )
    engine.conn.execute(
        "UPDATE incidents SET escalated_sim = %s, escalation_event_seq = %s "
        "WHERE id = %s",
        (report.sim_time, seq, incident["id"]),
    )
    engine.conn.execute(
        "UPDATE scheduled SET due_sim_time = %s WHERE id = %s", (new_due, pending["id"])
    )
    # And every open ticket about it jumps the queue.
    engine.conn.execute(
        "UPDATE tickets SET severity = 3 WHERE module_id = %s "
        "AND status IN ('open','triaged')",
        (module,),
    )
    return seq


@scheduler.job("escalation.handoff")
def handoff(
    engine: Engine, report: TickReport, holder: str, payload: dict[str, Any]
) -> None:
    """Somebody at the vendor who cannot fix it was told about the outage."""

    person = engine.conn.execute(
        "SELECT id, role, traits, status FROM persons WHERE id = %s", (holder,)
    ).fetchone()
    module = str(payload.get("module") or "")
    if person is None or person["status"] == "left" or not module:
        return
    incident = open_incident(engine, [module])
    if incident is None or incident["escalated"]:
        return  # fixed, or already escalated, while it was being passed on
    backlog = engine.conn.execute(
        "SELECT count(*) AS n FROM tickets WHERE status IN ('open','triaged')"
    ).fetchone()
    made = engine.decide(
        report,
        DecisionContext(
            person_id=holder,
            role=str(person["role"]),
            sim_time=report.sim_time,
            kind="escalation.handoff",
            facts={
                "by_phone": payload.get("zone") == "phone",
                "backlog": int(backlog["n"]) if backlog else 0,
            },
            traits=dict(person["traits"] or {}),
        ),
    )
    cause = payload.get("cause")
    seq = engine.emit(
        report,
        "escalation.relayed" if made.chosen.get("relay") else "escalation.dropped",
        actor_id=holder,
        org_id="tallybird",
        causes=[int(cause)] if cause else [],
        decision_id=made.id,
        payload={
            "module_id": module,
            "raised_by": str(payload.get("raised_by", "")),
            "decided_by": made.source,
        },
    )
    if not made.chosen.get("relay"):
        return
    if payload.get("zone") == "phone":
        # A call passed on is a ticket with a priority, not a customer at the
        # engineers' elbow.
        prioritise(
            engine, report, module=module, actor_id=holder, cause=seq, route="phone"
        )
        return
    escalate(
        engine,
        report,
        raised_by=str(payload.get("raised_by", "")),
        org_id=str(payload.get("org_id", "")),
        raised_with=holder,
        zone=str(payload.get("zone", "")),
        cause_seq=seq,
        decision_id=made.id,
        decided_by=made.source,
        module=module,
        routed=True,
    )


PRIORITY_KEEPS = 2
"""A procedural escalation — support's own, or a customer's call passed on —
halves the time left, once per incident. Somebody pressed in person still
quarters what remains after it (`escalate`): a queue that works must not make
a conversation worthless, which is the claim space rests on (`test_space`)."""


def prioritise(
    engine: Engine,
    report: TickReport,
    *,
    module: str,
    actor_id: str,
    cause: int,
    route: str,
) -> int | None:
    incident = open_incident(engine, [module])
    if incident is None:
        return None
    done = engine.conn.execute(
        "SELECT 1 FROM events WHERE kind = 'incident.prioritised' "
        "AND (payload->>'incident_id')::bigint = %s LIMIT 1",
        (incident["id"],),
    ).fetchone()
    if done is not None:
        return None
    pending = engine.conn.execute(
        "SELECT id, due_sim_time FROM scheduled WHERE kind = 'incident.end' "
        "AND subject_id = %s ORDER BY id LIMIT 1",
        (module,),
    ).fetchone()
    if pending is None:
        return None
    due = int(pending["due_sim_time"])
    keep = max(ESCALATION_FLOOR, (due - report.sim_time) // PRIORITY_KEEPS)
    new_due = min(due, report.sim_time + -(-keep // TICK) * TICK)
    seq = engine.emit(
        report,
        "incident.prioritised",
        actor_id=actor_id,
        org_id="tallybird",
        causes=[cause] if cause else [],
        payload={
            "incident_id": incident["id"],
            "module_id": module,
            "route": route,
            "minutes_saved": (due - new_due) // 60,
        },
    )
    engine.conn.execute(
        "UPDATE scheduled SET due_sim_time = %s WHERE id = %s", (new_due, pending["id"])
    )
    return seq


# -- finding a stake ------------------------------------------------------------


def _outage_stake(engine: Engine, group: list[Agent], down: list[str]) -> Stake | None:
    """A module is down, someone here can work on it, and someone here is stuck."""

    vendor = next((a for a in group if a.org == "tallybird"), None)
    if vendor is None:
        return None
    # The vendor's staff know about every outage but are not stuck on any: one
    # of them pressing a colleague is not a customer cornering the vendor, and
    # the one-shot never let it happen (`test_space`).
    affected = {
        a.id: known_outage(engine, a.org, down) for a in group if a.org != "tallybird"
    }
    askers = frozenset(person for person, module in affected.items() if module)
    if not askers:
        return None
    module = next(affected[p] for p in sorted(askers))
    assert module is not None
    incident = open_incident(engine, [module])
    if incident is None:
        return None
    return Stake(
        kind="outage",
        ref=f"incident:{incident['id']}",
        holder=vendor.id,
        askers=askers,
        causes=(incident["cause"],) if incident["cause"] else (),
        module_id=module,
        incident_id=incident["id"],
    )


def _invoice_stake(engine: Engine, group: list[Agent], now: SimTime) -> Stake | None:
    """A live bill between two firms, with the person who pays it standing here.

    The payer has to be present. A promise to pay is only worth recording from
    somebody who can actually pay — anyone else's word is a message they might
    carry back, which is not an obligation and must not be scored as one.
    """

    orgs = sorted({a.org for a in group})
    if len(orgs) < 2:
        return None
    by_org: dict[str, list[str]] = {}
    for agent in group:
        by_org.setdefault(agent.org, []).append(agent.id)

    horizon = now.seconds + ASK_FROM_DAYS_BEFORE_DUE * DAY
    for creditor in orgs:
        for debtor in orgs:
            if creditor == debtor:
                continue
            payer = engine.payer_of(debtor)
            if payer is None or str(payer["id"]) not in by_org.get(debtor, []):
                continue
            bill = engine.conn.execute(
                "SELECT id, due_sim, amount_cents, issued_seq FROM invoices "
                "WHERE paid_sim IS NULL AND written_off_sim IS NULL "
                "AND from_org_id = %s AND to_org_id = %s AND due_sim <= %s "
                "ORDER BY due_sim, id LIMIT 1",
                (creditor, debtor, horizon),
            ).fetchone()
            if bill is None:
                continue
            return Stake(
                kind="invoice",
                ref=f"invoice:{int(bill['id'])}",
                holder=str(payer["id"]),
                askers=frozenset(by_org.get(creditor, [])),
                causes=((int(bill["issued_seq"]),) if bill["issued_seq"] else ()),
                invoice_id=int(bill["id"]),
                days_late=max(0, (now.seconds - int(bill["due_sim"])) // DAY),
                large=int(bill["amount_cents"]) >= 200_000,
            )
    return None


def _news_stake(engine: Engine, group: list[Agent]) -> Stake | None:
    """Somebody here knows something the others do not."""

    ids = [a.id for a in group]
    for agent in group:
        tellable = memory.most_tellable(
            engine.conn, agent.id, [i for i in ids if i != agent.id]
        )
        if tellable is not None:
            return Stake(
                kind="news",
                ref=tellable.fact.id,
                holder=None,
                askers=frozenset(),
            )
    return None


def _stake_for(
    engine: Engine, group: list[Agent], down: list[str], now: SimTime
) -> Stake | None:
    """The most consequential thing these people have between them.

    Ordered, not scored: an outage is the cascade the world exists to show, a
    bill is money, news is only news. A group with two of them holds the
    conversation about the first and may hold another about the second later.
    """

    return (
        _outage_stake(engine, group, down)
        or _invoice_stake(engine, group, now)
        or _news_stake(engine, group)
    )


def _restate(
    engine: Engine, stake: Stake, members: list[Agent], down: list[str], now: SimTime
) -> Stake:
    """The same stake, read again over everyone who ended up in the room.

    The stake is found from the two people who fell into conversation, because
    that is what decides whether there is an episode at all — but the roles have
    to be right for the whole group. Without this a colleague who joined a
    conversation about their own firm's unpaid bill was offered a bystander's
    acts, and could not press about the thing they were there for.

    Only the same stake is accepted back. A bigger room can make a *different*
    stake look better, and swapping it here would mean the group was assembled
    for one matter and then asked about another.
    """

    if stake.kind == "outage":
        restated = _outage_stake(engine, members, down)
    elif stake.kind == "invoice":
        restated = _invoice_stake(engine, members, now)
    else:
        restated = _news_stake(engine, members)
    return restated if restated is not None and restated.ref == stake.ref else stake


# -- gates ----------------------------------------------------------------------


def _recently_together(engine: Engine, ids: list[str], now: SimTime) -> bool:
    row = engine.conn.execute(
        "SELECT 1 FROM episode_participants p JOIN episodes e ON e.id = p.episode_id "
        "WHERE p.person_id = ANY(%s) AND (e.closed_sim IS NULL OR e.closed_sim > %s) "
        "LIMIT 1",
        (ids, now.seconds - COOLDOWN),
    ).fetchone()
    return row is not None


def _budget_left(engine: Engine, now: SimTime) -> bool:
    row = engine.conn.execute(
        "SELECT count(*) AS n FROM episodes WHERE opened_sim >= %s",
        (now.day * DAY,),
    ).fetchone()
    return row is not None and int(row["n"]) < PER_DAY


# -- the episode ----------------------------------------------------------------


def run(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    asked: list[Agent],
    made: list[Made],
    by_id: dict[str, Agent],
    down: list[str],
    *,
    present: list[Agent] | None = None,
) -> set[frozenset[str]]:
    """Open and run every episode this tick. Returns the pairs it consumed.

    `asked` and `made` are the people at a decision point and what they chose
    (WORLD-0009); `present` is everyone about, who may join a conversation they
    did not start. Everyone present was asked, before WORLD-0009, and still is
    when `present` is not given.

    A pair that became an episode must not also be recorded as a one-shot
    encounter: the same meeting resolved twice would double-count its effects,
    which is the oldest trap in multi-resolution modelling. The caller seeds its
    own dedupe set with what comes back.
    """

    consumed: set[frozenset[str]] = set()
    for agent, decision in zip(asked, made, strict=True):
        other_id = decision.chosen.get("with")
        if not decision.chosen.get("interact") or not isinstance(other_id, str):
            continue
        other = by_id.get(other_id)
        if other is None or other.zone is not agent.zone:
            continue
        pair = frozenset({agent.id, other_id})
        if pair in consumed:
            continue
        if not _budget_left(engine, now):
            break
        group = _grow(engine, present or asked, agent, other, down, now)
        if group is None:
            continue
        stake, members = group
        ids = [a.id for a in members]
        if _recently_together(engine, ids, now):
            continue
        _hold(
            engine,
            report,
            now,
            stake,
            members,
            present or asked,
            parent_id=None,
            depth=0,
        )
        # Every pair inside the episode is now accounted for, not only the two
        # whose decision opened it.
        for first in ids:
            for second in ids:
                if first < second:
                    consumed.add(frozenset({first, second}))
        report.in_episode.update(ids)
    return consumed


def _grow(
    engine: Engine,
    present: list[Agent],
    first: Agent,
    second: Agent,
    down: list[str],
    now: SimTime,
) -> tuple[Stake, list[Agent]] | None:
    """The two who fell into conversation, their stake, and who else joins.

    Others in the same zone join when the stake is theirs too — the vendor's
    colleague, another firm the outage is hurting, someone who has not heard the
    news. Ordered by id and capped, so the group is a function of the world.
    """

    stake = _stake_for(engine, [first, second], down, now)
    if stake is None:
        return None

    members = [first, second]
    holders = (
        frozenset(memory.holders_of(engine.conn, stake.ref))
        if stake.kind == "news"
        else frozenset()
    )
    for candidate in sorted(present, key=lambda a: a.id):
        if len(members) >= MAX_PARTICIPANTS:
            break
        if candidate.id in (first.id, second.id) or candidate.zone is not first.zone:
            continue
        # Colleagues at their own desks are not in a conversation (WORLD-0003).
        if candidate.zone is candidate.own_zone and candidate.org in (
            first.org,
            second.org,
        ):
            continue
        if _joins(engine, stake, candidate, down, holders):
            members.append(candidate)
    return _restate(engine, stake, members, down, now), members


def _joins(
    engine: Engine,
    stake: Stake,
    candidate: Agent,
    down: list[str],
    holders: frozenset[str],
) -> bool:
    """Is this stake theirs too?

    `holders` is who already knows the news, read once by the caller: asking per
    candidate would be a query per person in the room, inside a tick that is
    holding a transaction open.
    """

    if stake.kind == "outage":
        return candidate.org == "tallybird" or bool(
            known_outage(engine, candidate.org, down)
        )
    if stake.kind == "invoice":
        return candidate.id in stake.askers or candidate.id == stake.holder
    # News travels to whoever has not heard it.
    return candidate.id not in holders


def _hold(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    stake: Stake,
    members: list[Agent],
    present: list[Agent],
    *,
    parent_id: int | None,
    depth: int,
) -> int:
    """Open an episode, run its rounds, close it. Returns its id."""

    seats = _seats(engine, now, stake, members)
    episode_id = _open(engine, report, stake, seats, parent_id=parent_id, depth=depth)
    local = Local()
    exit_reason = _rounds(engine, report, episode_id, stake, seats, local)
    _close(engine, report, now, episode_id, stake, seats, local, exit_reason)
    if depth < MAX_DEPTH:
        _carry_the_news(engine, report, now, seats, present, local, episode_id)
    return episode_id


def _seats(
    engine: Engine, now: SimTime, stake: Stake, members: list[Agent]
) -> list[Seat]:
    """Speaking order, drawn once for this group at this moment.

    Shuffled rather than sorted: person ids begin with their firm, so seating by
    id would have let the same firm speak first in every conversation for ever.
    CORE-0009 — the draw is about who these people are and when they met, and
    the tick count appears nowhere in it.
    """

    order = sorted(members, key=lambda a: a.id)
    rng = derive_rng(
        engine.root_seed,
        "episode",
        stake.kind,
        stake.ref,
        *[a.id for a in order],
        now.seconds,
    )
    rng.shuffle(order)
    return [Seat(agent=agent, seat=index) for index, agent in enumerate(order)]


def _open(
    engine: Engine,
    report: TickReport,
    stake: Stake,
    seats: list[Seat],
    *,
    parent_id: int | None,
    depth: int,
) -> int:
    zone = seats[0].agent.zone
    # The id is drawn before the event so the event can carry it. Events are
    # append-only (CORE-0007); writing one and then patching its payload would
    # be a second way for the log to become true, and there is only ever one.
    drawn = engine.conn.execute("SELECT nextval('episodes_id_seq') AS id").fetchone()
    assert drawn is not None
    episode_id = int(drawn["id"])

    seq = engine.emit(
        report,
        "episode.opened",
        actor_id=seats[0].agent.id,
        org_id=seats[0].agent.org,
        causes=list(stake.causes),
        payload={
            "episode_id": episode_id,
            "stake": stake.kind,
            "stake_ref": stake.ref,
            "zone": zone.value,
            "participants": [seat.agent.id for seat in seats],
            "depth": depth,
            "parent_id": parent_id,
        },
    )
    engine.conn.execute(
        "INSERT INTO episodes (id, zone, parent_id, depth, stake, stake_ref, "
        "opened_sim, opened_seq) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            episode_id,
            zone.value,
            parent_id,
            depth,
            stake.kind,
            stake.ref,
            report.sim_time,
            seq,
        ),
    )
    db.executemany(
        engine.conn,
        "INSERT INTO episode_participants (episode_id, person_id, seat) "
        "VALUES (%s,%s,%s)",
        [(episode_id, seat.agent.id, seat.seat) for seat in seats],
    )
    return episode_id


def _rounds(
    engine: Engine,
    report: TickReport,
    episode_id: int,
    stake: Stake,
    seats: list[Seat],
    local: Local,
) -> Exit:
    """Ask, fold, repeat. The only place sequence exists in this simulation."""

    for index in range(MAX_ROUNDS):
        standing = [seat for seat in seats if seat.agent.id not in local.left]
        if len(standing) < 2:
            return "emptied"

        tellable = _tellable_for(engine, standing, local)
        contexts = [
            _context(engine, report, stake, seat, standing, local, tellable)
            for seat in standing
        ]
        made = engine.decide_many(report, contexts)
        local.rounds = index + 1
        settled = _fold(
            engine, report, episode_id, index, stake, standing, made, local, tellable
        )
        if settled:
            return "settled"
    return "rounds"


def _tellable_for(
    engine: Engine, standing: list[Seat], local: Local
) -> dict[str, memory.Tellable]:
    """The one piece of news each speaker could pass on, for those not yet asked.

    Asked once per speaker per episode. Telling cannot be untold, so re-asking
    each round would thin one propensity into near-certainty — the hazard-rate
    trap of DECIDE-0001, inside an episode rather than across a day.
    """

    listeners = [seat.agent.id for seat in standing]
    found: dict[str, memory.Tellable] = {}
    for seat in standing:
        if seat.agent.id in local.asked_mention:
            continue
        others = [i for i in listeners if i != seat.agent.id]
        tellable = memory.most_tellable(engine.conn, seat.agent.id, others)
        if tellable is not None:
            found[seat.agent.id] = tellable
    return found


def _context(
    engine: Engine,
    report: TickReport,
    stake: Stake,
    seat: Seat,
    standing: list[Seat],
    local: Local,
    tellable: dict[str, memory.Tellable],
) -> DecisionContext:
    agent = seat.agent
    role = stake.role_of(agent.id)
    news = tellable.get(agent.id)
    return DecisionContext(
        person_id=agent.id,
        role=agent.role,
        sim_time=report.sim_time,
        kind="episode.round",
        facts={
            "org": agent.org,
            "here": agent.zone.value,
            "stake": stake.kind,
            "module": stake.module_id,
            "days_late": stake.days_late,
            "large": stake.large,
            "role_in_stake": role,
            "present": [
                {"id": other.agent.id, "org": other.agent.org, "role": other.agent.role}
                for other in standing
                if other.agent.id != agent.id
            ],
            "raised": local.raised,
            "pressed": local.pressed,
            "promised": local.promised,
            "refused": local.refused,
            "tension": local.tension,
            "tellable_topic": news.fact.topic if news else None,
        },
        traits=agent.traits,
    )


def _fold(
    engine: Engine,
    report: TickReport,
    episode_id: int,
    index: int,
    stake: Stake,
    standing: list[Seat],
    made: list[Made],
    local: Local,
    tellable: dict[str, memory.Tellable],
) -> bool:
    """Apply a round's acts in seat order, and say whether it settled.

    Everyone decided from the state as it stood at the start of the round, and
    their acts are combined once here. Two people cannot therefore both be the
    first to press, and nobody's decision depended on somebody else's within the
    round — which is exactly what Jev's independent questions can support.
    """

    acts: list[dict[str, object]] = []
    # Keyed by person, never positional: `standing` is in load order and the
    # fold walks seat order, so a list of votes would have been read back
    # against the wrong people the moment the two disagreed.
    settled_votes: dict[str, bool] = {}
    for seat, decision in sorted(
        zip(standing, made, strict=True), key=lambda pair: pair[0].seat
    ):
        person = seat.agent.id
        act = str(decision.chosen.get("act", "other"))
        local.moods[person] = int(decision.chosen.get("mood", 2))
        settled_votes[person] = bool(decision.chosen.get("settled"))
        acts.append({"person_id": person, "act": act, "seat": seat.seat})

        if person in tellable:
            local.asked_mention.add(person)
            if decision.chosen.get("mention"):
                local.told[person] = tellable[person]

        if act == "leave":
            local.left.add(person)
        elif act == "press":
            local.pressed = True
            local.raised = True
        elif act == "promise":
            local.promised_by = person
            local.raised = True
        elif act == "decline":
            local.refused = True
            local.raised = True
            local.tension = min(3, local.tension + 1)
        elif act in ("explain", "ask"):
            local.raised = True
        elif act == "small_talk":
            local.tension = max(0, local.tension - 1)
        elif act == "other":
            local.other_acts += 1

    engine.emit(
        report,
        "episode.round",
        actor_id=standing[0].agent.id,
        org_id=standing[0].agent.org,
        decision_id=made[0].id,
        payload={
            "episode_id": episode_id,
            "round": index,
            "stake": stake.kind,
            "acts": acts,
            "left": sorted(local.left),
            "tension": local.tension,
            "decided_by": made[0].source,
        },
    )
    engine.conn.execute(
        "UPDATE episodes SET rounds = %s WHERE id = %s", (index + 1, episode_id)
    )
    for person in local.left:
        engine.conn.execute(
            "UPDATE episode_participants SET left_round = %s WHERE episode_id = %s "
            "AND person_id = %s AND left_round IS NULL",
            (index, episode_id, person),
        )
    # Everyone still in the room has to think it is done. One person walking
    # away satisfied is not agreement.
    remaining = [
        vote
        for person, vote in sorted(settled_votes.items())
        if person not in local.left
    ]
    return bool(remaining) and all(remaining)


def _close(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    episode_id: int,
    stake: Stake,
    seats: list[Seat],
    local: Local,
    exit_reason: Exit,
) -> None:
    """One reaction phase: everything the episode changed, written once.

    Ordered deliberately. The closing event is emitted first so that every
    effect can cite it, which is what lets a reader walk from a conversation to
    an invoice by following `causes` — the same query that already walks a
    one-shot encounter.
    """

    by_id = {seat.agent.id: seat.agent for seat in seats}
    outcome: dict[str, Any] = {
        "stake": stake.kind,
        "stake_ref": stake.ref,
        "rounds": local.rounds,
        "pressed": local.pressed,
        "promised": local.promised,
        "refused": local.refused,
        "tension": local.tension,
        "facts_passed": sum(len(t.missing) for t in local.told.values()),
        "left": sorted(local.left),
        "ontology_gaps": local.other_acts,
    }
    closed_seq = engine.emit(
        report,
        "episode.closed",
        actor_id=seats[0].agent.id,
        org_id=seats[0].agent.org,
        causes=list(stake.causes),
        payload={
            "episode_id": episode_id,
            "zone": seats[0].agent.zone.value,
            "participants": [seat.agent.id for seat in seats],
            "exit_reason": exit_reason,
            **outcome,
        },
    )

    for person, mood in sorted(local.moods.items()):
        engine.conn.execute(
            "UPDATE positions SET mood = %s WHERE person_id = %s", (mood, person)
        )

    for teller in sorted(local.told):
        _pass_on(engine, report, now, local.told[teller], teller, closed_seq)

    # Pressed, or promised: the vendor giving their word to look at it now is
    # the same thing happening as being pushed into it, and an episode where
    # the holder volunteered would otherwise be worth strictly less than one
    # where they were bullied.
    if (local.pressed or local.promised) and stake.kind == "outage":
        asker = next(
            (seat.agent for seat in seats if seat.agent.id in stake.askers), None
        )
        if asker is not None and stake.holder is not None:
            escalate(
                engine,
                report,
                raised_by=asker.id,
                org_id=asker.org,
                raised_with=stake.holder,
                zone=asker.zone.value,
                cause_seq=closed_seq,
                decision_id=None,
                decided_by="episode",
            )

    if local.promised and stake.kind == "invoice" and stake.invoice_id is not None:
        promiser = local.promised_by
        assert promiser is not None
        creditor = next(
            (seat.agent.id for seat in seats if seat.agent.id in stake.askers),
            None,
        )
        if creditor is not None:
            due = report.sim_time + PROMISE_HORIZON
            commitment = memory.promise(
                engine.conn,
                episode_id=episode_id,
                from_person_id=promiser,
                to_person_id=creditor,
                invoice_id=stake.invoice_id,
                sim_time=report.sim_time,
                seq=closed_seq,
                due_sim=due,
            )
            engine.emit(
                report,
                "promise.made",
                actor_id=promiser,
                org_id=by_id[promiser].org,
                causes=[closed_seq],
                payload={
                    "commitment_id": commitment,
                    "episode_id": episode_id,
                    "invoice_id": stake.invoice_id,
                    "to": creditor,
                    "due_sim": due,
                },
            )
            engine.schedule(
                due, "commitment.due", str(commitment), {"invoice": stake.invoice_id}
            )

    engine.conn.execute(
        "UPDATE episodes SET closed_sim = %s, closed_seq = %s, exit_reason = %s, "
        "outcome = %s WHERE id = %s",
        (report.sim_time, closed_seq, exit_reason, json.dumps(outcome), episode_id),
    )


def _pass_on(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    tellable: memory.Tellable,
    teller: str,
    closed_seq: int,
) -> None:
    """One person told others something. Write down who now knows it.

    And, when it is an outage: somebody who has just been told that the software
    they use is down *knows now*, rather than whenever their own draw was going
    to tell them. That is the whole of word of mouth reaching the economy — an
    earlier notice is an earlier ticket, and an earlier ticket is an earlier fix.
    """

    learned: list[str] = []
    for listener in tellable.missing:
        if memory.learn(
            engine.conn,
            listener,
            tellable.fact.id,
            sim_time=report.sim_time,
            seq=closed_seq,
            from_person_id=teller,
            hops=tellable.hops + 1,
        ):
            learned.append(listener)
    if not learned:
        return

    engine.emit(
        report,
        "fact.passed",
        actor_id=teller,
        causes=[closed_seq],
        payload={
            "fact_id": tellable.fact.id,
            "topic": tellable.fact.topic,
            "from": teller,
            "to": learned,
            "hops": tellable.hops + 1,
        },
    )
    if tellable.fact.topic == "outage" and tellable.fact.incident_id is not None:
        _hear_of_outage(engine, report, tellable, learned, closed_seq)


def _hear_of_outage(
    engine: Engine,
    report: TickReport,
    tellable: memory.Tellable,
    learned: list[str],
    closed_seq: int,
) -> None:
    incident_id = tellable.fact.incident_id
    module = tellable.fact.about_module_id
    assert incident_id is not None and module is not None
    # Only somebody whose firm uses the broken module has been told anything
    # that matters to their day. Hearing that a feature you do not use is down
    # is not news you would raise a ticket about.
    subscribed = engine.conn.execute(
        "SELECT p.id FROM persons p JOIN subscriptions s ON s.org_id = p.org_id "
        "WHERE p.id = ANY(%s) AND s.module_id = %s AND s.active ORDER BY p.id",
        (learned, module),
    ).fetchall()
    for row in subscribed:
        person = str(row["id"])
        # One upsert, two cases, and both of them are word of mouth working:
        # somebody who had no notice at all now has one, and somebody whose own
        # draw was going to tell them this afternoon knows now instead. Written
        # as an insert and a separate update it reported only the second, which
        # is why a run could pass 84 people an outage and emit nothing.
        heard = engine.conn.execute(
            "INSERT INTO outage_notices (incident_id, person_id, notice_sim) "
            "VALUES (%s,%s,%s) ON CONFLICT (incident_id, person_id) "
            "DO UPDATE SET notice_sim = EXCLUDED.notice_sim "
            "WHERE outage_notices.ticket_id IS NULL "
            "AND outage_notices.notice_sim > EXCLUDED.notice_sim "
            "RETURNING person_id",
            (incident_id, person, report.sim_time),
        ).fetchone()
        if heard is None:
            continue
        engine.emit(
            report,
            "outage.heard",
            actor_id=person,
            causes=[closed_seq],
            payload={
                "incident_id": incident_id,
                "module_id": module,
                "person_id": person,
                "fact_id": tellable.fact.id,
            },
        )


def _carry_the_news(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    seats: list[Seat],
    present: list[Agent],
    local: Local,
    parent_id: int,
) -> None:
    """Somebody who has just heard something turns to the rest of the room.

    This is the one recursion the world actually motivates, and the reason it
    exists is the group cap: a conversation seats four, so in a busy cafe the
    people at the next table have not heard. Rather than broadcasting to the
    zone — which would make the cap meaningless and diffusion instantaneous —
    news ripples outward in a second, smaller conversation, one level deep.

    A side conversation is an episode and nothing else: same rounds, same gates,
    same fold-back, `depth = 1` and no children of its own.
    """

    if not local.told or not _budget_left(engine, now):
        return

    inside = {seat.agent.id for seat in seats}
    for teller in sorted(local.told):
        passed = local.told[teller]
        # Somebody in this episode who has just learned it, and can pass it on.
        carrier = next(
            (
                seat.agent
                for seat in sorted(seats, key=lambda s: s.agent.id)
                if seat.agent.id in passed.missing and seat.agent.id not in local.left
            ),
            None,
        )
        if carrier is None:
            continue
        # Who holds it, in one query rather than one per candidate: this runs
        # inside a tick that is holding a transaction open.
        holders = frozenset(memory.holders_of(engine.conn, passed.fact.id))
        outsiders = [
            agent
            for agent in sorted(present, key=lambda a: a.id)
            if agent.id not in inside
            and agent.zone is carrier.zone
            and agent.id not in holders
        ]
        if not outsiders:
            continue
        members = [carrier, *outsiders][:MAX_PARTICIPANTS]
        child = Stake(kind="news", ref=passed.fact.id, holder=None, askers=frozenset())
        _hold(
            engine,
            report,
            now,
            child,
            members,
            present,
            parent_id=parent_id,
            depth=1,
        )
        report.in_episode.update(agent.id for agent in members)
        return


# -- a promise falls due --------------------------------------------------------


@scheduler.job("commitment.due")
def commitment_due(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """The day someone said they would pay by. Score the promise either way.

    A promise nobody ever scores is decoration. Paying settles it as kept where
    the money moves; this is the other half, and without it a broken promise
    would look exactly like one that was never made.
    """

    invoice_id = int(payload.get("invoice", 0))
    if not invoice_id:
        return
    row = engine.conn.execute(
        "SELECT paid_sim FROM invoices WHERE id = %s", (invoice_id,)
    ).fetchone()
    if row is None or row["paid_sim"] is not None:
        return
    open_promise = memory.open_commitment(engine.conn, invoice_id)
    if open_promise is None:
        return
    settled = memory.close_commitments_for(
        engine.conn, invoice_id, sim_time=report.sim_time, kept=False
    )
    if not settled:
        return
    engine.emit(
        report,
        "promise.broken",
        actor_id=open_promise.from_person_id,
        causes=[],
        payload={
            "commitment_id": open_promise.id,
            "invoice_id": invoice_id,
            "to": open_promise.to_person_id,
            "days_promised": (report.sim_time - open_promise.made_sim) // DAY,
        },
    )
