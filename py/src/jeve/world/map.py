"""The town: four buildings round a plaza (WORLD-0003).

Built in code rather than drawn, and served to the client as data, so the
renderer and the pathfinder cannot disagree about where a wall is. The map is
static: nothing here reads the database or the clock.

Coordinates are tiles, x east and y south, origin top-left.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

WIDTH = 40
HEIGHT = 28

type Tile = tuple[int, int]


class Zone(StrEnum):
    SOFTWARE_OFFICE = "software_office"
    LAW_OFFICE = "law_office"
    ACCOUNTING_OFFICE = "accounting_office"
    CAFE = "cafe"
    PLAZA = "plaza"
    HOME = "home"
    """Off the map. Where everyone is when their workplace is shut."""


ORG_ZONE: dict[str, Zone] = {
    "tallybird": Zone.SOFTWARE_OFFICE,
    "halloran": Zone.LAW_OFFICE,
    "ledgerline": Zone.ACCOUNTING_OFFICE,
    "thirdrail": Zone.CAFE,
}
ZONE_ORG: dict[Zone, str] = {zone: org for org, zone in ORG_ZONE.items()}

WALKABLE = frozenset(
    {"floor", "door", "plaza", "path", "grass", "chair", "bench", "deck"}
)
SITTABLE = frozenset({"chair", "bench"})
"""Walkable tiles that are furniture to sit on. Someone whose spot is one of
these is drawn sitting (WEB-0004); everybody else stands."""


@dataclass(frozen=True, slots=True)
class Building:
    zone: Zone
    x0: int
    y0: int
    x1: int
    y1: int
    """Inclusive outer wall bounds."""
    door: Tile
    faces_south: bool
    """True when the door is in the south wall (the building sits north of the
    plaza band); furniture is laid out from the far wall towards the door."""


BUILDINGS: tuple[Building, ...] = (
    Building(Zone.SOFTWARE_OFFICE, 2, 2, 15, 10, (9, 10), True),
    Building(Zone.LAW_OFFICE, 24, 2, 37, 10, (30, 10), True),
    Building(Zone.ACCOUNTING_OFFICE, 2, 17, 15, 25, (9, 17), False),
    Building(Zone.CAFE, 24, 17, 37, 25, (30, 17), False),
)

# Where someone coming from home steps onto the map: the ends of the avenue.
ENTRIES: tuple[Tile, ...] = ((19, 0), (20, 27))

FOUNTAIN: tuple[Tile, ...] = ((19, 13), (20, 13), (19, 14), (20, 14))
TREES: tuple[Tile, ...] = (
    (17, 3), (22, 3), (17, 7), (22, 7), (17, 20), (22, 20), (17, 24), (22, 24),
    (4, 12), (12, 15), (27, 12), (35, 15), (1, 13), (38, 14),
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class TownMap:
    tiles: tuple[tuple[str, ...], ...]
    """tiles[y][x] is a tile kind."""
    zones: tuple[tuple[str, ...], ...]
    """zones[y][x] is the zone a tile belongs to."""
    seats: dict[Zone, tuple[Tile, ...]]
    """Where the people who work in a zone stand, one each, in staff order."""
    visitor_spots: dict[Zone, tuple[Tile, ...]]
    """Where anyone else stands when they come by."""

    def kind(self, tile: Tile) -> str:
        x, y = tile
        return self.tiles[y][x]

    def walkable(self, tile: Tile) -> bool:
        x, y = tile
        return 0 <= x < WIDTH and 0 <= y < HEIGHT and self.tiles[y][x] in WALKABLE

    def zone_of(self, tile: Tile) -> Zone:
        x, y = tile
        return Zone(self.zones[y][x])

    def sittable(self, zone: Zone) -> tuple[Tile, ...]:
        """The places in a zone where one sits: its chairs and benches, staff's
        and visitors' alike, in the order they are handed out."""

        spots = (*self.seats[zone], *self.visitor_spots[zone])
        return tuple(t for t in dict.fromkeys(spots) if self.kind(t) in SITTABLE)


def _office(grid: list[list[str]], b: Building) -> tuple[list[Tile], list[Tile]]:
    """Two rows of desks along the far wall, a meeting corner near the door."""

    seats: list[Tile] = []
    far, step = (b.y0 + 2, 1) if b.faces_south else (b.y1 - 2, -1)
    for row in range(2):
        y = far + row * 3 * step
        for x in range(b.x0 + 2, b.x1 - 1, 3):
            grid[y][x] = "desk"
            seats.append((x, y + step))
    near = b.y1 - 1 if b.faces_south else b.y0 + 1
    visitors = [(x, near) for x in range(b.x0 + 2, b.x1 - 1, 2) if x != b.door[0]]
    return seats, visitors


