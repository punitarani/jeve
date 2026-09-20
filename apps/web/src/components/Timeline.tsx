"use client";

import type { SimEvent } from "@jeve/contracts";
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
              {describe(event) && (
                <span className="muted"> · {describe(event)}</span>
              )}
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
      return `${cents(p.amount_cents)}${Number(p.days_late) > 0 ? ` · ${p.days_late}d late` : ""}`;
    case "payment.deferred":
      return String(p.reason ?? "");
    case "ticket.opened":
      return String(p.subject ?? "");
    case "ticket.triaged":
      return `${p.queue} · severity ${p.severity}`;
    case "cafe.sale":
      return `${cents(p.amount_cents)}${p.pos_down ? " · cash only" : ""}`;
    case "cafe.walkout":
      return String(p.reason ?? "");
    default:
      return "";
  }
}

function cents(value: unknown): string {
  return typeof value === "number"
    ? (value / 100).toLocaleString("en-US", { style: "currency", currency: "USD" })
    : "";
}
