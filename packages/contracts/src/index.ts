/**
 * The API contract, as zod schemas — generated. Do not edit by hand.
 *
 * Source of truth: the pydantic models in `jeve.api.contracts`
 * (py/src/jeve/api/contracts.py). `nx run contracts:generate` rewrites this
 * file and `contracts:check-drift` fails on the diff; `test_api.py` validates
 * real responses against the same models, so drift is a failing check rather
 * than a runtime surprise.
 *
 * Every response is parsed at the boundary rather than cast. An endpoint that
 * changes shape then fails loudly in one place instead of becoming `undefined`
 * three components deep.
 */
import { z } from "zod";

export const Clock = z.object({
  sim_time: z.number().int(),
  label: z.string(),
  day: z.number().int(),
  weekday: z.number().int(),
  in_office_hours: z.boolean(),
  tick_seq: z.number().int(),
  /** Every value the database's CHECK allows. `paused_budget` was missing, so the day the governor paused the world the page would have failed to parse. */
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
  /** Whether this deployment carries a BRAINTRUST_API_KEY (LLM-0009). False means nothing is traced, silently and by design. True means the key is present, not that Braintrust is accepting the spans — the SDK reports a rejected key or project only on the daemon's stderr. */
  tracing: z.boolean(),
});
export type Health = z.infer<typeof Health>;

export const TicketCounts = z.object({
  untriaged: z.number().int(),
  open: z.number().int(),
});
export type TicketCounts = z.infer<typeof TicketCounts>;

export const UnpaidInvoices = z.object({
  n: z.number().int(),
  cents: z.number().int(),
});
export type UnpaidInvoices = z.infer<typeof UnpaidInvoices>;

export const WorldState = z.object({
  seq: z.number().int(),
  clock: Clock,
  health: Health,
  orgs: z.array(Org),
  modules: z.array(Module),
  tickets: TicketCounts,
  unpaid_invoices: UnpaidInvoices,
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
  label: z.string(),
  depth: z.number().int().optional(),
});
export type SimEvent = z.infer<typeof SimEvent>;

export const EventPage = z.object({
  events: z.array(SimEvent),
  /** the newest seq in this page: the cursor for `after` */
  seq: z.number().int(),
  /** the oldest seq in this page: the cursor for `before`; 0 when empty */
  oldest: z.number().int(),
  /** whether another page exists in the direction this one travelled */
  more: z.boolean(),
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
  traits: z.record(z.string(), z.number()),
  decision_seq: z.number().int().optional(),
  status: z.string().optional(),
});
export type Person = z.infer<typeof Person>;

export const Decision = z.object({
  id: z.number().int(),
  decision_seq: z.number().int(),
  sim_time: z.number().int(),
  tick_seq: z.number().int(),
  label: z.string(),
  question_set: z.string(),
  /** Which kind of decider answered — the research question, per row. */
  source: z.enum(["rules", "jev", "llm"]),
  /** Empty for a rules decision; the full distribution when a model answered. */
  distributions: z.record(z.string(), z.record(z.string(), z.number())),
  prng_path: z.string(),
  draws: z.record(z.string(), z.number()),
  chosen: z.record(z.string(), z.unknown()),
  model_call: z.string().nullable(),
});
export type Decision = z.infer<typeof Decision>;

export const PersonsResponse = z.object({
  persons: z.array(Person),
});
export type PersonsResponse = z.infer<typeof PersonsResponse>;

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

export const SpendWithoutDedup = z.object({
  spend_usd: z.number(),
  per_sim_day: PerSimDay,
});
export type SpendWithoutDedup = z.infer<typeof SpendWithoutDedup>;

export const DecisionsByModel = z.object({
  model: z.string(),
  decisions: z.number().int(),
  calls: z.number().int(),
});
export type DecisionsByModel = z.infer<typeof DecisionsByModel>;

export const DecisionsByKind = z.object({
  kind: z.string(),
  source: z.string(),
  decisions: z.number().int(),
  calls: z.number().int(),
  usd: z.number(),
});
export type DecisionsByKind = z.infer<typeof DecisionsByKind>;

