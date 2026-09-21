"""The four layouts, on the town as it is and on the town that is coming (WEB-0004).

A layout is written in its building's own frame, so that it survives the map
growing. That is a claim about code nobody has run yet unless something runs
it: these tests furnish each building at today's bounds *and* at the bounds and
headcounts session 3 is about to give it, on a grid built here, and walk from
the door to every place a person can be sent.

`find_path` only knows the real town, so reachability here is a small BFS.
"""

from __future__ import annotations

from collections import deque

import pytest

from jeve.world.map import BUILDINGS, LAYOUTS, SITTABLE, WALKABLE, Building, Tile, Zone

# Inclusive outer walls, door, which way it faces, and how many work there.
COMING: tuple[tuple[Building, int], ...] = (
    (Building(Zone.SOFTWARE_OFFICE, 2, 2, 27, 16, (14, 16), True), 44),
    (Building(Zone.LAW_OFFICE, 38, 4, 59, 16, (48, 16), True), 24),
    (Building(Zone.ACCOUNTING_OFFICE, 4, 27, 23, 39, (14, 27), False), 20),
    (Building(Zone.CAFE, 38, 27, 59, 39, (48, 27), False), 16),
)
COMING_SIZE = (64, 44)
COMING_BAND = range(18, 26)

TODAY_STAFF = {
    Zone.SOFTWARE_OFFICE: 8,
    Zone.LAW_OFFICE: 5,
    Zone.ACCOUNTING_OFFICE: 5,
    Zone.CAFE: 6,
}
TODAY: tuple[tuple[Building, int], ...] = tuple(
    (b, TODAY_STAFF[b.zone]) for b in BUILDINGS
)
TODAY_SIZE = (40, 28)
TODAY_BAND = range(11, 17)

CASES = [
    pytest.param(b, staff, TODAY_SIZE, TODAY_BAND, False, id=f"today-{b.zone.value}")
    for b, staff in TODAY
] + [
    pytest.param(b, staff, COMING_SIZE, COMING_BAND, True, id=f"coming-{b.zone.value}")
    for b, staff in COMING
]


def shell(b: Building, size: tuple[int, int], band: range) -> list[list[str]]:
    """Grass, a paved band, and one empty building with its door and its path:
    what `town()` hands a layout."""

    width, height = size
    grid = [["plaza" if y in band else "grass"] * width for y in range(height)]
    for y in range(b.y0, b.y1 + 1):
        for x in range(b.x0, b.x1 + 1):
            edge = x in (b.x0, b.x1) or y in (b.y0, b.y1)
            grid[y][x] = "wall" if edge else "floor"
    grid[b.door[1]][b.door[0]] = "door"
    step = 1 if b.faces_south else -1
    y = b.door[1] + step
    while y not in band:
        grid[y][b.door[0]] = "path"
        y += step
    grid[y][b.door[0]] = "path"
    return grid


def reachable(grid: list[list[str]], start: Tile) -> set[Tile]:
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for step in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            sx, sy = step
            if step in seen or not (0 <= sy < len(grid) and 0 <= sx < len(grid[0])):
                continue
            if grid[sy][sx] in WALKABLE:
                seen.add(step)
                queue.append(step)
    return seen


@pytest.mark.parametrize(("b", "staff", "size", "band", "coming"), CASES)
def test_a_layout_seats_its_staff_and_every_place_can_be_walked_to(
    b: Building, staff: int, size: tuple[int, int], band: range, coming: bool
) -> None:
    grid = shell(b, size, band)
    seats, spots = LAYOUTS[b.zone](grid, b, staff)

    assert len(seats) >= (staff if coming else 6), (len(seats), staff)
    assert len(seats) >= staff
    assert spots, "nowhere for a visitor to go"
    if b.zone is Zone.CAFE:
        assert len(spots) >= 4

    # One person to a place, and a visitor is never sent to somebody's desk.
    assert len(set(seats)) == len(seats)
    assert len(set(spots)) == len(spots)
    assert not set(seats) & set(spots)

    within = reachable(grid, b.door)
    for x, y in (*seats, *spots):
        assert grid[y][x] in WALKABLE, (x, y, grid[y][x])
        assert (x, y) in within, f"no way from the door to {(x, y)}"

    # The door and the way to it stay clear, and the walls stay walls.
    assert grid[b.door[1]][b.door[0]] == "door"
    for y in range(b.y0, b.y1 + 1):
        for x in range(b.x0, b.x1 + 1):
            if (x in (b.x0, b.x1) or y in (b.y0, b.y1)) and (x, y) != b.door:
                assert grid[y][x] == "wall"


@pytest.mark.parametrize(("b", "staff", "size", "band", "coming"), CASES)
def test_office_staff_sit_and_cafe_staff_stand(
    b: Building, staff: int, size: tuple[int, int], band: range, coming: bool
) -> None:
    grid = shell(b, size, band)
    seats, spots = LAYOUTS[b.zone](grid, b, staff)
    sitting = [grid[y][x] in SITTABLE for x, y in seats]
    if b.zone is Zone.CAFE:
        assert not any(sitting)
        # Somewhere to sit outside, in front of the door wall.
        outside = [(x, y) for x, y in spots if not (b.y0 <= y <= b.y1)]
        assert outside and all(grid[y][x] in SITTABLE for x, y in outside)
    else:
        assert all(sitting)


def test_the_four_buildings_are_furnished_differently() -> None:
    """Audit D4: with labels hidden, furniture is most of what tells them apart."""

    signature: dict[Zone, frozenset[str]] = {}
    for b, staff in COMING:
        grid = shell(b, COMING_SIZE, COMING_BAND)
        LAYOUTS[b.zone](grid, b, staff)
        inside = {grid[y][x] for y in range(b.y0, b.y1 + 1) for x in range(b.x0, b.x1)}
        signature[b.zone] = frozenset(inside - {"wall", "floor", "door", "chair"})
    assert {"server_rack", "whiteboard"} <= signature[Zone.SOFTWARE_OFFICE]
    assert {"partition", "bookshelf", "conference", "reception"} <= signature[
        Zone.LAW_OFFICE
    ]
    assert {"filing", "partition", "conference"} <= signature[Zone.ACCOUNTING_OFFICE]
    assert {"counter", "kitchen", "table"} <= signature[Zone.CAFE]
    assert len(set(signature.values())) == 4
