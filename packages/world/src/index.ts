/**
 * `mountWorld(container, options)`: one package, two mounts.
 *
 * The landing-page hero and the full-page explorer are the same scene with
 * different options. The hero has no controls and moves its own camera; the
 * explorer hands the camera to the visitor and reports what they click.
 *
 * Data flow. One `GET /world/map` (static). One `GET /world/agents` for where
 * everyone is, refreshed whenever a new tick is seen. And the `seq`-cursored
 * event stream, from which `agent.moved` events — each carrying the tiles
 * walked — drive the animation. The same events, fetched as history, drive the
 * idle replay; so live and replay are one mechanism, not two.
 */
import {
  AgentsFrame,
  EventPage,
  SimEvent,
  TownMap,
  type Zone,
} from "@jeve/contracts";

import type { z } from "zod";

import { HeroCamera } from "./attention";
import { WorldModel, type Move } from "./model";
import { WorldView } from "./render";

export { WorldModel } from "./model";
export type { Walker, Move } from "./model";
export { buildVoxels } from "./voxels";

export type WorldStatus = ReturnType<WorldModel["snapshot"]> & {
  glOk: boolean;
  /** Name of a CPU rasteriser if that is what WebGL is, else null. */
  software: string | null;
  /** False while the canvas is off-screen or the tab is hidden: nothing drawn. */
  drawing: boolean;
  bubbles: number;
  /** Hero only: the scene the camera is on ("street", "room:tallybird", "town"). */
  scene: string;
  /** Hero only: a few words about that scene for the caption, else "". */
  watching: string;
};

export type MountOptions = {
  api: string;
  mode: "hero" | "explore";
  onSelectAgent?: (personId: string | null) => void;
  onSelectBuilding?: (orgId: string | null) => void;
  onStatus?: (status: WorldStatus) => void;
  debug?: boolean;
};

export type WorldHandle = {
  dispose(): void;
  status(): WorldStatus;
  /** For tests: where a person is drawn, in CSS pixels inside the container. */
  screenPositionOf(personId: string): { x: number; y: number } | null;
  screenPositionOfBuilding(orgId: string): { x: number; y: number } | null;
  /** A fixed point on the ground: a reference that does not depend on people. */
  screenPositionOfTile(x: number, y: number): { x: number; y: number };
};

declare global {
  interface Window {
    __jeveWorld?: Record<string, WorldHandle>;
  }
}

const TOPIC_WORDS: Record<string, string> = {
  the_outage: "the outage",
  work: "work",
  money: "money",
  small_talk: "small talk",
  other: "...",
};

type Bubble = { element: HTMLDivElement; personId: string; until: number };

function toMove(event: SimEvent): Move | null {
  if (event.kind !== "agent.moved") return null;
  const payload = event.payload as {
    person_id?: string;
    from_zone?: Zone;
    to_zone?: Zone;
    path?: [number, number][];
  };
  if (!payload.person_id || !payload.to_zone || !payload.from_zone) return null;
  return {
    seq: event.seq,
    tick: event.tick_seq ?? 0,
    personId: payload.person_id,
    fromZone: payload.from_zone,
    toZone: payload.to_zone,
    path: payload.path ?? [],
  };
}

