"""The town: four buildings round a plaza (WORLD-0003).

Built in code rather than drawn, and served to the client as data, so the
renderer and the pathfinder cannot disagree about where a wall is. The map is
static: nothing here reads the database or the clock.

Coordinates are tiles, x east and y south, origin top-left.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
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

WALKABLE = frozenset({"floor", "door", "plaza", "path", "grass", "chair", "bench"})
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


# -- layouts (WEB-0004) ------------------------------------------------------
#
# One function per building, because three offices out of one function were one
# building in three colours (audit D4). Each is written in the building's own
# frame and never in tile numbers: the town is about to grow, and the same
# function has to furnish a 12x7 floor today and a 24x13 one tomorrow.
# `tests/test_layouts.py` builds each on both and walks to every seat.


@dataclass(slots=True)
class _Room:
    """A building's floor in its own frame.

    `u` runs west to east, `v` from the far wall (0) towards the wall with the
    door in it, whichever way the building faces. Nothing is placed except on
    bare floor, so a layout cannot overwrite a wall, a door or its own
    furniture, and a piece that does not fit is simply not there.
    """

    grid: list[list[str]]
    b: Building

    @property
    def width(self) -> int:
        return self.b.x1 - self.b.x0 - 1

    @property
    def depth(self) -> int:
        return self.b.y1 - self.b.y0 - 1

    @property
    def door_u(self) -> int:
        return self.b.door[0] - self.b.x0 - 1

    @property
    def cam(self) -> int:
        """Which side of a desk to sit so as to face the camera, as a step in
        `v`. The camera looks from the south-east, so that is the north side."""

        return -1 if self.b.faces_south else 1

    def tile(self, u: int, v: int) -> Tile:
        y = self.b.y0 + 1 + v if self.b.faces_south else self.b.y1 - 1 - v
        return (self.b.x0 + 1 + u, y)

    def bare(self, u: int, v: int) -> Tile | None:
        """The tile at (u, v) if it is inside and unfurnished."""

        if not (0 <= u < self.width and 0 <= v < self.depth):
            return None
        x, y = self.tile(u, v)
        return (x, y) if self.grid[y][x] == "floor" else None

    def put(self, u: int, v: int, kind: str) -> Tile | None:
        spot = self.bare(u, v)
        if spot is not None:
            self.grid[spot[1]][spot[0]] = kind
        return spot

    def desk(self, u: int, v: int, side: int, kind: str = "desk") -> Tile | None:
        """A desk at (u, v) with its chair one step `side` in v. Both or neither."""

        if self.bare(u, v) is None or self.bare(u, v + side) is None:
            return None
        self.put(u, v, kind)
        return self.put(u, v + side, "chair")

    def outside(self, u: int, n: int) -> Tile | None:
        """The tile `n` steps out from the door wall, if it is open ground."""

        x = self.b.x0 + 1 + u
        y = self.b.y1 + n if self.b.faces_south else self.b.y0 - n
        if not (0 <= y < len(self.grid) and 0 <= x < len(self.grid[0])):
            return None
        return (x, y) if self.grid[y][x] in ("grass", "plaza") else None

    def standing(self, spots: list[tuple[int, int]]) -> list[Tile]:
        """Those of `spots` that are still bare floor: where a visitor stands."""

        found = (self.bare(u, v) for u, v in spots)
        return list(dict.fromkeys(t for t in found if t is not None))


def _software(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Pods of facing desks, whiteboards and a server rack on the far wall, and
    a standing table in each front corner."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    want = staff + max(2, staff // 8)
    for u in range(w - 2, w):
        room.put(u, 0, "server_rack")
    for u in range(1, w - 3):
        if u % 6 in (1, 2, 3):
            room.put(u, 0, "whiteboard")

    # A pod is six desks, three facing three, and four rows deep: chairs, two
    # rows of desks back to back, chairs; then an aisle. Every fourth column is
    # a cross-aisle. Each band of pods takes an equal share of the desks, from
    # the west, and what is left over at the east end is where people stand
    # round a high table.
    bands = list(range(1, d - 5, 5))
    columns = [u for u in range(1, w - 1) if u % 4 != 0]
    each = -(-want // max(1, len(bands)))
    seats: list[Tile] = []
    around: list[tuple[int, int]] = []
    for v0 in bands:
        placed = 0
        for u in columns:
            for desk_v, side in ((v0 + 1, -1), (v0 + 2, 1)):
                if placed < each and (seat := room.desk(u, desk_v, side)):
                    seats.append(seat)
                    placed += 1
        for u in range(w - 3, 1, -4):
            if all(room.bare(u + k, v0 + 1) for k in (-2, -1, 0, 1)):
                room.put(u, v0 + 1, "table")
                around += [(u - 1, v0 + 1), (u + 1, v0 + 1), (u, v0 + 2)]

    for u in (2, w - 3):
        if abs(u - room.door_u) > 2 and room.put(u, d - 1, "table"):
            around += [(u - 1, d - 1), (u + 1, d - 1), (u, d - 2)]
    room.put(0, d - 2, "whiteboard")
    room.put(0, d - 1, "plant")
    room.put(w - 1, d - 1, "plant")
    door = [(room.door_u + k, d - 1) for k in (-2, 2, -3, 3)]
    return seats, room.standing(around + door)


def _law(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Partners' offices behind glass along the far wall, a bullpen of
    associates, a conference table, reception by the door, books on the walls."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    want = staff + 2
    seats: list[Tile] = []

    # An office is three tiles wide and two deep behind a glass front, with its
    # doorway on the right: desk in the middle, the partner behind it facing
    # the door, shelves in the corner.
    for base in range(0, w - 2, 4):
        room.put(base, 0, "bookshelf")
        room.put(base, 1, "plant")
        if seat := room.desk(base + 1, 1, -1):
            seats.append(seat)
        room.put(base, 2, "partition")
        room.put(base + 1, 2, "partition")
        if base + 3 < w - 1:
            for v in range(3):
                room.put(base + 3, v, "partition")
    for u in range(w - w % 4, w):
        room.put(u, 0, "bookshelf")

    # The conference table, on the far side of the door from the bullpen. Its
    # chairs are for whoever comes to the meeting.
    cv = (d + 3) // 2
    first, last = room.door_u + 2, min(room.door_u + 6, w - 3)
    meeting: list[Tile] = []
    for u in range(first, last + 1):
        if (
            room.bare(u, cv - 1)
            and room.bare(u, cv + 1)
            and room.put(u, cv, "conference")
        ):
            meeting += [
                t
                for t in (room.put(u, cv - 1, "chair"), room.put(u, cv + 1, "chair"))
                if t
            ]
    if meeting:
        meeting += [
            t
            for t in (room.put(first - 1, cv, "chair"), room.put(last + 1, cv, "chair"))
            if t
        ]

    # The bullpen: v=3 is the corridor in front of the offices.
    columns = range(1, room.door_u - 1)
    rows: list[tuple[int, int]] = []
    v = 4
    if d >= 9:
        rows += [(5, -1), (6, 1)]
        v = 8
    if v + 1 <= d - 2:
        rows.append((v + 1, -1) if room.cam == -1 else (v, 1))
    for desk_v, side in rows:
        for u in columns:
            if len(seats) < want and (seat := room.desk(u, desk_v, side)):
                seats.append(seat)

    # Reception faces whoever comes in. Only where there is room for it.
    if all(room.bare(room.door_u + k, d - 1) for k in (2, 3)) and room.bare(
        room.door_u + 2, d - 2
    ):
        room.put(room.door_u + 3, d - 1, "reception")
        if seat := room.desk(room.door_u + 2, d - 1, -1, "reception"):
            seats.append(seat)

    for v in range(4, d - 1):
        room.put(0, v, "bookshelf")
        room.put(w - 1, v, "bookshelf")
    door = [(room.door_u + k, d - 2) for k in (-1, 1)] + [(room.door_u - 2, d - 1)]
    return seats, meeting + room.standing(door)


def _accounting(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Rows of bookkeepers all facing one way, filing cabinets down the side
    walls, and a glass meeting room in a far corner."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    want = staff + 2

    # The meeting room: four wide, three deep, glass on two sides, a doorway.
    for v in range(4):
        room.put(w - 5, v, "partition")
    for u in range(w - 4, w):
        if u != w - 3:
            room.put(u, 3, "partition")
    meeting: list[Tile] = []
    for u in (w - 3, w - 2):
        room.put(u, 1, "conference")
        meeting += [t for t in (room.put(u, 0, "chair"), room.put(u, 2, "chair")) if t]
    if end := room.put(w - 4, 1, "chair"):
        meeting.append(end)

    for v in range(1, d - 2):
        room.put(0, v, "filing")
        if v > 3:
            room.put(w - 1, v, "filing")

    # Desks in ranks, three rows apart, everyone facing the camera; the column
    # in line with the door is the aisle. Each rank takes an equal share, from
    # the west, and an island of cabinets stands where a rank stops short.
    seats: list[Tile] = []
    ranks = list(range(1, d - 2, 3))
    each = -(-want // max(1, len(ranks)))
    for base in ranks:
        desk_v, side = (base + 1, -1) if room.cam == -1 else (base, 1)
        placed = 0
        for u in range(2, w - 2):
            if (
                u != room.door_u
                and placed < each
                and (seat := room.desk(u, desk_v, side))
            ):
                seats.append(seat)
                placed += 1
        if all(room.bare(u, desk_v) for u in range(w - 6, w - 2)):
            room.put(w - 4, desk_v, "filing")
            room.put(w - 5, desk_v, "filing")

    room.put(1, d - 1, "plant")
    room.put(w - 2, d - 1, "plant")
    door = [(room.door_u + k, d - 1) for k in (-2, 2, -3, 3)]
    return seats, meeting + room.standing(door)


def _cafe(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Kitchen along the far wall, staff between it and the counter, tables on
    the floor, and more tables outside the door under an awning."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    for u in range(1, w - 1):
        room.put(u, 0, "kitchen")
    # The way behind the counter is a gap at its east end.
    for u in range(w - 1):
        room.put(u, 2, "counter")
    # Staff stand; every other place first, so a small shift is spread out.
    behind = [room.bare(u, 1) for u in (*range(0, w, 2), *range(1, w, 2))]
    seats = [t for t in behind if t is not None][: max(staff, 6) + 2]

    # A table for two: chair, table, chair along the wall, never across the
    # line of the door. Indoors on every other row from the counter; outdoors
    # from the second row out, because the first is under the awning and
    # hidden from the camera by the cafe's own wall.
    def indoors(v: int) -> Callable[[int, str], Tile | None]:
        def place(u: int, kind: str) -> Tile | None:
            return room.put(u, v, kind)

        return place

    def outdoors(n: int) -> Callable[[int, str], Tile | None]:
        def place(u: int, kind: str) -> Tile | None:
            spot = room.outside(u, n)
            if spot is not None:
                grid[spot[1]][spot[0]] = kind
            return spot

        return place

    def table_for_two(place: Callable[[int, str], Tile | None], u: int) -> list[Tile]:
        if room.door_u in (u, u + 1, u + 2) or place(u + 1, "table") is None:
            return []
        return [t for t in (place(u, "chair"), place(u + 2, "chair")) if t]

    visitors: list[Tile] = []
    for v in range(4, d - 1, 2):
        for u in range(1, w - 2, 4):
            if all(room.bare(u + k, v) for k in range(3)):
                visitors += table_for_two(indoors(v), u)
    for n in (2, 3):
        for u in range(0, w - 2, 4):
            if all(room.outside(u + k, n) for k in range(3)):
                visitors += table_for_two(outdoors(n), u)

    queue = [(room.door_u + k, 3) for k in (-1, 0, 1, 2)]
    return seats, visitors + room.standing(queue)


type Layout = Callable[[list[list[str]], Building, int], tuple[list[Tile], list[Tile]]]

LAYOUTS: dict[Zone, Layout] = {
    Zone.SOFTWARE_OFFICE: _software,
    Zone.LAW_OFFICE: _law,
    Zone.ACCOUNTING_OFFICE: _accounting,
    Zone.CAFE: _cafe,
}
"""`layout(grid, building, staff) -> (seats, visitor spots)`. `seats` has room
for `staff` people and is in the order it is handed out."""


def _plaza(
    grid: list[list[str]], fountain: tuple[Tile, ...], buildings: tuple[Building, ...]
) -> list[Tile]:
    """Benches, lamps and planters round the fountain, and a lamp either side of
    every door. Returns where people in the plaza go: the benches, and standing
    room round the fountain. Furniture only ever replaces open paving or grass,
    so it cannot close a path."""

    def put(x: int, y: int, kind: str) -> Tile | None:
        if not (0 <= y < len(grid) and 0 <= x < len(grid[0])):
            return None
        if grid[y][x] not in ("plaza", "grass"):
            return None
        grid[y][x] = kind
        return (x, y)

    xs, ys = [x for x, _ in fountain], [y for _, y in fountain]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    benches: list[Tile] = []
    for x, side in ((x0 - 2, -1), (x1 + 2, 1)):
        for y in (y0 - 1, y1 + 1):
            if bench := put(x, y, "bench"):
                benches.append(bench)
            put(x + side, y, "planter")
        for y in (y0 - 2, y1 + 2):
            put(x, y, "lamp")
    for b in buildings:
        out = 2 if b.faces_south else -2
        for dx in (-2, 2):
            put(b.door[0] + dx, b.door[1] + out, "lamp")

    ring = [
        (x, y)
        for y in range(y0 - 2, y1 + 3)
        for x in range(x0 - 2, x1 + 3)
        if 0 <= y < len(grid)
        and 0 <= x < len(grid[0])
        and grid[y][x] in ("plaza", "path")
        and min(abs(x - fx) + abs(y - fy) for fx, fy in fountain) in (1, 2)
    ]
    return benches + ring


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

    # Headcounts come from the seed, so a layout seats whoever the town employs
    # without a second list to keep in step. Imported here: the map is imported
    # by modules that must not pull in the database at import time.
    from jeve.world.seed_world import STAFF

    staff = {org: sum(1 for o, _, _ in STAFF if o == org) for org in ORG_ZONE}
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
        own, guests = LAYOUTS[b.zone](grid, b, staff[ZONE_ORG[b.zone]])
        seats[b.zone] = tuple(own)
        visitors[b.zone] = tuple(guests)
        # A layout may put people outside its walls (the cafe's terrace). Where
        # somebody in a zone can be, the tile is in that zone: it is what the
        # API's frame is checked against, and what a click on them resolves to.
        for x, y in (*own, *guests):
            zones[y][x] = b.zone.value

    for x, y in FOUNTAIN:
        grid[y][x] = "fountain"
    for x, y in TREES:
        if grid[y][x] in ("grass", "plaza"):
            grid[y][x] = "tree"

    seats[Zone.PLAZA] = ()
    visitors[Zone.PLAZA] = tuple(_plaza(grid, FOUNTAIN, BUILDINGS))

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
        "fountain": "~", "chair": "h", "bench": "n",
        "whiteboard": "w", "server_rack": "S", "bookshelf": "B",
        "conference": "c", "reception": "r", "filing": "f", "partition": "|",
        "kitchen": "k", "plant": "p", "planter": "P", "lamp": "i",
    }  # fmt: skip
    return "\n".join("".join(glyph[k] for k in row) for row in town().tiles)
