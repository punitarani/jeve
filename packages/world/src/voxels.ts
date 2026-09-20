/**
 * The town as boxes. Pure data: a list of (position, size, colour), so it can
 * be inspected and tested without a GPU. The renderer turns the whole list into
 * a single instanced mesh — one draw call for every tile, wall, desk and tree.
 *
 * All geometry is procedural. There are no sprites, models or textures from
 * anywhere, so there is nothing here to license.
 */
import { ORG_PALETTE, type TileKind, type TownMap, type Zone } from "@jeve/contracts";

export type Voxel = {
  x: number;
  y: number;
  z: number;
  sx: number;
  sy: number;
  sz: number;
  color: string;
};

const ZONE_ORG: Partial<Record<Zone, string>> = {
  software_office: "tallybird",
  law_office: "halloran",
  accounting_office: "ledgerline",
  cafe: "thirdrail",
};

const GROUND: Partial<Record<TileKind, [string, string]>> = {
  grass: ["#7fb86a", "#77b063"],
  plaza: ["#d9d2c1", "#d2cab8"],
  path: ["#ebe5d6", "#e4ddcc"],
  tree: ["#7fb86a", "#77b063"],
  fountain: ["#d9d2c1", "#d2cab8"],
};

const WALL_HEIGHT = 1.5;

function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const channel = (shift: number) =>
    Math.max(0, Math.min(255, Math.round(((n >> shift) & 255) * (1 + amount))));
  const value = (channel(16) << 16) | (channel(8) << 8) | channel(0);
  return `#${value.toString(16).padStart(6, "0")}`;
}

/** Every static box in the town. y is up; x and z are the tile grid. */
export function buildVoxels(map: TownMap): Voxel[] {
  const voxels: Voxel[] = [];
  const box = (
    x: number,
    y: number,
    z: number,
    sx: number,
    sy: number,
    sz: number,
    color: string,
  ) => voxels.push({ x, y, z, sx, sy, sz, color });

  for (let ty = 0; ty < map.height; ty++) {
    for (let tx = 0; tx < map.width; tx++) {
      const kind = map.tiles[ty]?.[tx];
      const zone = map.zones[ty]?.[tx];
      if (kind === undefined || zone === undefined) continue;
      const checker = (tx + ty) % 2;
      const org = ZONE_ORG[zone];
      const palette = org === undefined ? undefined : ORG_PALETTE[org];

      // The ground under everything. Interiors take a tint of the firm's
      // colour, so a building reads as belonging to someone from any zoom.
      const pair = GROUND[kind];
      const ground =
        pair !== undefined
          ? (pair[checker] ?? pair[0])
          : shade(palette?.floor ?? "#dddddd", checker === 0 ? 0 : -0.04);
      box(tx, -0.1, ty, 1, 0.2, 1, ground);

      switch (kind) {
        case "wall":
          // Roofless, so the people inside are the point of the picture.
          box(tx, WALL_HEIGHT / 2, ty, 1, WALL_HEIGHT, 1, palette?.wall ?? "#888888");
          box(tx, WALL_HEIGHT + 0.06, ty, 1, 0.12, 1, palette?.accent ?? "#555555");
          break;
        case "door":
          box(tx, 0.02, ty, 1, 0.05, 1, palette?.accent ?? "#555555");
          break;
        case "desk":
          box(tx, 0.32, ty, 0.92, 0.12, 0.7, "#b98a55");
          box(tx, 0.13, ty, 0.8, 0.26, 0.08, "#8b6239");
          box(tx + 0.18, 0.52, ty - 0.08, 0.42, 0.3, 0.06, "#2b2f3a");
          break;
        case "counter":
          box(tx, 0.4, ty, 1, 0.8, 0.7, "#8b5a3c");
          box(tx, 0.84, ty, 1, 0.08, 0.8, "#e9dcc6");
          break;
        case "table":
          box(tx, 0.36, ty, 0.7, 0.08, 0.7, "#e9dcc6");
          box(tx, 0.16, ty, 0.14, 0.32, 0.14, "#6b4a35");
          break;
        case "tree":
          box(tx, 0.45, ty, 0.26, 0.9, 0.26, "#7a5536");
          box(tx, 1.2, ty, 1.05, 0.8, 1.05, "#3f8f4f");
          box(tx, 1.78, ty, 0.66, 0.5, 0.66, "#52a862");
          break;
        case "fountain":
          box(tx, 0.18, ty, 1, 0.36, 1, "#b9b2a2");
          box(tx, 0.4, ty, 0.78, 0.1, 0.78, "#6cb7e6");
          break;
        default:
          break;
      }
    }
  }

  // A sign block over each door, in the firm's colour.
  for (const building of map.buildings) {
    const palette = ORG_PALETTE[building.org_id];
    const [dx, dz] = building.door;
    box(dx, WALL_HEIGHT + 0.5, dz, 2.6, 0.6, 0.3, palette?.body ?? "#999999");
  }
  // The fountain's jet.
  const jets = map.tiles.flatMap((row, ty) =>
    row.flatMap((kind, tx) => (kind === "fountain" ? [[tx, ty] as const] : [])),
  );
  if (jets.length > 0) {
    const cx = jets.reduce((s, [x]) => s + x, 0) / jets.length;
    const cz = jets.reduce((s, [, z]) => s + z, 0) / jets.length;
    box(cx, 0.85, cz, 0.3, 0.9, 0.3, "#9fd4f2");
  }
  return voxels;
}

/** The parts of a person. One instanced mesh per part. */
export const PERSON_PARTS = [
  { name: "legs", y: 0.2, sx: 0.34, sy: 0.4, sz: 0.24 },
  { name: "body", y: 0.62, sx: 0.46, sy: 0.46, sz: 0.3 },
  { name: "head", y: 1.04, sx: 0.36, sy: 0.36, sz: 0.36 },
  { name: "hair", y: 1.25, sx: 0.4, sy: 0.1, sz: 0.4 },
] as const;

export const SKIN_TONES = ["#f2c9a5", "#d9a57c", "#a9744f", "#7b4f34", "#f0d5b8"];
export const HAIR_TONES = ["#2b1d14", "#5a3b22", "#1c1c22", "#8a5a2b", "#c9c2b8"];
