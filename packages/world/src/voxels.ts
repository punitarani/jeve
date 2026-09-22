/**
 * The town as boxes. Pure data: a list of (position, size, colour, corner
 * occlusion, floor), so it can be inspected and tested without a GPU. The
 * renderer turns the list into instanced meshes — per storey, one draw call
 * for everything lit and one for everything that glows.
 *
 * All geometry is procedural. There are no sprites, models or textures from
 * anywhere, so there is nothing here to license.
 *
 * WEB-0004: what makes boxes read as a place rather than a diagram is baked
 * here, once, and costs nothing per frame. Each box carries eight occlusion
 * numbers, one per corner, from asking how much of its own floor stands above
 * that corner; and each block's colour is nudged by a hash of where it is, so
 * a wall is made of blocks and a lawn is not one green.
 *
 * Nothing here knows a firm's id or colours (WORLD-0006): a building's
 * palette comes with it on `/world/map`, and what a kind of firm builds —
 * how tall, what floor, what hangs over the door — is a table keyed by
 * `Building.kind` with a default, so a thirteenth firm renders unasked.
 */
import type { Building, Storey, TileKind, TownMap } from "@jeve/contracts";

/**
 * One storey, in world units: the slab of the floor above sits here, and a
 * person on floor `n` is drawn at `n * STOREY`.
 */
export const STOREY = 2.4;

/** Corner order: index = (x > 0 ? 1 : 0) + (z > 0 ? 2 : 0) + (y > 0 ? 4 : 0). */
export type CornerOcclusion = [number, number, number, number, number, number, number, number];

/**
 * What an unlit voxel is, which decides how it is coloured through the day:
 * glass by day and lit from inside at night, a lamp that is grey until dusk,
 * a screen or a sign's lettering that is always on, a pool of light on the
 * ground under a lamp.
 */
export type Glow = "window" | "lamp" | "screen" | "sign" | "pool";

export type Voxel = {
  x: number;
  y: number;
  z: number;
  sx: number;
  sy: number;
  sz: number;
  color: string;
  /** Multipliers in 0..1, one per corner; 1 is open sky. */
  ao: CornerOcclusion;
  /** Set on voxels that are drawn unlit. Absent on everything the sun lights. */
  glow?: Glow;
  /** The storey it belongs to, so the renderer can show or hide a floor at a time. */
  floor: number;
};

type Palette = Building["palette"];

/** A tile's kind at (tx, ty) on one floor's grid, or undefined off that grid. */
export type KindAt = (tx: number, ty: number) => TileKind | undefined;

/** The ground floor: `map.tiles`, the whole town. */
export function groundKinds(map: TownMap): KindAt {
  return (tx, ty) => map.tiles[ty]?.[tx];
}

/** An upper floor: a local grid over its building's footprint. */
export function storeyKinds(storey: Storey): KindAt {
  return (tx, ty) => storey.tiles[ty - storey.y0]?.[tx - storey.x0];
}

// -- what a kind of firm builds ---------------------------------------------

type Dressing = "awning" | "portico" | "mast" | "boxes" | "none";

type KindStyle = {
  /**
   * How tall the top storey's wall is. Roofs are absent (WEB-0002), so this is
   * how much of the room the camera sees, and with the parapet's colour most
   * of what a silhouette has to say. A storey with another above it is a full
   * `STOREY` tall whatever the kind, so the slab has something to sit on.
   */
  wall: number;
  /**
   * What they walk on. A floor is most of what the camera sees of a roofless
   * building, so it is a material, not a tint: carpet tiles, parquet, lino, a
   * cafe's checkerboard.
   */
  floor: (tx: number, ty: number, tint: string) => string;
  /** A chair's seat and frame. */
  chair: [string, string];
  /** Tables are stood round, not sat at: nobody sits in a stand-up. */
  standingTables: boolean;
  /** What the building wears over its door (audit D4). */
  dressing: Dressing;
};

const DEFAULT_STYLE: KindStyle = {
  wall: 1.5,
  floor: (tx, ty, tint) => jitter(blend("#cfcac0", tint, 0.3), 0.04, tx, ty, 35),
  chair: ["#5a5f6b", "#2c2f38"],
  standingTables: false,
  dressing: "boxes",
};

/** Keyed by `Building.kind`. Anything not here gets `DEFAULT_STYLE`. */
const KIND_STYLES: Record<string, Partial<KindStyle>> = {
  software: {
    wall: 1.6,
    floor: (tx, ty, tint) => jitter(blend("#8d97ab", tint, 0.25), 0.05, tx >> 1, ty >> 1, 31),
    chair: ["#3d4558", "#23262f"],
    standingTables: true,
    dressing: "mast",
  },
  law: {
    wall: 2.0,
    // Boards run east-west, two tiles long, staggered row by row.
    floor: (tx, ty) => jitter("#a9784a", 0.09, (tx + ty) >> 1, ty, 32),
    chair: ["#6b3f2a", "#3a2a20"],
    dressing: "portico",
  },
  accounting: {
    wall: 1.45,
    floor: (tx, ty, tint) => jitter(blend("#b9c4b2", tint, 0.3), 0.04, tx, ty, 33),
    chair: ["#52705f", "#2f3a34"],
  },
  property: {
    wall: 1.6,
    floor: (tx, ty, tint) => jitter(blend("#9a9aa6", tint, 0.3), 0.05, tx >> 1, ty >> 1, 37),
    chair: ["#4a5568", "#23262f"],
  },
  cafe: {
    wall: 1.2,
    floor: (tx, ty) => jitter((tx + ty) % 2 === 0 ? "#e4d3bd" : "#b8705a", 0.04, tx, ty, 34),
    chair: ["#c99a62", "#7d5a36"],
    dressing: "awning",
  },
  clinic: {
    wall: 1.5,
    floor: (tx, ty, tint) => jitter(blend("#d8dedb", tint, 0.2), 0.03, tx, ty, 38),
    chair: ["#cfe4ec", "#8a9099"],
  },
  studio: {
    wall: 1.7,
    floor: (tx, ty, tint) => jitter(blend("#b9b5ad", tint, 0.2), 0.05, tx, ty, 39),
    chair: ["#d9944a", "#3a3f4a"],
  },
  bank: {
    wall: 2.0,
    // Marble, in two-tile slabs.
    floor: (tx, ty, tint) =>
      jitter(blend(((tx >> 1) + (ty >> 1)) % 2 === 0 ? "#d9d4c8" : "#c9c3b6", tint, 0.15), 0.03, tx >> 1, ty >> 1, 40),
    chair: ["#2f4a7a", "#23262f"],
    dressing: "portico",
  },
  hardware: {
    wall: 1.5,
    floor: (tx, ty) => jitter("#a8a49c", 0.06, tx, ty, 42),
    chair: ["#5f4331", "#3a2a20"],
    dressing: "awning",
  },
  gym: {
    wall: 1.8,
    floor: (tx, ty, tint) => jitter(blend("#4a4f55", tint, 0.25), 0.05, tx, ty, 43),
    chair: ["#2c2f38", "#4a4f58"],
    dressing: "none",
  },
  supplier: {
    wall: 1.9,
    floor: (tx, ty) => jitter("#9d9a92", 0.06, tx, ty, 44),
    chair: ["#5f4331", "#3a2a20"],
    dressing: "none",
  },
};

function styleOf(kind: string | undefined): KindStyle {
  const own = kind === undefined ? undefined : KIND_STYLES[kind];
  return own === undefined ? DEFAULT_STYLE : { ...DEFAULT_STYLE, ...own };
}

/** How tall a wall on `floor` of `building` is; a storey under another is a full one. */
function wallHeight(building: Building | undefined, floor: number): number {
  if (building === undefined) return DEFAULT_STYLE.wall;
  return floor < building.floors - 1 ? STOREY : styleOf(building.kind).wall;
}

/** The top of a building's highest wall. */
function roofOf(building: Building): number {
  return (building.floors - 1) * STOREY + wallHeight(building, building.floors - 1);
}

const GROUND: Partial<Record<TileKind, string>> = {
  grass: "#6fae58",
  plaza: "#cfc6b2",
  path: "#e3dac6",
  tree: "#6fae58",
  fountain: "#cfc6b2",
};

/** How much of the sky a tile's contents block, as (height, how much of the tile they fill). */
const SOLID: Partial<Record<TileKind, [number, number]>> = {
  desk: [0.45, 0.6],
  counter: [0.92, 0.9],
  table: [0.42, 0.45],
  tree: [1.1, 0.4],
  fountain: [0.42, 1],
  chair: [0.3, 0.25],
  bench: [0.3, 0.4],
  sofa: [0.5, 0.7],
  stair: [1.6, 0.85],
  server_rack: [1.5, 0.75],
  bookshelf: [1.4, 0.5],
  conference: [0.46, 0.85],
  reception: [0.95, 0.7],
  filing: [1.1, 0.5],
  partition: [1.25, 0.25],
  kitchen: [0.92, 0.75],
  kitchenette: [0.9, 0.7],
  shelf: [1.45, 0.4],
  rack: [1.9, 0.6],
  equipment: [1.0, 0.45],
  dental_chair: [0.9, 0.5],
  teller: [1.9, 0.75],
  plant: [0.9, 0.3],
  planter: [0.7, 0.8],
};

/** What one sits at, or stands at: a chair is drawn up to it and faces it. */
export const SURFACES: ReadonlySet<TileKind> = new Set<TileKind>([
  "desk",
  "table",
  "counter",
  "conference",
  "reception",
  "teller",
  "kitchenette",
  "equipment",
  "rack",
  "shelf",
]);

/** Unit steps on the grid, as (dx, dz). North is -z. */
export type Dir = [number, number];
const SIDES: Dir[] = [
  [0, -1],
  [0, 1],
  [-1, 0],
  [1, 0],
];

