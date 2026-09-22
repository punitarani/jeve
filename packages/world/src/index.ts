/**
 * `mountWorld(container, options)`: one package, two mounts.
 *
 * The landing-page hero and the full-page explorer are the same scene with
 * different options. The hero has no controls and moves its own camera; the
 * explorer hands the camera to the visitor and reports what they click.
 *
 * Data flow. One `GET /world/map` (static). One `GET /world/agents` for where
 * everyone is, refreshed whenever a new tick is seen. And the `seq`-cursored
 * event stream, from which `agent.moved` events — each carrying the nodes
 * walked — drive the animation. The same events, fetched as history, drive the
 * idle replay; so live and replay are one mechanism, not two.
 */
import {
  AgentsFrame,
  EventPage,
  SimEvent,
  TownMap,
  type Node,
  type Palette,
} from "@jeve/contracts";
import type { z } from "zod";

import { WorldModel, type Move } from "./model";
import { WorldView, type ViewTarget } from "./render";
import { STOREY } from "./voxels";

export { WorldModel } from "./model";
export type { Walker, Move } from "./model";
export { STOREY, buildVoxels } from "./voxels";

export type WorldStatus = ReturnType<WorldModel["snapshot"]> & {
  glOk: boolean;
  /** Name of a CPU rasteriser if that is what WebGL is, else null. */
  software: string | null;
  /** False while the canvas is off-screen or the tab is hidden: nothing drawn. */
  drawing: boolean;
  bubbles: number;
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
  /**
   * A firm's colours, from the map this world already holds — so a panel
   * beside the scene paints a firm without a fetch of its own. Null before
   * the map has arrived, or for an id that is not a building.
   */
  paletteOf(orgId: string): Palette | null;
  /**
   * Cut the buildings at storey `n`: every floor above it is not drawn, and
   * neither are the people on it. Null shows everything. The explorer's
   * segmented control drives it; the hero's tour drives its own (each mount
   * has a model of its own, so neither reaches the other).
   */
  setLevelCut(n: number | null): void;
  readonly levelCut: number | null;
  /**
   * How many storeys the tallest building has, from the map this world
   * holds: what a level-cut control offers. 0 before the map has arrived.
   */
  maxFloors(): number;
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

/**
 * One stop of the hero's tour: where to look, and how the buildings are cut
 * while looking. A storey stop cuts at its own floor, so the camera looks
 * into the room rather than at the slab over it; the district and a
 * single-storey building are seen whole.
 */
type Stop = ViewTarget & { cut: number | null };

/**
 * The tour: the whole district first, then each building in the order the
 * map lists them, however many there are. A building with storeys is visited
 * once per floor from the top down, cut at that floor for the stop; the next
 * stop puts the cut back (to null, or to its own floor). A building's stop is
 * framed to its width.
 */
function tourOf(map: TownMap, whole: ViewTarget): Stop[] {
  return [
    { ...whole, cut: null },
    ...map.buildings.flatMap((b): Stop[] => {
      const at = {
        x: (b.x0 + b.x1) / 2,
        z: (b.y0 + b.y1) / 2,
        span: Math.max(19, b.x1 - b.x0 + 9),
      };
      if (b.floors <= 1) return [{ ...at, cut: null }];
      return Array.from({ length: b.floors }, (_, i) => ({ ...at, cut: b.floors - 1 - i }));
    }),
  ];
}

/** A node as the payload carries it. The floor is always sent; the type admits its absence so an older log still replays. */
type Step = [number, number] | [number, number, number];

function toMove(event: SimEvent): Move | null {
  if (event.kind !== "agent.moved") return null;
  const payload = event.payload as {
    person_id?: string;
    from_zone?: string;
    to_zone?: string;
    from_floor?: number;
    to_floor?: number;
    path?: Step[];
  };
  if (!payload.person_id || !payload.to_zone || !payload.from_zone) return null;
  const steps = payload.path ?? [];
  const from = payload.from_floor ?? 0;
  const to = payload.to_floor ?? 0;
  return {
    seq: event.seq,
    tick: event.tick_seq ?? 0,
    personId: payload.person_id,
    fromZone: payload.from_zone,
    toZone: payload.to_zone,
    // A step without a floor is on the floor the walk left, or, at the far
    // end, the one it reached.
    path: steps.map(
      (step, i): Node => [step[0], step[1], step[2] ?? (i === steps.length - 1 ? to : from)],
    ),
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
  let tour: Stop[] = [];
  let tourIndex = 0;
  let tourNextAt = 0;
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
    } else if (event.kind === "ticket.escalated") {
      const payload = event.payload as { raised_by?: string; module_id?: string };
      if (payload.raised_by) say(payload.raised_by, `fix ${payload.module_id}!`, now);
      const where = model.walkers.get(payload.raised_by ?? "");
      if (where && options.mode === "hero") {
        // Something happened: go and look at it — cut to their floor, or the
        // storeys over them would hide it. The next stop resets the cut.
        view.lookAt({ x: where.x, z: where.y, span: 15 });
        model.levelCut = where.floor;
        tourNextAt = now + 6500;
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
    if (options.mode === "hero" && tour.length > 0 && now >= tourNextAt) {
      const stop = tour[tourIndex % tour.length];
      if (stop !== undefined) {
        view.lookAt(stop);
        model.levelCut = stop.cut;
      }
      tourIndex++;
      tourNextAt = now + 7000;
    }
    // Scrolled past, or in a background tab: keep the model honest, draw nothing.
    const drawing = onScreen && !document.hidden;
    view.frame(now, drawing);

    for (let i = bubbles.length - 1; i >= 0; i--) {
      const bubble = bubbles[i];
      if (bubble === undefined) continue;
      const walker = model.walkers.get(bubble.personId);
      const rect = container.getBoundingClientRect();
      if (now > bubble.until || walker === undefined || !walker.visible || !model.shown(walker)) {
        bubble.element.remove();
        bubbles.splice(i, 1);
        continue;
      }
      const p = view.project(walker.x, 1.75 + walker.floor * STOREY, walker.y);
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

  /** Where a person is drawn: from the height of their floor. */
  const projectPerson = (w: { x: number; y: number; floor: number }) =>
    view.project(w.x, 0.7 + w.floor * STOREY, w.y);

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
    }),
    screenPositionOf(personId) {
      const walker = model.walkers.get(personId);
      if (walker === undefined || !walker.visible || !model.shown(walker)) return null;
      return projectPerson(walker);
    },
    screenPositionOfTile: (x, y) => view.project(x, 0, y),
    screenPositionOfBuilding(orgId) {
      const map = model.map;
      const b = map?.buildings.find((candidate) => candidate.org_id === orgId);
      if (map == null || b === undefined) return null;
      // The floor tile furthest, on screen, from anybody: a click there means
      // the building and cannot be mistaken for the person standing next to it.
      const people = [...model.walkers.values()]
        .filter((w) => w.visible && model.shown(w))
        .map(projectPerson);
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
    paletteOf(orgId) {
      return model.map?.buildings.find((b) => b.org_id === orgId)?.palette ?? null;
    },
    setLevelCut(n) {
      model.levelCut = n;
    },
    get levelCut() {
      return model.levelCut;
    },
    maxFloors() {
      return Math.max(0, ...(model.map?.buildings.map((b) => b.floors) ?? []));
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
      const whole = { x: map.width / 2, z: map.height / 2, span: view.spanOf(map) + 1 };
      tour = tourOf(map, whole);
      view.lookAt(whole);

      const frame = await getJson("/world/agents", AgentsFrame);
      if (disposed) return;
      // Enough recorded movement for the replay's few ticks even when everyone
      // walks at once, so it grows with the staff; the API's page is capped.
      const limit = Math.min(1000, Math.max(160, frame.agents.length * 4));
      const history = await getJson(
        `/events?kinds=agent.moved&latest=true&limit=${limit}`,
        EventPage,
      );
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