def _cafe(grid: list[list[str]], b: Building) -> tuple[list[Tile], list[Tile]]:
    """A counter along the back wall with staff behind it; tables out front."""

    counter_y = b.y1 - 3
    for x in range(b.x0 + 2, b.x1 - 1):
        grid[counter_y][x] = "counter"
    seats = [(x, counter_y + 1) for x in range(b.x0 + 1, b.x1, 2)]
    visitors: list[Tile] = []
    for y in (b.y0 + 2, b.y0 + 4):
        for x in range(b.x0 + 2, b.x1 - 1, 3):
            grid[y][x] = "table"
            visitors.append((x + 1, y))
    # The way behind the counter: a gap at its east end.
    grid[counter_y][b.x1 - 2] = "floor"
    return seats, visitors


@cache
def town() -> TownMap:
    grid = [["grass"] * WIDTH for _ in range(HEIGHT)]
    zones = [[Zone.PLAZA.value] * WIDTH for _ in range(HEIGHT)]

    # The plaza: an east-west band between the buildings, and a north-south
    # avenue through the middle of it.
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if 11 <= y <= 16 or 16 <= x <= 23:
                grid[y][x] = "plaza"
    for y in range(HEIGHT):
        grid[y][19] = grid[y][20] = "path"
    for x in range(WIDTH):
        grid[13][x] = grid[14][x] = "path"

    seats: dict[Zone, tuple[Tile, ...]] = {}
    visitors: dict[Zone, tuple[Tile, ...]] = {}
    for b in BUILDINGS:
        for y in range(b.y0, b.y1 + 1):
            for x in range(b.x0, b.x1 + 1):
                edge = x in (b.x0, b.x1) or y in (b.y0, b.y1)
                grid[y][x] = "wall" if edge else "floor"
                zones[y][x] = b.zone.value
        grid[b.door[1]][b.door[0]] = "door"
        # A path from the door to the plaza band, so the way in is visible.
        direction = 1 if b.faces_south else -1
        y = b.door[1] + direction
        while 0 <= y < HEIGHT and grid[y][b.door[0]] != "path":
            grid[y][b.door[0]] = "path"
            y += direction
        layout = _cafe if b.zone is Zone.CAFE else _office
        own, guests = layout(grid, b)
        seats[b.zone] = tuple(own)
        visitors[b.zone] = tuple(guests)

    for x, y in FOUNTAIN:
        grid[y][x] = "fountain"
    for x, y in TREES:
        if grid[y][x] in ("grass", "plaza"):
            grid[y][x] = "tree"

    # Benches are implied: people in the plaza stand round the fountain.
    ring = [
        (x, y)
        for y in range(11, 17)
        for x in range(16, 24)
        if grid[y][x] in ("plaza", "path")
        and min(abs(x - fx) + abs(y - fy) for fx, fy in FOUNTAIN) in (1, 2)
    ]
    seats[Zone.PLAZA] = ()
    visitors[Zone.PLAZA] = tuple(ring)

    return TownMap(
        tiles=tuple(tuple(row) for row in grid),
        zones=tuple(tuple(row) for row in zones),
        seats=seats,
        visitor_spots=visitors,
    )


def find_path(start: Tile, goal: Tile) -> list[Tile]:
    """A* over walkable tiles, four-connected. Includes both ends.

    Deterministic: ties on cost break on the tile itself, so the same two
    points give the same route on every run and every machine. Returns an
    empty list when there is no route, which on this map means a bug.
    """

    world = town()
    if start == goal:
        return [start]
    if not world.walkable(goal):
        return []

    def estimate(tile: Tile) -> int:
        return abs(tile[0] - goal[0]) + abs(tile[1] - goal[1])

    frontier: list[tuple[int, int, Tile]] = [(estimate(start), 0, start)]
    came_from: dict[Tile, Tile] = {}
    cost: dict[Tile, int] = {start: 0}
    while frontier:
        _, spent, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]
        if spent > cost[current]:
            continue
        x, y = current
        for step in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not world.walkable(step):
                continue
            total = spent + 1
            if total < cost.get(step, 1 << 30):
                cost[step] = total
                came_from[step] = current
                heapq.heappush(frontier, (total + estimate(step), total, step))
    return []


def spot_for(
    zone: Zone, *, org_zone: Zone, staff_index: int, taken: set[Tile], salt: int
) -> Tile:
    """Where someone stands in a zone.

    At their own workplace, their own seat. Anywhere else, the first free
    visitor spot, starting from a position that varies by person and tick so
    visitors do not all queue for the same chair.
    """

    world = town()
    if zone is org_zone and world.seats[zone]:
        own = world.seats[zone]
        return own[staff_index % len(own)]
    spots = world.visitor_spots[zone]
    for offset in range(len(spots)):
        candidate = spots[(salt + offset) % len(spots)]
        if candidate not in taken:
            return candidate
    return spots[salt % len(spots)]


def entry_for(tile: Tile) -> Tile:
    """The map edge someone walking in from home arrives at."""

    return min(ENTRIES, key=lambda e: abs(e[0] - tile[0]) + abs(e[1] - tile[1]))


def ascii_map() -> str:
    glyph = {
        "grass": ",", "plaza": ".", "path": ":", "wall": "#", "floor": " ",
        "door": "D", "desk": "d", "counter": "=", "table": "t", "tree": "T",
        "fountain": "~",
    }  # fmt: skip
    return "\n".join("".join(glyph[k] for k in row) for row in town().tiles)