/** The side of a tile on which a neighbour of one of `kinds` lies, if any. */
export function sideWith(
  kinds: KindAt,
  tx: number,
  ty: number,
  wanted: ReadonlySet<TileKind>,
): Dir | null {
  for (const side of SIDES) {
    const kind = kinds(tx + side[0], ty + side[1]);
    if (kind !== undefined && wanted.has(kind)) return side;
  }
  return null;
}

const BACKING: ReadonlySet<TileKind> = new Set<TileKind>(["wall"]);
const CHAIRS: ReadonlySet<TileKind> = new Set<TileKind>(["chair"]);

/** The middle of the fountain, which is what the plaza looks at. */
export function fountainOf(map: TownMap): [number, number] | null {
  let n = 0;
  let sx = 0;
  let sz = 0;
  map.tiles.forEach((row, ty) =>
    row.forEach((kind, tx) => {
      if (kind !== "fountain") return;
      n++;
      sx += tx;
      sz += ty;
    }),
  );
  return n === 0 ? null : [sx / n, sz / n];
}

/**
 * Which way a tile faces when nobody has said: towards the desk, table or
 * counter beside it, or, from a bench, towards the fountain. The chair is
 * drawn by this and the person on it is turned by this, so they agree.
 */
export function facingAt(
  kinds: KindAt,
  tx: number,
  ty: number,
  fountain: [number, number] | null,
): Dir | null {
  if (kinds(tx, ty) !== "bench") return sideWith(kinds, tx, ty, SURFACES);
  if (fountain === null) return null;
  const [dx, dz] = [fountain[0] - tx, fountain[1] - ty];
  return Math.abs(dx) >= Math.abs(dz) ? [Math.sign(dx), 0] : [0, Math.sign(dz)];
}

const OPEN: CornerOcclusion = [1, 1, 1, 1, 1, 1, 1, 1];

// -- colour -----------------------------------------------------------------

/** Three by five: the smallest letters that are still letters. */
const FONT: Record<string, string[]> = {
  A: [".#.", "#.#", "###", "#.#", "#.#"],
  B: ["##.", "#.#", "##.", "#.#", "##."],
  C: [".##", "#..", "#..", "#..", ".##"],
  D: ["##.", "#.#", "#.#", "#.#", "##."],
  E: ["###", "#..", "##.", "#..", "###"],
  F: ["###", "#..", "##.", "#..", "#.."],
  G: [".##", "#..", "#.#", "#.#", ".##"],
  H: ["#.#", "#.#", "###", "#.#", "#.#"],
  I: ["###", ".#.", ".#.", ".#.", "###"],
  J: ["..#", "..#", "..#", "#.#", ".#."],
  K: ["#.#", "#.#", "##.", "#.#", "#.#"],
  L: ["#..", "#..", "#..", "#..", "###"],
  M: ["#.#", "###", "###", "#.#", "#.#"],
  N: ["##.", "#.#", "#.#", "#.#", "#.#"],
  O: [".#.", "#.#", "#.#", "#.#", ".#."],
  P: ["##.", "#.#", "##.", "#..", "#.."],
  Q: [".#.", "#.#", "#.#", "###", ".##"],
  R: ["##.", "#.#", "##.", "#.#", "#.#"],
  S: [".##", "#..", ".#.", "..#", "##."],
  T: ["###", ".#.", ".#.", ".#.", ".#."],
  U: ["#.#", "#.#", "#.#", "#.#", "###"],
  V: ["#.#", "#.#", "#.#", "#.#", ".#."],
  W: ["#.#", "#.#", "###", "###", "#.#"],
  X: ["#.#", "#.#", ".#.", "#.#", "#.#"],
  Y: ["#.#", "#.#", ".#.", ".#.", ".#."],
  Z: ["###", "..#", ".#.", "#..", "###"],
  "0": ["###", "#.#", "#.#", "#.#", "###"],
  "1": [".#.", "##.", ".#.", ".#.", "###"],
  "2": ["##.", "..#", ".#.", "#..", "###"],
  "3": ["##.", "..#", ".#.", "..#", "##."],
  "4": ["#.#", "#.#", "###", "..#", "..#"],
  "5": ["###", "#..", "##.", "..#", "##."],
  "6": [".##", "#..", "###", "#.#", "###"],
  "7": ["###", "..#", ".#.", ".#.", ".#."],
  "8": ["###", "#.#", "###", "#.#", "###"],
  "9": ["###", "#.#", "###", "..#", "##."],
  "&": [".#.", "#.#", ".#.", "#.#", ".##"],
};

/** The first letter of each of a name's first three words, if the font has it. */
export function monogram(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 3)
    .map((word) => word.charAt(0).toUpperCase())
    .filter((letter) => FONT[letter] !== undefined)
    .join("");
}

/** A stable number in 0..1 from tile coordinates. Never `Math.random`. */
export function hash2(x: number, y: number, salt = 0): number {
  let n = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(salt | 0, 362437);
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
}

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function hex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  const value = (clamp(r) << 16) | (clamp(g) << 8) | clamp(b);
  return `#${value.toString(16).padStart(6, "0")}`;
}

export function shade(color: string, amount: number): string {
  const [r, g, b] = rgb(color);
  return hex(r * (1 + amount), g * (1 + amount), b * (1 + amount));
}

/** Towards grey. Firm colours are chosen for a legend, and are loud on a wall. */
function mute(color: string, amount: number): string {
  const [r, g, b] = rgb(color);
  const grey = r * 0.3 + g * 0.59 + b * 0.11;
  return hex(r + (grey - r) * amount, g + (grey - g) * amount, b + (grey - b) * amount);
}

/** The parapet: the firm's own colour at full strength, the one loud line on a building. */
function capOf(palette: Palette | undefined): string {
  return palette === undefined ? "#555555" : blend(palette.wall, palette.accent, 0.45);
}

/** The firm's colour, let down with plaster: at full strength under a filmic curve it came out as poster paint. */
function plasterOf(palette: Palette | undefined): string {
  return blend(mute(palette?.wall ?? "#888888", 0.15), "#e6dfd0", 0.42);
}

function blend(a: string, b: string, t: number): string {
  const [ar, ag, ab] = rgb(a);
  const [br, bg, bb] = rgb(b);
  return hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t);
}

/**
 * Block-to-block variation: brightness, and a little warm-or-cool, from a hash
 * of where the block is. The same town every time, on every machine.
 */
function jitter(color: string, amount: number, x: number, y: number, salt = 0): string {
  const [r, g, b] = rgb(color);
  const light = 1 + (hash2(x, y, salt) - 0.5) * 2 * amount;
  const warm = (hash2(x, y, salt + 17) - 0.5) * amount * 60;
  return hex(r * light + warm, g * light, b * light - warm);
}

// -- occlusion --------------------------------------------------------------

/** One floor's contents, as heights over that floor: what shades what on it. */
type Field = {
  x0: number;
  y0: number;
  width: number;
  depth: number;
  /** The floor's own height in the world: heights in `height` are over it. */
  base: number;
  height: Float32Array;
  fill: Float32Array;
};

function heightField(
  kinds: KindAt,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  base: number,
  wallAt: (tx: number, ty: number) => number,
): Field {
  const width = x1 - x0 + 1;
  const depth = y1 - y0 + 1;
  const height = new Float32Array(width * depth);
  const fill = new Float32Array(width * depth);
  for (let ty = y0; ty <= y1; ty++) {
    for (let tx = x0; tx <= x1; tx++) {
      const kind = kinds(tx, ty);
      if (kind === undefined) continue;
      const solid: [number, number] | undefined =
        kind === "wall" ? [wallAt(tx, ty), 1] : SOLID[kind];
      if (solid === undefined) continue;
      const i = (ty - y0) * width + (tx - x0);
      height[i] = solid[0];
      fill[i] = solid[1];
    }
  }
  return { x0, y0, width, depth, base, height, fill };
}

const REACH = 0.3;
const STRENGTH = 0.78;
const CONTACT = 0.72;

/**
 * Eight corner multipliers for a box.
 *
 * For each corner, look a little way out on the four diagonals and ask how
 * much of each tile found there stands above the corner. Two of four is a
 * floor tile against a wall; three of four is the inside of a corner, and it
 * is the darkest place in a room, as it should be. A box that stands on the
 * floor also loses light along its foot. `own` is the tile a piece of
 * furniture stands in, which does not shade itself; the ground passes nothing,
 * because a floor tile *is* shaded by the desk on it.
 */
function occlusion(
  field: Field,
  v: { x: number; y: number; z: number; sx: number; sy: number; sz: number },
  own: [number, number] | null,
): CornerOcclusion {
  const out: CornerOcclusion = [1, 1, 1, 1, 1, 1, 1, 1];
  for (let corner = 0; corner < 8; corner++) {
    const cx = v.x + ((corner & 1) === 0 ? -0.5 : 0.5) * v.sx;
    const cz = v.z + ((corner & 2) === 0 ? -0.5 : 0.5) * v.sz;
    const cy = v.y + ((corner & 4) === 0 ? -0.5 : 0.5) * v.sy;
    let blocked = 0;
    for (let s = 0; s < 4; s++) {
      const tx = Math.round(cx + ((s & 1) === 0 ? -REACH : REACH)) - field.x0;
      const tz = Math.round(cz + ((s & 2) === 0 ? -REACH : REACH)) - field.y0;
      if (tx < 0 || tz < 0 || tx >= field.width || tz >= field.depth) continue;
      if (own !== null && own[0] - field.x0 === tx && own[1] - field.y0 === tz) continue;
      const i = tz * field.width + tx;
      const above = field.base + (field.height[i] ?? 0) - cy;
      if (above <= 0.02) continue;
      blocked += (field.fill[i] ?? 0) * Math.min(1, above / 0.8);
    }
    let light = 1 - (STRENGTH * blocked) / 4;
    if (own !== null && cy - field.base < 0.06) light *= CONTACT;
    out[corner] = Math.max(0.25, light);
  }
  return out;
}

