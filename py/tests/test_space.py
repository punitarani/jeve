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
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.map import (
    HEIGHT,
    ORG_ZONE,
    WIDTH,
    Zone,
    entry_for,
    find_path,
    town,
)
from jeve.world.seed_world import ROOT_SEED, seed
from tests.test_world import event_log_hash

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
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(
        conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, encounters=encounters
    )
    advance(conn, engine, until=at(days))


def first_services_invoice(conn: Connection[DictRow]) -> int:
    row = conn.execute(
        "SELECT min(sim_time) AS t FROM events WHERE kind = 'invoice.issued' "
        "AND payload->>'invoice_kind' = 'services'"
    ).fetchone()
    assert row is not None and row["t"] is not None
    return int(row["t"])


# -- the map ---------------------------------------------------------------


def test_every_place_someone_can_stand_is_reachable_from_the_street() -> None:
    world = town()
    assert len(world.tiles) == HEIGHT and len(world.tiles[0]) == WIDTH
    for zone in (*ORG_ZONE.values(), Zone.PLAZA):
        spots = (*world.seats[zone], *world.visitor_spots[zone])
        assert spots, zone
        for spot in spots:
            assert world.walkable(spot), (zone, spot)
            assert world.zone_of(spot) is zone, (zone, spot)
            path = find_path(entry_for(spot), spot)
            assert path and path[-1] == spot, (zone, spot)


def test_every_workplace_seats_all_of_its_staff() -> None:
    world = town()
    from jeve.world.seed_world import STAFF

    for org, zone in ORG_ZONE.items():
        staff = sum(1 for staff_org, _, _ in STAFF if staff_org == org)
        assert len(set(world.seats[zone])) >= staff, (org, staff)


def test_a_path_walks_one_tile_at_a_time_and_never_through_a_wall() -> None:
    world = town()
    start = world.seats[Zone.SOFTWARE_OFFICE][0]
    goal = world.visitor_spots[Zone.CAFE][3]
    path = find_path(start, goal)
    assert path[0] == start and path[-1] == goal
    for (ax, ay), (bx, by) in pairwise(path):
        assert abs(ax - bx) + abs(ay - by) == 1
        assert world.walkable((bx, by))
    # The only way out of a building is its door.
    assert (9, 10) in path and (30, 17) in path
    assert find_path(start, goal) == path


def test_there_is_no_path_into_a_desk() -> None:
    assert find_path((19, 0), (4, 4)) == []


# -- people in it ----------------------------------------------------------


def test_people_are_at_work_when_it_is_open_and_home_when_it_is_not(
    conn: Connection[DictRow],
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)

    advance(conn, engine, until=at(0, 8))  # cafe open since 07:00, offices shut
    rows = conn.execute(
        "SELECT p.org_id, count(*) FILTER (WHERE s.zone <> 'home') AS out "
        "FROM positions s JOIN persons p ON p.id = s.person_id GROUP BY p.org_id"
    ).fetchall()
    by_org = {str(r["org_id"]): int(r["out"]) for r in rows}
    assert by_org["thirdrail"] == 6
    assert by_org["tallybird"] == by_org["halloran"] == by_org["ledgerline"] == 0

    advance(conn, engine, until=at(0, 10))
    out = conn.execute(
        "SELECT count(*) AS n FROM positions WHERE zone <> 'home'"
    ).fetchone()
    assert out is not None and int(out["n"]) == 24

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
        "SELECT person_id, zone, x, y, path FROM positions WHERE zone <> 'home'"
    ).fetchall()
    assert len({(r["x"], r["y"]) for r in rows}) > 12
    for row in rows:
        tile = (int(row["x"]), int(row["y"]))
        assert world.walkable(tile), row
        assert world.zone_of(tile).value == row["zone"], row
        if row["path"]:
            assert tuple(row["path"][-1]) == tile


def test_movement_is_an_event_only_when_the_zone_changes(
    conn: Connection[DictRow],
) -> None:
    """One `agent.moved` per person per tick would be ~770 a day, burying the
    outage and quietly improving cost-per-thousand-events for free."""

    run(conn, days=2)
    same = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'agent.moved' "
        "AND payload->>'from_zone' = payload->>'to_zone'"
    ).fetchone()
    moves = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'agent.moved'"
    ).fetchone()
    assert same is not None and int(same["n"]) == 0
    assert moves is not None and 48 <= int(moves["n"]) < 2 * 24 * 40


def test_an_encounter_is_between_people_who_had_to_move_to_meet(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=2)
    rows = conn.execute(
        "SELECT e.payload->>'zone' AS zone, a.org_id AS a_org, b.org_id AS b_org "
        "FROM events e JOIN persons a ON a.id = e.payload->>'a' "
        "JOIN persons b ON b.id = e.payload->>'b' WHERE e.kind = 'encounter'"
    ).fetchall()
    assert len(rows) > 10
    for row in rows:
        colleagues_at_their_desks = (
            row["a_org"] == row["b_org"]
            and ORG_ZONE[str(row["a_org"])].value == row["zone"]
        )
        assert not colleagues_at_their_desks, row


# -- and why it matters ----------------------------------------------------


def test_switching_encounters_off_changes_when_invoices_go_out(
    conn: Connection[DictRow],
) -> None:
    """The requirement, stated as a test. Same seed, same policy, same people
    walking the same routes; the only difference is whether meeting someone can
    change anything. If billing came out the same, space would be decorative."""

    run(conn, days=5, encounters=True)
    with_space = first_services_invoice(conn)
    blocked_with = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'invoice.blocked'"
    ).fetchone()
    hash_with = event_log_hash(conn)

    run(conn, days=5, encounters=False)
    without_space = first_services_invoice(conn)
    blocked_without = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'invoice.blocked'"
    ).fetchone()

    assert hash_with != event_log_hash(conn)
    assert with_space < without_space, (
        f"invoices went out at {SimTime(with_space)} with encounters and "
        f"{SimTime(without_space)} without"
    )
    assert blocked_with is not None and blocked_without is not None
    assert int(blocked_with["n"]) < int(blocked_without["n"])
    # The outage still bit. Escalation shortens it; it does not unhappen it.
    assert int(blocked_with["n"]) > 0


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
        assert row["to_org"] == "tallybird"
        assert row["by_org"] != "tallybird"
        subscribed = conn.execute(
            "SELECT 1 FROM subscriptions WHERE org_id = %s AND module_id = %s",
            (row["by_org"], row["m"]),
        ).fetchone()
        assert subscribed is not None, row