/** One building's footprint. `door` is the walkable tile in its wall. */
export const Building = z.object({
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  org_id: z.string(),
  name: z.string(),
  x0: z.number().int(),
  y0: z.number().int(),
  x1: z.number().int(),
  y1: z.number().int(),
  door: z.tuple([z.number().int(), z.number().int()]),
});
export type Building = z.infer<typeof Building>;

/** GET /world/map — the whole town, as data. Static for a page's life. */
export const TownMap = z.object({
  width: z.number().int(),
  height: z.number().int(),
  tiles: z.array(z.array(z.enum(["grass", "plaza", "path", "wall", "floor", "door", "desk", "counter", "table", "tree", "fountain", "chair", "bench", "whiteboard", "server_rack", "bookshelf", "conference", "reception", "filing", "partition", "kitchen", "plant", "planter", "lamp"]))),
  zones: z.array(z.array(z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]))),
  buildings: z.array(Building),
  crowd_spots: z.record(z.string(), z.array(z.tuple([z.number().int(), z.number().int()]))),
  seats: z.record(z.string(), z.array(z.tuple([z.number().int(), z.number().int()]))),
});
export type TownMap = z.infer<typeof TownMap>;

/** One member of staff's position, as /world/agents serves it. */
export const Agent = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  role: z.string(),
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  x: z.number().int().nullable(),
  y: z.number().int().nullable(),
  path: z.array(z.tuple([z.number().int(), z.number().int()])),
  moved_tick: z.number().int(),
  mood: z.number().int(),
});
export type Agent = z.infer<typeof Agent>;

/** GET /world/agents — the current frame: staff, the crowd, what is down. */
export const AgentsFrame = z.object({
  seq: z.number().int(),
  tick_seq: z.number().int(),
  sim_time: z.number().int(),
  label: z.string(),
  status: z.enum(["running", "paused", "paused_budget", "waiting_on_model", "waiting_on_budget", "halted"]),
  agents: z.array(Agent),
  crowd: z.record(z.string(), z.number().int()),
  down_modules: z.array(z.string()),
});
export type AgentsFrame = z.infer<typeof AgentsFrame>;

/** A person's last decision: the distribution Jev returned and the draw. */
export const DecisionBrief = z.object({
  id: z.number().int(),
  sim_time: z.number().int(),
  label: z.string(),
  question_set: z.string(),
  source: z.enum(["rules", "jev", "llm"]),
  model: z.string().nullable(),
  chosen: z.record(z.string(), z.unknown()),
  distributions: z.record(z.string(), z.record(z.string(), z.number())),
  draws: z.record(z.string(), z.number()),
});
export type DecisionBrief = z.infer<typeof DecisionBrief>;

/** Whom a person last met, and what the meeting led to. */
export const EncounterBrief = z.object({
  seq: z.number().int(),
  label: z.string(),
  with_id: z.string(),
  with_name: z.string(),
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  topic: z.string(),
  initiated: z.boolean(),
  led_to: z.array(z.string()),
});
export type EncounterBrief = z.infer<typeof EncounterBrief>;

/** GET /world/agents/{id} — who they are, what they last decided, met. */
export const AgentDetail = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  org_name: z.string(),
  role: z.string(),
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  mood: z.number().int(),
  traits: z.record(z.string(), z.number()),
  trait_words: z.record(z.string(), z.string()),
  last_decision: DecisionBrief.nullable(),
  last_encounter: EncounterBrief.nullable(),
});
export type AgentDetail = z.infer<typeof AgentDetail>;

/** GET /orgs/{id} — one firm's books, people, and what is going on. */
export const OrgDetail = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["software", "law", "accounting", "cafe"]),
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  cash_cents: z.number().int(),
  receivable_cents: z.number().int(),
  staff_present: z.number().int(),
  staff_total: z.number().int(),
  open_tickets: z.number().int(),
  unpaid_invoices: z.number().int(),
  active: z.array(z.string()),
});
export type OrgDetail = z.infer<typeof OrgDetail>;

