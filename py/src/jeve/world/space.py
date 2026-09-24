"""Space, and why it matters (WORLD-0003).

Staff have positions. Somebody at a decision point decides where to go next and
whether to stop and talk to someone who is in the same place. Two people in the
same zone is an *encounter*, and an encounter is the only way some things can
happen: a lawyer whose invoicing is down can press the vendor to fix it only if
she and someone from the vendor are standing in the same room.

That is what makes space load-bearing rather than decorative. An escalation
pulls the end of the outage forward, which moves when blocked invoices go out,
which moves when they are paid. Switch encounters off and the billing timeline
is different; `tests/test_space.py` asserts exactly that.

Order within a tick, and why: everyone decides from where they are *now*;
encounters resolve among the people co-located now; then everyone moves. Jev
answers the questions in one request independently, so "where next" cannot
depend on "whom did I talk to" — and asking both about the present moment is
what keeps it to one call per person per decision point.

**Not everyone is asked every tick** (WORLD-0009). The field report counted
5,331 `agent.tick` answers per office worker and 8,783 per member of cafe staff,
most of them somebody alone at their own desk being asked again whether they
would like to stay there. DECIDE-0001 already said an agent is evaluated at a
decision point; this is where that is enforced. See `decision_point`.

What a meeting *changes* lives in `episodes.py`, at either resolution: the
one-shot encounter below calls `episodes.escalate` for its single consequence,
and a meeting with a real stake becomes a multi-round episode instead. This
module is about where people are and who stops to talk; that one is about what
comes of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jeve.core.clock import DAY, HOUR, TICK, SimTime
from jeve.core.orgs import shift_for
from jeve.core.seed import derive_seed
from jeve.decide.policy import DecisionContext
from jeve.world import episodes, shocks
from jeve.world.map import ORG_ZONE, Tile, Zone, entry_for, find_path, spot_for

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport

LUNCH_START = 12 * HOUR
LUNCH_END = 14 * HOUR
"""Lunch is a window in which every quarter hour is a decision point: whether to
go for lunch *now* is the one choice a desk worker makes on the quarter hour,
and the lunch curve (3% of office staff in the cafe mid-morning, 31% at noon in
the field report) is what the wake policy must not flatten."""

SWAMPED_AT = 20
"""Open tickets beyond which the software company's staff have the queue on
their minds. The same line `backlog_words` draws for "deep"."""


@dataclass(frozen=True, slots=True)
class Agent:
    id: str
    org: str
    role: str
    traits: dict[str, object]
    zone: Zone
    tile: Tile | None
    index: int
    """Position among their own org's staff: which seat is theirs."""
    role_index: int = 0
    """Position among their own org's staff in the same role: which shift."""
    mind: str = ""
    """What was on their mind the last time they were asked (WORLD-0009)."""

    @property
    def own_zone(self) -> Zone:
        return ORG_ZONE[self.org]


def on_shift(
    agent: Agent,
    when: SimTime,
    *,
    absent: frozenset[str] = frozenset(),
    extra: frozenset[str] = frozenset(),
) -> bool:
    """Whether this person is due at work now. Roles keep hours (field report
    defect 5): the cafe's weekend part-timer used to work six days a week,
    because hours belonged to the firm and not to the job. And the rota can
    override them (WORLD-0011): somebody off sick stays home, somebody covering
    works their firm's open hours."""

    if agent.id in absent:
        return False
    if agent.id in extra:
        return when.cafe_open if agent.org == "thirdrail" else when.in_office_hours
    return shift_for(agent.org, agent.role, agent.role_index).covers(
        when.weekday, when.time_of_day
    )