// -- the town ---------------------------------------------------------------

/** How far the country runs past the last tile, as a fraction of the map's
 * longer side. A wider district gets a wider country. */
export const OUTSKIRTS_REACH = 0.7;
/**
 * What a CPU rasteriser gets instead. The meadow is most of the boxes and
 * nobody walks on it, so a software renderer draws a shallower country rather
 * than none: a town on bare ground is the one thing that reads as broken, and
 * every screenshot this machine takes is of a town on bare ground (WEB-0003).
 */
export const OUTSKIRTS_REACH_SOFTWARE = 0.25;

/**
 * Every static box in the town, every storey of it. y is up; x and z are the
 * tile grid. `outskirts` is how far the country past the last tile runs, as a
 * fraction of the map's longer side; 0 leaves the town on bare ground.
 */
export function buildVoxels(
  map: TownMap,
  { outskirts = OUTSKIRTS_REACH }: { outskirts?: number } = {},
): Voxel[] {
  const voxels: Voxel[] = [];
  const byZone = new Map<string, Building>(map.buildings.map((b) => [b.zone, b]));
  const ground = groundKinds(map);
  const fountain = fountainOf(map);
  const footprintOf = (tx: number, ty: number): Building | undefined =>
    map.buildings.find((b) => tx >= b.x0 && tx <= b.x1 && ty >= b.y0 && ty <= b.y1);

  /** An unshaded box, for what stands clear of everything; on the ground floor unless told the storey it belongs to. */
  const plain = (x: number, y: number, z: number, sx: number, sy: number, sz: number, color: string, floor = 0) =>
    voxels.push({ x, y, z, sx, sy, sz, color, ao: OPEN, floor });
  const glowOn = (
    floor: number,
    kind: Glow,
    x: number,
    y: number,
    z: number,
    sx: number,
    sy: number,
    sz: number,
    color: string,
  ) => voxels.push({ x, y, z, sx, sy, sz, color, ao: OPEN, glow: kind, floor });

  /**
   * One floor, furnished. Written once and run for the ground and for every
   * storey: `kinds` is that floor's grid, the bounds are in world tiles, and
   * `lift` is the floor's height, added to every box. The ground floor alone
   * has an outdoors — lawns, paving, the terrace, trees, the fountain.
   */
  function furnish(
    kinds: KindAt,
    floor: number,
    x0: number,
    y0: number,
    x1: number,
    y1: number,
    zoneAt: (tx: number, ty: number) => string | undefined,
  ): void {
    const lift = floor * STOREY;
    const buildingAt = (tx: number, ty: number): Building | undefined => {
      const zone = zoneAt(tx, ty);
      return zone === undefined ? undefined : byZone.get(zone);
    };
    const field = heightField(kinds, x0, y0, x1, y1, lift, (tx, ty) =>
      wallHeight(buildingAt(tx, ty), floor),
    );

    /** A lit box standing in tile `own` (or the floor itself, when null). */
    const box = (
      own: [number, number] | null,
      x: number,
      y: number,
      z: number,
      sx: number,
      sy: number,
      sz: number,
      color: string,
    ) => {
      const v = { x, y: y + lift, z, sx, sy, sz };
      voxels.push({ ...v, color, ao: occlusion(field, v, own), floor });
    };
    const glow = (kind: Glow, x: number, y: number, z: number, sx: number, sy: number, sz: number, color: string) =>
      glowOn(floor, kind, x, y + lift, z, sx, sy, sz, color);

    /**
     * A pane of glass through every third block of an outside wall, standing a
     * hair proud of both faces so it shows from the street and from the room.
     * Unlit: pale sky by day, lit from inside at night, which is most of what
     * tells a visitor that it *is* night.
     */
    const windowIn = (tx: number, ty: number, tall: number): void => {
      const wallAt = (x: number, y: number) => kinds(x, y) === "wall";
      const alongX = wallAt(tx - 1, ty) && wallAt(tx + 1, ty);
      const alongZ = wallAt(tx, ty - 1) && wallAt(tx, ty + 1);
      if (alongX === alongZ) return; // a corner, a junction or a stub
      if ((alongX ? tx : ty) % 3 !== 1) return;
      const y = tall * 0.56;
      const high = tall * 0.36;
      // A painted frame a little proud of the wall, and the glass proud of that.
      const trim = "#f1ede4";
      if (alongX) {
        voxels.push({ x: tx, y: y + lift, z: ty, sx: 0.76, sy: high + 0.14, sz: 1.02, color: trim, ao: OPEN, floor });
        glow("window", tx, y, ty, 0.62, high, 1.04, "#bfe0f5");
      } else {
        voxels.push({ x: tx, y: y + lift, z: ty, sx: 1.02, sy: high + 0.14, sz: 0.76, color: trim, ao: OPEN, floor });
        glow("window", tx, y, ty, 1.04, high, 0.62, "#bfe0f5");
      }
      // What a lit window throws on the floor, inside and out.
      glow("pool", tx, 0.03, ty, 4.2, 0, 4.2, "#ffc774");
    };

    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        const kind = kinds(tx, ty);
        // Off the grid, or the nothing outside a storey's footprint.
        if (kind === undefined || kind === "void") continue;
        const own: [number, number] = [tx, ty];
        const building = buildingAt(tx, ty);
        const palette = building?.palette;
        const style = styleOf(building?.kind);
        const indoors = floor > 0 || footprintOf(tx, ty) !== undefined;

        // The floor under everything but walls, which stand on their own foot.
        // Interiors take the firm's material and a tint of its colour, so a
        // building reads as belonging to someone from any zoom. Outdoors is
        // laid in 2x2 pavers.
        if (kind !== "wall") {
          const base = GROUND[kind];
          const paving = jitter(GROUND.plaza ?? "#cfc6b2", 0.05, tx >> 1, ty >> 1, 3);
          const surface =
            base !== undefined
              ? kind === "plaza" || kind === "fountain"
                ? paving
                : jitter(base, kind === "path" ? 0.035 : 0.09, tx, ty, 1)
              : indoors
                ? style.floor(tx, ty, palette?.floor ?? "#dddddd")
                : kind === "chair" || kind === "table"
                  ? // A terrace: boards under the tables outside the cafe.
                    jitter("#a9825a", 0.08, tx, ty >> 1, 36)
                  : paving;
          box(null, tx, -0.1, ty, 1, 0.2, 1, surface);
        }
        // Furniture is drawn in its own frame: +z is the way it faces.
        const facing = (dir: Dir | null): Dir => dir ?? [0, 1];
        const away = (dir: Dir | null): Dir => (dir === null ? [0, 1] : [-dir[0], -dir[1]]);
        const place =
          ([dx, dz]: Dir) =>
          (lx: number, y: number, lz: number, sx: number, sy: number, sz: number, color: string) =>
            box(own, tx + lx * dz + lz * dx, y, ty - lx * dx + lz * dz, dx !== 0 ? sz : sx, sy, dx !== 0 ? sx : sz, color);
        const light =
          ([dx, dz]: Dir) =>
          (k: Glow, lx: number, y: number, lz: number, sx: number, sy: number, sz: number, color: string) =>
            glow(k, tx + lx * dz + lz * dx, y, ty - lx * dx + lz * dz, dx !== 0 ? sz : sx, sy, dx !== 0 ? sx : sz, color);
        /** Towards the door: where a customer stands, and what a counter faces. */
        const toDoor: Dir = building === undefined || building.faces_south ? [0, 1] : [0, -1];

        switch (kind) {
          case "wall": {
            // Roofless, so the people inside are the point of the picture. Laid
            // in three courses, each block its own shade: a wall built of
            // something, not extruded.
            const tall = wallHeight(building, floor);
            const wall = plasterOf(palette);
            const courses = 3;
            const each = tall / courses;
            for (let c = 0; c < courses; c++) {
              // Offset alternate courses by half a block, like brickwork.
              const bond = c % 2 === 0 ? tx + ty : tx + ty + 1;
              box(own, tx, each * (c + 0.5), ty, 1, each, 1, jitter(wall, 0.07, bond >> 1, c + floor * 3, ty - tx));
            }
            // The parapet, on the top storey only: below it the next slab sits.
            if (floor === (building?.floors ?? 1) - 1) {
              box(own, tx, tall + 0.07, ty, 1, 0.14, 1, jitter(capOf(palette), 0.05, tx, ty, 5));
            }
            windowIn(tx, ty, tall);
            break;
          }
          case "door":
            box(own, tx, 0.02, ty, 1, 0.05, 1, palette?.accent ?? "#555555");
            break;
          case "stair": {
            // Three treads rising away from the door into the far corner, where
            // the flight above lands; a rail on the open side.
            const up: Dir = building === undefined || building.faces_south ? [0, -1] : [0, 1];
            const at = place(up);
            const tread = jitter("#8d7a63", 0.05, tx, ty, 90);
            for (let step = 0; step < 3; step++) {
              const h = (STOREY * (step + 1)) / 4;
              at(0, h / 2, -1 / 3 + step / 3, 0.86, h, 1 / 3, shade(tread, step * 0.05));
            }
            at(0.45, STOREY * 0.42, 0, 0.06, STOREY * 0.84, 0.96, "#3a3f4a");
            at(0.45, STOREY * 0.84, 0, 0.06, 0.06, 0.96, "#6f4d31");
            break;
          }
          case "desk": {
            // Turned to whoever sits at it: the screen faces the chair.
            const front = facing(sideWith(kinds, tx, ty, CHAIRS));
            const at = place(front);
            at(0, 0.4, 0, 0.94, 0.1, 0.72, jitter("#b98a55", 0.06, tx, ty));
            at(-0.36, 0.175, 0, 0.1, 0.35, 0.62, "#7d5a36");
            at(0.36, 0.175, 0, 0.1, 0.35, 0.62, "#7d5a36");
            at(0.1, 0.64, -0.14, 0.5, 0.34, 0.06, "#23262f");
            light(front)("screen", 0.1, 0.65, -0.105, 0.43, 0.27, 0.01, "#9fd0ff");
            at(0.1, 0.47, -0.14, 0.08, 0.06, 0.08, "#23262f");
            at(-0.05, 0.46, 0.14, 0.34, 0.02, 0.12, "#d9dde1");
            break;
          }
          case "counter":
            box(own, tx, 0.4, ty, 1, 0.8, 0.72, jitter("#8b5a3c", 0.06, tx, ty));
            box(own, tx, 0.85, ty, 1, 0.1, 0.84, jitter("#eadfca", 0.04, tx, ty));
            break;
          case "teller": {
            // A counter with a glass screen over it, facing whoever queues.
            const at = place(toDoor);
            at(0, 0.45, 0, 1, 0.9, 0.7, blend(palette?.wall ?? "#888888", "#3a2a20", 0.35));
            at(0, 0.93, 0, 1, 0.06, 0.8, "#efe6d2");
            at(0, 1.42, -0.06, 1, 0.9, 0.05, "#cfe4ec");
            at(0, 1.9, -0.06, 1, 0.06, 0.12, "#56606b");
            at(-0.2, 0.99, 0.12, 0.34, 0.02, 0.24, "#d9dde1");
            break;
          }
          case "table":
            if (style.standingTables) {
              // A high table to stand round: nobody sits in a stand-up.
              box(own, tx, 1.0, ty, 0.8, 0.07, 0.8, "#e9edf2");
              box(own, tx, 0.5, ty, 0.12, 0.96, 0.12, "#3a3f4a");
              box(own, tx, 0.03, ty, 0.5, 0.05, 0.5, "#3a3f4a");
              box(own, tx + 0.15, 1.08, ty - 0.1, 0.22, 0.02, 0.3, "#2b2f3a");
            } else {
              const cloth = indoors ? "#eadfca" : "#f3efe6";
              box(own, tx, 0.4, ty, 0.78, 0.08, 0.78, jitter(cloth, 0.05, tx, ty));
              box(own, tx, 0.18, ty, 0.14, 0.36, 0.14, "#5f4331");
              box(own, tx + 0.12, 0.49, ty + 0.1, 0.1, 0.1, 0.1, "#fafafa");
              if (!indoors) {
                // A parasol: the terrace is the one place with a roof of any kind.
                const stripe = hash2(tx, ty, 41) > 0.5 ? "#c8453c" : "#e9b44c";
                box(own, tx, 1.05, ty, 0.07, 1.3, 0.07, "#6f4d31");
                box(own, tx, 1.72, ty, 1.5, 0.08, 1.5, stripe);
                box(own, tx, 1.8, ty, 0.8, 0.08, 0.8, "#f3efe6");
              }
            }
            break;
          case "chair": {
            const at = place(facing(facingAt(kinds, tx, ty, floor === 0 ? fountain : null)));
            const [seat, frame] = style.chair;
            at(0, 0.235, 0, 0.5, 0.07, 0.5, seat);
            at(0, 0.11, 0, 0.1, 0.2, 0.1, frame);
            at(0, 0.025, 0, 0.42, 0.05, 0.42, frame);
            at(0, 0.52, -0.27, 0.5, 0.5, 0.07, seat);
            break;
          }
          case "sofa": {
            // Low and wide, in the firm's accent, its back to the wall it is against.
            const at = place(away(sideWith(kinds, tx, ty, BACKING)));
            const cushion = palette?.accent ?? "#7a5a4a";
            at(0, 0.2, 0.05, 0.96, 0.32, 0.7, cushion);
            at(0, 0.5, -0.32, 0.96, 0.44, 0.16, shade(cushion, -0.1));
            at(-0.42, 0.36, 0.05, 0.12, 0.28, 0.7, shade(cushion, -0.15));
            at(0.42, 0.36, 0.05, 0.12, 0.28, 0.7, shade(cushion, -0.15));
            at(0, 0.03, 0, 0.8, 0.06, 0.5, "#3a2a20");
            break;
          }
          case "dental_chair": {
            // Reclined: a seat, and a back leaning away from it in three steps
            // of thirty degrees' worth, under a lamp on an arm.
            const front = facing(sideWith(kinds, tx, ty, CHAIRS));
            const at = place(front);
            at(0, 0.18, 0, 0.4, 0.36, 0.4, "#8a9099");
            at(0, 0.5, 0.12, 0.6, 0.12, 0.66, "#cfe4ec");
            for (let i = 0; i < 3; i++) {
              at(0, 0.56 + i * 0.16, -0.26 - i * 0.1, 0.6, 0.16, 0.14, "#cfe4ec");
            }
            at(0.34, 1.0, 0.1, 0.05, 1.1, 0.05, "#8a9099");
            at(0.2, 1.55, 0.1, 0.34, 0.04, 0.05, "#8a9099");
            light(front)("lamp", 0.05, 1.5, 0.1, 0.26, 0.08, 0.26, "#fff1c4");
            break;
          }
          case "bench": {
            // Benches look at the fountain.
            const at = place(facing(facingAt(kinds, tx, ty, floor === 0 ? fountain : null)));
            at(0, 0.235, 0, 0.98, 0.07, 0.46, "#a9825a");
            at(-0.4, 0.1, 0, 0.08, 0.2, 0.4, "#3a3f4a");
            at(0.4, 0.1, 0, 0.08, 0.2, 0.4, "#3a3f4a");
            at(0, 0.5, -0.24, 0.98, 0.36, 0.06, "#a9825a");
            break;
          }
          case "whiteboard": {
            const at = place(away(sideWith(kinds, tx, ty, BACKING)));
            at(0, 1.0, -0.45, 0.96, 0.66, 0.05, "#8a9099");
            at(0, 1.0, -0.42, 0.88, 0.58, 0.03, "#f6f8fa");
            at(0, 0.66, -0.4, 0.9, 0.04, 0.1, "#8a9099");
            const inks = ["#d2453c", "#2f6fd0", "#2f8a57", "#23262f"];
            for (let i = 0; i < 3; i++) {
              const ink = inks[Math.floor(hash2(tx, ty, 50 + i) * inks.length)] ?? "#23262f";
              const wide = 0.25 + hash2(tx, ty, 60 + i) * 0.4;
              at(-0.3 + wide / 2 + hash2(tx, ty, 70 + i) * 0.1, 1.17 - i * 0.16, -0.4, wide, 0.04, 0.01, ink);
            }
            break;
          }
          case "server_rack": {
            const front = away(sideWith(kinds, tx, ty, BACKING));
            const at = place(front);
            at(0, 0.78, -0.05, 0.84, 1.56, 0.8, "#262932");
            at(0, 1.575, -0.05, 0.6, 0.03, 0.56, "#15171c");
            const lights = ["#5dff8a", "#5dc8ff", "#ffb84d"];
            for (let row = 0; row < 5; row++) {
              for (let col = 0; col < 3; col++) {
                if (hash2(tx * 7 + col, ty * 5 + row, 80) < 0.35) continue;
                const led = lights[Math.floor(hash2(tx + col, ty + row, 81) * lights.length)] ?? "#5dff8a";
                light(front)("screen", -0.24 + col * 0.24, 0.3 + row * 0.26, 0.355, 0.1, 0.05, 0.01, led);
              }
            }
            break;
          }
          case "bookshelf": {
            const at = place(away(sideWith(kinds, tx, ty, BACKING)));
            at(0, 0.72, -0.28, 0.98, 1.44, 0.42, "#6b4a2f");
            const spines = ["#8a2430", "#2f4a7a", "#2f6a4a", "#c9a227", "#5a3b22", "#d8d2c4"];
            for (let shelf = 0; shelf < 3; shelf++) {
              let x = -0.42;
              for (let book = 0; book < 4; book++) {
                const wide = 0.16 + hash2(tx * 3 + book, ty * 3 + shelf, 90) * 0.08;
                const tall = 0.26 + hash2(tx * 3 + book, ty * 3 + shelf, 91) * 0.1;
                const spine = spines[Math.floor(hash2(tx + book, ty + shelf, 92) * spines.length)] ?? "#8a2430";
                at(x + wide / 2, 0.18 + shelf * 0.45 + tall / 2, -0.055, wide - 0.02, tall, 0.04, spine);
                x += wide;
              }
            }
            break;
          }
          case "shelf": {
            // Shop shelving: a tall thin unit with two planes and goods on them.
            const at = place(away(sideWith(kinds, tx, ty, BACKING)));
            const wood = jitter("#8b6b4a", 0.06, tx, ty, 93);
            at(0, 0.72, -0.32, 0.96, 1.44, 0.3, wood);
            at(0, 0.5, -0.24, 1.0, 0.04, 0.46, shade(wood, 0.18));
            at(0, 1.0, -0.24, 1.0, 0.04, 0.46, shade(wood, 0.18));
            const goods = ["#d8d2c4", "#c8453c", "#2f6fd0", "#e9b44c", "#4f9f58"];
            for (let plane = 0; plane < 2; plane++) {
              for (let i = 0; i < 3; i++) {
                if (hash2(tx + i, ty + plane, 94) < 0.25) continue;
                const tin = goods[Math.floor(hash2(tx * 3 + i, ty * 2 + plane, 95) * goods.length)] ?? "#d8d2c4";
                at(-0.3 + i * 0.3, 0.63 + plane * 0.5, -0.22, 0.2, 0.22, 0.22, tin);
              }
            }
            break;
          }
          case "rack": {
            // Warehouse racking: taller, steel, cartons on the shelves.
            const at = place(away(sideWith(kinds, tx, ty, BACKING)));
            const steel = "#4a4f58";
            for (const ux of [-0.44, 0.44]) {
              for (const uz of [-0.3, 0.3]) at(ux, 0.95, uz, 0.06, 1.9, 0.06, steel);
            }
            for (const y of [0.32, 0.92, 1.52]) at(0, y, 0, 0.96, 0.05, 0.68, "#5c6270");
            const carton = jitter("#b28a5e", 0.08, tx, ty, 96);
            at(-0.22, 0.54, 0, 0.36, 0.38, 0.5, carton);
            at(0.22, 0.54, 0, 0.36, 0.38, 0.5, shade(carton, -0.06));
            at(0, 1.14, 0, 0.5, 0.38, 0.5, shade(carton, 0.05));
            break;
          }
          case "equipment": {
            // Gym kit in dark grey: a bench under a bar, or a machine with a screen.
            const front = toDoor;
            const at = place(front);
            if (hash2(tx, ty, 97) < 0.5) {
              at(0, 0.42, 0, 0.36, 0.1, 0.96, "#2c2f38");
              for (const lx of [-0.12, 0.12]) {
                for (const lz of [-0.36, 0.36]) at(lx, 0.18, lz, 0.06, 0.36, 0.06, "#4a4f58");
              }
              for (const lx of [-0.42, 0.42]) at(lx, 0.55, -0.25, 0.06, 1.1, 0.06, "#4a4f58");
              at(0, 1.02, -0.25, 1.1, 0.05, 0.05, "#7f8790");
              for (const lx of [-0.55, 0.55]) at(lx, 1.02, -0.25, 0.06, 0.4, 0.4, "#23262f");
            } else {
              at(0, 0.1, 0.1, 0.7, 0.1, 0.9, "#2c2f38");
              at(0, 0.6, -0.4, 0.7, 0.9, 0.08, "#3a3f4a");
              at(0, 0.95, -0.15, 0.06, 0.06, 0.5, "#7f8790");
              light(front)("screen", 0, 0.85, -0.355, 0.3, 0.16, 0.01, "#9fd0ff");
            }
            break;
          }
          case "conference":
            box(own, tx, 0.43, ty, 1, 0.08, 0.9, jitter("#5a3d2b", 0.04, tx, ty));
            box(own, tx, 0.2, ty, 0.5, 0.4, 0.3, "#3a2a20");
            break;
          case "reception":
            box(own, tx, 0.45, ty, 1, 0.9, 0.56, blend(palette?.wall ?? "#888888", "#3a2a20", 0.35));
            box(own, tx, 0.93, ty, 1, 0.06, 0.7, "#efe6d2");
            break;
          case "filing": {
            const front = away(sideWith(kinds, tx, ty, BACKING));
            const at = place(front);
            at(0, 0.55, -0.18, 0.92, 1.1, 0.58, jitter("#b7b2a4", 0.05, tx, ty));
            for (let drawer = 0; drawer < 3; drawer++) {
              at(0, 0.2 + drawer * 0.36, 0.115, 0.8, 0.02, 0.01, "#6d6a60");
              at(0, 0.33 + drawer * 0.36, 0.12, 0.2, 0.04, 0.02, "#54524b");
            }
            break;
          }
          case "partition": {
            // Glass: pale, framed, low enough to see over.
            const solid = new Set<TileKind>(["partition", "wall"]);
            const isSolid = (x: number, y: number) => solid.has(kinds(x, y) ?? "grass");
            const alongX = isSolid(tx - 1, ty) || isSolid(tx + 1, ty);
            const alongZ = isSolid(tx, ty - 1) || isSolid(tx, ty + 1);
            if (alongX || !alongZ) {
              box(own, tx, 0.62, ty, 1, 1.2, 0.08, "#cfe4ec");
              box(own, tx, 1.25, ty, 1, 0.07, 0.14, "#56606b");
            }
            if (alongZ) {
              box(own, tx, 0.62, ty, 0.08, 1.2, 1, "#cfe4ec");
              box(own, tx, 1.25, ty, 0.14, 0.07, 1, "#56606b");
            }
            break;
          }
          case "kitchen": {
            const front = away(sideWith(kinds, tx, ty, BACKING));
            const at = place(front);
            const what = Math.floor(hash2(tx, ty, 95) * 4);
            if (what === 0) {
              at(0, 0.78, -0.12, 0.92, 1.56, 0.72, "#e4e7ea"); // a fridge
              at(0.34, 0.9, 0.25, 0.05, 0.5, 0.03, "#8a9099");
            } else {
              at(0, 0.45, -0.12, 1, 0.9, 0.72, "#b9bec4");
              at(0, 0.925, -0.12, 1, 0.05, 0.76, "#d9dde1");
              if (what === 1) {
                at(0, 0.45, 0.245, 0.7, 0.5, 0.01, "#2b2f3a"); // an oven, lit
                light(front)("lamp", 0, 0.45, 0.255, 0.5, 0.3, 0.01, "#ffb060");
              } else if (what === 2) {
                at(-0.22, 0.96, -0.1, 0.3, 0.03, 0.3, "#23262f"); // a hob and a pot
                at(0.22, 0.96, -0.1, 0.3, 0.03, 0.3, "#23262f");
                at(0.22, 1.06, -0.1, 0.26, 0.18, 0.26, "#8a9099");
              } else {
                at(0, 0.955, -0.1, 0.6, 0.02, 0.4, "#7f8790"); // a sink
                at(0, 1.08, -0.36, 0.06, 0.26, 0.06, "#8a9099");
              }
            }
            break;
          }
          case "kitchenette": {
            // A kitchen's little brother, in a lobby: a unit, a kettle, a
            // coffee machine with its light on.
            const front = away(sideWith(kinds, tx, ty, BACKING));
            const at = place(front);
            at(0, 0.42, -0.12, 0.96, 0.84, 0.66, "#c9cdd2");
            at(0, 0.87, -0.12, 0.96, 0.05, 0.7, "#e2e5e8");
            at(-0.25, 1.0, -0.2, 0.24, 0.22, 0.24, "#3a3f4a");
            at(0.22, 1.03, -0.22, 0.3, 0.28, 0.26, "#8a9099");
            light(front)("lamp", 0.22, 0.98, -0.085, 0.1, 0.05, 0.01, "#ff9c3c");
            break;
          }
          case "plant": {
            const leaf = jitter("#3f8f4f", 0.1, tx, ty, 6);
            box(own, tx, 0.18, ty, 0.42, 0.36, 0.42, "#b5673f");
            box(own, tx, 0.62, ty, 0.64, 0.52, 0.64, leaf);
            box(own, tx, 1.0, ty, 0.4, 0.3, 0.4, shade(leaf, 0.15));
            break;
          }
          case "planter": {
            const leaf = jitter("#3f8f4f", 0.1, tx, ty, 7);
            box(own, tx, 0.2, ty, 0.92, 0.4, 0.92, "#9c968a");
            box(own, tx, 0.5, ty, 0.8, 0.24, 0.8, leaf);
            for (let i = 0; i < 3; i++) {
              const petal = ["#f2e27a", "#e0757c", "#f7f4ec"][i] ?? "#f2e27a";
              box(own, tx + (hash2(tx, ty, 30 + i) - 0.5) * 0.6, 0.66, ty + (hash2(tx, ty, 33 + i) - 0.5) * 0.6, 0.14, 0.1, 0.14, petal);
            }
            break;
          }
          case "lamp":
            box(own, tx, 0.06, ty, 0.32, 0.12, 0.32, "#2c2f38");
            box(own, tx, 1.15, ty, 0.12, 2.2, 0.12, "#2c2f38");
            box(own, tx, 2.36, ty, 0.46, 0.08, 0.46, "#2c2f38");
            glow("lamp", tx, 2.2, ty, 0.32, 0.24, 0.32, "#fff1c4");
            glow("pool", tx, 0.035, ty, 7, 0, 7, "#d9923f");
            break;
          case "tree": {
            // Three sizes of tree, from where it stands.
            const size = 0.85 + hash2(tx, ty, 9) * 0.4;
            const leaf = jitter("#3d8a4b", 0.1, tx, ty, 4);
            box(own, tx, 0.5 * size, ty, 0.26, 1.0 * size, 0.26, "#6f4d31");
            box(own, tx, 1.3 * size, ty, 1.1 * size, 0.8 * size, 1.1 * size, leaf);
            box(own, tx, 1.95 * size, ty, 0.68 * size, 0.5 * size, 0.68 * size, shade(leaf, 0.14));
            break;
          }
          case "fountain":
            box(own, tx, 0.18, ty, 1, 0.36, 1, jitter("#aaa595", 0.05, tx, ty));
            box(own, tx, 0.39, ty, 0.8, 0.08, 0.8, "#5fb0e4");
            break;
          default:
            break;
        }
        if (kind === "grass" && hash2(tx, ty, 21) > 0.82) {
          // A tuft, so a lawn has something on it.
          const ox = (hash2(tx, ty, 22) - 0.5) * 0.6;
          const oz = (hash2(tx, ty, 23) - 0.5) * 0.6;
          const flower = hash2(tx, ty, 24) > 0.7;
          box(own, tx + ox, 0.06, ty + oz, 0.16, 0.12, 0.16, flower ? "#f2e27a" : "#4f9447");
        }
      }
    }
  }

  // The ground floor: the whole town. Then every storey over its footprint.
  furnish(ground, 0, 0, 0, map.width - 1, map.height - 1, (tx, ty) => map.zones[ty]?.[tx]);
  for (const storey of map.storeys) {
    const building = byZone.get(storey.zone);
    if (building === undefined) continue;
    furnish(storeyKinds(storey), storey.floor, building.x0, building.y0, building.x1, building.y1, () => storey.zone);
  }

  // At night the lights are on indoors: a wash of warm pools across each floor.
  for (const building of map.buildings) {
    for (let floor = 0; floor < building.floors; floor++) {
      for (let ty = building.y0 + 2; ty < building.y1; ty += 3) {
        for (let tx = building.x0 + 2; tx < building.x1; tx += 3) {
          glowOn(floor, "pool", tx + 0.5, floor * STOREY + 0.03, ty + 0.5, 7, 0, 7, "#ffb866");
        }
      }
    }
  }

  // A name board over each door, in the firm's colour, with the firm's
  // monogram on it in lit blocks: "Halloran & Pike LLP" is H&P. On a single
  // storey it sits on top of the wall over the door and carries the letters
  // both ways, the camera's south face reading left to right; where the wall
  // carries on above, it hangs on the wall's outside face over a transom
  // that fills the top of the doorway, and reads outwards only.
  for (const building of map.buildings) {
    const palette = building.palette;
    const [dx, dz] = building.door;
    const tall = wallHeight(building, 0);
    const out = building.faces_south ? 1 : -1;
    const stacked = building.floors > 1;
    const alongX = ground(dx - 1, dz) === "wall" || ground(dx + 1, dz) === "wall";
    if (stacked && alongX) {
      // The transom: plaster from head height to the storey above.
      plain(dx, (tall + 1.45) / 2, dz, 1, tall - 1.45, 1, plasterOf(palette));
    }
    const by = stacked ? tall - 0.55 : tall + 0.62;
    const bz = stacked ? dz + out * 0.66 : dz;
    const long = 3.2;
    const [sx, sz] = alongX ? [long, 0.34] : [0.34, long];
    plain(dx, by, bz, sx, 0.7, sz, palette.body);
    if (alongX) {
      const text = monogram(building.name);
      const px = 0.115;
      const wide = (text.length * 4 - 1) * px;
      for (const face of stacked ? [out] : [1, -1]) {
        [...text].forEach((letter, i) => {
          const rows = FONT[letter] ?? [];
          rows.forEach((row, r) => {
            for (let c = 0; c < 3; c++) {
              if (row[c] !== "#") continue;
              const along = -wide / 2 + (i * 4 + c + 0.5) * px;
              glowOn(0, "sign", dx + face * along, by + (2 - r) * px, bz + face * 0.175, px, px, 0.02, "#fff6dc");
            }
          });
        });
      }
    }
    // The lintel the board hangs from, so the doorway is a doorway.
    if (!stacked) plain(dx, tall + 0.07, dz, 1, 0.14, 1, capOf(palette));
  }

  // What each building wears outside (audit D4), by what kind of firm it is.
  // No roofs (WEB-0002): an awning, a portico, a mast, window boxes. Doors
  // are in north or south walls.
  for (const building of map.buildings) {
    const [dx, dz] = building.door;
    if (dz !== building.y0 && dz !== building.y1) continue;
    const out = dz === building.y1 ? 1 : -1;
    const tall = wallHeight(building, 0);
    switch (styleOf(building.kind).dressing) {
      case "awning": {
        // A striped awning the length of the front, in two steps so it slopes,
        // with a scalloped edge. It shades the first row outside the door, and
        // hangs at head height however tall the wall behind it.
        const eave = Math.min(tall, 1.7);
        for (let tx = building.x0 + 1; tx < building.x1; tx++) {
          const stripe = tx % 2 === 0 ? "#c8453c" : "#f3efe6";
          plain(tx, eave + 0.3, dz + out * 0.72, 1, 0.08, 0.5, stripe);
          plain(tx, eave + 0.16, dz + out * 1.2, 1, 0.08, 0.5, stripe);
          plain(tx, eave + 0.03, dz + out * 1.43, 1, 0.2, 0.05, stripe);
        }
        for (const tx of [building.x0 + 1, dx - 1, dx + 1, building.x1 - 1]) {
          plain(tx + (tx < dx ? -0.4 : 0.4), (eave + 0.12) / 2, dz + out * 1.38, 0.08, eave + 0.12, 0.08, "#f3efe6");
        }
        break;
      }
      case "portico": {
        // Two columns and a pediment: a firm that wants to look like a bank.
        for (const side of [-1, 1]) {
          plain(dx + side, 0.08, dz + out * 0.85, 0.66, 0.16, 0.66, "#d8d0bd");
          plain(dx + side, (tall + 0.16) / 2, dz + out * 0.85, 0.44, tall + 0.16, 0.44, "#ece5d3");
          plain(dx + side, tall + 0.2, dz + out * 0.85, 0.62, 0.12, 0.62, "#d8d0bd");
        }
        plain(dx, tall + 0.37, dz + out * 0.85, 3.2, 0.22, 0.8, "#ece5d3");
        plain(dx, tall + 0.55, dz + out * 0.85, 2.2, 0.16, 0.7, "#ece5d3");
        plain(dx, tall + 0.69, dz + out * 0.85, 1.1, 0.12, 0.6, "#ece5d3");
        break;
      }
      case "mast": {
        // A mast and a dish on the back corner of the roof, with a light that
        // is on at night; and planters of bamboo either side of the door.
        const roof = roofOf(building);
        const top = building.floors - 1;
        const mx = building.x0;
        const mz = out === 1 ? building.y0 : building.y1;
        plain(mx, roof + 0.9, mz, 0.12, 1.6, 0.12, "#5c6670", top);
        plain(mx + 0.3, roof + 0.75, mz, 0.5, 0.5, 0.08, "#dfe5ec", top);
        plain(mx + 0.3, roof + 0.75, mz + 0.08, 0.12, 0.12, 0.12, "#5c6670", top);
        glowOn(top, "lamp", mx, roof + 1.76, mz, 0.18, 0.14, 0.18, "#ff6b5e");
        for (const side of [-2, 2]) {
          if (ground(dx + side, dz + out) === "wall") continue;
          plain(dx + side, 0.2, dz + out * 0.85, 0.6, 0.4, 0.5, "#3a3f4a");
          plain(dx + side, 0.8, dz + out * 0.85, 0.44, 0.9, 0.36, "#4f9f58");
        }
        break;
      }
      case "boxes": {
        // Window boxes along the front: somebody waters them.
        for (let tx = building.x0 + 1; tx < building.x1; tx++) {
          if (tx % 3 !== 1 || Math.abs(tx - dx) < 2) continue;
          plain(tx, tall * 0.34, dz + out * 0.6, 0.8, 0.16, 0.2, "#6b4a2f");
          plain(tx, tall * 0.34 + 0.13, dz + out * 0.6, 0.72, 0.12, 0.16, "#4f9f58");
          plain(tx - 0.2, tall * 0.34 + 0.2, dz + out * 0.62, 0.12, 0.08, 0.12, "#e0757c");
          plain(tx + 0.18, tall * 0.34 + 0.2, dz + out * 0.62, 0.12, 0.08, 0.12, "#f2e27a");
        }
        break;
      }
      case "none":
        break;
    }
  }

  // The fountain's jet.
  if (fountain !== null) {
    const [cx, cz] = fountain;
    plain(cx, 0.75, cz, 0.34, 0.7, 0.34, "#aaa595");
    plain(cx, 1.2, cz, 0.2, 0.3, 0.2, "#9fd4f2");
  }

  // -- the outskirts ---------------------------------------------------------
  //
  // Past the last real tile the town runs out into the country: the avenues
  // that meet the edge keep going as lanes that wander, thin to a rut, and
  // dissolve in the grass; groves and thickets stand where a coarse noise says
  // they should; and the field pales toward the horizon with distance, so the
  // renderer's fog is finishing something already fading rather than hiding an
  // edge. None of this is in `map.tiles` — nobody walks out there; it only
  // has to look like somewhere. How far it runs is a fraction of the map's
  // longer side, so a wider district gets a wider country.
  if (outskirts <= 0) return voxels;
  const OUTSKIRTS = Math.max(8, Math.round(outskirts * Math.max(map.width, map.height)));
  const grass = GROUND.grass ?? "#6fae58";
  const HAZE = "#9db49b";
  /** A lit box in the field, standing on nothing that shades it. */
  const field = (x: number, y: number, z: number, sx: number, sy: number, sz: number, color: string) =>
    plain(x, y, z, sx, sy, sz, color);
  /**
   * Aerial haze baked into the field: none at the town's edge, most of the way
   * gone by the far end of the outskirts. Fixed, unlike the sky — a voxel's
   * colour is baked once — so the renderer's fog still carries the time of day.
   */
  const hazeAt = (reach: number): number => {
    const t = Math.min(1, Math.max(0, (reach - 2) / Math.max(1, OUTSKIRTS - 8)));
    return t * t * (3 - 2 * t) * 0.72;
  };
  /** Distance in tiles from a cell's nearest corner to the map rectangle. */
  const gap = (lo: number, size: number, span: number): number =>
    lo + size <= 0 ? 1 - lo - size : lo >= span ? lo - span + 1 : 0;
  const reachOf = (tx: number, ty: number): number =>
    Math.max(gap(tx, 1, map.width), gap(ty, 1, map.height));
  /**
   * A coarse value noise says where the country is lumpy: trees arrive as
   * groves and hedge lines rather than a scatter of one-offs.
   */
  const noiseAt = (x: number, y: number, cell: number, salt: number): number => {
    const gx = x / cell;
    const gy = y / cell;
    const x0 = Math.floor(gx);
    const y0 = Math.floor(gy);
    const fx = gx - x0;
    const fy = gy - y0;
    const sx = fx * fx * (3 - 2 * fx);
    const sy = fy * fy * (3 - 2 * fy);
    const n00 = hash2(x0, y0, salt);
    const n10 = hash2(x0 + 1, y0, salt);
    const n01 = hash2(x0, y0 + 1, salt);
    const n11 = hash2(x0 + 1, y0 + 1, salt);
    return n00 + (n10 - n00) * sx + (n01 - n00) * sy + (n00 - n10 - n01 + n11) * sx * sy;
  };
  // One slab beneath it all, centred on the town, deeper than any pan limit
  // plus a screen of ground, and already into the haze so where the tiles end
  // is not an edge. Its top sits a hair under the tiles' tops — no z-fighting.
  const underlay = Math.max(480, (Math.max(map.width, map.height) + 2 * OUTSKIRTS) * 3);
  field((map.width - 1) / 2, -0.12, (map.height - 1) / 2, underlay, 0.2, underlay, blend(grass, HAZE, 0.72));

  // The lanes: wherever a path tile meets the edge it becomes a country lane.
  // Straight off the avenue, then wandering on slow noise — two tracks wide,
  // then one, then a speckle that dissolves into the field.
  const LANE_LEN = OUTSKIRTS + 2;
  // Where the lane thins, as a share of its own length rather than a count of
  // steps: at the full reach these are the 6, 10 and 30 they always were, and
  // a shallow country still gets the whole shape instead of a lane cut off.
  const WANDER_AT = Math.max(2, Math.round(LANE_LEN * 0.104));
  const TWO_TRACKS = Math.max(WANDER_AT + 1, Math.round(LANE_LEN * 0.172));
  const ONE_TRACK = Math.max(TWO_TRACKS + 2, Math.round(LANE_LEN * 0.517));
  const DISSOLVE = Math.max(1, LANE_LEN - ONE_TRACK);
  const road = new Map<string, number>(); // "tx,ty" -> lane step
  const posts: { x: number; z: number }[] = [];
  const lanterns: { x: number; z: number }[] = [];
  const lane = (
    base: number,
    fixed: number,
    dx: number,
    dy: number,
    width: number,
    salt: number,
  ): void => {
    let prev: number[] = [];
    for (let s = 1; s <= LANE_LEN; s++) {
      const wander =
        s <= WANDER_AT
          ? 0
          : (noiseAt(s, 0, 7, salt) - 0.5) * Math.min(2.6, (s - WANDER_AT) * 0.15);
      const w = Math.min(width, s <= TWO_TRACKS ? 2 : s <= ONE_TRACK ? 1 : 0);
      const now: number[] =
        w === 2
          ? [Math.floor(base + wander), Math.floor(base + wander) + 1]
          : w === 1 || hash2(s, 0, salt + 91) < ((LANE_LEN - s) / DISSOLVE) * 0.85
            ? [Math.round(base + wander)]
            : [];
      // Previous step's cells too, so a bend never leaves a diagonal gap.
      for (const lat of new Set([...now, ...(w > 0 ? prev : [])])) {
        const tx = dx === 0 ? lat : fixed + dx * s;
        const ty = dy === 0 ? lat : fixed + dy * s;
        const key = `${tx},${ty}`;
        if (!road.has(key)) road.set(key, s);
      }
      prev = now;
      // A verge fence and a lantern while the lane is still two tracks wide.
      const lo = Math.floor(base + wander);
      if (w === 2 && s >= 8 && s <= 24 && s % 3 === 1) {
        for (const side of [lo - 1, lo + 2]) {
          if (hash2(s, side, 97) > 0.75) continue;
          posts.push(dx === 0 ? { x: side, z: fixed + dy * s } : { x: fixed + dx * s, z: side });
        }
      }
      if (w === 2 && s === 12) {
        lanterns.push(dx === 0 ? { x: lo - 1, z: fixed + dy * s } : { x: fixed + dx * s, z: lo - 1 });
      }
    }
  };
  // Where the paths leave: consecutive exit tiles are one lane, centred.
  const exits = (cells: number[], run: (first: number, width: number) => void): void => {
    let start = 0;
    for (let i = 1; i < cells.length; i++) {
      if (cells[i] !== (cells[i - 1] ?? 0) + 1) {
        run(cells[start] ?? 0, i - start);
        start = i;
      }
    }
    if (cells.length > 0) run(cells[start] ?? 0, cells.length - start);
  };
  {
    const north: number[] = [];
    const south: number[] = [];
    const west: number[] = [];
    const east: number[] = [];
    for (let x = 0; x < map.width; x++) {
      if (ground(x, 0) === "path") north.push(x);
      if (ground(x, map.height - 1) === "path") south.push(x);
    }
    for (let y = 0; y < map.height; y++) {
      if (ground(0, y) === "path") west.push(y);
      if (ground(map.width - 1, y) === "path") east.push(y);
    }
    exits(north, (first, width) => lane(first + width / 2 - 0.5, 0, 0, -1, width, 11));
    exits(south, (first, width) => lane(first + width / 2 - 0.5, map.height - 1, 0, 1, width, 12));
    exits(west, (first, width) => lane(first + width / 2 - 0.5, 0, -1, 0, width, 13));
    exits(east, (first, width) => lane(first + width / 2 - 0.5, map.width - 1, 1, 0, width, 14));
  }
  for (const { x, z } of posts) {
    if (road.has(`${x},${z}`)) continue;
    field(x, 0.28, z, 0.13, 0.55, 0.13, blend("#6f4d31", HAZE, hazeAt(reachOf(x, z)) * 0.5));
  }
  for (const { x, z } of lanterns) {
    if (road.has(`${x},${z}`)) continue;
    field(x, 0.6, z, 0.14, 1.2, 0.14, "#4a4033");
    glowOn(0, "lamp", x, 1.34, z, 0.26, 0.2, 0.26, "#ffdf9a");
    glowOn(0, "pool", x, 0.02, z, 4, 0, 4, "#d9923f");
  }

  // The field is emitted in 4x4 cells on one lattice, so it can go coarser
  // with distance and never leave a seam: real tiles near the town, one box
  // doing four further out, and past most of the outskirts the underlay alone
  // carries it — which is the point: by then it is all haze anyway.
  const CELL = 4;
  const FAR = OUTSKIRTS - 6;
  const TREES = OUTSKIRTS * 0.65;
  const TUFTS = OUTSKIRTS * 0.35;
  const inMap = (tx: number, ty: number, size: number): boolean =>
    tx + size > 0 && tx < map.width && ty + size > 0 && ty < map.height;
  const emit = (tx: number, ty: number, unit: number, reach: number): void => {
    if (inMap(tx, ty, unit)) return;
    if (unit > 1) {
      let onRoad = false;
      for (let a = 0; a < unit && !onRoad; a++) {
        for (let b = 0; b < unit; b++) {
          if (road.has(`${tx + a},${ty + b}`)) onRoad = true;
        }
      }
      if (onRoad) {
        for (let a = 0; a < unit; a++) for (let b = 0; b < unit; b++) emit(tx + a, ty + b, 1, reach);
        return;
      }
    }
    const cx = tx + unit / 2 - 0.5;
    const cz = ty + unit / 2 - 0.5;
    const haze = hazeAt(reach);
    const step = road.get(`${tx},${ty}`);
    if (unit === 1 && step !== undefined) {
      // Pale where the avenue hands off, worn to dirt, then dissolving back
      // into the field it crosses.
      const base = blend("#ded3ba", "#b39d76", Math.min(1, step / 18));
      const fading = Math.min(1, Math.max(0, (step - (ONE_TRACK - 4)) / DISSOLVE)) * 0.7;
      const dirt = blend(jitter(base, 0.05, tx, ty, 7), blend(grass, HAZE, haze * 0.8), fading);
      field(tx, -0.1, ty, 1, 0.2, 1, dirt);
      return;
    }
    // Meadow, mottled in patches by the same noise that decides the groves.
    const mottle = noiseAt(tx, ty, 13, 51);
    let base = jitter(grass, 0.08, tx, ty, 1);
    if (mottle > 0.64) base = shade(base, -0.07);
    else if (mottle < 0.34) base = blend(base, "#83bd68", 0.35);
    field(cx, -0.1, cz, unit, 0.2, unit, blend(base, HAZE, haze));
    if (step !== undefined || reach > TREES) return;
    const forest = noiseAt(tx, ty, 11, 41);
    const h = hash2(tx, ty, 61);
    if ((forest > 0.58 && h < (forest - 0.56) * 1.5) || (forest <= 0.44 && h < 0.004)) {
      // The town's own three-box tree, hazed by distance like the grass under it.
      const size = 0.85 + hash2(tx, ty, 9) * 0.4;
      const leaf = blend(jitter("#3d8a4b", 0.1, tx, ty, 4), HAZE, haze * 0.55);
      const trunk = blend("#6f4d31", HAZE, haze * 0.55);
      field(cx, 0.5 * size, cz, 0.26, 1.0 * size, 0.26, trunk);
      field(cx, 1.3 * size, cz, 1.1 * size, 0.8 * size, 1.1 * size, leaf);
      field(cx, 1.95 * size, cz, 0.68 * size, 0.5 * size, 0.68 * size, shade(leaf, 0.14));
    } else if (forest > 0.5 && h < 0.11) {
      // Thicket edge: bushes where the grove thins out.
      const shrub = blend("#35703f", HAZE, haze * 0.55);
      field(cx + (hash2(tx, ty, 26) - 0.5) * 0.4, 0.18, cz + (hash2(tx, ty, 27) - 0.5) * 0.4, 0.7, 0.36, 0.7, shrub);
      field(cx, 0.34, cz, 0.45, 0.32, 0.45, shade(shrub, 0.12));
    } else if (unit === 1 && reach <= TUFTS && hash2(tx, ty, 63) < 0.1) {
      // A tuft or a flower, as on the town's lawns — detail is for up close.
      const ox = (hash2(tx, ty, 22) - 0.5) * 0.6;
      const oz = (hash2(tx, ty, 23) - 0.5) * 0.6;
      const flower = hash2(tx, ty, 24) > 0.7;
      field(tx + ox, 0.06, ty + oz, 0.16, 0.12, 0.16, flower ? "#f2e27a" : "#4f9447");
    } else if (unit === 1 && hash2(tx, ty, 65) < 0.005) {
      field(cx + 0.2, 0.09, cz - 0.15, 0.3, 0.18, 0.26, blend("#9aa0a4", HAZE, haze));
    }
  };
  for (let my = -OUTSKIRTS; my < map.height + OUTSKIRTS; my += CELL) {
    for (let mx = -OUTSKIRTS; mx < map.width + OUTSKIRTS; mx += CELL) {
      const reach = Math.max(gap(mx, CELL, map.width), gap(my, CELL, map.height));
      if (reach === 0 || reach > FAR) continue; // inside the map, or pure underlay
      const unit = reach <= 6 ? 1 : 2;
      for (let sy = 0; sy < CELL; sy += unit) {
        for (let sx = 0; sx < CELL; sx += unit) {
          emit(mx + sx, my + sy, unit, reach);
        }
      }
    }
  }

  return voxels;
}