export const DialogueLine = z.object({
  speaker: z.string(),
  text: z.string(),
});
export type DialogueLine = z.infer<typeof DialogueLine>;

/** The typed record of one encounter — this, not the prose, is what happened (GEN-0001). */
export const EncounterTyped = z.object({
  seq: z.number().int(),
  between: z.tuple([z.string(), z.string()]),
  zone: z.string(),
  topic: z.string(),
  mood: z.string(),
  escalated: z.boolean(),
});
export type EncounterTyped = z.infer<typeof EncounterTyped>;

/** A rendering of the typed record. `skipped` is sent only by a fresh render — cached prose has none — so the wire omits it rather than sending null. */
export const EncounterProse = z.object({
  lines: z.array(DialogueLine),
  model: z.string(),
  cost_usd: z.number(),
  cached: z.boolean(),
  skipped: z.array(z.string()).optional(),
});
export type EncounterProse = z.infer<typeof EncounterProse>;

/** GET /encounters/{seq}/dialogue — the record always; prose if held. */
export const EncounterDialogue = z.object({
  typed: EncounterTyped,
  prose: EncounterProse.nullable(),
  reason: z.string().nullable(),
});
export type EncounterDialogue = z.infer<typeof EncounterDialogue>;

/** One person at the table. `seat` is speaking order, drawn when the episode opened; `left_round` is set if they walked away early. */
export const EpisodeParticipant = z.object({
  person_id: z.string(),
  name: z.string(),
  org_id: z.string().nullable(),
  role: z.string(),
  seat: z.number().int(),
  left_round: z.number().int().nullable(),
  /** Whether they could settle the matter, wanted it settled, or were only in the room. Derived from the acts they were offered. */
  role_in_stake: z.enum(["holder", "asker", "bystander"]),
});
export type EpisodeParticipant = z.infer<typeof EpisodeParticipant>;

/** What one person did in one round — the typed record, not a line of dialogue. There is no prose here to render. */
export const EpisodeAct = z.object({
  person_id: z.string(),
  act: z.string(),
  seat: z.number().int(),
});
export type EpisodeAct = z.infer<typeof EpisodeAct>;

export const EpisodeRound = z.object({
  round: z.number().int(),
  acts: z.array(EpisodeAct),
  left: z.array(z.string()),
  tension: z.number().int(),
  decided_by: z.enum(["rules", "jev", "llm", "episode"]),
});
export type EpisodeRound = z.infer<typeof EpisodeRound>;

/** What the episode changed. Every field here reached the world through an event that cites the episode's closing event, never through this record. */
export const EpisodeOutcome = z.object({
  pressed: z.boolean(),
  promised: z.boolean(),
  refused: z.boolean(),
  tension: z.number().int(),
  facts_passed: z.number().int(),
  /** Acts that landed on `other`: the share of a decision surface the typed vocabulary did not cover, which is the project's primary research measurement (DECIDE-0001). */
  ontology_gaps: z.number().int(),
});
export type EpisodeOutcome = z.infer<typeof EpisodeOutcome>;

/** GET /episodes/{id} — a meeting that got more than one round. */
export const Episode = z.object({
  id: z.number().int(),
  zone: z.enum(["software_office", "law_office", "accounting_office", "cafe", "plaza", "home"]),
  stake: z.enum(["outage", "invoice", "news"]),
  stake_ref: z.string(),
  depth: z.number().int(),
  parent_id: z.number().int().nullable(),
  opened_sim: z.number().int(),
  opened_label: z.string(),
  opened_seq: z.number().int(),
  closed_sim: z.number().int().nullable(),
  closed_seq: z.number().int().nullable(),
  rounds: z.number().int(),
  exit_reason: z.enum(["settled", "emptied", "rounds"]).nullable(),
  outcome: EpisodeOutcome,
  participants: z.array(EpisodeParticipant),
  round_log: z.array(EpisodeRound),
  /** What the episode caused, by following `causes` from its closing event — an escalation, a fact passed on, a promise. */
  led_to: z.array(SimEvent),
});
export type Episode = z.infer<typeof Episode>;

