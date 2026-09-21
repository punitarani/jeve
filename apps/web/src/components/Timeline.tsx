"use client";

import type { SimEvent } from "@jeve/contracts";
import { money } from "@/lib/api";
import { EVENT_TONE, ORG_COLORS } from "@/lib/tone";

/**
 * Events in time order. Selecting one dims everything that is not causally
 * related to it and annotates the rest with their distance from it, so a
 * cascade reads as a shape rather than as a list you have to reconstruct.
 */
export function Timeline({
  events,
  selected,
  chain,
  onSelect,
}: {
  events: SimEvent[];
  selected: number | null;
  chain: Map<number, number> | null;
  onSelect: (seq: number) => void;
}) {
  return (
    <div className="lane" data-testid="timeline">
      {events.map((event) => {
        const depth = chain?.get(event.seq);
        const related = chain === null || depth !== undefined;
        const tone = EVENT_TONE[event.kind] ?? "neutral";
        const detail = describe(event);
        return (
          <button
            key={event.seq}
            className={[
              "ev",
              tone,
              selected === event.seq ? "sel" : "",
              related ? "" : "dim",
            ]
              .filter(Boolean)
              .join(" ")}
            data-testid={`event-${event.seq}`}
            data-kind={event.kind}
            data-related={related ? "yes" : "no"}
            onClick={() => onSelect(event.seq)}
          >
            <span className="muted">{event.label ?? event.sim_time}</span>
            <span
              style={{
                color: event.org_id ? ORG_COLORS[event.org_id] : undefined,
              }}
            >
              {event.org_id ?? "—"}
            </span>
            <span>
              {event.kind}
              {detail && <span className="muted"> · {detail}</span>}
            </span>
            <span className="depth">
              {depth === undefined
                ? `#${event.seq}`
                : depth === 0
                  ? "root"
                  : depth > 0
                    ? `+${depth}`
                    : `${depth}`}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * One line of detail per kind, read straight off the payload.
 *
 * Keys are copied from each `engine.emit(...)` call site, not from
 * `jeve.world.events` — that module is stale and imported by nothing. Two
 * halves of the same transaction disagree on purpose (`catering.ordered`
 * carries `org_id`, `catering.delivered` carries `to_org_id`), so nothing
 * here pattern-matches a key it has not been told about.
 */
function describe(event: SimEvent): string {
  const p = event.payload as Record<string, unknown>;
  switch (event.kind) {
    case "incident.started":
    case "incident.ended":
      return String(p.module_id ?? "");
    case "invoice.blocked":
      return `${p.module_id} down · ${p.pending} clients waiting`;
    case "invoice.issued":
      return `${cents(p.amount_cents)} ${p.invoice_kind ?? ""}`.trim();
    case "payment.made":
      return join(cents(p.amount_cents), late(p.days_late, "d late"));
    case "payment.deferred":
      return words(p.reason);
    case "ticket.opened":
    // Both halves of the same emit, so both carry `subject`.
    case "ticket.reopened":
      return String(p.subject ?? "");
    case "ticket.triaged":
      return `${p.queue} · severity ${p.severity}`;
    case "cafe.sale":
      return join(cents(p.amount_cents), p.pos_down === true && "cash only");
    case "cafe.walkout":
      return words(p.reason);
    case "encounter":
      return join(words(p.zone), words(p.topic));
    // The payload has only the id — no module, no subject — so this is the
    // ceiling without a join the client cannot do.
    case "ticket.answered":
      return ticket(p);
    case "ticket.closed":
      return join(ticket(p), words(p.reason));
    case "ticket.escalated":
      return join(String(p.module_id ?? ""), late(p.minutes_saved, "m sooner"));
    // `payload.label` is "month 3". `event.label` is the clock string the API
    // adds to every row — a different thing that happens to share a name.
    case "month.end":
      return String(p.label ?? "");
    case "payroll.paid":
      return join(
        cents(p.amount_cents),
        count(p.staff, "staff"),
        late(p.minutes_late, "m late"),
      );
    case "payroll.held":
      return join(cents(p.amount_cents), words(p.reason));
    case "credit.issued":
      return join(cents(p.amount_cents), words(p.level));
    case "insolvency.warning": {
      const cash = cents(p.cash_cents);
      return join(words(p.cause), cash && `${cash} cash`);
    }
    case "close.completed":
      return join(String(p.client ?? ""), late(p.days_late, "d late"));
    case "close.deferred":
      return String(p.reason ?? "");
    case "catering.ordered":
      return join(words(p.size), cents(p.amount_cents));
    case "catering.delivered":
      return join(
        words(p.size),
        cents(p.amount_cents),
        // Null when nobody at the cafe was free: the customer fetched it.
        p.carried_by === null && "collected",
      );
    case "invoice.chased":
      return late(p.days_late, "d late");
    case "invoice.written_off":
      return join(cents(p.amount_cents), late(p.days_late, "d late"));
    default:
      return "";
  }
}

/** Joins the parts that exist, so a missing one leaves no stray separator. */
function join(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" · ");
}

/**
 * Enum values travel as `law_office` and `the_outage`. The prose in
 * `jeve.decide.questions` is part of a Jev request body, whose exact bytes
 * are a cache key (DECIDE-0004) — mirroring it here would invite someone to
 * keep the two in sync and re-record every cassette. Underscores to spaces.
 */
function words(value: unknown): string {
  return typeof value === "string" ? value.replaceAll("_", " ") : "";
}

/** Lateness reads as nothing at all when there is none. */
function late(value: unknown, unit: string): string {
  return typeof value === "number" && value > 0 ? `${value}${unit}` : "";
}

function count(value: unknown, unit: string): string {
  return typeof value === "number" ? `${value} ${unit}` : "";
}

function ticket(p: Record<string, unknown>): string {
  return typeof p.ticket_id === "number" ? `ticket #${p.ticket_id}` : "";
}

/** Money is integer cents everywhere; `money` is the one formatter. */
function cents(value: unknown): string {
  return typeof value === "number" ? money(value) : "";
}