// -- people -----------------------------------------------------------------
//
// A person is thirteen boxes: chunky, a head that is two fifths of their
// height, and something on it that says what they do (WEB-0004, audit D3). The
// rig is data — a pivot, an offset from it and a size per part, in a frame
// where +z is the way they face and y is up from their feet — and the renderer
// poses it. Standing height is 1.36 before the hat.

export const SKIN_TONES = ["#f2c9a5", "#d9a57c", "#a9744f", "#7b4f34", "#f0d5b8"];
export const HAIR_TONES = ["#2b1d14", "#5a3b22", "#1c1c22", "#8a5a2b", "#c9c2b8", "#a3482a"];
export const TROUSER_TONES = ["#2f3542", "#3b3a36", "#25324a", "#4a3f35"];

export const HIP = 0.34;
export const SHOULDER = 0.76;
export const HEAD_TOP = 1.36;

/** Which joint a part hangs from, which decides how a pose moves it. */
export type Joint = "legL" | "legR" | "armL" | "armR" | "torso";

export type RigPart = {
  name: string;
  joint: Joint;
  /** The joint, in the person's frame. Limbs rotate about x through it. */
  pivot: [number, number, number];
  /** The box's centre, from the pivot, before any rotation. */
  offset: [number, number, number];
  size: [number, number, number];
};