def load_agents(engine: Engine) -> list[Agent]:
    """Everyone still employed, with their seat and their shift.

    Seats are counted over everyone who ever held one, so somebody leaving does
    not move the rest of the office down a desk.
    """

    rows = engine.conn.execute(
        "SELECT p.id, p.org_id, p.role, p.traits, p.status, s.zone, s.x, s.y, "
        "s.mind FROM persons p JOIN positions s ON s.person_id = p.id "
        "WHERE p.kind = 'staff' ORDER BY p.id"
    ).fetchall()
    seen: dict[str, int] = {}
    seen_role: dict[tuple[str, str], int] = {}
    agents: list[Agent] = []
    for row in rows:
        org = str(row["org_id"])
        role = str(row["role"])
        index = seen.get(org, 0)
        seen[org] = index + 1
        role_index = seen_role.get((org, role), 0)
        seen_role[(org, role)] = role_index + 1
        if row["status"] == "left":
            continue
        tile = (int(row["x"]), int(row["y"])) if row["x"] is not None else None
        agents.append(
            Agent(
                id=str(row["id"]),
                org=org,
                role=role,
                traits=dict(row["traits"] or {}),
                zone=Zone(str(row["zone"])),
                tile=tile,
                index=index,
                role_index=role_index,
                mind=str(row["mind"] or ""),
            )
        )
    return agents


def _place(
    engine: Engine,
    report: TickReport,
    agent: Agent,
    zone: Zone,
    taken: set[Tile],
    *,
    decision_id: int | None = None,
) -> None:
    """Move someone to a zone, walking there, and say so if the zone changed."""

    if zone is Zone.HOME:
        if agent.tile is None:
            return
        path = find_path(agent.tile, entry_for(agent.tile))
        target: Tile | None = None
    else:
        # CORE-0009: about this person arriving here now, not about the tick count.
        salt = derive_seed(
            engine.root_seed, "spot", agent.id, zone.value, report.sim_time
        )
        target = spot_for(
            zone,
            org_zone=agent.own_zone,
            staff_index=agent.index,
            taken=taken,
            salt=salt % 997,
        )
        taken.add(target)
        start = agent.tile if agent.tile is not None else entry_for(target)
        path = find_path(start, target)

    engine.conn.execute(
        "UPDATE positions SET zone = %s, x = %s, y = %s, path = %s, moved_tick = %s "
        "WHERE person_id = %s",
        (
            zone.value,
            target[0] if target else None,
            target[1] if target else None,
            json.dumps([list(step) for step in path]),
            report.tick_seq,
            agent.id,
        ),
    )
    if zone is not agent.zone:
        # Only zone changes are events. A step across a room is a frame, not
        # something that happened in the economy, and one per person per tick
        # would bury everything else in the log.
        engine.emit(
            report,
            "agent.moved",
            actor_id=agent.id,
            org_id=agent.org,
            decision_id=decision_id,
            payload={
                "person_id": agent.id,
                "from_zone": agent.zone.value,
                "to_zone": zone.value,
                "steps": max(0, len(path) - 1),
                # The tiles walked. A client animates exactly this, live or
                # replayed from the log, so there is one mechanism for both.
                "path": [list(step) for step in path],
            },
        )


def send(
    engine: Engine,
    report: TickReport,
    *,
    org: str,
    to: Zone,
    prefer: tuple[str, ...] = (),
) -> str | None:
    """Send someone from a firm on an errand. Returns who went, if anyone could.

    An errand is a rule, not a choice: the lunch has to get there. Whoever is at
    their own workplace right now can go, in order of `prefer` — and one person
    cannot carry two lunches to two offices in the same fifteen minutes, so a
    second errand in the same tick goes to somebody else. What the runner does
    once they have arrived is theirs to decide on the next `agent.tick`.
    """

    agents = load_agents(engine)
    rank = {role: index for index, role in enumerate(prefer)}
    free = sorted(
        (a for a in agents if a.org == org and a.zone is a.own_zone),
        key=lambda a: (rank.get(a.role, len(rank)), a.id),
    )
    if not free or to is free[0].own_zone:
        return None
    runner = free[0]
    taken: set[Tile] = {a.tile for a in agents if a.tile is not None}
    if runner.tile is not None:
        taken.discard(runner.tile)
    _place(engine, report, runner, to, taken)
    return runner.id


