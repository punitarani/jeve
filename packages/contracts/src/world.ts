/**
 * The spatial world's domain vocabulary (WORLD-0003, WEB-0002, WORLD-0008).
 *
 * What lives here is what the *client's scene model* needs beyond the wire:
 * the tile-kind union and the Tile and Node coordinates. Zones are strings —
 * a firm's id, `plaza` or `home` — and a firm's colours arrive with its
 * building on `/world/map` and with the firm on `/state`, so a thirteenth firm
 * is a data change (CORE-0012). The API response schemas that consume these —
 * TownMap, Agent, AgentsFrame, AgentDetail, OrgDetail, EncounterDialogue — are
 * generated from `jeve.api.contracts` into ./index.ts like everything else on
 * the wire, so they are deliberately not defined here.
 */
import { z } from "zod";

export const PLAZA = "plaza";
export const HOME = "home";

export const TILE_KINDS = [
	"grass",
	"plaza",
	"path",
	"wall",
	"floor",
	"door",
	"desk",
	"counter",
	"table",
	"tree",
	"fountain",
	// WEB-0004: furniture that tells the buildings apart. `chair`, `bench`
	// and `sofa` can be walked onto and sat on; `stair` is walked onto and
	// climbed; the rest are in the way.
	"chair",
	"bench",
	"sofa",
	"stair",
	"whiteboard",
	"server_rack",
	"bookshelf",
	"conference",
	"reception",
	"filing",
	"partition",
	"kitchen",
	"kitchenette",
	"shelf",
	"rack",
	"equipment",
	"dental_chair",
	"teller",
	"plant",
	"planter",
	"lamp",
	// Upper storeys are local grids over a footprint; outside it is nothing.
	"void",
] as const;
export const TileKind = z.enum(TILE_KINDS);
export type TileKind = z.infer<typeof TileKind>;

export const Tile = z.tuple([z.number().int(), z.number().int()]);
export type Tile = z.infer<typeof Tile>;

/** Where someone can be: a tile and the floor it is on. */
export const Node = z.tuple([z.number().int(), z.number().int(), z.number().int()]);
export type Node = z.infer<typeof Node>;
