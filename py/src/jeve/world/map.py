"""The district: twelve buildings in three rows, with floors (WORLD-0006).

Built in code rather than drawn, and served to the client as data, so the
renderer and the pathfinder cannot disagree about where a wall is. The map is
static: nothing here reads the database or the clock. Every building is placed
by a rule from the roster (`jeve.core.orgs`), never by a tile number: twelve
firms were not going to be hand-placed, and a thirteenth will not be either.

Coordinates are tiles, x east and y south, origin top-left. A place someone can
stand is a *node*: `(x, y, floor)`. Floor 0 is the ground, where the street is
and where every building's ground floor is laid into the one grid; each upper
floor is a storey of its own over the building's footprint, reached by the
stair in its far corner. Zones are buildings (a firm's id), the plaza, or home.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache, partial

from jeve.core.orgs import ORGS, OrgSpec

type Tile = tuple[int, int]
type Node = tuple[int, int, int]
"""(x, y, floor): where someone can be."""

PLAZA = "plaza"
HOME = "home"
"""Off the map. Where everyone is when their workplace is shut."""

WALKABLE = frozenset(
    {"floor", "door", "plaza", "path", "grass", "chair", "bench", "sofa", "stair"}
)
SITTABLE = frozenset({"chair", "bench", "sofa"})
"""Walkable tiles that are furniture to sit on. Someone whose spot is one of
these is drawn sitting (WEB-0004); everybody else stands."""

# -- the plan ------------------------------------------------------------------
#
# Three rows of four lots. Row 0 faces south onto the first street, row 1 faces
# north onto it, an alley of grass and trees runs behind row 1, and row 2 faces
# south onto the second street along the bottom edge. An avenue runs north to
# south between lots 1 and 2 of every row; where it crosses the first street is
# the plaza and its fountain.

MARGIN = 2
GAP = 3
"""Tiles between two neighbouring buildings in a row."""
AVENUE = 8
STREET = 7
ALLEY = 5
OUTER_DEPTH = 11
"""Every building is this deep, outer walls included: nine tiles of floor."""
ROW_FACES_SOUTH = (True, False, True)
STAIR_STEPS = 3
"""What a flight of stairs costs a walker, in tiles."""


@dataclass(frozen=True, slots=True)
class Building:
    zone: str
    """The firm's id: a zone is a building."""
    x0: int
    y0: int
    x1: int
    y1: int
    """Inclusive outer wall bounds."""
    door: Tile
    faces_south: bool
    """True when the door is in the south wall (the building sits north of its
    street); furniture is laid out from the far wall towards the door."""
    floors: int
    stair: Tile
    """The stair's tile, the same on every floor of the building."""

    def contains(self, tile: Tile) -> bool:
        return self.x0 <= tile[0] <= self.x1 and self.y0 <= tile[1] <= self.y1


@dataclass(frozen=True, slots=True)
class Storey:
    """One upper floor: the building's footprint, furnished on its own."""

    zone: str
    floor: int
    tiles: tuple[tuple[str, ...], ...]
    """Local: `tiles[y - y0][x - x0]`, walls on the edge, no door."""