export function mountWorld(container: HTMLElement, options: MountOptions): WorldHandle {
  const model = new WorldModel();
  const view = new WorldView(container, model, {
    interactive: options.mode === "explore",
    debug: options.debug ?? false,
  });
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden";
  container.style.position = container.style.position || "relative";
  container.appendChild(overlay);

  let disposed = false;
  let onScreen = true;
  let raf = 0;
  let stream: EventSource | null = null;
  let frameTimer: ReturnType<typeof setTimeout> | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  // The hero's camera is a director, not a clock: it watches people, and the
  // explorer drives its own.
  const hero = options.mode === "hero" ? new HeroCamera() : null;
  const bubbles: Bubble[] = [];

  async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
    const response = await fetch(`${options.api}${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return schema.parse(await response.json());
  }

  async function refreshFrame(): Promise<void> {
    if (disposed) return;
    try {
      const frame = await getJson("/world/agents", AgentsFrame);
      if (!disposed) model.applyFrame(frame, performance.now());
    } catch (error) {
      console.warn("jeve world: could not refresh agents", error);
    }
  }

  function scheduleRefresh(): void {
    if (frameTimer !== null) return;
    frameTimer = setTimeout(() => {
      frameTimer = null;
      void refreshFrame();
    }, 350);
  }

  function say(personId: string, text: string, now: number): void {
    const element = document.createElement("div");
    element.textContent = text;
    element.dataset.testid = "speech-bubble";
    element.style.cssText =
      "position:absolute;transform:translate(-50%,-100%);padding:3px 8px;" +
      "border-radius:9px;background:rgba(255,255,255,.95);color:#1d2230;" +
      "font:600 11px/1.3 system-ui,sans-serif;white-space:nowrap;" +
      "box-shadow:0 1px 4px rgba(0,0,0,.25);opacity:0;transition:opacity .25s";
    overlay.appendChild(element);
    bubbles.push({ element, personId, until: now + 5200 });
  }

  function onEvent(event: SimEvent): void {
    const now = performance.now();
    model.noteSeq(event.seq, now);
    const move = toMove(event);
    if (move !== null) {
      model.liveMove(move, now);
    } else if (event.kind === "encounter") {
      const payload = event.payload as { a?: string; b?: string; topic?: string };
      const words = TOPIC_WORDS[payload.topic ?? ""] ?? payload.topic ?? "...";
      if (payload.a) say(payload.a, words, now);
      if (payload.a && payload.b) hero?.encounter(payload.a, payload.b, now);
    } else if (event.kind === "ticket.escalated") {
      const payload = event.payload as { raised_by?: string; module_id?: string };
      if (payload.raised_by) say(payload.raised_by, `fix ${payload.module_id}!`, now);
      const where = model.walkers.get(payload.raised_by ?? "");
      if (where?.visible === true) {
        // Something happened: go and look at it.
        hero?.drama(where.x, where.y, now);
      }
    }
    if ((event.tick_seq ?? 0) > model.tick) scheduleRefresh();
  }

  function openStream(): void {
    if (disposed) return;
    stream?.close();
    stream = new EventSource(`${options.api}/stream?after=${model.seq}&lifetime_s=600`);
    stream.onmessage = (message) => {
      const parsed = SimEvent.safeParse(JSON.parse(message.data as string));
      if (parsed.success) onEvent(parsed.data);
    };
    // The server recycles the stream on its own terms (API-0001); resuming
    // from `seq` costs nothing, so reconnect with the cursor we hold.
    stream.onerror = () => {
      stream?.close();
      if (!disposed) setTimeout(openStream, 1500);
    };
  }

  function loop(now: number): void {
    if (disposed) return;
    // Every frame, not every seven seconds: a scene that is people moving is
    // tracked as it moves, and its score moves with them.
    if (hero !== null) view.lookAt(hero.frame(model, now));
    // Scrolled past, or in a background tab: keep the model honest, draw nothing.
    const drawing = onScreen && !document.hidden;
    view.frame(now, drawing);

    for (let i = bubbles.length - 1; i >= 0; i--) {
      const bubble = bubbles[i];
      if (bubble === undefined) continue;
      const walker = model.walkers.get(bubble.personId);
      const rect = container.getBoundingClientRect();
      if (now > bubble.until || walker === undefined || !walker.visible) {
        bubble.element.remove();
        bubbles.splice(i, 1);
        continue;
      }
      const p = view.project(walker.x, 1.75, walker.y);
      // Only in the viewport: a bubble for someone off-screen is not drawn.
      const inside = p.x > 0 && p.y > 0 && p.x < rect.width && p.y < rect.height;
      bubble.element.style.display = inside ? "block" : "none";
      bubble.element.style.left = `${p.x}px`;
      bubble.element.style.top = `${p.y}px`;
      bubble.element.style.opacity = now > bubble.until - 400 ? "0" : "1";
    }
    options.onStatus?.(handle.status());
    raf = requestAnimationFrame(loop);
  }

  // -- clicks (explore mode) ------------------------------------------------

  let downAt: { x: number; y: number } | null = null;
  function onPointerDown(event: PointerEvent): void {
    downAt = { x: event.clientX, y: event.clientY };
  }
  function onPointerUp(event: PointerEvent): void {
    if (downAt === null) return;
    const dragged = Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 5;
    downAt = null;
    if (dragged) return; // that was a pan, not a click
    const rect = container.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const person = model.pick(px, py, view.project);
    if (person !== null) {
      options.onSelectAgent?.(person.id);
      return;
    }
    const ground = view.unproject(px, py);
    const zone = ground === null ? null : model.zoneAt(ground.x, ground.y);
    const building = model.map?.buildings.find((b) => b.zone === zone);
    if (building !== undefined) options.onSelectBuilding?.(building.org_id);
    else {
      options.onSelectAgent?.(null);
      options.onSelectBuilding?.(null);
    }
  }

  const handle: WorldHandle = {
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      stream?.close();
      if (frameTimer !== null) clearTimeout(frameTimer);
      if (pollTimer !== null) clearInterval(pollTimer);
      observer.disconnect();
      watcher.disconnect();
      view.canvas.removeEventListener("pointerdown", onPointerDown);
      view.canvas.removeEventListener("pointerup", onPointerUp);
      overlay.remove();
      view.dispose();
      if (window.__jeveWorld) delete window.__jeveWorld[options.mode];
    },
    status: () => ({
      ...model.snapshot(),
      glOk: view.glOk,
      software: view.software,
      drawing: onScreen && !document.hidden,
      bubbles: bubbles.length,
      scene: hero?.key ?? "explore",
      watching: hero?.watching ?? "",
    }),
    screenPositionOf(personId) {
      const walker = model.walkers.get(personId);
      if (walker === undefined || !walker.visible) return null;
      return view.project(walker.x, 0.7, walker.y);
    },
    screenPositionOfTile: (x, y) => view.project(x, 0, y),
    screenPositionOfBuilding(orgId) {
      const map = model.map;
      const b = map?.buildings.find((candidate) => candidate.org_id === orgId);
      if (map == null || b === undefined) return null;
      // The floor tile furthest, on screen, from anybody: a click there means
      // the building and cannot be mistaken for the person standing next to it.
      const people = [...model.walkers.values()]
        .filter((w) => w.visible)
        .map((w) => view.project(w.x, 0.7, w.y));
      let best: { x: number; y: number } | null = null;
      let bestClearance = -1;
      for (let ty = b.y0 + 1; ty < b.y1; ty++) {
        for (let tx = b.x0 + 1; tx < b.x1; tx++) {
          if (map.tiles[ty]?.[tx] !== "floor") continue;
          const at = view.project(tx, 0, ty);
          const clearance = Math.min(
            ...people.map((p) => Math.hypot(p.x - at.x, p.y - at.y)),
            Number.POSITIVE_INFINITY,
          );
          if (clearance > bestClearance) {
            bestClearance = clearance;
            best = at;
          }
        }
      }
      return best;
    },
  };

  const observer = new ResizeObserver(() => view.resize());
  observer.observe(container);
  const watcher = new IntersectionObserver(
    (entries) => {
      onScreen = entries.some((entry) => entry.isIntersecting);
    },
    { threshold: 0.02 },
  );
  watcher.observe(container);
  if (options.mode === "explore") {
    view.canvas.addEventListener("pointerdown", onPointerDown);
    view.canvas.addEventListener("pointerup", onPointerUp);
  }
  window.__jeveWorld = { ...(window.__jeveWorld ?? {}), [options.mode]: handle };

  void (async () => {
    try {
      const map = await getJson("/world/map", TownMap);
      if (disposed) return;
      model.setMap(map);
      view.build(map);
      // The frame eases from the town-wide default toward whatever the
      // director judges worth a look: an establishing shot that lands itself.

      const [frame, history] = await Promise.all([
        getJson("/world/agents", AgentsFrame),
        getJson("/events?kinds=agent.moved&latest=true&limit=160", EventPage),
      ]);
      if (disposed) return;
      model.applyFrame(frame, performance.now());
      model.seedHistory(history.events.flatMap((e) => toMove(e) ?? []));
      model.playLatest(performance.now());
      openStream();
      pollTimer = setInterval(() => void refreshFrame(), 5000);
    } catch (error) {
      console.error("jeve world: failed to start", error);
      container.dataset.error = String(error);
    }
  })();

  raf = requestAnimationFrame(loop);
  return handle;
}
