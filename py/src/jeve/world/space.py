"""Space, and why it matters (WORLD-0003, WORLD-0006).

Staff have positions: a zone, a floor, a tile. At a *decision point* — when
they arrive, when the stay they chose runs out, when a piece of software they
use goes down, when someone from its vendor walks in, or at lunch — a person
decides where to go next and whether to stop and talk to someone who is in the
same place (WORLD-0007). Two people on the same floor of the same building is
an *encounter*, and an encounter is the only way some things can happen: a
lawyer whose invoicing is down can press the vendor to fix it only if she and
someone from the vendor are standing in the same room.

That is what makes space load-bearing rather than decorative. An escalation
pulls the end of the outage forward, which moves when blocked invoices go out,
which moves when they are paid. Switch encounters off and the billing timeline
is different; `tests/test_space.py` asserts exactly that.

A zone is a building — the firm's id — the plaza, or home; a floor is which
storey of the building. A team works on one floor; the ground floor of a
building with floors above it has a lobby, which is where the teams of one firm
run into each other. Someone counts as *here* only if being in the same place
took one of the two leaving their workplace: colleagues at their desks are
always together, and that is not an encounter.

Order within a tick, and why: those who are due decide from where they are
*now*; encounters resolve among the people co-located now, started by the ones
who decided; then the ones who decided move, and everybody whose day is over
goes home. Jev answers the questions in one request independently, so "where
next" cannot depend on "whom did I talk to" — and asking both about the
present moment is what keeps it to one call per person per decision.

How long a stay lasts is code, not a question (DECIDE-0001): a band of ticks
per kind of place, drawn about the person and the moment (CORE-0009). An hour
or two at the desk; a quarter or half hour anywhere else; long enough at the
vendor's to say your piece. Nobody goes two hours without being asked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from jeve.core.clock import HOUR, TICK, SimTime
from jeve.core.orgs import BY_ID, ORGS, module_owner, social_places, staff_ids, uses
from jeve.core.seed import derive_rng, derive_seed
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import candidates
from jeve.memory import beliefs
from jeve.world.map import HOME, PLAZA, Node, Tile, entry_for, find_path, spot_for, town

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport

# What an escalation buys: the vendor drops everything, and the time left to
# fix is cut to a quarter — never to less than half an hour, and only once per
# incident however many people complain.
ESCALATION_KEEPS = 4
ESCALATION_FLOOR = 2 * TICK

# How long a stay lasts, in ticks, by the kind of place chosen (WORLD-0007).
# Drawn in code, never asked: a dwell is pacing, not a judgement. The top of
# the longest band is the mandatory timer — nobody goes two hours unasked.
DWELL_TICKS: dict[str, tuple[int, int]] = {
    "workplace": (4, 8),
    "about": (1, 2),
    "visit": (1, 1),
}
LUNCH = 12 * HOUR
"""The one schedule boundary: everyone at work is asked at noon."""


@dataclass(frozen=True, slots=True)
class Agent:
    id: str
    org: str
    team: str
    role: str
    traits: dict[str, object]
    zone: str
    floor: int
    tile: Tile | None
    index: int
    """Position among the people who work on their floor: which seat is theirs."""
    own_floor: int
    uses: frozenset[str]
    """The modules this person's firm depends on — its own products, for a
    vendor's staff — and so the outages they have reason to know about."""
    due_at: int
    """Sim time of their next decision point, unless something wakes them."""
    last_decided: int

    @property
    def own_zone(self) -> str:
        return self.org

    @property
    def at_workplace(self) -> bool:
        return self.zone == self.org and self.floor == self.own_floor

    @property
    def node(self) -> Node | None:
        return None if self.tile is None else (self.tile[0], self.tile[1], self.floor)


def on_shift(org: str, when: SimTime) -> bool:
    return when.open_for(BY_ID[org].hours)


@cache
def _seating() -> dict[str, tuple[int, int]]:
    """Every member of staff's floor and seat index, from the roster: the
    order the teams are listed in is the order the seats are handed out."""

    out: dict[str, tuple[int, int]] = {}
    for org in ORGS:
        counted: dict[int, int] = {}
        floors = {f"{org.id}.{team.id}": team.floor for team in org.teams}
        for person_id in staff_ids(org.id):
            floor = floors[".".join(person_id.split(".")[:2])]
            out[person_id] = (floor, counted.get(floor, 0))
            counted[floor] = counted.get(floor, 0) + 1
    return out


