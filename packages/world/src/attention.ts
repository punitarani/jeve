/**
 * The hero's camera director: where to look, chosen by where the people are.
 *
 * What came before was a clock. Every seven seconds the camera moved to the
 * next stop on a fixed list — the whole town, then each building in turn —
 * so it dutifully zoomed into empty offices, and looked straight past the
 * lunch-hour migration. This director instead scores every plausible scene
 * each frame and decides like a documentary camera would:
 *
 * - A room with nobody in it is never a shot. An emptied town is only ever
 *   the wide establishing frame.
 * - People on the move are the story: while several are walking, the camera
 *   frames the corridor — where they left and where they are headed — and
 *   tracks it as they go.
 * - A conversation that has just started, or an escalation that has just
 *   happened, interrupts politely and briefly.
 * - Between comparably interesting places it wanders: a shot is always cut
 *   inside a 3–8 second band — stolen early by a clearly better scene, or
 *   retired at eight seconds whatever the gap — so it never parks.
 *
 * GL-free like the model it reads: all inputs are plain numbers, so the whole
 * decision is unit-tested without a browser (`test/attention.test.ts`).
 */
import type { TownMap } from "@jeve/contracts";

import type { Walker } from "./model";
import type { ViewTarget } from "./render";

/** The slice of a person the director needs. `Walker` satisfies it. */
export type Body = Pick<
  Walker,
  "x" | "y" | "visible" | "walking" | "route" | "routeToZone"
>;

/** The slice of the scene model the director needs. `WorldModel` satisfies it. */
export type World = {
  map: TownMap | null;
  walkers: ReadonlyMap<string, Body>;
  crowd: readonly { x: number; y: number }[];
};

export type Scene = ViewTarget & {
  /** Stable identity across frames: same scene, fresh geometry. */
  key: string;
  /** A few words for the caption, or "" when the shot needs none. */
  label: string;
  score: number;
};

// -- the scores -------------------------------------------------------------
//
// Scores are attention, not importance: a full room outscores a quiet one, a
// street full of walkers outscores a full room, a fresh conversation outscores
// the commute it was overheard on, and an escalation outscores everything
// briefly. Numbers are tuned so the ordering reads that way end to end.

const TOWN = 1;
/** Nobody is out at all: the wide shot is the only shot, so make sure it wins. */
const TOWN_ALONE = 3;
const OUT_PERSON = 1.4;
const OUT_CROWD = 0.22;
const ROOM_PERSON = 1;
const ROOM_ARRIVING = 0.6;
const ROOM_CROWD = 0.22;
/** One person crossing the map is a modest shot. */
const STREET_SOLO = 1.7;
/** Two and more is a migration in progress: follow it. */
const STREET_BASE = 2.4;
const STREET_EACH = 1.8;
const CHAT = 9.5;
const ALERT = 14;

// -- the rhythm --------------------------------------------------------------

/** A shot gets this long before anything short of a clearly better one cuts it. */
const MIN_DWELL_MS = 3_000;
/**
 * And it never gets more than this: at the cap the camera moves to the best
 * alternative whatever the score gap, so a great scene is a scene, not a
 * parking spot. When the held scene is still winning it wins the next frame
 * too — the cut is a glance, not a verdict.
 */
const MAX_DWELL_MS = 8_000;
/** Before the cap, a challenger must beat the held shot by this much. */
const HYSTERESIS = 1.45;
/** A place not looked at for this long earns this much on its next bid. */
const NOVELTY_AFTER_MS = 40_000;
const NOVELTY = 2.2;
/** An escalation holds the camera this long. */
const ALERT_MS = 6_500;
/** A conversation is re-bid every encounter, lapsing this long after the last. */
const CHAT_MS = 9_000;

/** People standing within this of each other are one outdoor scene. */
const CLUSTER_RADIUS = 6;
/** The view is landscape; a span of S tiles high shows about 1.5*S across. */
const WIDE_ASPECT = 1.5;

type Rect = { x0: number; y0: number; x1: number; y1: number };

const inRect = (x: number, y: number, r: Rect): boolean =>
  x >= r.x0 - 0.6 && x <= r.x1 + 0.6 && y >= r.y0 - 0.6 && y <= r.y1 + 0.6;

const clamp = (v: number, lo: number, hi: number): number =>
  Math.min(hi, Math.max(lo, v));

/**
 * Centre and span covering a set of points, with breathing room.
 *
 * The centre is the centroid, not the box's middle: a shot of people walking
 * frames where the mass of them is, and as they walk the mass moves — that is
 * what makes the camera track rather than step.
 */
