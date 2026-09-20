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
  status: z.enum(["running", "paused", "waiting_on_model", "halted"]),
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

export const WorldState = z.object({
  seq: z.number().int(),
  clock: Clock,
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

export const Economics = z.object({
  spend_usd: z.number(),
  model_calls: z.number().int(),
  sim_days: z.number(),
  counts: z.record(z.string(), z.number().int()),
  per_sim_day: z.object({
    usd_per_100_persons: z.number(),
    usd_per_10_orgs: z.number(),
    usd_per_1000_events: z.number(),
  }),
  note: z.string(),
});
export type Economics = z.infer<typeof Economics>;

export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
