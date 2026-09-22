/**
 * The one place that talks to FastAPI.
 *
 * Every response is parsed with its zod schema before it reaches a component,
 * so a shape change fails here with a readable message instead of surfacing as
 * `undefined` inside a render.
 */
import {
  CausalChain,
  Economics,
  EventPage,
  PersonDecisions,
  PersonsResponse,
  WorldState,
  type SimEvent,
} from "@jeve/contracts";
import type { ZodType } from "zod";

export const API =
  process.env.NEXT_PUBLIC_JEVE_API ?? "http://127.0.0.1:8000";

async function get<T>(path: string, schema: ZodType<T>): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    throw new Error(`${path} did not match the contract: ${parsed.error.message}`);
  }
  return parsed.data;
}

export const fetchState = () => get("/state", WorldState);

const leaving = (kinds: readonly string[]) =>
  kinds.length > 0 ? `&exclude=${kinds.join(",")}` : "";

/**
 * The newest `limit` events, oldest first: where a page should open. Kinds
 * in `exclude` are left out server-side, so a window of six hundred reaches
 * the newest outage instead of filling with the district's small-talk.
 */
export const fetchLatestEvents = (limit = 300, exclude: readonly string[] = []) =>
  get(`/events?latest=true&limit=${limit}${leaving(exclude)}`, EventPage);

/**
 * The page immediately older than `before`, oldest first.
 *
 * `before` is the `oldest` of the page you already hold, so scrollback is the
 * same one-integer cursor that walks forwards (API-0002).
 */
export const fetchOlderEvents = (
  before: number,
  limit = 200,
  exclude: readonly string[] = [],
) => get(`/events?before=${before}&limit=${limit}${leaving(exclude)}`, EventPage);

/**
 * Every event of the given kinds strictly between two cursors, oldest first:
 * what a kind left out of the pages so far looks like inside the window the
 * reader already holds.
 */
export const fetchKindsBetween = (
  after: number,
  before: number,
  kinds: readonly string[],
) =>
  get(
    `/events?after=${after}&before=${before}&kinds=${kinds.join(",")}&limit=1000`,
    EventPage,
  );
export const fetchCausal = (seq: number, direction: "up" | "down" = "down") =>
  get(`/causal/${seq}?direction=${direction}`, CausalChain);
/**
 * Staff, all of them: the API pages at a hundred by default, and the district
 * has more than twice that. Five hundred is its ceiling.
 */
export const fetchPersons = (org?: string) =>
  get(`/persons?limit=500${org ? `&org=${org}` : ""}`, PersonsResponse);
export const fetchDecisions = (personId: string) =>
  get(`/persons/${encodeURIComponent(personId)}/decisions`, PersonDecisions);
export const fetchEconomics = () => get("/economics", Economics);

export type { SimEvent };

/** Money is integer cents everywhere; format only at the edge. */
export function money(cents: number): string {
  return (cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export const EVENT_TONE: Record<string, string> = {
  "incident.started": "bad",
  "incident.ended": "good",
  "invoice.blocked": "bad",
  "retail.walkout": "bad",
  "payment.deferred": "warn",
  "ticket.opened": "warn",
  "invoice.issued": "good",
  "payment.made": "good",
  "retail.sale": "good",
  "ticket.answered": "good",
  "ticket.triaged": "neutral",
  "month.end": "mark",
};