def load_agents(engine: Engine) -> list[Agent]:
    rows = engine.conn.execute(
        "SELECT p.id, p.org_id, p.team_id, p.role, p.traits, "
        "  s.zone, s.floor, s.x, s.y, s.next_decision_sim, s.last_decision_sim "
        "FROM persons p JOIN positions s ON s.person_id = p.id "
        "WHERE p.kind = 'staff' ORDER BY p.id"
    ).fetchall()
    seating = _seating()
    agents: list[Agent] = []
    for row in rows:
        person_id = str(row["id"])
        org = str(row["org_id"])
        own_floor, index = seating.get(person_id, (0, 0))
        tile = (int(row["x"]), int(row["y"])) if row["x"] is not None else None
        agents.append(
            Agent(
                id=person_id,
                org=org,
                team=str(row["team_id"] or ""),
                role=str(row["role"]),
                traits=dict(row["traits"] or {}),
                zone=str(row["zone"]),
                floor=int(row["floor"]),
                tile=tile,
                index=index,
                own_floor=own_floor,
                uses=uses(org),
                due_at=int(row["next_decision_sim"]),
                last_decided=int(row["last_decision_sim"]),
            )
        )
    return agents


def _place(
    engine: Engine,
    report: TickReport,
    agent: Agent,
    zone: str,
    floor: int,
    taken: set[Node],
    *,
    decision_id: int | None = None,
) -> None:
    """Move someone to a place, walking there, and say so if the place changed."""

    if zone == HOME:
        assert agent.node is not None
        path = find_path(agent.node, entry_for(agent.tile or (0, 0)))
        target: Node | None = None
    else:
        # CORE-0009: about this person arriving here now, not about the tick count.
        salt = derive_seed(
            engine.root_seed, "spot", agent.id, zone, floor, report.sim_time
        )
        tile = spot_for(
            zone,
            floor,
            own=zone == agent.org and floor == agent.own_floor,
            staff_index=agent.index,
            taken=taken,
            salt=salt % 997,
        )
        target = (tile[0], tile[1], floor)
        taken.add(target)
        start = agent.node if agent.node is not None else entry_for(tile)
        path = find_path(start, target)

    engine.conn.execute(
        "UPDATE positions SET zone = %s, floor = %s, x = %s, y = %s, path = %s, "
        "moved_tick = %s WHERE person_id = %s",
        (
            zone,
            floor if target is not None else 0,
            target[0] if target else None,
            target[1] if target else None,
            json.dumps([list(step) for step in path]),
            report.tick_seq,
            agent.id,
        ),
    )
    if zone != agent.zone or (target is not None and floor != agent.floor):
        # Only changes of place are events. A step across a room is a frame,
        # not something that happened in the economy, and one per person per
        # tick would bury everything else in the log.
        engine.emit(
            report,
            "agent.moved",
            actor_id=agent.id,
            org_id=agent.org,
            decision_id=decision_id,
            payload={
                "person_id": agent.id,
                "from_zone": agent.zone,
                "to_zone": zone,
                "from_floor": agent.floor,
                "to_floor": floor if target is not None else 0,
                "steps": max(0, len(path) - 1),
                # The nodes walked. A client animates exactly this, live or
                # replayed from the log, so there is one mechanism for both.
                "path": [list(step) for step in path],
            },
        )


def send(
    engine: Engine,
    report: TickReport,
    *,
    org: str,
    to: str,
    floor: int = 0,
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
        (a for a in agents if a.org == org and a.at_workplace),
        key=lambda a: (rank.get(a.role, len(rank)), a.id),
    )
    if not free or to == org:
        return None
    runner = free[0]
    taken: set[Node] = {a.node for a in agents if a.node is not None}
    if runner.node is not None:
        taken.discard(runner.node)
    _place(engine, report, runner, to, floor, taken)
    return runner.id


def _known_outage(agent: Agent, down: list[str]) -> str | None:
    """A broken module this person has reason to know about: one their firm
    depends on, or, for a vendor's own staff, one their firm sells."""

    known = sorted(set(down) & agent.uses)
    return known[0] if known else None