const part = (
  name: string,
  joint: Joint,
  pivot: [number, number, number],
  offset: [number, number, number],
  size: [number, number, number],
): RigPart => ({ name, joint, pivot, offset, size });

/** The parts every person has. Hats are two more, from `HATS`. */
export const RIG: RigPart[] = [
  part("legL", "legL", [-0.14, HIP, 0], [0, -HIP / 2, 0], [0.24, HIP, 0.26]),
  part("legR", "legR", [0.14, HIP, 0], [0, -HIP / 2, 0], [0.24, HIP, 0.26]),
  part("body", "torso", [0, HIP, 0], [0, 0.23, 0], [0.58, 0.46, 0.36]),
  part("front", "torso", [0, HIP, 0], [0, 0.23, 0.185], [0.2, 0.4, 0.02]),
  part("armL", "armL", [-0.375, SHOULDER, 0], [0, -0.17, 0], [0.17, 0.42, 0.2]),
  part("armR", "armR", [0.375, SHOULDER, 0], [0, -0.17, 0], [0.17, 0.42, 0.2]),
  part("head", "torso", [0, 0.8, 0], [0, 0.28, 0], [0.6, 0.56, 0.56]),
  part("eyeL", "torso", [0, 0.8, 0], [-0.14, 0.27, 0.285], [0.09, 0.13, 0.02]),
  part("eyeR", "torso", [0, 0.8, 0], [0.14, 0.27, 0.285], [0.09, 0.13, 0.02]),
  part("hairTop", "torso", [0, HEAD_TOP, 0], [0, 0.05, -0.02], [0.64, 0.12, 0.6]),
  part("hairBack", "torso", [0, 0.8, 0], [0, 0.34, -0.27], [0.64, 0.46, 0.1]),
];

