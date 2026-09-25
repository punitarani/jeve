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
    for desk in desks:
        assert find_path((19, 0), desk) == []


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
    # The early shift: shift lead, the morning barista and the baker. The owner
    # comes in at eight, the afternoon barista at noon, the weekend part-timer
    # on Saturday (field report, defect 5).
    assert by_org["thirdrail"] == 3
    assert by_org["tallybird"] == by_org["halloran"] == by_org["ledgerline"] == 0

    advance(conn, engine, until=at(0, 10))
    out = conn.execute(
        "SELECT count(*) AS n FROM positions WHERE zone <> 'home'"
    ).fetchone()
    assert out is not None and int(out["n"]) == 18 + 4

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
    assert blocked_with == blocked() == 2


def test_a_conversation_in_the_cafe_reaches_an_invoice(
    conn: Connection[DictRow],
) -> None:
    """The cascade query from the definition of done: start at a conversation,
    follow `causes` forward, arrive at money. A meeting with a stake is an
    episode (WORLD-0007) and one without is an encounter, so the conversation is
    whichever the meeting was. A complaint to someone who cannot fix it
    reaches the engineers through their relay (WORLD-0012), one step later."""

    run(conn, days=5)
    reached = conn.execute(
        """
        WITH RECURSIVE downstream AS (
            SELECT seq, kind, causes, 0 AS depth FROM events
            WHERE kind IN ('encounter', 'episode.closed') AND seq IN (
                SELECT unnest(causes) FROM events
                WHERE kind IN ('ticket.escalated', 'escalation.relayed')
                  AND payload->>'module_id' = 'invoicing')
            UNION
            SELECT e.seq, e.kind, e.causes, d.depth + 1
            FROM events e JOIN downstream d ON d.seq = ANY(e.causes)
        )
        SELECT seq, kind, causes, min(depth) AS depth FROM downstream
        GROUP BY seq, kind, causes
        """
    ).fetchall()
    at_depth = {int(r["seq"]): (str(r["kind"]), int(r["depth"])) for r in reached}

    def back(seq: int, kind: str) -> int:
        """The cause of `seq` that is a `kind`, one step nearer the talk."""

        causes = next(r["causes"] for r in reached if int(r["seq"]) == seq)
        depth = at_depth[seq][1]
        return next(int(c) for c in causes if at_depth.get(int(c)) == (kind, depth - 1))

    # Follow one chain back from the nearest invoice: a week can hold more than
    # one outage, and the one a talk shortened need not be the one that held up
    # the bills, so depths are read along a single path, not per kind.
    invoice = min(
        (seq for seq, (kind, _) in at_depth.items() if kind == "invoice.issued"),
        key=lambda seq: at_depth[seq][1],
    )
    ended = back(invoice, "incident.ended")
    escalated = back(ended, "ticket.escalated")
    assert at_depth[escalated][1] in (1, 2)
    origin = escalated
    while at_depth[origin][1] > 0:
        causes = next(r["causes"] for r in reached if int(r["seq"]) == origin)
        origin = next(
            int(c)
            for c in causes
            if int(c) in at_depth and at_depth[int(c)][1] == at_depth[origin][1] - 1
        )
    assert at_depth[origin][0] in ("encounter", "episode.closed")


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


# -- decision points (WORLD-0009) ----------------------------------------------


def test_the_weekend_part_timer_works_the_weekend(conn: Connection[DictRow]) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    advance(conn, engine, until=at(5, 10))
    weekday = conn.execute(
        "SELECT count(*) AS n FROM events WHERE kind = 'agent.moved' "
        "AND actor_id = 'thirdrail.weekend.23' AND sim_time < %s",
        (at(5),),
    ).fetchone()
    assert weekday is not None and int(weekday["n"]) == 0
    here = conn.execute(
        "SELECT zone FROM positions WHERE person_id = 'thirdrail.weekend.23'"
    ).fetchone()
    assert here is not None and here["zone"] == "cafe"
    conn.rollback()


def test_nobody_is_asked_to_stay_at_their_desk_every_quarter_hour(
    conn: Connection[DictRow],
) -> None:
    """5,331 answers per office worker and 8,783 per member of cafe staff in the
    field report, most of them "stay". Somebody alone at their own desk with
    nothing new is asked on the hour and through lunch; the cafe's staff alone
    behind their counter are not asked at all."""

    run(conn, days=2)
    rows = conn.execute(
        "SELECT p.org_id, count(*) AS n FROM decisions d JOIN persons p "
        "ON p.id = d.person_id WHERE d.question_set = 'agent.tick' "
        "GROUP BY p.org_id"
    ).fetchall()
    asked = {str(r["org_id"]): int(r["n"]) for r in rows}
    # Two days of office hours are 64 quarter hours per office worker.
    office_people = {"tallybird": 8, "halloran": 5, "ledgerline": 5}
    for org, people in office_people.items():
        assert asked[org] < 0.7 * 64 * people, (org, asked[org])
        # Arriving, the hours, lunch: at least twelve a day each.
        assert asked[org] >= 2 * 12 * people, (org, asked[org])
    # The cafe's staff are asked only when somebody from another firm is in, or
    # when they are away from the counter: not before the offices open.
    from jeve.core.orgs import shift_for
    from jeve.world.seed_world import STAFF

    nth: dict[str, int] = {}
    on_shift = 0
    for org, role, _ in STAFF:
        if org != "thirdrail":
            continue
        shift = shift_for(org, role, nth.get(role, 0))
        nth[role] = nth.get(role, 0) + 1
        on_shift += sum(
            (shift.end - shift.start) // 900 for day in (0, 1) if day in shift.days
        )
    assert asked["thirdrail"] < 0.6 * on_shift, (asked["thirdrail"], on_shift)
    before_nine = conn.execute(
        "SELECT count(*) AS n FROM decisions d JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'agent.tick' AND p.org_id = 'thirdrail' "
        "AND d.sim_time % 86400 < 9 * 3600"
    ).fetchone()
    # Arrivals only: nobody from another firm is about before nine.
    assert before_nine is not None and int(before_nine["n"]) <= 2 * 4


def test_lunch_still_empties_the_offices(conn: Connection[DictRow]) -> None:
    """The lunch curve (3% of office staff in the cafe mid-morning, 31% at noon)
    is what asking less often must not flatten."""

    run(conn, days=2)
    moves = conn.execute(
        "SELECT (sim_time % 86400) / 3600 AS hour, count(*) AS n FROM events "
        "WHERE kind = 'agent.moved' AND payload->>'to_zone' = 'cafe' "
        "AND org_id <> 'thirdrail' GROUP BY 1"
    ).fetchall()
    by_hour = {int(r["hour"]): int(r["n"]) for r in moves}
    lunch = by_hour.get(12, 0) + by_hour.get(13, 0)
    morning = by_hour.get(10, 0) + by_hour.get(11, 0)
    assert lunch > 2 * max(1, morning), by_hour
