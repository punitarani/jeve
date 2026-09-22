"""Space is load-bearing (WORLD-0003).

The requirement is not that people have coordinates. It is that where they are
*changes what happens*: switch encounters off and the billing timeline must be
different. If it were the same, the map would be decoration and these tests are
written to fail in that case.

Run on the rules policy — null model N1 — so they need no cassette and say
nothing about Jev. They are about the world's mechanics.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import pairwise

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import SimTime, at
from jeve.core.orgs import HEADCOUNT, ORGS, module_owner, modules_of
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.map import Node, entry_for, find_path, town
from jeve.world.seed_world import ROOT_SEED, seed
from tests.test_world import event_log_hash
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def run(conn: Connection[DictRow], *, days: int, encounters: bool = True) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(
            conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, encounters=encounters
        )
        advance(conn, engine, until=at(days))

    build_once(conn, f"rules:{days}d:encounters={encounters}", build)


def first_services_invoice(conn: Connection[DictRow]) -> int:
    row = conn.execute(
        # Month-end invoices to outside clients: not a lunch bill, not the
        # accountant's fee, which are also `services` and have nothing to do
        # with the outage.
        "SELECT min(sim_time) AS t FROM events WHERE kind = 'invoice.issued' "
        "AND payload->>'invoice_kind' = 'services' "
        "AND payload->>'to' LIKE '%%.client.%%'"
    ).fetchone()
    assert row is not None and row["t"] is not None
    return int(row["t"])


# -- the map ---------------------------------------------------------------


def test_every_place_someone_can_stand_is_reachable_from_the_street() -> None:
    world = town()
    assert len(world.tiles) == world.height and len(world.tiles[0]) == world.width
    assert set(world.seats) == set(world.visitor_spots)
    for (zone, floor), seats in world.seats.items():
        spots = (*seats, *world.visitor_spots[(zone, floor)])
        assert spots, (zone, floor)
        for x, y in spots:
            node: Node = (x, y, floor)
            assert world.walkable(node), (zone, node)
            assert world.zone_of((x, y)) == zone, (zone, node)
            path = find_path(entry_for((x, y)), node)
            assert path and path[-1] == node, (zone, node)


def test_every_workplace_seats_all_of_its_staff() -> None:
    world = town()
    for org in ORGS:
        for floor in range(org.floors):
            seats = set(world.seats[(org.id, floor)])
            assert len(seats) >= org.staff_on(floor), (org.id, floor)


def test_a_path_walks_one_tile_at_a_time_and_never_through_a_wall() -> None:
    """From a desk on the top floor of the software company to a table at the
    cafe: down the stair, out of the door, across the street, in at the door."""

    world = town()
    software = world.building("tallybird")
    cafe = world.building("thirdrail")
    x, y = world.seats[("tallybird", software.floors - 1)][0]
    start: Node = (x, y, software.floors - 1)
    x, y = world.visitor_spots[("thirdrail", 0)][3]
    goal: Node = (x, y, 0)
    path = find_path(start, goal)
    assert path[0] == start and path[-1] == goal
    for (ax, ay, af), (bx, by, bf) in pairwise(path):
        if af != bf:
            # A flight of stairs: the same tile, one floor apart, both stairs.
            assert (ax, ay) == (bx, by) and abs(af - bf) == 1
            assert world.kind((ax, ay, af)) == world.kind((bx, by, bf)) == "stair"
        else:
            assert abs(ax - bx) + abs(ay - by) == 1
        assert world.walkable((bx, by, bf))
    # The only way down is the stair, and the only way out is the door.
    assert (*software.stair, 1) in path
    assert (*software.door, 0) in path and (*cafe.door, 0) in path
    assert find_path(start, goal) == path


def test_there_is_no_path_into_a_desk() -> None:
    # Looked up, not written down: the layouts decide where the desks are
    # (WEB-0004), and they are allowed to move them.
    world = town()
    desks = [
        (x, y)
        for y, row in enumerate(world.tiles)
        for x, kind in enumerate(row)
        if kind == "desk"
    ]
    assert desks
    entry: Node = (*world.entries[0], 0)
    for x, y in desks:
        assert find_path(entry, (x, y, 0)) == []


# -- people in it ----------------------------------------------------------


def test_people_are_at_work_when_it_is_open_and_home_when_it_is_not(
    conn: Connection[DictRow],
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)

    # Just after eight in the morning: the cafe, the gym, the yard and the
    # clinic are open; the offices and the shop are not. Every firm keeps its
    # own hours, and the eight o'clock tick has run.
    advance(conn, engine, until=at(0, 8, 15))
    rows = conn.execute(
        "SELECT p.org_id, count(*) FILTER (WHERE s.zone <> 'home') AS out "
        "FROM positions s JOIN persons p ON p.id = s.person_id GROUP BY p.org_id"
    ).fetchall()
    by_org = {str(r["org_id"]): int(r["out"]) for r in rows}
    early = SimTime(at(0, 8))
    for org in ORGS:
        expected = org.headcount if early.open_for(org.hours) else 0
        assert by_org[org.id] == expected, (org.id, by_org[org.id], expected)
    assert 0 < sum(by_org.values()) < HEADCOUNT

    advance(conn, engine, until=at(0, 10))
    out = conn.execute(
        "SELECT count(*) AS n FROM positions WHERE zone <> 'home'"
    ).fetchone()
    assert out is not None and int(out["n"]) == HEADCOUNT

    advance(conn, engine, until=at(1, 7))  # overnight
    out = conn.execute(
        "SELECT count(*) AS n FROM positions WHERE zone <> 'home'"
    ).fetchone()
    assert out is not None and int(out["n"]) == 0


def test_nobody_stands_in_a_wall_or_in_the_wrong_zone(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=1)
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    advance(conn, engine, until=at(0, 13))  # lunchtime: people are about
    world = town()
    rows = conn.execute(
        "SELECT person_id, zone, floor, x, y, path FROM positions WHERE zone <> 'home'"
    ).fetchall()
    assert len({(r["x"], r["y"], r["floor"]) for r in rows}) > HEADCOUNT // 2
    for row in rows:
        node = (int(row["x"]), int(row["y"]), int(row["floor"]))
        assert world.walkable(node), row
        assert world.zone_of(node[:2]) == row["zone"], row
        if row["path"]:
            assert tuple(row["path"][-1]) == node


def test_movement_is_an_event_only_when_the_zone_changes(
    conn: Connection[DictRow],
) -> None:
    """One `agent.moved` per person per tick would be ~770 a day, burying the
    outage and quietly improving cost-per-thousand-events for free."""

    run(conn, days=2)
    same = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'agent.moved' "
        "AND payload->>'from_zone' = payload->>'to_zone' "
        "AND payload->>'from_floor' = payload->>'to_floor'"
    ).fetchone()
    moves = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'agent.moved'"
    ).fetchone()
    assert same is not None and int(same["n"]) == 0
    assert moves is not None and 2 * HEADCOUNT <= int(moves["n"]) < 2 * HEADCOUNT * 52


def test_an_encounter_is_between_people_who_had_to_move_to_meet(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=2)
    rows = conn.execute(
        "SELECT e.payload->>'zone' AS zone, (e.payload->>'floor')::int AS floor, "
        "  a.org_id AS a_org, b.org_id AS b_org, "
        "  ta.floor AS a_floor, tb.floor AS b_floor "
        "FROM events e JOIN persons a ON a.id = e.payload->>'a' "
        "JOIN persons b ON b.id = e.payload->>'b' "
        "JOIN teams ta ON ta.id = a.team_id JOIN teams tb ON tb.id = b.team_id "
        "WHERE e.kind = 'encounter'"
    ).fetchall()
    assert len(rows) > 10
    for row in rows:
        # Two colleagues on their own floor of their own building are at
        # their desks: that is work, not an encounter. The same two meeting
        # in the lobby downstairs is one.
        colleagues_at_their_desks = (
            row["a_org"] == row["b_org"] == row["zone"]
            and row["a_floor"] == row["b_floor"] == row["floor"]
        )
        assert not colleagues_at_their_desks, row


# -- and why it matters ----------------------------------------------------


def test_switching_encounters_off_changes_when_invoices_go_out(
    conn: Connection[DictRow],
) -> None:
    """The requirement, stated as a test. Same seed, same policy, same people
    walking the same routes; the only difference is whether meeting someone can
    change anything. If billing came out the same, space would be decorative."""

    def outage_minutes() -> int:
        row = conn.execute(
            "SELECT (payload->>'minutes')::int AS minutes FROM events "
            "WHERE kind = 'incident.ended' AND payload->>'module_id' = 'invoicing' "
            # The month-end outage, not some ninety-minute blip earlier in the week.
            "ORDER BY (payload->>'minutes')::int DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        return int(row["minutes"])

    def blocked() -> int:
        row = conn.execute(
            "SELECT count(*) AS n FROM events WHERE kind = 'invoice.blocked'"
        ).fetchone()
        assert row is not None
        return int(row["n"])

    run(conn, days=5, encounters=True)
    with_space = first_services_invoice(conn)
    minutes_with, blocked_with = outage_minutes(), blocked()
    hash_with = event_log_hash(conn)

    run(conn, days=5, encounters=False)
    without_space = first_services_invoice(conn)

    assert hash_with != event_log_hash(conn)
    assert with_space < without_space, (
        f"invoices went out at {SimTime(with_space)} with encounters and "
        f"{SimTime(without_space)} without"
    )
    assert minutes_with < outage_minutes()
    # The outage still bit. Escalation shortens it; it does not unhappen it.
    # (A blocked run says so once per firm, not once per tick it stays blocked.)
    billing_on_it = [
        org
        for org in ORGS
        if org.billing and modules_of(org.id, "invoicing") == ("invoicing",)
    ]
    assert len(billing_on_it) >= 2
    assert blocked_with == blocked() == len(billing_on_it)


def test_a_conversation_in_the_cafe_reaches_an_invoice(
    conn: Connection[DictRow],
) -> None:
    """The cascade query from the definition of done: start at an encounter,
    follow `causes` forward, arrive at money."""

    run(conn, days=5)
    reached = conn.execute(
        """
        WITH RECURSIVE downstream AS (
            SELECT seq, kind, 0 AS depth FROM events
            WHERE kind = 'encounter' AND seq IN (
                SELECT unnest(causes) FROM events
                WHERE kind = 'ticket.escalated'
                  AND payload->>'module_id' = 'invoicing')
            UNION
            SELECT e.seq, e.kind, d.depth + 1
            FROM events e JOIN downstream d ON d.seq = ANY(e.causes)
        )
        SELECT kind, min(depth) AS depth FROM downstream GROUP BY kind
        """
    ).fetchall()
    depth = {str(r["kind"]): int(r["depth"]) for r in reached}
    assert depth["encounter"] == 0
    assert depth["ticket.escalated"] == 1
    assert depth["incident.ended"] == 2
    assert depth["invoice.issued"] == 3


def test_an_outage_is_escalated_at_most_once(conn: Connection[DictRow]) -> None:
    run(conn, days=5)
    rows = conn.execute(
        "SELECT payload->>'incident_id' AS incident, count(*) AS n FROM events "
        "WHERE kind = 'ticket.escalated' GROUP BY 1"
    ).fetchall()
    assert rows
    assert all(int(r["n"]) == 1 for r in rows)
    # And it never makes an outage *longer*.
    worse = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated' "
        "AND (payload->>'minutes_saved')::int < 0"
    ).fetchone()
    assert worse is not None and int(worse["n"]) == 0


def test_only_someone_affected_can_escalate_and_only_to_the_vendor(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5)
    rows = conn.execute(
        "SELECT a.org_id AS by_org, b.org_id AS to_org, e.payload->>'module_id' AS m "
        "FROM events e JOIN persons a ON a.id = e.payload->>'raised_by' "
        "JOIN persons b ON b.id = e.payload->>'raised_with' "
        "WHERE e.kind = 'ticket.escalated'"
    ).fetchall()
    assert rows
    for row in rows:
        assert row["to_org"] == module_owner(str(row["m"]))
        assert row["by_org"] != row["to_org"]
        subscribed = conn.execute(
            "SELECT 1 FROM subscriptions WHERE org_id = %s AND module_id = %s",
            (row["by_org"], row["m"]),
        ).fetchone()
        assert subscribed is not None, row
