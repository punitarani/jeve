/**
 * The spatial world's domain vocabulary (WORLD-0003, WEB-0002).
 *
 * What lives here is what the *client's scene model* needs beyond the wire:
 * the zone and tile-kind unions, the Tile coordinate, and the per-org voxel
 * palette. The API response schemas that consume these — TownMap, Agent,
 * AgentsFrame, AgentDetail, OrgDetail, EncounterDialogue — are generated
 * from `jeve.api.contracts` into ./index.ts like everything else on the
 * wire, so they are deliberately not defined here.
 */
import { z } from "zod";

export const ZONES = [
	"software_office",
	"law_office",
	"accounting_office",
	"cafe",
	"plaza",
	"home",
] as const;
export const Zone = z.enum(ZONES);
export type Zone = z.infer<typeof Zone>;

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
	// WEB-0004: furniture that tells the four buildings apart. `chair` and
	// `bench` can be walked onto and sat on; the rest are in the way.
	"chair",
	"bench",
	"whiteboard",
	"server_rack",
	"bookshelf",
	"conference",
	"reception",
	"filing",
	"partition",
	"kitchen",
	"plant",
	"planter",
	"lamp",
] as const;
export const TileKind = z.enum(TILE_KINDS);
export type TileKind = z.infer<typeof TileKind>;

export const Tile = z.tuple([z.number().int(), z.number().int()]);
export type Tile = z.infer<typeof Tile>;

/** Per-org voxel palettes. Procedural geometry, no third-party assets. */
export const ORG_PALETTE: Record<
	string,
	{ wall: string; floor: string; body: string; accent: string }
> = {
	tallybird: {
		wall: "#5b78d6",
		floor: "#c9d4f5",
		body: "#7c9cff",
		accent: "#2b3f8c",
	},
	halloran: {
		wall: "#a8871f",
		floor: "#efe3b8",
		body: "#c9a227",
		accent: "#5e4a0c",
	},
	ledgerline: {
		wall: "#3f9470",
		floor: "#cdebdc",
		body: "#5bb98c",
		accent: "#1f4d3a",
	},
	thirdrail: {
		wall: "#b9555c",
		floor: "#f6d3d5",
		body: "#e0757c",
		accent: "#6b2227",
	},
};