@dataclass(frozen=True, slots=True)
class TownMap:
    width: int
    height: int
    tiles: tuple[tuple[str, ...], ...]
    """tiles[y][x] is a tile kind, on the ground."""
    zones: tuple[tuple[str, ...], ...]
    """zones[y][x] is the zone a ground tile belongs to."""
    buildings: tuple[Building, ...]
    storeys: tuple[Storey, ...]
    seats: dict[tuple[str, int], tuple[Tile, ...]]
    """Where the people who work on a floor stand, one each, in staff order."""
    visitor_spots: dict[tuple[str, int], tuple[Tile, ...]]
    """Where anyone else stands when they come by a floor."""
    entries: tuple[Tile, ...]
    """Where someone coming from home steps onto the map: the road ends."""
    fountain: tuple[Tile, ...]

    def building(self, zone: str) -> Building:
        for b in self.buildings:
            if b.zone == zone:
                return b
        raise KeyError(f"no building for zone {zone!r}")

    def kind(self, node: Node) -> str:
        x, y, floor = node
        if floor == 0:
            return self.tiles[y][x]
        zone = self.zones[y][x]
        for storey in self.storeys:
            if storey.zone == zone and storey.floor == floor:
                b = self.building(zone)
                return storey.tiles[y - b.y0][x - b.x0]
        return "void"

    def walkable(self, node: Node) -> bool:
        x, y, floor = node
        if not (0 <= x < self.width and 0 <= y < self.height and floor >= 0):
            return False
        if floor == 0:
            return self.tiles[y][x] in WALKABLE
        zone = self.zones[y][x]
        b = next((b for b in self.buildings if b.zone == zone), None)
        if b is None or floor >= b.floors or not b.contains((x, y)):
            return False
        return self.kind(node) in WALKABLE

    def zone_of(self, tile: Tile) -> str:
        x, y = tile
        return self.zones[y][x]

    def floors_of(self, zone: str) -> int:
        b = next((b for b in self.buildings if b.zone == zone), None)
        return 1 if b is None else b.floors

    def sittable(self, zone: str, floor: int = 0) -> tuple[Tile, ...]:
        """The places on a floor where one sits: its chairs, benches and sofas,
        staff's and visitors' alike, in the order they are handed out."""

        spots = (
            *self.seats.get((zone, floor), ()),
            *self.visitor_spots.get((zone, floor), ()),
        )
        return tuple(
            t for t in dict.fromkeys(spots) if self.kind((*t, floor)) in SITTABLE
        )


# -- layouts (WEB-0004) ------------------------------------------------------
#
# One function per style, because three offices out of one function were one
# building in three colours (audit D4). Each is written in the building's own
# frame and never in tile numbers, so the same function furnishes a 12x7 floor
# and a 20x9 one. `tests/test_layouts.py` builds every storey of the district
# and walks to every seat.


@dataclass(slots=True)
class _Room:
    """A building's floor in its own frame.

    `u` runs west to east, `v` from the far wall (0) towards the wall with the
    door in it, whichever way the building faces. Nothing is placed except on
    bare floor, so a layout cannot overwrite a wall, a door, the stair or its
    own furniture, and a piece that does not fit is simply not there.
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


type Layout = Callable[[list[list[str]], Building, int], tuple[list[Tile], list[Tile]]]
"""`layout(grid, building, staff) -> (seats, visitor spots)`. `seats` has room
for `staff` people and is in the order it is handed out."""


def _software(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Pods of facing desks, whiteboards and a server rack on the far wall, and
    a standing table in each front corner."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    want = staff + max(2, staff // 8)
    for u in range(w - 3, w - 1):
        room.put(u, 0, "server_rack")
    for u in range(1, w - 4):
        if u % 6 in (1, 2, 3):
            room.put(u, 0, "whiteboard")

    # A pod is six desks, three facing three, and four rows deep: chairs, two
    # rows of desks back to back, chairs; then an aisle. Every fourth column is
    # a cross-aisle. Each band of pods takes an equal share of the desks, from
    # the west, and what is left over at the east end is where people stand
    # round a high table.
    bands = list(range(1, max(2, d - 4), 5))
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
    for base in range(0, w - 3, 4):
        room.put(base, 0, "bookshelf")
        room.put(base, 1, "plant")
        if seat := room.desk(base + 1, 1, -1):
            seats.append(seat)
        room.put(base, 2, "partition")
        room.put(base + 1, 2, "partition")
        if base + 3 < w - 2:
            for v in range(3):
                room.put(base + 3, v, "partition")
    for u in range(w - (w - 1) % 4 - 1, w - 1):
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
    # In the west corner, because the stair has the east one.
    for v in range(4):
        room.put(4, v, "partition")
    for u in range(0, 4):
        if u != 2:
            room.put(u, 3, "partition")
    meeting: list[Tile] = []
    for u in (1, 2):
        room.put(u, 1, "conference")
        meeting += [t for t in (room.put(u, 0, "chair"), room.put(u, 2, "chair")) if t]
    if end := room.put(3, 1, "chair"):
        meeting.append(end)

    for v in range(1, d - 2):
        room.put(w - 1, v, "filing")
        if v > 3:
            room.put(0, v, "filing")

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
    for u in range(1, w - 2):
        room.put(u, 0, "kitchen")
    # The way behind the counter is a gap at its east end.
    for u in range(w - 2):
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


def _rooms(
    kind: str, grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Small rooms off a corridor: two along each of the far and door walls'
    rows, each with a `kind` in the middle — a desk, or a dentist's chair —
    and a chair either side of it. The corridor is where a visitor waits."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    want = staff + 2
    seats: list[Tile] = []

    def cell(base: int, back: int, front: int, side_v: range) -> None:
        # `back` is the wall row the unit stands against, `front` the row of
        # the glass with the doorway in the middle.
        room.put(base + 1, back, kind)
        room.put(base, back, "bookshelf" if kind == "desk" else "filing")
        room.put(base + 2, back, "plant")
        for u in (base, base + 2):
            room.put(u, front, "partition")
        mid = (back + front) // 2
        for u in (base, base + 2):
            if len(seats) < want and (seat := room.put(u, mid, "chair")):
                seats.append(seat)
        if base + 3 < w - 2:
            for v in side_v:
                room.put(base + 3, v, "partition")

    for base in range(0, w - 4, 4):
        cell(base, 0, 2, range(0, 3))
    if d >= 8:
        for base in range(0, w - 4, 4):
            if abs(base + 1 - room.door_u) <= 2:
                continue
            cell(base, d - 1, d - 3, range(d - 3, d))

    corridor = [
        (u, v)
        for v in range(3, d - 3)
        for u in (room.door_u - 1, room.door_u + 1, 1, w - 3)
    ]
    room.put(w - 2, d - 1, "plant")
    return seats, room.standing(corridor)


def _shopfloor(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """A counter three rows in from the door with staff behind it, and aisles
    of shelving to browse in front of the far wall."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    counter_v = d - 3
    for u in range(1, w - 2):
        room.put(u, counter_v, "counter")
    behind = [
        room.bare(u, counter_v - 1) for u in (*range(1, w - 2, 2), *range(2, w - 2, 2))
    ]
    seats = [t for t in behind if t is not None][: staff + 2]
    for u in range(1, w - 3, 3):
        for v in range(0, counter_v - 2):
            room.put(u, v, "shelf")
    aisles = [(u, v) for u in range(2, w - 2, 3) for v in range(0, counter_v - 2)]
    queue = [(room.door_u + k, counter_v + 1) for k in (-1, 0, 1, 2)]
    room.put(w - 2, d - 1, "plant")
    return seats, room.standing(aisles + queue)