function framePoints(
  points: { x: number; y: number }[],
  pad: number,
  lo: number,
  hi: number,
): { x: number; z: number; span: number } {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  let sx = 0;
  let sy = 0;
  for (const p of points) {
    if (p.x < x0) x0 = p.x;
    if (p.x > x1) x1 = p.x;
    if (p.y < y0) y0 = p.y;
    if (p.y > y1) y1 = p.y;
    sx += p.x;
    sy += p.y;
  }
  const n = Math.max(1, points.length);
  const need = Math.max(y1 - y0, (x1 - x0) / WIDE_ASPECT);
  return {
    x: sx / n,
    z: sy / n,
    span: clamp(need + pad, lo, hi),
  };
}

type Cluster = { staff: { x: number; y: number }[]; crowd: { x: number; y: number }[] };

/** Greedy clustering: near a member means the same scene, whatever the mix. */
function clusters(
  staff: { x: number; y: number }[],
  crowd: { x: number; y: number }[],
  radius: number,
): Cluster[] {
  const found: Cluster[] = [];
  const place = (p: { x: number; y: number }, isStaff: boolean): void => {
    for (const c of found) {
      const near = [...c.staff, ...c.crowd].some(
        (q) => Math.hypot(q.x - p.x, q.y - p.y) <= radius,
      );
      if (near) {
        (isStaff ? c.staff : c.crowd).push(p);
        return;
      }
    }
    found.push(isStaff ? { staff: [p], crowd: [] } : { staff: [], crowd: [p] });
  };
  for (const p of staff) place(p, true);
  for (const p of crowd) place(p, false);
  return found;
}

export class HeroCamera {
  private currentKey = "";
  private current: Scene = { key: "", label: "", x: 20, z: 14, span: 41, score: 0 };
  private since = Number.NEGATIVE_INFINITY;
  private visited = new Map<string, number>();
  private chats: { a: string; b: string; until: number }[] = [];
  private alert: { x: number; z: number; until: number } | null = null;

  /** An encounter just happened between two people: worth watching, briefly. */
  encounter(a: string, b: string, now: number): void {
    const existing = this.chats.find(
      (c) => (c.a === a && c.b === b) || (c.a === b && c.b === a),
    );
    if (existing !== undefined) existing.until = now + CHAT_MS;
    else this.chats.push({ a, b, until: now + CHAT_MS });
  }

  /** Something happened at a tile: go and look. The newest one wins. */
  drama(x: number, z: number, now: number): void {
    this.alert = { x, z, until: now + ALERT_MS };
  }

  /** A few words about what is on screen, for the caption; "" when town-wide. */
  get watching(): string {
    return this.current.label;
  }

  /** The scene's key, for the status line and tests. */
  get key(): string {
    return this.currentKey;
  }

  /**
   * The shot the camera should be easing toward this frame.
   *
   * Called every rAF: candidates are rebuilt from live positions, so a scene
   * that is people — the street, a pair talking — is tracked as it moves, and
   * the decision itself costs a walk over a few dozen points.
   */
  frame(world: World, now: number): ViewTarget {
    const scenes = this.scenes(world, now);
    const novelty = (key: string): number =>
      now - (this.visited.get(key) ?? Number.NEGATIVE_INFINITY) > NOVELTY_AFTER_MS
        ? NOVELTY
        : 0;

    const held = scenes.find((s) => s.key === this.currentKey);
    let challenger: Scene | undefined;
    let bid = Number.NEGATIVE_INFINITY;
    for (const s of scenes) {
      if (s.key === this.currentKey) continue;
      const score = s.score + novelty(s.key);
      if (score > bid) {
        bid = score;
        challenger = s;
      }
    }

    const heldFor = now - this.since;
    // The held shot dissolved (the walkers arrived, the chat ended, the drama
    // expired): whoever bids highest takes over, no dwell owed to a ghost.
    let next: Scene | undefined = held ?? challenger;
    if (
      next !== undefined &&
      challenger !== undefined &&
      held !== undefined &&
      // A clearly better scene may steal early; at the cap it takes over by
      // right. Either way the camera is never on one thing longer than
      // MAX_DWELL_MS.
      ((heldFor > MIN_DWELL_MS && bid > held.score * HYSTERESIS) ||
        heldFor > MAX_DWELL_MS)
    ) {
      next = challenger;
    }

    if (next === undefined) return this.current;
    if (next.key !== this.currentKey) {
      // Do not hurry back to what was just left: the visit is what cools it.
      this.visited.set(this.currentKey, now);
      this.since = now;
      this.currentKey = next.key;
    }
    this.current = next;
    return { x: next.x, z: next.z, span: next.span };
  }

