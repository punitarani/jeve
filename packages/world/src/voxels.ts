/**
 * The town as boxes. Pure data: a list of (position, size, colour, corner
 * occlusion), so it can be inspected and tested without a GPU. The renderer
 * turns the list into instanced meshes — one draw call for everything lit, one
 * for everything that glows.
 *
 * All geometry is procedural. There are no sprites, models or textures from
 * anywhere, so there is nothing here to license.
 *
 * WEB-0004: what makes boxes read as a place rather than a diagram is baked
 * here, once, and costs nothing per frame. Each box carries eight occlusion
 * numbers, one per corner, from asking how much of the map stands above that
 * corner; and each block's colour is nudged by a hash of where it is, so a
 * wall is made of blocks and a lawn is not one green.
 */
import { ORG_PALETTE, type TileKind, type TownMap, type Zone } from "@jeve/contracts";

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
};

const ZONE_ORG: Partial<Record<Zone, string>> = {
  software_office: "tallybird",
  law_office: "halloran",
  accounting_office: "ledgerline",
  cafe: "thirdrail",
};

/**
 * How tall each firm builds. Roofs are absent (WEB-0002), so height and the
 * colour of the parapet are most of what a silhouette has to say.
 */
const WALL_HEIGHT: Partial<Record<Zone, number>> = {
  software_office: 1.6,
  law_office: 2.0,
  accounting_office: 1.45,
  cafe: 1.2,
};
const DEFAULT_WALL = 1.5;

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
  server_rack: [1.5, 0.75],
  bookshelf: [1.4, 0.5],
  conference: [0.46, 0.85],
  reception: [0.95, 0.7],
  filing: [1.1, 0.5],
  partition: [1.25, 0.25],
  kitchen: [0.92, 0.75],
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
  map: TownMap,
  tx: number,
  ty: number,
  kinds: ReadonlySet<TileKind>,
): Dir | null {
  for (const side of SIDES) {
    const kind = map.tiles[ty + side[1]]?.[tx + side[0]];
    if (kind !== undefined && kinds.has(kind)) return side;
  }
  return null;
}

const BACKING: ReadonlySet<TileKind> = new Set<TileKind>(["wall"]);

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
  map: TownMap,
  tx: number,
  ty: number,
  fountain: [number, number] | null,
): Dir | null {
  if (map.tiles[ty]?.[tx] !== "bench") return sideWith(map, tx, ty, SURFACES);
  if (fountain === null) return null;
  const [dx, dz] = [fountain[0] - tx, fountain[1] - ty];
  return Math.abs(dx) >= Math.abs(dz) ? [Math.sign(dx), 0] : [0, Math.sign(dz)];
}

/**
 * What each firm walks on. A floor is most of what the camera sees of a
 * roofless building, so it is a material, not a tint: carpet tiles, parquet,
 * linoleum, and a cafe's checkerboard.
 */
