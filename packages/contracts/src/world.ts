/**
 * The spatial world, as the API serves it (WORLD-0003, WEB-0002).
 *
 * The map is data, not an asset: the server builds it and the client draws
 * whatever arrives, so the renderer and the pathfinder cannot disagree about
 * where a wall is.
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
] as const;
export const TileKind = z.enum(TILE_KINDS);
export type TileKind = z.infer<typeof TileKind>;

const Tile = z.tuple([z.number().int(), z.number().int()]);
export type Tile = z.infer<typeof Tile>;

export const Building = z.object({
  zone: Zone,
  org_id: z.string(),
  name: z.string(),
  x0: z.number().int(),
  y0: z.number().int(),
  x1: z.number().int(),
  y1: z.number().int(),
  door: Tile,
});
export type Building = z.infer<typeof Building>;

export const TownMap = z.object({
  width: z.number().int(),
  height: z.number().int(),
  tiles: z.array(z.array(TileKind)),
  zones: z.array(z.array(Zone)),
  buildings: z.array(Building),
  crowd_spots: z.record(z.string(), z.array(Tile)),
  /**
   * Per zone, the tiles somebody sits on rather than stands on: chairs and
   * benches, whether they belong to staff or to visitors (WEB-0004). A barista's
   * place behind the counter is not one.
   */
  seats: z.record(z.string(), z.array(Tile)),
});
export type TownMap = z.infer<typeof TownMap>;

export const Agent = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  role: z.string(),
  zone: Zone,
  x: z.number().int().nullable(),
  y: z.number().int().nullable(),
  path: z.array(Tile),
  moved_tick: z.number().int(),
  mood: z.number().int(),
});
export type Agent = z.infer<typeof Agent>;

export const AgentsFrame = z.object({
  seq: z.number().int(),
  tick_seq: z.number().int(),
  sim_time: z.number().int(),
  label: z.string(),
  status: z.string(),
  agents: z.array(Agent),
  /** Counterparties are demand, not people with positions: how many to draw. */
  crowd: z.record(z.string(), z.number().int()),
  down_modules: z.array(z.string()),
});
export type AgentsFrame = z.infer<typeof AgentsFrame>;

const Distribution = z.record(z.string(), z.number());

export const AgentDetail = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  org_name: z.string(),
  role: z.string(),
  zone: Zone,
  mood: z.number().int(),
  traits: z.record(z.string(), z.number()),
  trait_words: z.record(z.string(), z.string()),
  last_decision: z
    .object({
      id: z.number().int(),
      sim_time: z.number().int(),
      label: z.string(),
      question_set: z.string(),
      source: z.string(),
      model: z.string().nullable(),
      chosen: z.record(z.string(), z.unknown()),
      distributions: z.record(z.string(), Distribution),
      draws: z.record(z.string(), z.number()),
    })
    .nullable(),
  last_encounter: z
    .object({
      seq: z.number().int(),
      label: z.string(),
      with_id: z.string(),
      with_name: z.string(),
      zone: Zone,
      topic: z.string(),
      initiated: z.boolean(),
      led_to: z.array(z.string()),
    })
    .nullable(),
});
export type AgentDetail = z.infer<typeof AgentDetail>;

export const OrgDetail = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  zone: Zone,
  cash_cents: z.number().int(),
  receivable_cents: z.number().int(),
  staff_present: z.number().int(),
  staff_total: z.number().int(),
  open_tickets: z.number().int(),
  unpaid_invoices: z.number().int(),
  active: z.array(z.string()),
});
export type OrgDetail = z.infer<typeof OrgDetail>;

/** Per-org voxel palettes. Procedural geometry, no third-party assets. */
export const ORG_PALETTE: Record<
  string,
  { wall: string; floor: string; body: string; accent: string }
> = {
  tallybird: { wall: "#5b78d6", floor: "#c9d4f5", body: "#7c9cff", accent: "#2b3f8c" },
  halloran: { wall: "#a8871f", floor: "#efe3b8", body: "#c9a227", accent: "#5e4a0c" },
  ledgerline: { wall: "#3f9470", floor: "#cdebdc", body: "#5bb98c", accent: "#1f4d3a" },
  thirdrail: { wall: "#b9555c", floor: "#f6d3d5", body: "#e0757c", accent: "#6b2227" },
};

/**
 * One encounter: the typed record, and prose if it could be had (GEN-0001).
 * `typed` is what happened. `prose` is a rendering of it for a reader, and is
 * read by nothing else.
 */
export const EncounterDialogue = z.object({
  typed: z.object({
    seq: z.number().int(),
    between: z.array(z.string()),
    zone: z.string(),
    topic: z.string(),
    mood: z.string(),
    escalated: z.boolean(),
  }),
  prose: z
    .object({
      lines: z.array(z.object({ speaker: z.string(), text: z.string() })),
      model: z.string(),
      cost_usd: z.number(),
      cached: z.boolean(),
      skipped: z.array(z.string()).optional(),
    })
    .nullable(),
  reason: z.string().nullable(),
});
export type EncounterDialogue = z.infer<typeof EncounterDialogue>;