# -- what is on somebody's mind ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Situation:
    """The firm-level facts a person could have on their mind, read once a tick.

    The field report found agents could not perceive money: `on_their_mind`
    took four values and all four were about the outage. Unpaid wages, a firm
    that is short, a broken promise and a lost customer were all in the world
    and none of them reached anybody's mood.
    """

    unpaid: frozenset[str] = frozenset()
    """Firms whose payroll is being held."""
    paid_today: frozenset[str] = frozenset()
    short: frozenset[str] = frozenset()
    """Firms that warned of insolvency in the last week."""
    let_down: frozenset[str] = frozenset()
    """Firms somebody broke a promise to in the last three days."""
    lost_customer: frozenset[str] = frozenset()
    """Firms that lost a customer in the last week."""
    swamped: bool = False
    """The support queue is deep."""
    rough: frozenset[str] = frozenset()
    """Firms for which three or more things have gone wrong in five days."""
    colleague_left: frozenset[str] = frozenset()
    """Firms somebody quit in the last three days."""


def situation(engine: Engine, now: SimTime) -> Situation:
    def orgs(query: str, *params: object) -> frozenset[str]:
        return frozenset(
            str(row["org"])
            for row in engine.conn.execute(query, params).fetchall()
            if row["org"]
        )

    unpaid = orgs(
        "SELECT DISTINCT subject_id AS org FROM scheduled "
        "WHERE kind = 'payroll.run' AND payload ? 'held'"
    )
    paid_today = orgs(
        "SELECT DISTINCT org_id AS org FROM events WHERE kind = 'payroll.paid' "
        "AND sim_time >= %s",
        now.day * DAY,
    )
    short = orgs(
        "SELECT DISTINCT org_id AS org FROM events WHERE kind = 'insolvency.warning' "
        "AND sim_time >= %s",
        now.seconds - 7 * DAY,
    )
    let_down = orgs(
        "SELECT DISTINCT p.org_id AS org FROM events e JOIN persons p "
        "ON p.id = e.payload->>'to' WHERE e.kind = 'promise.broken' "
        "AND e.sim_time >= %s",
        now.seconds - 3 * DAY,
    )
    lost = orgs(
        "SELECT DISTINCT org_id AS org FROM events "
        "WHERE kind = 'subscription.cancelled' AND sim_time >= %s",
        now.seconds - 7 * DAY,
    )
    left = orgs(
        "SELECT DISTINCT org_id AS org FROM events WHERE kind = 'staff.left' "
        "AND sim_time >= %s",
        now.seconds - 3 * DAY,
    )
    backlog = engine.conn.execute(
        "SELECT count(*) AS n FROM tickets WHERE status IN ('open','triaged')"
    ).fetchone()
    rough = orgs(
        "SELECT org_id AS org FROM events WHERE sim_time >= %s AND kind = ANY(%s) "
        "GROUP BY org_id HAVING count(*) >= 3",
        now.seconds - 5 * DAY,
        [
            "payroll.held",
            "insolvency.warning",
            "invoice.blocked",
            "invoice.disputed",
            "close.deferred",
            "staff.left",
            "subscription.cancelled",
        ],
    )
    return Situation(
        unpaid=unpaid,
        paid_today=paid_today,
        short=short,
        let_down=let_down,
        lost_customer=lost,
        swamped=bool(backlog and int(backlog["n"]) > SWAMPED_AT),
        rough=rough,
        colleague_left=left,
    )


def mind_of(agent: Agent, outage: str | None, now: Situation) -> str:
    """The one thing most on this person's mind, as a typed key.

    One, in a fixed order of salience, rather than a list: every extra line in
    a request multiplies the situations that can never share a cached call, and
    Jev's accuracy falls as irrelevant state grows. Unpaid wages outrank an
    outage because an outage is somebody else's problem to fix.
    """

    if agent.org in now.unpaid:
        return "unpaid"
    if outage:
        return f"outage:{outage}"
    if agent.org in now.short:
        return "short"
    if agent.org in now.let_down:
        return "let_down"
    if agent.org in now.lost_customer:
        return "lost_customer"
    if agent.org in now.colleague_left:
        return "colleague_left"
    if agent.org == "tallybird" and now.swamped:
        return "swamped"
    if agent.org in now.rough:
        return "rough_week"
    if agent.org in now.paid_today:
        return "payday"
    return "nothing"