function floorOf(zone: Zone, tx: number, ty: number, tint: string): string {
  switch (zone) {
    case "software_office":
      return jitter(blend("#8d97ab", tint, 0.25), 0.05, tx >> 1, ty >> 1, 31);
    case "law_office":
      // Boards run east-west, two tiles long, staggered row by row.
      return jitter("#a9784a", 0.09, (tx + ty) >> 1, ty, 32);
    case "accounting_office":
      return jitter(blend("#b9c4b2", tint, 0.3), 0.04, tx, ty, 33);
    case "cafe":
      return jitter((tx + ty) % 2 === 0 ? "#e4d3bd" : "#b8705a", 0.04, tx, ty, 34);
    default:
      return jitter(blend("#cfcac0", tint, 0.3), 0.04, tx, ty, 35);
  }
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
function capOf(palette: { wall: string; accent: string } | undefined): string {
  return palette === undefined ? "#555555" : blend(palette.wall, palette.accent, 0.45);
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

type Field = { width: number; depth: number; height: Float32Array; fill: Float32Array };

function heightField(map: TownMap): Field {
  const height = new Float32Array(map.width * map.height);
  const fill = new Float32Array(map.width * map.height);
  for (let ty = 0; ty < map.height; ty++) {
    for (let tx = 0; tx < map.width; tx++) {
      const kind = map.tiles[ty]?.[tx];
      const zone = map.zones[ty]?.[tx];
      if (kind === undefined) continue;
      const solid: [number, number] | undefined =
        kind === "wall"
          ? [(zone && WALL_HEIGHT[zone]) ?? DEFAULT_WALL, 1]
          : SOLID[kind];
      if (solid === undefined) continue;
      height[ty * map.width + tx] = solid[0];
      fill[ty * map.width + tx] = solid[1];
    }
  }
  return { width: map.width, depth: map.height, height, fill };
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
 * ground also loses light along its foot. `own` is the tile a piece of
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
      const tx = Math.round(cx + ((s & 1) === 0 ? -REACH : REACH));
      const tz = Math.round(cz + ((s & 2) === 0 ? -REACH : REACH));
      if (tx < 0 || tz < 0 || tx >= field.width || tz >= field.depth) continue;
      if (own !== null && own[0] === tx && own[1] === tz) continue;
      const i = tz * field.width + tx;
      const above = (field.height[i] ?? 0) - cy;
      if (above <= 0.02) continue;
      blocked += (field.fill[i] ?? 0) * Math.min(1, above / 0.8);
    }
    let light = 1 - (STRENGTH * blocked) / 4;
    if (own !== null && cy < 0.06) light *= CONTACT;
    out[corner] = Math.max(0.25, light);
  }
  return out;
}

// -- the town ---------------------------------------------------------------