export const EpisodePage = z.object({
  episodes: z.array(Episode),
  more: z.boolean(),
});
export type EpisodePage = z.infer<typeof EpisodePage>;

export const Economics = z.object({
  spend_usd: z.number(),
  spend_is_estimated_calls: z.number().int(),
  model_calls: z.number().int(),
  input_tokens: z.number().int(),
  sim_days: z.number(),
  counts: z.record(z.string(), z.number().int()),
  per_sim_day: PerSimDay,
  without_dedup: SpendWithoutDedup,
  dedup_rate: z.number(),
  unpriced_decisions: z.number().int(),
  decisions_by_model: z.array(DecisionsByModel),
  by_kind: z.array(DecisionsByKind),
  note: z.string(),
});
export type Economics = z.infer<typeof Economics>;

export const ReportVitals = z.object({
  sim_days: z.number().int(),
  events: z.number().int(),
  decisions: z.number().int(),
  /** Decisions a model call answered. */
  modelled: z.number().int(),
  distinct_calls: z.number().int(),
  /** 1 - distinct_calls / modelled: the share of modelled decisions answered by a call made before. */
  cache_hit_rate: z.number(),
  /** Priced as /economics prices it: each call this run used, once, at what it cost when first made. */
  spend_usd: z.number(),
  ledger_entries: z.number().int(),
  /** Sum of every ledger entry. Zero, or the books are wrong. */
  ledger_imbalance_cents: z.number().int(),
  incidents: z.number().int(),
  incidents_escalated: z.number().int(),
  escalations: z.number().int(),
  escalations_in_cafe: z.number().int(),
  persons: z.record(z.string(), z.number().int()),
});
export type ReportVitals = z.infer<typeof ReportVitals>;

export const ReportCashSeries = z.object({
  account_id: z.string(),
  /** Null for the household sector. */
  org_id: z.string().nullable(),
  name: z.string(),
  /** Cents at the end of each sim-day, from `first_day`. */
  values: z.array(z.number().int()),
});
export type ReportCashSeries = z.infer<typeof ReportCashSeries>;

export const ReportCash = z.object({
  first_day: z.number().int(),
  series: z.array(ReportCashSeries),
});
export type ReportCash = z.infer<typeof ReportCash>;

export const ReportCacheDay = z.object({
  day: z.number().int(),
  /** Modelled decisions that sim-day. */
  decisions: z.number().int(),
  /** Of those, calls never made before. */
  new_calls: z.number().int(),
});
export type ReportCacheDay = z.infer<typeof ReportCacheDay>;

export const ReportCallSet = z.object({
  question_set: z.string(),
  decisions: z.number().int(),
  /** Settled by a gate, with no model call. */
  gated: z.number().int(),
  calls: z.number().int(),
  usd: z.number(),
});
export type ReportCallSet = z.infer<typeof ReportCallSet>;

export const ReportPerson = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  role: z.string(),
  /** agent.tick decisions. */
  decisions: z.number().int(),
  /** Mean chosen mood, 0-3. */
  mood: z.number().nullable(),
  /** Share of ticks they chose to talk. */
  talk_share: z.number(),
  /** Share of their time on the map spent at the cafe, walked from agent.moved. */
  cafe_share: z.number(),
  /** Outages they escalated in person. */
  raised: z.number().int(),
  /** Escalations raised with them. */
  received: z.number().int(),
  sociability: z.number(),
  diligence: z.number(),
});
export type ReportPerson = z.infer<typeof ReportPerson>;

export const ReportHourShare = z.object({
  hour: z.number().int(),
  share: z.number(),
});
export type ReportHourShare = z.infer<typeof ReportHourShare>;

export const ReportCafeHour = z.object({
  hour: z.number().int(),
  sales: z.number().int(),
  walkouts: z.number().int(),
});
export type ReportCafeHour = z.infer<typeof ReportCafeHour>;