export type HatShape =
  | "none"
  | "cap"
  | "beanie"
  | "beret"
  | "toque"
  | "brim"
  | "hardhat"
  | "visor"
  | "headset"
  | "bun"
  | "bandana";

type HatBox = { offset: [number, number, number]; size: [number, number, number] };

/** Two boxes per hat, placed from the top of the head. `coversHair` hides the hair on top. */
export const HATS: Record<HatShape, { a: HatBox | null; b: HatBox | null; coversHair: boolean }> = {
  none: { a: null, b: null, coversHair: false },
  cap: {
    a: { offset: [0, 0.08, -0.01], size: [0.65, 0.16, 0.6] },
    b: { offset: [0, 0.03, 0.4], size: [0.52, 0.05, 0.28] },
    coversHair: true,
  },
  beanie: {
    a: { offset: [0, 0.1, -0.01], size: [0.67, 0.22, 0.62] },
    b: { offset: [0, 0.27, -0.01], size: [0.17, 0.14, 0.17] },
    coversHair: true,
  },
  beret: {
    a: { offset: [0.05, 0.06, -0.02], size: [0.76, 0.12, 0.7] },
    b: { offset: [0.05, 0.15, -0.02], size: [0.09, 0.07, 0.09] },
    coversHair: true,
  },
  toque: {
    a: { offset: [0, 0.06, 0], size: [0.6, 0.12, 0.56] },
    b: { offset: [0, 0.29, 0], size: [0.72, 0.36, 0.68] },
    coversHair: true,
  },
  brim: {
    a: { offset: [0, 0.025, 0], size: [0.88, 0.05, 0.84] },
    b: { offset: [0, 0.17, 0], size: [0.54, 0.26, 0.5] },
    coversHair: true,
  },
  hardhat: {
    a: { offset: [0, 0.1, 0], size: [0.69, 0.2, 0.65] },
    b: { offset: [0, 0.03, 0.39], size: [0.44, 0.05, 0.22] },
    coversHair: true,
  },
  visor: {
    a: { offset: [0, -0.1, 0], size: [0.66, 0.09, 0.62] },
    b: { offset: [0, -0.12, 0.43], size: [0.54, 0.04, 0.3] },
    coversHair: false,
  },
  headset: {
    a: { offset: [0, 0.14, 0], size: [0.7, 0.06, 0.12] },
    b: { offset: [0.33, -0.28, 0.02], size: [0.1, 0.24, 0.22] },
    coversHair: false,
  },
  bun: {
    a: { offset: [0, 0.16, -0.2], size: [0.28, 0.24, 0.28] },
    b: null,
    coversHair: false,
  },
  bandana: {
    a: { offset: [0, -0.04, 0], size: [0.66, 0.14, 0.62] },
    b: { offset: [0.12, -0.08, -0.36], size: [0.14, 0.12, 0.14] },
    coversHair: false,
  },
};

