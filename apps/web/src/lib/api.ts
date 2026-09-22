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
import * as Sentry from "@sentry/nextjs";
import type { ZodType } from "zod";

export const API =
  process.env.NEXT_PUBLIC_JEVE_API ?? "http://127.0.0.1:8000";

type Outcome = "ok" | `http_${number}` | "network" | "contract";

/**
 * CORE-0012: what the browser sees of the API, counted per route *template* —
 * `/causal/{seq}`, never `/causal/4117` — so a dashboard has a handful of
 * series rather than one per event a viewer clicked. Every call is a no-op
 * until a DSN is baked in.
 */
function note(route: string, outcome: Outcome): void {
  Sentry.metrics.count("jeve.web.api.request", 1, {
    attributes: { route, outcome },
  });
}

async function get<T>(route: string, path: string, schema: ZodType<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { cache: "no-store" });
  } catch (error) {
    // The API being down is the landing page's "not reachable" state, not a
    // bug in this code: counted and logged, never filed.
    note(route, "network");
    Sentry.logger.warn("api unreachable", { route, error: String(error) });
    throw error;
  }
  if (!response.ok) {
    note(route, `http_${response.status}`);
    Sentry.logger.warn("api request failed", { route, status: response.status });
    throw new Error(`${path} returned ${response.status}`);
  }
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    // A contract mismatch is a bug — the schema and the server disagree — and
    // the server is the one that changed, so it is filed, not just counted.
    note(route, "contract");
    const error = new Error(`${path} did not match the contract: ${parsed.error.message}`);
    Sentry.captureException(error, { tags: { route } });
    throw error;
  }
  note(route, "ok");
  return parsed.data;
}

export const fetchState = () => get("/state", "/state", WorldState);

/** The newest `limit` events, oldest first: where a page should open. */
export const fetchLatestEvents = (limit = 300) =>
  get("/events", `/events?latest=true&limit=${limit}`, EventPage);

/**
 * The page immediately older than `before`, oldest first.
 *
 * `before` is the `oldest` of the page you already hold, so scrollback is the
 * same one-integer cursor that walks forwards (API-0002).
 */
export const fetchOlderEvents = (before: number, limit = 200) =>
  get("/events", `/events?before=${before}&limit=${limit}`, EventPage);
export const fetchCausal = (seq: number, direction: "up" | "down" = "down") =>
  get("/causal/{seq}", `/causal/${seq}?direction=${direction}`, CausalChain);
export const fetchPersons = (org?: string) =>
  get("/persons", `/persons${org ? `?org=${org}` : ""}`, PersonsResponse);
export const fetchDecisions = (personId: string) =>
  get(
    "/persons/{id}/decisions",
    `/persons/${encodeURIComponent(personId)}/decisions`,
    PersonDecisions,
  );
export const fetchEconomics = () => get("/economics", "/economics", Economics);

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
  "cafe.walkout": "bad",
  "payment.deferred": "warn",
  "ticket.opened": "warn",
  "invoice.issued": "good",
  "payment.made": "good",
  "cafe.sale": "good",
  "ticket.answered": "good",
  "ticket.triaged": "neutral",
  "month.end": "mark",
};