def _hall(
    kind: str, grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """An open floor of `kind` units in rows — racks in a warehouse, machines
    in a gym — with the people who work there standing beside them and room
    between the rows for whoever comes in."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    seats: list[Tile] = []
    between: list[tuple[int, int]] = []
    rows = list(range(1, d - 2, 3))
    for v in rows:
        for u in range(1, w - 2):
            # A break in every run, so a row can be crossed.
            if u % 5 == 0:
                continue
            if kind == "rack":
                room.put(u, v, kind)
            elif u % 2 == 1:
                room.put(u, v, kind)
        for u in range(1, w - 2, 2):
            if len(seats) < staff + 2 and (seat := room.bare(u, v + 1)):
                seats.append(seat)
        between += [(u, v + 1) for u in range(2, w - 2, 2)]
    front = [(room.door_u + k, d - 1) for k in (-2, 2, -3, 3)]
    room.put(0, d - 1, "plant")
    return seats, room.standing(between + front)


def _branch(
    grid: list[list[str]], b: Building, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """A counter of tellers across the middle, chairs to wait on by the door,
    and glass offices along the far wall for whoever signs things."""

    room = _Room(grid, b)
    w, d = room.width, room.depth
    seats: list[Tile] = []
    for base in range(0, w - 4, 4):
        room.put(base, 0, "filing")
        if seat := room.desk(base + 1, 1, -1):
            seats.append(seat)
        room.put(base, 2, "partition")
        room.put(base + 1, 2, "partition")
        if base + 3 < w - 2:
            for v in range(3):
                room.put(base + 3, v, "partition")
    counter_v = d - 4
    for u in range(1, w - 2):
        room.put(u, counter_v, "teller")
    behind = [
        room.bare(u, counter_v - 1) for u in (*range(1, w - 2, 2), *range(2, w - 2, 2))
    ]
    seats += [t for t in behind if t is not None][: max(0, staff + 2 - len(seats))]
    waiting: list[Tile] = []
    for u in range(1, w - 2, 2):
        if abs(u - room.door_u) <= 1:
            continue
        if seat := room.put(u, d - 2, "chair"):
            waiting.append(seat)
    queue = [(room.door_u + k, counter_v + 1) for k in (-1, 0, 1, 2)]
    room.put(w - 2, d - 1, "plant")
    return seats, waiting + room.standing(queue)


def _lobby(room: _Room) -> tuple[list[Tile], list[tuple[int, int]]]:
    """The ground floor of a building with floors above: a kitchenette and a
    few sofas by the door, where the teams of one firm run into each other.
    Furnished before the team's layout, which then works round it. Returns the
    sofas, and where one might stand — settled once the layout has had its
    say, because a spot that is bare now may be a desk chair by then."""

    w, d = room.width, room.depth
    sofas: list[Tile] = []
    standing: list[tuple[int, int]] = []
    for u in (1, 2):
        if abs(u - room.door_u) > 2:
            room.put(u, d - 1, "kitchenette")
            standing.append((u, d - 2))
    lounge = [u for u in (w - 4, w - 3, w - 2) if abs(u - room.door_u) > 2]
    if len(lounge) == 3:
        room.put(lounge[1], d - 1, "table")
        for u in (lounge[0], lounge[2]):
            if sofa := room.put(u, d - 1, "sofa"):
                sofas.append(sofa)
            standing.append((u, d - 2))
    return sofas, standing


LAYOUTS: dict[str, Layout] = {
    "pods": _software,
    "offices": _law,
    "ranks": _accounting,
    "counter": _cafe,
    "rooms": partial(_rooms, "desk"),
    "clinic": partial(_rooms, "dental_chair"),
    "shopfloor": _shopfloor,
    "warehouse": partial(_hall, "rack"),
    "gym": partial(_hall, "equipment"),
    "branch": _branch,
}

STANDING_STYLES = frozenset({"counter", "shopfloor", "warehouse", "gym"})
"""Styles whose staff stand at their place rather than sit."""


def _stair(room: _Room) -> Tile:
    """The stair, in the far east corner of every floor, and the landing in
    front of it kept clear: a floor that cannot be reached is a wall."""

    stair = room.put(room.width - 1, 0, "stair")
    assert stair is not None, "no room for a stair"
    for u, v in ((room.width - 2, 0), (room.width - 1, 1), (room.width - 1, 2)):
        room.put(u, v, "landing")
    return stair


def _restore_landing(grid: list[list[str]]) -> None:
    for row in grid:
        for x, kind in enumerate(row):
            if kind == "landing":
                row[x] = "floor"


def _shell(b: Building, width: int, height: int, band: range | None) -> list[list[str]]:
    """Grass, a paved band, and one empty building with its door and its path:
    what a layout is handed when it is measured rather than placed."""

    grid = [
        ["plaza" if band is not None and y in band else "grass"] * width
        for y in range(height)
    ]
    for y in range(b.y0, b.y1 + 1):
        for x in range(b.x0, b.x1 + 1):
            edge = x in (b.x0, b.x1) or y in (b.y0, b.y1)
            grid[y][x] = "wall" if edge else "floor"
    grid[b.door[1]][b.door[0]] = "door"
    return grid


def furnish(
    grid: list[list[str]], b: Building, floor: int, style: str, staff: int
) -> tuple[list[Tile], list[Tile]]:
    """Furnish one storey of a building in `grid`: the stair first, then the
    lobby on a ground floor that has floors above it, then the team's own
    layout round both. Returns (seats, visitor spots)."""

    room = _Room(grid, b)
    if b.floors > 1:
        _stair(room)
    sofas, standing = _lobby(room) if floor == 0 and b.floors > 1 else ([], [])
    seats, spots = LAYOUTS[style](grid, b, staff)
    _restore_landing(grid)
    lobby = sofas + [t for t in room.standing(standing) if t not in seats]
    return seats, list(dict.fromkeys(lobby + spots))


def _seats_at(style: str, interior: int, staff: int, *, lobby: bool) -> int:
    """How many seats `style` yields on a floor `interior` tiles wide."""

    b = Building(
        zone="probe",
        x0=0,
        y0=0,
        x1=interior + 1,
        y1=OUTER_DEPTH - 1,
        door=(interior // 2 + 1, OUTER_DEPTH - 1),
        faces_south=True,
        floors=2 if lobby else 1,
        stair=(interior, 1),
    )
    grid = _shell(b, interior + 2, OUTER_DEPTH + 3, range(OUTER_DEPTH, OUTER_DEPTH + 3))
    seats, _ = furnish(grid, b, 0, style, staff)
    return len(seats)


def width_for(style: str, staff: int, *, lobby: bool) -> int:
    """The narrowest interior width at which `style` seats `staff`."""

    for interior in range(10, 41):
        if _seats_at(style, interior, staff, lobby=lobby) >= staff:
            return interior
    raise ValueError(f"{style} cannot seat {staff} people in forty tiles")


# -- the district ------------------------------------------------------------------


def _plaza(
    grid: list[list[str]],
    square: tuple[Tile, ...],
    buildings: tuple[Building, ...],
    *,
    centre: str,
) -> list[Tile]:
    """Benches, lamps and planters round a square, and a lamp either side of
    every door. Returns where people go: the benches, and standing room round
    the square. Furniture only ever replaces open paving or grass, so it cannot
    close a path."""

    def put(x: int, y: int, kind: str) -> Tile | None:
        if not (0 <= y < len(grid) and 0 <= x < len(grid[0])):
            return None
        if grid[y][x] not in ("plaza", "grass"):
            return None
        grid[y][x] = kind
        return (x, y)

    xs, ys = [x for x, _ in square], [y for _, y in square]
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
        and min(abs(x - fx) + abs(y - fy) for fx, fy in square) in (1, 2)
    ]
    for x, y in square:
        grid[y][x] = centre
    return benches + ring


def _lots() -> tuple[list[list[OrgSpec]], dict[str, int]]:
    """The roster by row and slot, and each building's outer width."""

    rows: list[list[OrgSpec]] = [[] for _ in ROW_FACES_SOUTH]
    for org in sorted(ORGS, key=lambda o: o.lot):
        rows[org.lot[0]].append(org)
    widths: dict[str, int] = {}
    for org in ORGS:
        need = 0
        for floor in range(org.floors):
            style = org.layout_on(floor)
            staff = org.staff_on(floor)
            need = max(
                need, width_for(style, staff, lobby=floor == 0 and org.floors > 1)
            )
        widths[org.id] = need + 2
    return rows, widths


@cache
def town() -> TownMap:
    """The district, built once from the roster."""

    rows, widths = _lots()
    left = max(sum(widths[o.id] for o in row[:2]) + GAP for row in rows)
    right = max(sum(widths[o.id] for o in row[2:]) + GAP for row in rows)
    avenue_x = MARGIN + left
    width = avenue_x + AVENUE + right + MARGIN
    # Rows and streets, top to bottom.
    y = MARGIN
    row_y: list[int] = []
    streets: list[range] = []
    for index in range(len(rows)):
        row_y.append(y)
        y += OUTER_DEPTH
        if index == 0:
            streets.append(range(y, y + STREET))
            y += STREET
        elif index == 1:
            y += ALLEY
        else:
            streets.append(range(y, y + STREET))
            y += STREET
    height = y + MARGIN

    grid = [["grass"] * width for _ in range(height)]
    zones = [[PLAZA] * width for _ in range(height)]
    for street in streets:
        for yy in street:
            for x in range(width):
                grid[yy][x] = "plaza"
    for yy in range(height):
        for x in range(avenue_x, avenue_x + AVENUE):
            grid[yy][x] = "plaza"
    mid = avenue_x + AVENUE // 2
    for yy in range(height):
        grid[yy][mid - 1] = grid[yy][mid] = "path"
    for street in streets:
        centre = street.start + STREET // 2
        for x in range(width):
            grid[centre][x] = grid[centre + 1][x] = "path"

    buildings: list[Building] = []
    for index, row in enumerate(rows):
        faces_south = ROW_FACES_SOUTH[index]
        y0 = row_y[index]
        y1 = y0 + OUTER_DEPTH - 1
        # Row 1 faces north onto the first street, so its street is above it;
        # the others face south onto the street below them.
        x = MARGIN
        for slot, org in enumerate(row):
            if slot == 2:
                x = avenue_x + AVENUE
            x1 = x + widths[org.id] - 1
            door = (x + widths[org.id] // 2, y1 if faces_south else y0)
            stair = (x1 - 1, y0 + 1 if faces_south else y1 - 1)
            buildings.append(
                Building(org.id, x, y0, x1, y1, door, faces_south, org.floors, stair)
            )
            x = x1 + 1 + GAP

    for b in buildings:
        for yy in range(b.y0, b.y1 + 1):
            for x in range(b.x0, b.x1 + 1):
                edge = x in (b.x0, b.x1) or yy in (b.y0, b.y1)
                grid[yy][x] = "wall" if edge else "floor"
                zones[yy][x] = b.zone
        grid[b.door[1]][b.door[0]] = "door"
        # A path from the door to the street, so the way in is visible.
        direction = 1 if b.faces_south else -1
        yy = b.door[1] + direction
        while 0 <= yy < height and grid[yy][b.door[0]] != "path":
            grid[yy][b.door[0]] = "path"
            yy += direction

    seats: dict[tuple[str, int], tuple[Tile, ...]] = {}
    visitors: dict[tuple[str, int], tuple[Tile, ...]] = {}
    storeys: list[Storey] = []
    by_id = {org.id: org for org in ORGS}
    for b in buildings:
        org = by_id[b.zone]
        for floor in range(b.floors):
            if floor == 0:
                floor_grid = grid
            else:
                floor_grid = [["void"] * width for _ in range(height)]
                for yy in range(b.y0, b.y1 + 1):
                    for x in range(b.x0, b.x1 + 1):
                        edge = x in (b.x0, b.x1) or yy in (b.y0, b.y1)
                        floor_grid[yy][x] = "wall" if edge else "floor"
            own, guests = furnish(
                floor_grid, b, floor, org.layout_on(floor), org.staff_on(floor)
            )
            seats[(b.zone, floor)] = tuple(own)
            visitors[(b.zone, floor)] = tuple(guests)
            if floor == 0:
                # A layout may put people outside its walls (the cafe's
                # terrace). Where somebody in a zone can be, the tile is in
                # that zone: it is what the API's frame is checked against,
                # and what a click on them resolves to.
                for x, yy in (*own, *guests):
                    zones[yy][x] = b.zone
            else:
                storeys.append(
                    Storey(
                        b.zone,
                        floor,
                        tuple(
                            tuple(floor_grid[yy][b.x0 : b.x1 + 1])
                            for yy in range(b.y0, b.y1 + 1)
                        ),
                    )
                )

    # The plaza: the fountain where the avenue crosses the first street, and
    # a planted square where it crosses the second.
    first, second = streets[0], streets[-1]
    fy = first.start + STREET // 2
    fountain = ((mid - 1, fy - 1), (mid, fy - 1), (mid - 1, fy), (mid, fy))
    sy = second.start + STREET // 2
    square = ((mid - 1, sy - 1), (mid, sy - 1), (mid - 1, sy), (mid, sy))
    plaza_spots = _plaza(grid, fountain, tuple(buildings), centre="fountain")
    plaza_spots += _plaza(grid, square, (), centre="planter")
    seats[(PLAZA, 0)] = ()
    visitors[(PLAZA, 0)] = tuple(plaza_spots)
    for x, yy in fountain:
        zones[yy][x] = PLAZA

    # Trees: down the alley behind the second row, and in the margins.
    alley = range(row_y[1] + OUTER_DEPTH, row_y[2])
    for yy in alley:
        for x in range(3, width - 3, 4):
            if grid[yy][x] == "grass" and (x + yy) % 3 == 0:
                grid[yy][x] = "tree"
    for x in range(1, width - 1, 5):
        for yy in (0, height - 1):
            if grid[yy][x] == "grass":
                grid[yy][x] = "tree"

    entries: tuple[Tile, ...] = (
        (mid - 1, 0),
        (mid, height - 1),
        (0, fy),
        (width - 1, fy + 1),
        (0, sy),
        (width - 1, sy + 1),
    )
    return TownMap(
        width=width,
        height=height,
        tiles=tuple(tuple(row) for row in grid),
        zones=tuple(tuple(row) for row in zones),
        buildings=tuple(buildings),
        storeys=tuple(storeys),
        seats=seats,
        visitor_spots=visitors,
        entries=entries,
        fountain=fountain,
    )


WIDTH = town().width
HEIGHT = town().height


def find_path(start: Node, goal: Node) -> list[Node]:
    """A* over walkable nodes, four-connected on a floor and up or down a stair.
    Includes both ends.

    Deterministic: ties on cost break on the node itself, so the same two
    points give the same route on every run and every machine. Returns an
    empty list when there is no route, which on this map means a bug.
    """

    world = town()
    if start == goal:
        return [start]
    if not world.walkable(goal):
        return []

    def estimate(node: Node) -> int:
        return (
            abs(node[0] - goal[0])
            + abs(node[1] - goal[1])
            + STAIR_STEPS * abs(node[2] - goal[2])
        )

    def neighbours(node: Node) -> list[tuple[Node, int]]:
        x, y, floor = node
        out: list[tuple[Node, int]] = []
        for step in (
            (x + 1, y, floor),
            (x - 1, y, floor),
            (x, y + 1, floor),
            (x, y - 1, floor),
        ):
            if world.walkable(step):
                out.append((step, 1))
        if world.kind(node) == "stair":
            for other in (floor + 1, floor - 1):
                if (
                    world.walkable((x, y, other))
                    and world.kind((x, y, other)) == "stair"
                ):
                    out.append(((x, y, other), STAIR_STEPS))
        return out

    frontier: list[tuple[int, int, Node]] = [(estimate(start), 0, start)]
    came_from: dict[Node, Node] = {}
    cost: dict[Node, int] = {start: 0}
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
        for step, price in neighbours(current):
            total = spent + price
            if total < cost.get(step, 1 << 30):
                cost[step] = total
                came_from[step] = current
                heapq.heappush(frontier, (total + estimate(step), total, step))
    return []


def spot_for(
    zone: str,
    floor: int,
    *,
    own: bool,
    staff_index: int,
    taken: set[Node],
    salt: int,
) -> Tile:
    """Where someone stands on a floor.

    At their own workplace, their own seat. Anywhere else, the first free
    visitor spot, starting from a position that varies by person and arrival
    so visitors do not all queue for the same chair.
    """

    world = town()
    if own and world.seats.get((zone, floor)):
        seats = world.seats[(zone, floor)]
        return seats[staff_index % len(seats)]
    spots = world.visitor_spots[(zone, floor)]
    for offset in range(len(spots)):
        candidate = spots[(salt + offset) % len(spots)]
        if (*candidate, floor) not in taken:
            return candidate
    return spots[salt % len(spots)]


def entry_for(tile: Tile) -> Node:
    """The map edge someone walking in from home arrives at."""

    world = town()
    x, y = min(world.entries, key=lambda e: abs(e[0] - tile[0]) + abs(e[1] - tile[1]))
    return (x, y, 0)


GLYPHS = {
    "grass": ",", "plaza": ".", "path": ":", "wall": "#", "floor": " ",
    "door": "D", "desk": "d", "counter": "=", "table": "t", "tree": "T",
    "fountain": "~", "chair": "h", "bench": "n", "sofa": "s",
    "whiteboard": "w", "server_rack": "S", "bookshelf": "B",
    "conference": "c", "reception": "r", "filing": "f", "partition": "|",
    "kitchen": "k", "kitchenette": "K", "plant": "p", "planter": "P", "lamp": "i",
    "stair": "^", "shelf": "H", "rack": "R", "equipment": "E",
    "dental_chair": "U", "teller": "=", "void": " ",
}  # fmt: skip


def ascii_map(zone: str | None = None, floor: int = 0) -> str:
    """The ground, or one storey of one building."""

    world = town()
    if floor == 0 and zone is None:
        return "\n".join("".join(GLYPHS[k] for k in row) for row in world.tiles)
    assert zone is not None
    for storey in world.storeys:
        if storey.zone == zone and storey.floor == floor:
            return "\n".join("".join(GLYPHS[k] for k in row) for row in storey.tiles)
    b = world.building(zone)
    return "\n".join(
        "".join(GLYPHS[k] for k in row[b.x0 : b.x1 + 1])
        for row in world.tiles[b.y0 : b.y1 + 1]
    )