/**
 * What somebody wears, from what they do.
 *
 * `hatColor` and `frontColor` are a hex, or `org` for the firm's accent, or
 * `hair` for the person's own hair (a bun is hair). `front` is the strip down
 * the chest: a tie, or an apron when `apron` widens it.
 */
export type RoleLook = {
  hat: HatShape;
  hatColor: string;
  front: "none" | "tie" | "apron";
  frontColor: string;
};

const LOOK = (
  hat: HatShape,
  hatColor = "org",
  front: RoleLook["front"] = "none",
  frontColor = "#ffffff",
): RoleLook => ({ hat, hatColor, front, frontColor });

/**
 * Role to look, first match wins. A table, with a default, because the town is
 * about to be staffed with roles that do not exist yet: executives, associates,
 * bookkeepers, sales, product, ops, kitchen. Patterns, not exact names, so
 * `senior_accountant` and `staff_accountant` need no line each.
 */
export const ROLE_LOOKS: [RegExp, RoleLook][] = [
  [/baker|kitchen|chef|cook|pastry/, LOOK("toque", "#f7f4ec", "apron", "#f7f4ec")],
  [/barista|shift|server|cashier|waiter|weekend/, LOOK("cap", "org", "apron", "#3a2b26")],
  [/owner/, LOOK("bandana", "#c8453c", "apron", "#3a2b26")],
  [/sre|ops|devops|infra|reliab/, LOOK("hardhat", "#f0c02e")],
  [/eng_lead|tech_lead|architect/, LOOK("cap", "#23262f")],
  [/engineer|developer|programmer/, LOOK("beanie", "org")],
  [/support|helpdesk|success/, LOOK("headset", "#23262f")],
  [/product|design|ux|research/, LOOK("beret", "#b5443c")],
  [/sales|account_manager|business|marketing/, LOOK("brim", "#d8c48e", "tie", "#b5443c")],
  [/partner|principal|founder|exec|chief|ceo|cfo|cto|director|president/, LOOK("brim", "#2a2a33", "tie", "#8a2430")],
  [/paralegal|clerk/, LOOK("bun", "hair", "tie", "#2f4a7a")],
  [/associate|lawyer|attorney|counsel/, LOOK("none", "hair", "tie", "#2f4a7a")],
  [/bookkeep|payroll/, LOOK("visor", "#c98a2b")],
  [/accountant|audit|tax|controller/, LOOK("visor", "#2f8a57")],
  [/admin|office_manager|reception|assistant/, LOOK("bun", "hair")],
  [/manager|lead|head/, LOOK("cap", "#4a4f5c")],
];

const DEFAULT_LOOK = LOOK("none", "hair");

export function lookFor(role: string): RoleLook {
  const key = role.toLowerCase();
  for (const [pattern, look] of ROLE_LOOKS) if (pattern.test(key)) return look;
  return DEFAULT_LOOK;
}

/** Every box a person is drawn with: the rig, then the two hat boxes. */
export const PERSON_BOXES = RIG.length + 2;
