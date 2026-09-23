"""Space, and why it matters (WORLD-0003).

Staff have positions. Each open tick every one of them decides where to go next
and whether to stop and talk to someone who is in the same place. Two people in
the same zone is an *encounter*, and an encounter is the only way some things
can happen: a lawyer whose invoicing is down can press the vendor to fix it only
if she and someone from the vendor are standing in the same room.

That is what makes space load-bearing rather than decorative. An escalation
pulls the end of the outage forward, which moves when blocked invoices go out,
which moves when they are paid. Switch encounters off and the billing timeline
is different; `tests/test_space.py` asserts exactly that.

Order within a tick, and why: everyone decides from where they are *now*;
encounters resolve among the people co-located now; then everyone moves. Jev
answers the questions in one request independently, so "where next" cannot
depend on "whom did I talk to" — and asking both about the present moment is
what keeps it to one call per person per tick.

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

from jeve.core.clock import TICK, SimTime
from jeve.core.seed import derive_seed
from jeve.decide.policy import DecisionContext
from jeve.world import episodes
from jeve.world.map import ORG_ZONE, Tile, Zone, entry_for, find_path, spot_for

if TYPE_CHECKING:
    from jeve.world.engine import Engine, Made, TickReport


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

    @property
    def own_zone(self) -> Zone:
        return ORG_ZONE[self.org]


def on_shift(org: str, when: SimTime) -> bool:
    return when.cafe_open if org == "thirdrail" else when.in_office_hours


def load_agents(engine: Engine) -> list[Agent]:
    rows = engine.conn.execute(
        "SELECT p.id, p.org_id, p.role, p.traits, s.zone, s.x, s.y "
        "FROM persons p JOIN positions s ON s.person_id = p.id "
        "WHERE p.kind = 'staff' ORDER BY p.id"
    ).fetchall()
    seen: dict[str, int] = {}
    agents: list[Agent] = []
    for row in rows:
        org = str(row["org_id"])
        index = seen.get(org, 0)
        seen[org] = index + 1
        tile = (int(row["x"]), int(row["y"])) if row["x"] is not None else None
        agents.append(
            Agent(
                id=str(row["id"]),
                org=org,
                role=str(row["role"]),
                traits=dict(row["traits"] or {}),
                zone=Zone(str(row["zone"])),
                tile=tile,
                index=index,
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
        assert agent.tile is not None
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


def run(engine: Engine, report: TickReport, now: SimTime) -> None:
    """One tick of space: arrive, decide, meet, move."""

    agents = load_agents(engine)
    taken: set[Tile] = {a.tile for a in agents if a.tile is not None}

    # Arrivals. Whether a workplace is open is a fact, not a judgement.
    arrived: dict[str, Agent] = {}
    for agent in agents:
        if agent.zone is Zone.HOME and on_shift(agent.org, now):
            _place(engine, report, agent, agent.own_zone, taken)
            arrived[agent.id] = agent
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
            consumed = episodes.run(engine, report, now, present, made, by_id, down)
        _encounters(engine, report, present, made, by_id, down, consumed)

    # Departures and moves, after everyone has decided from where they stood.
    closing = SimTime(report.sim_time + TICK)
    for agent, decision in zip(present, made, strict=True):
        engine.conn.execute(
            "UPDATE positions SET mood = %s WHERE person_id = %s",
            (int(decision.chosen.get("mood", 2)), agent.id),
        )
        if not on_shift(agent.org, closing):
            _place(engine, report, agent, Zone.HOME, taken)
            continue
        wanted = Zone(str(decision.chosen.get("next_zone", agent.zone.value)))
        if wanted is not agent.zone:
            if agent.tile is not None:
                taken.discard(agent.tile)
            _place(engine, report, agent, wanted, taken, decision_id=decision.id)
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
    present: list[Agent],
    made: list[Made],
    by_id: dict[str, Agent],
    down: list[str],
    consumed: set[frozenset[str]] | None = None,
) -> None:
    met: set[frozenset[str]] = set(consumed or ())
    for agent, decision in zip(present, made, strict=True):
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
                "zone": agent.zone.value,
                "topic": topic,
                "mood": int(decision.chosen.get("mood", 2)),
                "decided_by": decision.source,
            },
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
