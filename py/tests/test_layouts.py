"""Every storey of the district, furnished and walked (WEB-0004, WORLD-0008).

A layout is written in its building's own frame, so that it survives the
roster changing: the same function furnishes a 12-tile floor and a 24-tile one.
These tests build the real district and, for every floor of every building,
walk from the door — up the stair, for an upper floor — to every place a
person can be sent.
"""

from __future__ import annotations

import pytest

from jeve.core.orgs import BY_ID, ORGS
from jeve.world.map import (
    LAYOUTS,
    SITTABLE,
    STANDING_STYLES,
    WALKABLE,
    Building,
    Node,
    find_path,
    town,
)

STOREYS = [
    pytest.param(b, floor, id=f"{b.zone}-{floor}")
    for b in town().buildings
    for floor in range(b.floors)
]


def interior(b: Building, floor: int) -> dict[tuple[int, int], str]:
    world = town()
    return {
        (x, y): world.kind((x, y, floor))
        for y in range(b.y0, b.y1 + 1)
        for x in range(b.x0, b.x1 + 1)
    }


@pytest.mark.parametrize(("b", "floor"), STOREYS)
def test_a_storey_seats_its_team_and_every_place_can_be_walked_to(
    b: Building, floor: int
) -> None:
    world = town()
    org = BY_ID[b.zone]
    seats = world.seats[(b.zone, floor)]
    spots = world.visitor_spots[(b.zone, floor)]
    staff = org.staff_on(floor)

    assert len(seats) >= staff, (b.zone, floor, len(seats), staff)
    assert spots, "nowhere for a visitor to go"

    # One person to a place, and a visitor is never sent to somebody's desk.
    assert len(set(seats)) == len(seats)
    assert len(set(spots)) == len(spots)
    assert not set(seats) & set(spots)

    start: Node = (*b.door, 0)
    for x, y in (*seats, *spots):
        node: Node = (x, y, floor)
        assert world.kind(node) in WALKABLE, (node, world.kind(node))
        route = find_path(start, node)
        assert route, f"no way from the door to {node}"
        assert route[0] == start and route[-1] == node
        # The only way up is the stair: a route to an upper floor climbs it.
        if floor > 0:
            assert (*b.stair, floor) in route

    # The stair is where the building says it is, on every floor it has.
    if b.floors > 1:
        assert world.kind((*b.stair, floor)) == "stair"
    else:
        assert "stair" not in interior(b, floor).values()


@pytest.mark.parametrize(("b", "floor"), STOREYS)
def test_walls_stay_walls_and_the_door_stays_a_door(b: Building, floor: int) -> None:
    world = town()
    for (x, y), kind in interior(b, floor).items():
        on_edge = x in (b.x0, b.x1) or y in (b.y0, b.y1)
        if not on_edge:
            continue
        if floor == 0 and (x, y) == b.door:
            assert kind == "door"
        else:
            assert kind == "wall", ((x, y, floor), kind)
    assert world.zone_of(b.door) == b.zone


@pytest.mark.parametrize(("b", "floor"), STOREYS)
def test_office_staff_sit_and_counter_staff_stand(b: Building, floor: int) -> None:
    world = town()
    style = BY_ID[b.zone].layout_on(floor)
    sitting = [
        world.kind((x, y, floor)) in SITTABLE for x, y in world.seats[(b.zone, floor)]
    ]
    if style in STANDING_STYLES:
        assert not any(sitting), (b.zone, floor, style)
    elif style == "branch":
        # Tellers stand at their counter; the lending officers behind them sit.
        assert any(sitting) and not all(sitting), (b.zone, floor, style)
    else:
        assert all(sitting), (b.zone, floor, style)


def test_the_cafe_has_a_terrace() -> None:
    """Somewhere to sit outside, in front of the door wall."""

    world = town()
    cafes = [org for org in ORGS if org.layout_on(0) == "counter"]
    assert cafes
    for org in cafes:
        b = world.building(org.id)
        outside = [
            (x, y)
            for x, y in world.visitor_spots[(org.id, 0)]
            if not b.contains((x, y))
        ]
        assert outside, org.id
        assert all(world.kind((x, y, 0)) in SITTABLE for x, y in outside)
        assert all(world.zone_of(t) == org.id for t in outside)


def test_every_style_is_furnished_differently() -> None:
    """Audit D4: with labels hidden, furniture is most of what tells them apart."""

    world = town()
    signature: dict[str, frozenset[str]] = {}
    for b in world.buildings:
        for floor in range(b.floors):
            style = BY_ID[b.zone].layout_on(floor)
            inside = set(interior(b, floor).values())
            signature.setdefault(
                style,
                frozenset(
                    inside
                    - {
                        "wall",
                        "floor",
                        "door",
                        "chair",
                        "stair",
                        "sofa",
                        "kitchenette",
                        "reception",
                        "plant",
                    }
                ),
            )
    assert set(signature) == set(LAYOUTS), set(LAYOUTS) - set(signature)
    assert {"server_rack", "whiteboard"} <= signature["pods"]
    assert {"partition", "bookshelf", "conference"} <= signature["offices"]
    assert {"filing", "partition", "conference"} <= signature["ranks"]
    assert {"counter", "kitchen", "table"} <= signature["counter"]
    assert {"dental_chair"} <= signature["clinic"]
    assert {"shelf", "counter"} <= signature["shopfloor"]
    assert {"rack"} <= signature["warehouse"]
    assert {"equipment"} <= signature["gym"]
    assert {"teller"} <= signature["branch"]
    assert len(set(signature.values())) == len(signature)


def test_the_district_places_every_firm_on_its_lot() -> None:
    world = town()
    assert {b.zone for b in world.buildings} == {org.id for org in ORGS}
    for b in world.buildings:
        org = BY_ID[b.zone]
        assert b.floors == org.floors
        assert world.floors_of(b.zone) == org.floors
        # The door is on the street side, and the path from it reaches paving.
        assert b.door[1] == (b.y1 if b.faces_south else b.y0)
        assert world.walkable((*b.door, 0))
    # Buildings never overlap, and every one has room to breathe.
    for a in world.buildings:
        for b in world.buildings:
            if a is b:
                continue
            apart = (
                a.x1 < b.x0 - 1 or b.x1 < a.x0 - 1 or a.y1 < b.y0 - 1 or b.y1 < a.y0 - 1
            )
            assert apart, (a.zone, b.zone)