def _facts(
    engine: Engine,
    report: TickReport,
    agent: Agent,
    others: list[Agent],
    outage: str | None,
    strained: dict[str, bool],
) -> dict[str, Any]:
    vendor = module_owner(outage) if outage else None
    org = BY_ID[agent.org]
    present: list[dict[str, object]] = [
        {"id": o.id, "org": o.org, "role": o.role} for o in others
    ]
    # Everyone here is counted for the model; only a few are offered by name
    # of a label (DECIDE-0005), the people they know best sooner (MEM-0002).
    # The mapping from label to person is here, in facts, never in the state.
    known = beliefs.strengths(engine.conn, agent.id)
    offered = candidates(present, own_org=agent.org, vendor=vendor, strengths=known)
    incident = _open_incident(engine, [outage]) if outage else None
    return {
        "outage_hours": (
            (report.sim_time - int(incident["started"])) // HOUR if incident else 0
        ),
        "strained": strained.get(agent.org, False),
        "warned": strained.get(f"{agent.org}:warned", False),
        "employer_strain": beliefs.get(
            engine.conn, agent.id, "employer_strain", agent.org
        ),
        "strengths": known,
        "org": agent.org,
        "team": agent.team,
        "here": agent.zone,
        "floor": agent.floor,
        "own_zone": agent.own_zone,
        "own_floor": agent.own_floor,
        "at_workplace": agent.at_workplace,
        "present": present,
        "candidates": offered,
        "outage": outage,
        "vendor": vendor,
        "can_raise": bool(
            outage
            and agent.org != vendor
            and any(o.org == vendor for o in others if o.id in offered)
        ),
        "lobby": org.floors > 1,
        "social": {p.kind: p.id for p in social_places() if p.id != agent.org},
        "minds_counter": org.archetype == "retail",
    }


def _dwell(
    engine: Engine, report: TickReport, agent: Agent, zone: str, floor: int
) -> int:
    """How many ticks the stay just chosen lasts. About this person and this
    moment (CORE-0009), and about the kind of place, never the place's name."""

    if zone == agent.org and floor == agent.own_floor:
        band = "workplace"
    elif zone in BY_ID and zone != agent.org and not BY_ID[zone].social:
        band = "visit"
    else:
        band = "about"
    low, high = DWELL_TICKS[band]
    return derive_rng(engine.root_seed, "dwell", agent.id, report.sim_time).randint(
        low, high
    )


def _wakes(
    engine: Engine,
    report: TickReport,
    now: SimTime,
    present: list[Agent],
    arrived: set[str],
    down: list[str],
) -> list[Agent]:
    """Who has a decision to make this tick (WORLD-0007).

    Arrival; the stay they chose running out; a module they use going down
    since they last decided; somebody from the vendor of a module they know
    is down walking onto their floor; and noon. Every one of these is a fact,
    so the wake is code and the question stays about what to do.
    """

    earliest = min((a.last_decided for a in present), default=report.sim_time)
    fresh = [
        (str(row["module_id"]), int(row["started_sim"]))
        for row in engine.conn.execute(
            "SELECT module_id, started_sim FROM incidents WHERE started_sim > %s",
            (earliest,),
        ).fetchall()
    ]
    vendors_in = {(a.zone, a.floor, a.org) for a in present if a.id in arrived}
    awake: list[Agent] = []
    for agent in present:
        outage = _known_outage(agent, down)
        if (
            agent.id in arrived
            or now.seconds >= agent.due_at
            or now.time_of_day == LUNCH
            or any(
                module in agent.uses and started > agent.last_decided
                for module, started in fresh
            )
            or (
                outage is not None
                and (agent.zone, agent.floor, module_owner(outage)) in vendors_in
                and agent.org != module_owner(outage)
            )
        ):
            awake.append(agent)
    return awake