def dealings(engine: Engine, now: SimTime) -> dict[str, dict[str, str]]:
    """Firm -> the firms it has a live bill with, and which way it runs.

    A bill falls due within two days or is already late. Someone standing next
    to a person from the firm that owes theirs money has something to talk
    about, and the roster should say so (report recommendation 4).
    """

    rows = engine.conn.execute(
        "SELECT DISTINCT from_org_id, to_org_id FROM invoices "
        "WHERE paid_sim IS NULL AND written_off_sim IS NULL "
        "AND to_org_id IS NOT NULL AND due_sim <= %s",
        (now.seconds + 2 * DAY,),
    ).fetchall()
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        creditor, debtor = str(row["from_org_id"]), str(row["to_org_id"])
        out.setdefault(creditor, {})[debtor] = "owes_them"
        out.setdefault(debtor, {})[creditor] = "they_owe"
    return out


def decision_point(
    agent: Agent,
    others: list[Agent],
    mind: str,
    now: SimTime,
    *,
    arrived: bool,
) -> str | None:
    """Why this person is asked now, or None if this is not a decision point.

    DECIDE-0001's list, made concrete: arriving, being somewhere other than
    their own workplace, having company, their situation changing, the lunch
    window, and a mandatory timer on the hour. Someone at their own desk with
    nobody about and nothing new keeps doing what they were doing, which is
    what they would have answered anyway.

    The cafe's staff have no timer: behind their own counter with nobody from
    another firm in, the only answer was ever "stay" (97 to 99% of 8,783 answers
    each), and a model asked that is a model paid to say so.
    """

    if arrived:
        return "arrived"
    if agent.zone is not agent.own_zone:
        return "away"
    if others:
        return "company"
    if mind != agent.mind:
        return "mind"
    if agent.org == "thirdrail":
        return None
    if LUNCH_START <= now.time_of_day < LUNCH_END:
        return "lunch"
    if now.time_of_day % HOUR == 0:
        return "timer"
    return None


def run(engine: Engine, report: TickReport, now: SimTime) -> None:
    """One tick of space: arrive, decide, meet, move."""

    agents = load_agents(engine)
    taken: set[Tile] = {a.tile for a in agents if a.tile is not None}

    # Arrivals. Whether a workplace is open is a fact, not a judgement.
    absent, extra = shocks.off(engine, now.seconds)
    arrived: set[str] = set()
    for agent in agents:
        if agent.zone is Zone.HOME and on_shift(agent, now, absent=absent, extra=extra):
            _place(engine, report, agent, agent.own_zone, taken)
            arrived.add(agent.id)
    if arrived:
        agents = load_agents(engine)

    present = [a for a in agents if a.zone is not Zone.HOME]
    if not present:
        return

    down = [
        str(row["id"])
        for row in engine.conn.execute(
            "SELECT id FROM modules WHERE status = 'down' ORDER BY id"
        ).fetchall()
    ]
    by_zone: dict[Zone, list[Agent]] = {}
    for agent in present:
        by_zone.setdefault(agent.zone, []).append(agent)
    now_is = situation(engine, now)
    between = dealings(engine, now)

    asked: list[Agent] = []
    minds: list[str] = []
    contexts: list[DecisionContext] = []
    for agent in present:
        # Colleagues at their own desks are always together; that is not an
        # encounter. Someone counts as "here" only if being in the same place
        # took one of you leaving your workplace.
        others = [
            other
            for other in by_zone[agent.zone]
            if other.id != agent.id
            and not (agent.zone is agent.own_zone and other.org == agent.org)
        ]
        outage = episodes.known_outage(engine, agent.org, down)
        mind = mind_of(agent, outage, now_is)
        why = decision_point(agent, others, mind, now, arrived=agent.id in arrived)
        if why is None:
            continue
        asked.append(agent)
        minds.append(mind)
        contexts.append(
            DecisionContext(
                person_id=agent.id,
                role=agent.role,
                sim_time=report.sim_time,
                kind="agent.tick",
                facts={
                    "org": agent.org,
                    "here": agent.zone.value,
                    "own_zone": agent.own_zone.value,
                    "present": [
                        {"id": o.id, "org": o.org, "role": o.role} for o in others
                    ],
                    "outage": outage,
                    "mind": mind,
                    "dealings": {
                        o: way
                        for o, way in between.get(agent.org, {}).items()
                        if any(other.org == o for other in others)
                    },
                    # Somebody alone at their desk is asked on the hour, so the
                    # question is about the hour; everyone else, the quarter.
                    "horizon": "hour" if why == "timer" else "tick",
                    "can_raise": bool(
                        outage
                        and agent.org != "tallybird"
                        and any(o.org == "tallybird" for o in others)
                    ),
                },
                traits=agent.traits,
            )
        )

    made = engine.decide_many(report, contexts)
    by_id = {agent.id: agent for agent in present}
    if engine.encounters:
        # A meeting with a real stake gets rounds instead of one shot
        # (WORLD-0006). What comes back is every pair an episode already
        # accounted for: resolving the same meeting twice would double-count it.
        consumed: set[frozenset[str]] = set()
        if engine.episodes:
            consumed = episodes.run(
                engine, report, now, asked, made, by_id, down, present=present
            )
        _encounters(engine, report, asked, made, by_id, down, consumed)

    decided = {
        agent.id: (decision, mind)
        for agent, decision, mind in zip(asked, made, minds, strict=True)
    }
    # Departures and moves, after everyone has decided from where they stood.
    closing = SimTime(report.sim_time + TICK)
    for agent in present:
        choice = decided.get(agent.id)
        if choice is not None:
            decision, mind = choice
            engine.conn.execute(
                "UPDATE positions SET mood = %s, mind = %s WHERE person_id = %s",
                (int(decision.chosen.get("mood", 2)), mind, agent.id),
            )
        if not on_shift(agent, closing, absent=absent, extra=extra):
            _place(engine, report, agent, Zone.HOME, taken)
            continue
        wanted = (
            Zone(str(choice[0].chosen.get("next_zone", agent.zone.value)))
            if choice is not None
            else agent.zone
        )
        if wanted is not agent.zone:
            if agent.tile is not None:
                taken.discard(agent.tile)
            _place(
                engine,
                report,
                agent,
                wanted,
                taken,
                decision_id=choice[0].id if choice is not None else None,
            )
        elif agent.id not in arrived:
            # Stayed put: clear last tick's route so a client does not replay it.
            engine.conn.execute(
                "UPDATE positions SET path = '[]'::jsonb WHERE person_id = %s "
                "AND moved_tick < %s",
                (agent.id, report.tick_seq),
            )


