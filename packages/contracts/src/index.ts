/**
 * The API contract, as zod schemas.
 *
 * Every response is parsed at the boundary rather than cast. An endpoint that
 * changes shape then fails loudly in one place instead of becoming `undefined`
 * three components deep.
 *
 * pydantic is the source of truth (CORE-0006); `pnpm contracts:check` compares
 * these against the live OpenAPI document, so drift is a failing check rather
 * than a runtime surprise.
 */
import { z } from "zod";

export const Clock = z.object({
  sim_time: z.number().int(),
  label: z.string(),
  day: z.number().int(),
  weekday: z.number().int(),
  in_office_hours: z.boolean(),
  tick_seq: z.number().int(),
  // Every value the database's CHECK allows. `paused_budget` was missing, so
  // the day the governor paused the world the page would have failed to parse.
  status: z.enum(["running", "paused", "paused_budget", "waiting_on_model", "waiting_on_budget", "halted"]),
  speed: z.number(),
  run_id: z.string(),
});
export type Clock = z.infer<typeof Clock>;

export const Org = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["software", "law", "accounting", "cafe"]),
  cash_cents: z.number().int(),
  receivable_cents: z.number().int(),
});
export type Org = z.infer<typeof Org>;

export const Module = z.object({
  id: z.string(),
  name: z.string(),
  status: z.enum(["up", "down"]),
});
export type Module = z.infer<typeof Module>;

/** Is anybody driving? `clock.status` is the daemon's word; this is the evidence (SIM-0002). */
export const Health = z.object({
  /** Seconds since the daemon last proved it was alive. Null before its first beat. */
  heartbeat_age_s: z.number().nullable(),
  /** How far the last tick ran over its pacing. */
  lag_s: z.number(),
  last_error: z.string().nullable(),
  /** The status says a process should be alive and the heartbeat says none is. */
  stale: z.boolean(),
});
export type Health = z.infer<typeof Health>;

export const WorldState = z.object({
  seq: z.number().int(),
  clock: Clock,
  health: Health,
  orgs: z.array(Org),
  modules: z.array(Module),
  tickets: z.object({ untriaged: z.number().int(), open: z.number().int() }),
  unpaid_invoices: z.object({ n: z.number().int(), cents: z.number().int() }),
  persons: z.record(z.string(), z.number().int()),
});
export type WorldState = z.infer<typeof WorldState>;

export const SimEvent = z.object({
  seq: z.number().int(),
  sim_time: z.number().int(),
  tick_seq: z.number().int().optional(),
  kind: z.string(),
  actor_id: z.string().nullable(),
  org_id: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
  causes: z.array(z.number().int()),
  label: z.string().optional(),
  depth: z.number().int().optional(),
});
export type SimEvent = z.infer<typeof SimEvent>;

export const EventPage = z.object({
  events: z.array(SimEvent),
  seq: z.number().int(),
});
export type EventPage = z.infer<typeof EventPage>;

export const CausalChain = z.object({
  root: z.number().int(),
  direction: z.enum(["up", "down"]),
  events: z.array(SimEvent),
});
export type CausalChain = z.infer<typeof CausalChain>;

export const Person = z.object({
  id: z.string(),
  org_id: z.string().nullable(),
  name: z.string(),
  role: z.string(),
  kind: z.enum(["staff", "counterparty"]),
  traits: z.record(z.string(), z.number()).nullable(),
  decision_seq: z.number().int().optional(),
  status: z.string().optional(),
});
export type Person = z.infer<typeof Person>;

export const Decision = z.object({
  id: z.number().int(),
  decision_seq: z.number().int(),
  sim_time: z.number().int(),
  label: z.string().optional(),
  question_set: z.string(),
  /** Which kind of decider answered — the research question, per row. */
  source: z.enum(["rules", "jev", "llm"]),
  /** Empty for a rules decision; a real distribution once Jev is wired in. */
  distributions: z.record(z.string(), z.record(z.string(), z.number())),
  prng_path: z.string(),
  draws: z.record(z.string(), z.number()),
  chosen: z.record(z.string(), z.unknown()),
  model_call: z.string().nullable(),
});
export type Decision = z.infer<typeof Decision>;

export const PersonDecisions = z.object({
  person: Person,
  decisions: z.array(Decision),
});
export type PersonDecisions = z.infer<typeof PersonDecisions>;

export const PerSimDay = z.object({
  usd: z.number(),
  usd_per_100_persons: z.number(),
  usd_per_10_orgs: z.number(),
  usd_per_1000_events: z.number(),
});
export type PerSimDay = z.infer<typeof PerSimDay>;

export const Economics = z.object({
  spend_usd: z.number(),
  spend_is_estimated_calls: z.number().int(),
  model_calls: z.number().int(),
  input_tokens: z.number().int(),
  sim_days: z.number(),
  counts: z.record(z.string(), z.number().int()),
  per_sim_day: PerSimDay,
  without_dedup: z.object({ spend_usd: z.number(), per_sim_day: PerSimDay }),
  dedup_rate: z.number(),
  unpriced_decisions: z.number().int(),
  decisions_by_model: z.array(
    z.object({
      model: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
    }),
  ),
  by_kind: z.array(
    z.object({
      kind: z.string(),
      source: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
      usd: z.number(),
    }),
  ),
  note: z.string(),
});
export type Economics = z.infer<typeof Economics>;

export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
export * from "./world";