def run(engine: Engine, report: TickReport, now: SimTime) -> None:
    """One tick of space: arrive, wake, decide, meet, move."""

    agents = load_agents(engine)
    taken: set[Node] = {a.node for a in agents if a.node is not None}

    # Arrivals. Whether a workplace is open is a fact, not a judgement.
    arrived: set[str] = set()
    for agent in agents:
        if agent.zone == HOME and on_shift(agent.org, now):
            _place(engine, report, agent, agent.org, agent.own_floor, taken)
            arrived.add(agent.id)
    if arrived:
        agents = load_agents(engine)

    present = [a for a in agents if a.zone != HOME]
    if not present:
        return

    down = [
        str(row["id"])
        for row in engine.conn.execute(
            "SELECT id FROM modules WHERE status = 'down' ORDER BY id"
        ).fetchall()
    ]
    by_place: dict[tuple[str, int], list[Agent]] = {}
    for agent in present:
        by_place.setdefault((agent.zone, agent.floor), []).append(agent)

    deciding = _wakes(engine, report, now, present, arrived, down)
    strained = _strained(engine, report)
    contexts: list[DecisionContext] = []
    for agent in deciding:
        # Colleagues at their own desks are always together; that is not an
        # encounter. Someone counts as "here" only if being in the same place
        # took one of you leaving your workplace.
        others = [
            other
            for other in by_place[(agent.zone, agent.floor)]
            if other.id != agent.id
            and not (agent.at_workplace and other.org == agent.org)
        ]
        outage = _known_outage(agent, down)
        contexts.append(
            DecisionContext(
                person_id=agent.id,
                role=agent.role,
                sim_time=report.sim_time,
                kind="agent.tick",
                facts=_facts(engine, report, agent, others, outage, strained),
                traits=agent.traits,
            )
        )

    made = engine.decide_many(report, contexts)
    by_id = {agent.id: agent for agent in present}
    if engine.encounters:
        _encounters(engine, report, deciding, made, by_id, down)

    # Moves, after everyone who decided did so from where they stood, and the
    # stay each one chose; then everybody whose day is over goes home.
    closing = SimTime(report.sim_time + TICK)
    decided = {agent.id for agent in deciding}
    for agent, decision in zip(deciding, made, strict=True):
        _revise(engine, report, agent, decision, down)
        wanted_zone = str(decision.chosen.get("next_zone", agent.zone))
        wanted_floor = int(decision.chosen.get("next_floor", agent.floor))
        if wanted_zone not in (PLAZA, agent.org, *BY_ID) or wanted_zone == HOME:
            wanted_zone, wanted_floor = agent.zone, agent.floor
        stay = _dwell(engine, report, agent, wanted_zone, wanted_floor)
        engine.conn.execute(
            "UPDATE positions SET mood = %s, next_decision_sim = %s, "
            "last_decision_sim = %s WHERE person_id = %s",
            (
                int(decision.chosen.get("mood", 2)),
                report.sim_time + stay * TICK,
                report.sim_time,
                agent.id,
            ),
        )
        if not on_shift(agent.org, closing):
            continue
        if (wanted_zone, wanted_floor) != (agent.zone, agent.floor):
            if agent.node is not None:
                taken.discard(agent.node)
            _place(
                engine, report, agent, wanted_zone, wanted_floor, taken,
                decision_id=decision.id,
            )  # fmt: skip
    for agent in present:
        if not on_shift(agent.org, closing):
            if agent.id in decided and agent.node is not None:
                taken.discard(agent.node)
            _place(engine, report, agent, HOME, 0, taken)
    # Whoever stayed put keeps no route: a client would replay last tick's.
    engine.conn.execute(
        "UPDATE positions SET path = '[]'::jsonb WHERE moved_tick < %s "
        "AND path <> '[]'::jsonb",
        (report.tick_seq,),
    )


def _strained(engine: Engine, report: TickReport) -> dict[str, bool]:
    """Which firms held payroll or warned of insolvency this past week: what
    their staff have seen, and so what their view of the employer is about."""

    out: dict[str, bool] = {}
    for row in engine.conn.execute(
        "SELECT DISTINCT org_id, kind FROM events WHERE kind IN "
        "('payroll.held', 'insolvency.warning') AND sim_time > %s "
        "AND org_id IS NOT NULL",
        (report.sim_time - 7 * 86400,),
    ).fetchall():
        out[str(row["org_id"])] = True
        if row["kind"] == "insolvency.warning":
            out[f"{row['org_id']}:warned"] = True
    return out


def _revise(
    engine: Engine, report: TickReport, agent: Agent, decision: Made, down: list[str]
) -> None:
    """Whatever the decision said about the world, written down as a belief
    (MEM-0002): about the vendor whose product is down, about their employer."""

    level = decision.chosen.get("vendor_reliability")
    outage = _known_outage(agent, down)
    if level is not None and outage is not None:
        beliefs.set_level(
            engine.conn,
            agent.id,
            "vendor_reliability",
            module_owner(outage),
            int(str(level)),
            report.sim_time,
        )
    strain = decision.chosen.get("employer_strain")
    if strain is not None:
        beliefs.set_level(
            engine.conn, agent.id, "employer_strain", agent.org, int(str(strain)),
            report.sim_time,
        )  # fmt: skip