/** Every static box in the town. y is up; x and z are the tile grid. */
export function buildVoxels(map: TownMap): Voxel[] {
  const voxels: Voxel[] = [];
  const field = heightField(map);

  /** A lit box standing in tile `own` (or the ground itself, when null). */
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
    const v = { x, y, z, sx, sy, sz };
    voxels.push({ ...v, color, ao: occlusion(field, v, own) });
  };
  const glow = (
    kind: Glow,
    x: number,
    y: number,
    z: number,
    sx: number,
    sy: number,
    sz: number,
    color: string,
  ) => voxels.push({ x, y, z, sx, sy, sz, color, ao: OPEN, glow: kind });

  const kindAt = (tx: number, ty: number) => map.tiles[ty]?.[tx];
  const inside = (tx: number, ty: number) =>
    map.buildings.some((b) => tx >= b.x0 && tx <= b.x1 && ty >= b.y0 && ty <= b.y1);
  const fountain = fountainOf(map);

  for (let ty = 0; ty < map.height; ty++) {
    for (let tx = 0; tx < map.width; tx++) {
      const kind = kindAt(tx, ty);
      const zone = map.zones[ty]?.[tx];
      if (kind === undefined || zone === undefined) continue;
      const own: [number, number] = [tx, ty];
      const org = ZONE_ORG[zone];
      const palette = org === undefined ? undefined : ORG_PALETTE[org];

      // The ground under everything but walls, which stand on their own foot.
      // Interiors take a tint of the firm's colour, so a building reads as
      // belonging to someone from any zoom. Outdoors is laid in 2x2 pavers.
      const indoors = inside(tx, ty);
      if (kind !== "wall") {
        const base = GROUND[kind];
        const paving = jitter(GROUND.plaza ?? "#cfc6b2", 0.05, tx >> 1, ty >> 1, 3);
        const ground =
          base !== undefined
            ? kind === "plaza" || kind === "fountain"
              ? paving
              : jitter(base, kind === "path" ? 0.035 : 0.09, tx, ty, 1)
            : indoors
              ? floorOf(zone, tx, ty, palette?.floor ?? "#dddddd")
              : kind === "chair" || kind === "table"
                ? // A terrace: boards under the tables outside the cafe.
                  jitter("#a9825a", 0.08, tx, ty >> 1, 36)
                : paving;
        box(null, tx, -0.1, ty, 1, 0.2, 1, ground);
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

      switch (kind) {
        case "wall": {
          // Roofless, so the people inside are the point of the picture. Laid
          // in three courses, each block its own shade: a wall built of
          // something, not extruded.
          const tall = WALL_HEIGHT[zone] ?? DEFAULT_WALL;
          // The firm's colour, let down with plaster: at full strength under a
          // filmic curve it came out as poster paint.
          const wall = blend(mute(palette?.wall ?? "#888888", 0.15), "#e6dfd0", 0.42);
          const courses = 3;
          const each = tall / courses;
          for (let c = 0; c < courses; c++) {
            // Offset alternate courses by half a block, like brickwork.
            const bond = c % 2 === 0 ? tx + ty : tx + ty + 1;
            box(own, tx, each * (c + 0.5), ty, 1, each, 1, jitter(wall, 0.07, bond >> 1, c, ty - tx));
          }
          box(own, tx, tall + 0.07, ty, 1, 0.14, 1, jitter(capOf(palette), 0.05, tx, ty, 5));
          windowIn(tx, ty, tall);
          break;
        }
        case "door":
          box(own, tx, 0.02, ty, 1, 0.05, 1, palette?.accent ?? "#555555");
          break;
        case "desk": {
          // Turned to whoever sits at it: the screen faces the chair.
          const chairs = new Set<TileKind>(["chair"]);
          const at = place(facing(sideWith(map, tx, ty, chairs)));
          const front = facing(sideWith(map, tx, ty, chairs));
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
        case "table":
          if (zone === "software_office") {
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
          const at = place(facing(facingAt(map, tx, ty, fountain)));
          const [seat, frame] =
            zone === "law_office"
              ? ["#6b3f2a", "#3a2a20"]
              : zone === "cafe"
                ? ["#c99a62", "#7d5a36"]
                : zone === "accounting_office"
                  ? ["#52705f", "#2f3a34"]
                  : ["#3d4558", "#23262f"];
          at(0, 0.235, 0, 0.5, 0.07, 0.5, seat);
          at(0, 0.11, 0, 0.1, 0.2, 0.1, frame);
          at(0, 0.025, 0, 0.42, 0.05, 0.42, frame);
          at(0, 0.52, -0.27, 0.5, 0.5, 0.07, seat);
          break;
        }
        case "bench": {
          // Benches look at the fountain.
          const at = place(facing(facingAt(map, tx, ty, fountain)));
          at(0, 0.235, 0, 0.98, 0.07, 0.46, "#a9825a");
          at(-0.4, 0.1, 0, 0.08, 0.2, 0.4, "#3a3f4a");
          at(0.4, 0.1, 0, 0.08, 0.2, 0.4, "#3a3f4a");
          at(0, 0.5, -0.24, 0.98, 0.36, 0.06, "#a9825a");
          break;
        }
        case "whiteboard": {
          const at = place(away(sideWith(map, tx, ty, BACKING)));
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
          const front = away(sideWith(map, tx, ty, BACKING));
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
          const at = place(away(sideWith(map, tx, ty, BACKING)));
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
        case "conference":
          box(own, tx, 0.43, ty, 1, 0.08, 0.9, jitter("#5a3d2b", 0.04, tx, ty));
          box(own, tx, 0.2, ty, 0.5, 0.4, 0.3, "#3a2a20");
          break;
        case "reception":
          box(own, tx, 0.45, ty, 1, 0.9, 0.56, blend(palette?.wall ?? "#888888", "#3a2a20", 0.35));
          box(own, tx, 0.93, ty, 1, 0.06, 0.7, "#efe6d2");
          break;
        case "filing": {
          const front = away(sideWith(map, tx, ty, BACKING));
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
          const isSolid = (x: number, y: number) => solid.has(kindAt(x, y) ?? "grass");
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
          const front = away(sideWith(map, tx, ty, BACKING));
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

  /**
   * A pane of glass through every third block of an outside wall, standing a
   * hair proud of both faces so it shows from the street and from the room.
   * Unlit: pale sky by day, lit from inside at night, which is most of what
   * tells a visitor that it *is* night.
   */
  function windowIn(tx: number, ty: number, tall: number): void {
    const wallAt = (x: number, y: number) => kindAt(x, y) === "wall";
    const alongX = wallAt(tx - 1, ty) && wallAt(tx + 1, ty);
    const alongZ = wallAt(tx, ty - 1) && wallAt(tx, ty + 1);
    if (alongX === alongZ) return; // a corner, a junction or a stub
    if ((alongX ? tx : ty) % 3 !== 1) return;
    const y = tall * 0.56;
    const high = tall * 0.36;
    // A painted frame a little proud of the wall, and the glass proud of that.
    const trim = "#f1ede4";
    if (alongX) {
      voxels.push({ x: tx, y, z: ty, sx: 0.76, sy: high + 0.14, sz: 1.02, color: trim, ao: OPEN });
      glow("window", tx, y, ty, 0.62, high, 1.04, "#bfe0f5");
    } else {
      voxels.push({ x: tx, y, z: ty, sx: 1.02, sy: high + 0.14, sz: 0.76, color: trim, ao: OPEN });
      glow("window", tx, y, ty, 1.04, high, 0.62, "#bfe0f5");
    }
    // What a lit window throws on the ground, inside and out.
    glow("pool", tx, 0.03, ty, 4.2, 0, 4.2, "#ffc774");
  }

  // At night the lights are on indoors: a wash of warm pools across each floor.
  for (const building of map.buildings) {
    for (let ty = building.y0 + 2; ty < building.y1; ty += 3) {
      for (let tx = building.x0 + 2; tx < building.x1; tx += 3) {
        glow("pool", tx + 0.5, 0.03, ty + 0.5, 7, 0, 7, "#ffb866");
      }
    }
  }

  // A name board over each door, in the firm's colour, with the firm's
  // monogram on it in lit blocks: "Halloran & Pike LLP" is H&P. The camera
  // sees south faces, so that is the face that reads left to right; the north
  // face carries it too, the other way round, for whoever walks behind it.
  for (const building of map.buildings) {
    const palette = ORG_PALETTE[building.org_id];
    const [dx, dz] = building.door;
    const tall = WALL_HEIGHT[building.zone] ?? DEFAULT_WALL;
    const alongX = kindAt(dx - 1, dz) === "wall" || kindAt(dx + 1, dz) === "wall";
    const long = 3.2;
    const [sx, sz] = alongX ? [long, 0.34] : [0.34, long];
    voxels.push({
      x: dx,
      y: tall + 0.62,
      z: dz,
      sx,
      sy: 0.7,
      sz,
      color: palette?.body ?? "#999999",
      ao: OPEN,
    });
    if (alongX) {
      const text = monogram(building.name);
      const px = 0.115;
      const wide = (text.length * 4 - 1) * px;
      for (const face of [1, -1]) {
        [...text].forEach((letter, i) => {
          const rows = FONT[letter] ?? [];
          rows.forEach((row, r) => {
            for (let c = 0; c < 3; c++) {
              if (row[c] !== "#") continue;
              const along = -wide / 2 + (i * 4 + c + 0.5) * px;
              glow("sign", dx + face * along, tall + 0.62 + (2 - r) * px, dz + face * 0.175, px, px, 0.02, "#fff6dc");
            }
          });
        });
      }
    }
    // The lintel the board hangs from, so the doorway is a doorway.
    voxels.push({
      x: dx,
      y: tall + 0.07,
      z: dz,
      sx: alongX ? 1 : 1,
      sy: 0.14,
      sz: 1,
      color: capOf(palette),
      ao: OPEN,
    });
  }

  // What each building wears outside (audit D4). No roofs (WEB-0002): an
  // awning, a portico, a mast, window boxes. Doors are in north or south walls.
  const plain = (x: number, y: number, z: number, sx: number, sy: number, sz: number, color: string) =>
    voxels.push({ x, y, z, sx, sy, sz, color, ao: OPEN });
  for (const building of map.buildings) {
    const [dx, dz] = building.door;
    if (dz !== building.y0 && dz !== building.y1) continue;
    const out = dz === building.y1 ? 1 : -1;
    const tall = WALL_HEIGHT[building.zone] ?? DEFAULT_WALL;
    if (building.zone === "cafe") {
      // A striped awning the length of the front, in two steps so it slopes,
      // with a scalloped edge. It shades the first row outside the door.
      for (let tx = building.x0 + 1; tx < building.x1; tx++) {
        const stripe = tx % 2 === 0 ? "#c8453c" : "#f3efe6";
        plain(tx, tall + 0.3, dz + out * 0.72, 1, 0.08, 0.5, stripe);
        plain(tx, tall + 0.16, dz + out * 1.2, 1, 0.08, 0.5, stripe);
        plain(tx, tall + 0.03, dz + out * 1.43, 1, 0.2, 0.05, stripe);
      }
      for (const tx of [building.x0 + 1, dx - 1, dx + 1, building.x1 - 1]) {
        plain(tx + (tx < dx ? -0.4 : 0.4), (tall + 0.12) / 2, dz + out * 1.38, 0.08, tall + 0.12, 0.08, "#f3efe6");
      }
    } else if (building.zone === "law_office") {
      // Two columns and a pediment: a firm that wants to look like a bank.
      for (const side of [-1, 1]) {
        plain(dx + side, 0.08, dz + out * 0.85, 0.66, 0.16, 0.66, "#d8d0bd");
        plain(dx + side, (tall + 0.16) / 2, dz + out * 0.85, 0.44, tall + 0.16, 0.44, "#ece5d3");
        plain(dx + side, tall + 0.2, dz + out * 0.85, 0.62, 0.12, 0.62, "#d8d0bd");
      }
      plain(dx, tall + 0.37, dz + out * 0.85, 3.2, 0.22, 0.8, "#ece5d3");
      plain(dx, tall + 0.55, dz + out * 0.85, 2.2, 0.16, 0.7, "#ece5d3");
      plain(dx, tall + 0.69, dz + out * 0.85, 1.1, 0.12, 0.6, "#ece5d3");
    } else if (building.zone === "software_office") {
      // A mast and a dish on the back corner, with a light that is on at night.
      const mx = building.x0;
      const mz = out === 1 ? building.y0 : building.y1;
      plain(mx, tall + 0.9, mz, 0.12, 1.6, 0.12, "#5c6670");
      plain(mx + 0.3, tall + 0.75, mz, 0.5, 0.5, 0.08, "#dfe5ec");
      plain(mx + 0.3, tall + 0.75, mz + 0.08, 0.12, 0.12, 0.12, "#5c6670");
      glow("lamp", mx, tall + 1.76, mz, 0.18, 0.14, 0.18, "#ff6b5e");
      // And planters of bamboo either side of the door.
      for (const side of [-2, 2]) {
        if (kindAt(dx + side, dz + out) === "wall") continue;
        plain(dx + side, 0.2, dz + out * 0.85, 0.6, 0.4, 0.5, "#3a3f4a");
        plain(dx + side, 0.8, dz + out * 0.85, 0.44, 0.9, 0.36, "#4f9f58");
      }
    } else {
      // Window boxes along the front: the accountants water them.
      for (let tx = building.x0 + 1; tx < building.x1; tx++) {
        if (tx % 3 !== 1 || Math.abs(tx - dx) < 2) continue;
        plain(tx, tall * 0.34, dz + out * 0.6, 0.8, 0.16, 0.2, "#6b4a2f");
        plain(tx, tall * 0.34 + 0.13, dz + out * 0.6, 0.72, 0.12, 0.16, "#4f9f58");
        plain(tx - 0.2, tall * 0.34 + 0.2, dz + out * 0.62, 0.12, 0.08, 0.12, "#e0757c");
        plain(tx + 0.18, tall * 0.34 + 0.2, dz + out * 0.62, 0.12, 0.08, 0.12, "#f2e27a");
      }
    }
  }

  // The fountain's jet.
  if (fountain !== null) {
    const [cx, cz] = fountain;
    voxels.push({ x: cx, y: 0.75, z: cz, sx: 0.34, sy: 0.7, sz: 0.34, color: "#aaa595", ao: OPEN });
    voxels.push({ x: cx, y: 1.2, z: cz, sx: 0.2, sy: 0.3, sz: 0.2, color: "#9fd4f2", ao: OPEN });
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