  /** Every plausible scene this frame, scored. The heart of the director. */
  private scenes(world: World, now: number): Scene[] {
    const map = world.map;
    if (map === null) {
      return [{ key: "town", label: "", x: 20, z: 14, span: 41, score: TOWN }];
    }
    const walkers = [...world.walkers.values()].filter((w) => w.visible);
    const still = walkers.filter((w) => !w.walking);
    const moving = walkers.filter((w) => w.walking);
    const found: Scene[] = [];

    // The whole town, always an option. With nobody out it is *the* option —
    // and it is offered in three framings, so an hour of quiet is not an hour
    // of one unmoving rectangle.
    const cx = map.width / 2;
    const cz = map.height / 2;
    const townSpan = Math.max(map.height * 1.45, 34);
    const townScore = walkers.length === 0 ? TOWN_ALONE : TOWN;
    found.push(
      { key: "town", label: "", x: cx, z: cz, span: townSpan, score: townScore },
      {
        key: "town:north",
        label: "",
        x: cx,
        z: cz - map.height * 0.16,
        span: townSpan * 1.06,
        score: townScore,
      },
      {
        key: "town:south",
        label: "",
        x: cx,
        z: cz + map.height * 0.16,
        span: townSpan * 1.06,
        score: townScore,
      },
    );

    // Occupied rooms. Empty buildings are never candidates — that is the
    // point of the rewrite — and people on their way in count for it.
    for (const b of map.buildings) {
      let people = 0;
      for (const w of still) if (inRect(w.x, w.y, b)) people++;
      let crowdIn = 0;
      for (const d of world.crowd) if (inRect(d.x, d.y, b)) crowdIn++;
      let arriving = 0;
      for (const w of moving) if (w.routeToZone === b.zone) arriving++;
      const score = people * ROOM_PERSON + crowdIn * ROOM_CROWD + arriving * ROOM_ARRIVING;
      if (score < 0.5) continue;
      found.push({
        key: `room:${b.org_id}`,
        label: `at ${b.name}`,
        x: (b.x0 + b.x1) / 2,
        z: (b.y0 + b.y1) / 2,
        span: clamp(b.y1 - b.y0 + 5, 12, 26),
        score,
      });
    }

    // People out in the open: two on a bench, a queue outside the cafe, one
    // figure by the fountain — each cluster its own small scene.
    const open = (p: { x: number; y: number }) =>
      !map.buildings.some((b) => inRect(p.x, p.y, b));
    const outside = still.filter(open);
    const crowdOut = world.crowd.filter(open);
    for (const c of clusters(outside, crowdOut, CLUSTER_RADIUS)) {
      const score = c.staff.length * OUT_PERSON + c.crowd.length * OUT_CROWD;
      if (score < 0.5) continue;
      const at = framePoints([...c.staff, ...c.crowd], 6, 12, 24);
      found.push({
        key: `out:${Math.round(at.x / 5)}:${Math.round(at.z / 5)}`,
        label: "in the square",
        ...at,
        score,
      });
    }

    // The street, while anyone is crossing it. The shot covers both ends of
    // the walk — where they left and where they are headed — so a migration
    // reads as a river, not a dot.
    if (moving.length > 0) {
      const points = moving.flatMap((w) => {
        const end = w.route?.at(-1);
        return end === undefined
          ? [{ x: w.x, y: w.y }]
          : [{ x: w.x, y: w.y }, { x: end[0], y: end[1] }];
      });
      found.push({
        key: "street",
        label: "on the street",
        ...framePoints(points, 6, 13, 40),
        score:
          moving.length === 1
            ? STREET_SOLO
            : STREET_BASE + STREET_EACH * moving.length,
      });
    }

    // Conversations the event stream just reported, while both parties still
    // stand there. Two people talking is the most human thing in town.
    this.chats = this.chats.filter((chat) => now <= chat.until);
    for (const chat of this.chats) {
      const a = world.walkers.get(chat.a);
      const b = world.walkers.get(chat.b);
      if (a === undefined || b === undefined) continue;
      if (!a.visible || !b.visible || a.walking || b.walking) continue;
      if (Math.hypot(a.x - b.x, a.y - b.y) > 6) continue;
      found.push({
        key: `chat:${[chat.a, chat.b].sort().join("|")}`,
        label: "a conversation",
        x: (a.x + b.x) / 2,
        z: (a.y + b.y) / 2,
        span: 10.5,
        score: CHAT,
      });
    }

    // And the drama an event pointed at, for as long as its lease lasts.
    if (this.alert !== null && now <= this.alert.until) {
      found.push({
        key: "alert",
        label: "something is up",
        x: this.alert.x,
        z: this.alert.z,
        span: 15,
        score: ALERT,
      });
    }

    return found;
  }
}