export const ReportMood = z.object({
  /** `ordinary`, the id of the module the prompt said was down, or `other`. */
  mind: z.string(),
  decisions: z.number().int(),
  mood: z.number(),
});
export type ReportMood = z.infer<typeof ReportMood>;

export const ReportPayroll = z.object({
  org_id: z.string(),
  name: z.string(),
  paid: z.number().int(),
  held: z.number().int(),
  last_paid_day: z.number().int().nullable(),
  insolvency_warnings: z.number().int(),
});
export type ReportPayroll = z.infer<typeof ReportPayroll>;

export const ReportCollections = z.object({
  paid: z.number().int(),
  mean_days_late: z.number().nullable(),
  max_days_late: z.number().int().nullable(),
  open: z.number().int(),
  overdue: z.number().int(),
  written_off: z.number().int(),
});
export type ReportCollections = z.infer<typeof ReportCollections>;

export const ReportHouseholds = z.object({
  wages_cents: z.number().int(),
  spending_cents: z.number().int(),
});
export type ReportHouseholds = z.infer<typeof ReportHouseholds>;

export const ReportOutage = z.object({
  module_id: z.string(),
  name: z.string(),
  incidents: z.number().int(),
  escalated: z.number().int(),
  minutes_to_escalate: z.number().nullable(),
  /** Mean outage length when someone escalated it. */
  minutes_escalated: z.number().nullable(),
  minutes_not_escalated: z.number().nullable(),
  tickets: z.number().int(),
});
export type ReportOutage = z.infer<typeof ReportOutage>;

export const ReportTopic = z.object({
  topic: z.string(),
  n: z.number().int(),
});
export type ReportTopic = z.infer<typeof ReportTopic>;

export const ReportKnowledge = z.object({
  first_hand: z.number().int(),
  relayed: z.number().int(),
  encounters: z.number().int(),
});
export type ReportKnowledge = z.infer<typeof ReportKnowledge>;

/** One distinct model call: the state it was asked about and its answer. */
export const ReportAnswer = z.object({
  uses: z.number().int(),
  state: z.record(z.string(), z.unknown()),
  /** Per question: P(yes) for a yes/no question, otherwise the distribution. */
  ans: z.record(z.string(), z.unknown()),
});
export type ReportAnswer = z.infer<typeof ReportAnswer>;

/** Who the town replay draws: their seat and their walk to the cafe. */
export const CastMember = z.object({
  id: z.string(),
  name: z.string(),
  org_id: z.string(),
  role: z.string(),
  seat: z.tuple([z.number().int(), z.number().int()]),
  spot: z.tuple([z.number().int(), z.number().int()]),
  path: z.array(z.tuple([z.number().int(), z.number().int()])),
});
export type CastMember = z.infer<typeof CastMember>;

/** GET /report — the field report, recomputed at most once per tick. */
export const FieldReport = z.object({
  seq: z.number().int(),
  /** The database's clock when this was served, ISO-8601 UTC. */
  as_of: z.string(),
  clock: Clock,
  health: Health,
  /** The build that answered the latest modelled decision. */
  model: z.string().nullable(),
  vitals: ReportVitals,
  cash: ReportCash,
  cache_by_day: z.array(ReportCacheDay),
  calls: z.array(ReportCallSet),
  people: z.array(ReportPerson),
  office_at_cafe: z.array(ReportHourShare),
  cafe_by_hour: z.array(ReportCafeHour),
  mood_by_mind: z.array(ReportMood),
  payroll: z.array(ReportPayroll),
  collections: ReportCollections,
  households: ReportHouseholds,
  outages: z.array(ReportOutage),
  topics: z.array(ReportTopic),
  knowledge: ReportKnowledge,
  answers: z.record(z.string(), z.array(ReportAnswer)),
  cast: z.array(CastMember),
  queue: z.array(z.tuple([z.number().int(), z.number().int()])),
});
export type FieldReport = z.infer<typeof FieldReport>;

export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
export * from "./world";