def _encounters(
    engine: Engine,
    report: TickReport,
    present: list[Agent],
    made: list[Made],
    by_id: dict[str, Agent],
    down: list[str],
) -> None:
    met: set[frozenset[str]] = set()
    for agent, decision in zip(present, made, strict=True):
        other_id = decision.chosen.get("with")
        if not decision.chosen.get("interact") or not isinstance(other_id, str):
            continue
        other = by_id.get(other_id)
        pair = frozenset({agent.id, other_id})
        if (
            other is None
            or (other.zone, other.floor) != (agent.zone, agent.floor)
            or pair in met
        ):
            continue
        met.add(pair)

        topic = str(decision.chosen.get("topic") or "small_talk")
        outage = _known_outage(agent, down)
        incident = (
            _open_incident(engine, [outage])
            if topic == "the_outage" and outage
            else None
        )
        seq = engine.emit(
            report,
            "encounter",
            actor_id=agent.id,
            org_id=agent.org,
            decision_id=decision.id,
            causes=[incident["cause"]] if incident and incident["cause"] else [],
            payload={
                "a": agent.id,
                "b": other.id,
                "zone": agent.zone,
                "floor": agent.floor,
                "topic": topic,
                "mood": int(decision.chosen.get("mood", 2)),
                "decided_by": decision.source,
            },
        )
        # Two people who talked know each other a little better, and what
        # one knew the other now knows: an outage they discussed, a price
        # rise that came up over money (MEM-0002). Diffusion is a copy.
        beliefs.bump_relationship(engine.conn, agent.id, other.id, report.sim_time)
        if topic == "the_outage" and incident is not None:
            fact = f"outage:{incident['id']}"
            beliefs.learn(engine.conn, agent.id, fact, report.sim_time)
            beliefs.learn(engine.conn, other.id, fact, report.sim_time)
        elif topic == "money":
            for fact in _facts_known(engine, agent.id, "price_rise:"):
                beliefs.learn(engine.conn, other.id, fact, report.sim_time)
        if (
            decision.chosen.get("raise_outage")
            and outage is not None
            and other.org == module_owner(outage)
        ):
            _escalate(engine, report, agent, other, outage, seq, decision)


def _facts_known(engine: Engine, person_id: str, prefix: str) -> list[str]:
    return [
        str(row["entity_id"])
        for row in engine.conn.execute(
            "SELECT entity_id FROM beliefs WHERE person_id = %s AND slot = 'knows_of' "
            "AND entity_id LIKE %s",
            (person_id, prefix + "%"),
        ).fetchall()
    ]


def _open_incident(engine: Engine, down: list[str]) -> dict[str, Any] | None:
    if not down:
        return None
    row = engine.conn.execute(
        "SELECT id, module_id, cause_event_seq, escalated_sim, started_sim "
        "FROM incidents WHERE ended_sim IS NULL AND module_id = ANY(%s) "
        "ORDER BY id LIMIT 1",
        (down,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "module": str(row["module_id"]),
        "cause": int(row["cause_event_seq"]) if row["cause_event_seq"] else None,
        "escalated": row["escalated_sim"] is not None,
        "started": int(row["started_sim"]),
    }


def _escalate(
    engine: Engine,
    report: TickReport,
    agent: Agent,
    vendor: Agent,
    module: str,
    encounter_seq: int,
    decision: Made,
) -> None:
    """A customer has cornered the vendor in person. The fix gets priority."""

    incident = _open_incident(engine, [module])
    if incident is None or incident["escalated"]:
        return
    pending = engine.conn.execute(
        "SELECT id, due_sim_time FROM scheduled WHERE kind = 'incident.end' "
        "AND subject_id = %s ORDER BY id LIMIT 1",
        (module,),
    ).fetchone()
    if pending is None:
        return

    due = int(pending["due_sim_time"])
    remaining = max(0, due - report.sim_time)
    keep = max(ESCALATION_FLOOR, remaining // ESCALATION_KEEPS)
    # Whole ticks: the scheduler only looks once a tick.
    new_due = min(due, report.sim_time + -(-keep // TICK) * TICK)

    seq = engine.emit(
        report,
        "ticket.escalated",
        actor_id=agent.id,
        org_id=agent.org,
        decision_id=decision.id,
        causes=[encounter_seq] + ([incident["cause"]] if incident["cause"] else []),
        payload={
            "module_id": module,
            "incident_id": incident["id"],
            "raised_by": agent.id,
            "raised_with": vendor.id,
            "zone": agent.zone,
            "minutes_saved": (due - new_due) // 60,
            "decided_by": decision.source,
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


def town_map() -> Any:
    """The map, for callers outside `world` that must not import it at load."""

    return town()