def _encounters(
    engine: Engine,
    report: TickReport,
    asked: list[Agent],
    made: list[Made],
    by_id: dict[str, Agent],
    down: list[str],
    consumed: set[frozenset[str]] | None = None,
) -> None:
    met: set[frozenset[str]] = set(consumed or ())
    for agent, decision in zip(asked, made, strict=True):
        other_id = decision.chosen.get("with")
        if not decision.chosen.get("interact") or not isinstance(other_id, str):
            continue
        other = by_id.get(other_id)
        pair = frozenset({agent.id, other_id})
        if other is None or other.zone is not agent.zone or pair in met:
            continue
        met.add(pair)

        topic = str(decision.chosen.get("topic") or "small_talk")
        incident = (
            episodes.open_incident(engine, down) if topic == "the_outage" else None
        )
        payload: dict[str, object] = {
            "a": agent.id,
            "b": other.id,
            "zone": agent.zone.value,
            "topic": topic,
            "mood": int(decision.chosen.get("mood", 2)),
            "decided_by": decision.source,
        }
        if not engine.episodes:
            # The shadow of an episode: what one would have been about, had
            # episodes been on. Only in that arm, so every other world's log is
            # unchanged; it is what lets `make episodes` split its docking gap
            # into which meetings get rounds and what rounds do with them.
            stake = episodes.stake_of(
                engine, [agent, other], down, SimTime(report.sim_time)
            )
            payload["stake"] = stake.kind if stake is not None else None
        seq = engine.emit(
            report,
            "encounter",
            actor_id=agent.id,
            org_id=agent.org,
            decision_id=decision.id,
            causes=[incident["cause"]] if incident and incident["cause"] else [],
            payload=payload,
        )
        if decision.chosen.get("raise_outage") and other.org == "tallybird":
            episodes.escalate(
                engine,
                report,
                raised_by=agent.id,
                org_id=agent.org,
                raised_with=other.id,
                zone=agent.zone.value,
                cause_seq=seq,
                decision_id=decision.id,
                decided_by=decision.source,
            )
