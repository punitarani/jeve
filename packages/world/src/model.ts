/**
 * The scene model: who is where, and how they get there. No WebGL in here.
 *
 * Everything a test or a click needs — positions, interpolation along a path,
 * picking — is plain arithmetic on this object, so it works in a headless
 * browser with no GPU and keeps working if the renderer fails to start. The
 * renderer is a view over it and nothing more.
 *
 * The server ticks coarsely (a tick is fifteen sim-minutes) and says, for each
 * person who changed zone, the nodes they walked. The client's whole job is to
 * spread that walk over the real seconds until the next tick.
 *
 * A zone is a string: a firm's id, `plaza` or `home` (WORLD-0006). A node is
 * a tile and a floor; floor 0 is the ground and the street, and each upper
 * floor is a storey of its own over its building's footprint.
 */
import type { Agent, AgentsFrame, Node, TownMap } from "@jeve/contracts";

import { minuteOfDay, skyAt } from "./sky";
import { STOREY } from "./voxels";

export type Move = {
  seq: number;
  tick: number;
  personId: string;
  fromZone: string;
  toZone: string;
  /** (x, y, floor) nodes, both ends included. A flight of stairs is two nodes on one tile. */
  path: Node[];
};

export type Walker = {
  id: string;
  name: string;
  orgId: string;
  role: string;
  zone: string;
  /** 0 on the ground or off the map; a storey of the building they are in. */
  floor: number;
  mood: number;
  /** Tile coordinates, fractional while walking. */
  x: number;
  y: number;
  heading: number;
  visible: boolean;
  walking: boolean;
  /** Stable per-person phase so idle bobbing is not in lockstep. */
  phase: number;
  route: Node[] | null;
  routeStart: number;
  routeEnd: number;
  /** Where the walk ends up: a zone, or off the map. */
  routeToZone: string | null;

  // -- pose (WEB-0004). All optional, all set through `WorldModel.setPose`. --
  // The renderer draws from these and from nothing else: it does not read the
  // event stream. Unset means "no opinion", not "false" — see each field.

  /**
   * Drawn sitting: legs forward, body lowered onto the seat. When undefined the
   * renderer falls back to one inference: somebody standing still on a tile the
   * map lists in `seats` is sitting on it. `false` overrides that.
   */
  seated?: boolean;
  /** World yaw in radians to stand facing, as `heading` is: 0 faces +y (south). */
  facing?: number;
  /**
   * The id of the person they are talking to. While that person is visible it
   * wins over `facing`: they turn towards them, and gesture a little.
   */
  talkingTo?: string;
  /** Drawn with a ring on the ground under them and a marker over their head. */
  selected?: boolean;
};

export type Pose = Partial<Pick<Walker, "seated" | "facing" | "talkingTo" | "selected">>;

export type CrowdDot = { x: number; y: number; phase: number; tint: number };

const MS_PER_TILE = 85;
const MIN_WALK_MS = 1400;
const MAX_WALK_MS = 7000;
const STAGGER_MS = 1800;
/**
 * How long `seq` may stand still before the scene replays the last sim-hour.
 *
 * Short until a live event has been seen: a visitor who arrives while the
 * daemon is paused, or during sim-night, or after a fixture has reached its
 * horizon, should see the town moving within a few seconds. Long afterwards: a
 * healthy daemon ticks every fifteen seconds, and the quiet between two ticks
 * is not a stall.
 */
const STALL_BEFORE_FIRST_EVENT_MS = 3000;
const STALL_WHILE_LIVE_MS = 40000;
const REPLAY_TICK_MS = 2600;
const REPLAY_TICKS = 4;
/** The least recorded movement kept, however few people there are. */
const MIN_HISTORY = 240;

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

export class WorldModel {
  map: TownMap | null = null;
  walkers = new Map<string, Walker>();
  crowd: CrowdDot[] = [];
  seq = 0;
  tick = 0;
  label = "";
  status = "";
  downModules: string[] = [];
  /** True while the scene is replaying recorded movement rather than live. */
  replaying = false;
  /**
   * Light the scene as at this minute of the day instead of the sim clock's.
   * For looking at four times of day without simulating four days; null in
   * anything a visitor sees.
   */
  clockOverride: number | null = null;
  /**
   * Storeys above this one are not shown, and neither are the people on them:
   * a cut through the building, for looking at a floor the ones above would
   * hide. Null shows everything. The renderer and picking both read it.
   */
  levelCut: number | null = null;

  private truth = new Map<string, Agent>();
  private history: Move[] = [];
  private lastAdvanceAt = 0;
  private seenLive = false;
  private replayCursor = 0;
  private replayNextAt = 0;
  private replayTicks: number[] = [];

  setMap(map: TownMap): void {
    this.map = map;
  }

  /** Minutes since midnight on the sim clock: what the sky is a function of. */
  get minute(): number {
    return this.clockOverride ?? minuteOfDay(this.label);
  }

  /** Whether the level cut leaves this person in view. */
  shown(walker: Walker): boolean {
    return this.levelCut === null || walker.floor <= this.levelCut;
  }

  /**
   * How much recorded movement to keep: enough for the replay's few ticks
   * even when everyone walks at once, so it grows with the staff rather than
   * being a number that was right for two dozen people.
   */
  private get historyLimit(): number {
    return Math.max(MIN_HISTORY, this.walkers.size * REPLAY_TICKS * 2);
  }

  /**
   * Pose somebody (WEB-0004). The one way poses are set.
   *
   * Only the keys present in `pose` change, and a key present with the value
   * `undefined` clears that field back to "no opinion" — so
   * `setPose(id, { talkingTo: undefined })` ends a conversation and leaves
   * `seated` alone. Unknown ids are ignored: an event can name somebody the
   * first frame has not delivered yet.
   */
  setPose(id: string, pose: Pose): void {
    const walker = this.walkers.get(id);
    if (walker === undefined) return;
    if ("seated" in pose) walker.seated = pose.seated;
    if ("facing" in pose) walker.facing = pose.facing;
    if ("talkingTo" in pose) walker.talkingTo = pose.talkingTo;
    if ("selected" in pose) walker.selected = pose.selected;
  }

  /** The authoritative frame: where the server says everyone is right now. */
  applyFrame(frame: AgentsFrame, now: number): void {
    // The first frame says where things stand; it is not evidence that anything
    // is happening. A later frame with a higher `seq` is.
    if (this.lastAdvanceAt === 0) this.seq = Math.max(this.seq, frame.seq);
    else this.noteSeq(frame.seq, now);
    this.tick = frame.tick_seq;
    this.label = frame.label;
    this.status = frame.status;
    this.downModules = frame.down_modules;
    this.truth.clear();
    for (const agent of frame.agents) {
      this.truth.set(agent.id, agent);
      const existing = this.walkers.get(agent.id);
      if (existing === undefined) {
        this.walkers.set(agent.id, this.spawn(agent));
      } else if (!existing.walking && !this.replaying) {
        this.settle(existing, agent);
      } else {
        existing.mood = agent.mood;
      }
    }
    this.layoutCrowd(frame.crowd);
    if (this.lastAdvanceAt === 0) this.lastAdvanceAt = now;
  }

  private spawn(agent: Agent): Walker {
    const walker: Walker = {
      id: agent.id,
      name: agent.name,
      orgId: agent.org_id,
      role: agent.role,
      zone: agent.zone,
      floor: agent.floor,
      mood: agent.mood,
      x: agent.x ?? 0,
      y: agent.y ?? 0,
      heading: 0,
      visible: agent.x !== null,
      walking: false,
      phase: hash(agent.id) * Math.PI * 2,
      route: null,
      routeStart: 0,
      routeEnd: 0,
      routeToZone: null,
    };
    return walker;
  }

  private settle(walker: Walker, agent: Agent): void {
    walker.zone = agent.zone;
    walker.floor = agent.floor;
    walker.mood = agent.mood;
    walker.visible = agent.x !== null;
    if (agent.x !== null && agent.y !== null) {
      walker.x = agent.x;
      walker.y = agent.y;
    }
  }

  /** Movement the server has already recorded, kept for the idle replay. */
  seedHistory(moves: Move[]): void {
    this.history = [...moves].sort((a, b) => a.seq - b.seq).slice(-this.historyLimit);
  }

  /**
   * On arrival, show the most recent movement the server recorded.
   *
   * A visitor should see the town move within seconds, and with a live daemon
   * that cannot be left to luck: a tick is fifteen real seconds and nobody may
   * change rooms in it. This is not an invented animation — it is the latest
   * tick in which anyone walked anywhere, which by construction ends with
   * everyone where the server says they are now.
   */
  playLatest(now: number): number {
    const last = this.history.at(-1);
    if (last === undefined) return 0;
    const moves = this.history.filter((move) => move.tick === last.tick);
    for (const move of moves) this.walk(move, now);
    return moves.length;
  }

  /** A live `agent.moved`: walk it now. */
  liveMove(move: Move, now: number): void {
    this.noteSeq(move.seq, now);
    this.history.push(move);
    const over = this.history.length - this.historyLimit;
    if (over > 0) this.history.splice(0, over);
    this.walk(move, now);
  }

  /** A live event arrived. The world is advancing, so stop any replay. */
  noteSeq(seq: number, now: number): void {
    if (seq <= this.seq) return;
    this.seq = seq;
    this.seenLive = true;
    this.lastAdvanceAt = now;
    if (this.replaying) this.stopReplay(now);
  }

  /** True once a live event has arrived and none has been missed for long. */
  get live(): boolean {
    return this.seenLive && !this.replaying;
  }

  private walk(move: Move, now: number): void {
    const walker = this.walkers.get(move.personId);
    const first = move.path[0];
    if (walker === undefined || first === undefined || move.path.length < 2) return;
    const delay = hash(`${move.personId}:${move.tick}`) * STAGGER_MS;
    const duration = Math.min(
      MAX_WALK_MS,
      Math.max(MIN_WALK_MS, move.path.length * MS_PER_TILE),
    );
    walker.route = move.path;
    walker.routeStart = now + delay;
    walker.routeEnd = now + delay + duration;
    walker.routeToZone = move.toZone;
    walker.walking = true;
    walker.visible = true;
    walker.x = first[0];
    walker.y = first[1];
    walker.floor = first[2];
  }

  /** Advance every walker to `now`. Returns how many are mid-walk. */
  update(now: number): number {
    this.maybeReplay(now);
    let moving = 0;
    for (const walker of this.walkers.values()) {
      if (!walker.walking || walker.route === null) continue;
      if (now < walker.routeStart) {
        moving++;
        continue;
      }
      const span = walker.routeEnd - walker.routeStart;
      const t = span <= 0 ? 1 : Math.min(1, (now - walker.routeStart) / span);
      // Ease in and out: people accelerate away from a desk, they do not teleport
      // up to walking speed.
      const eased = t * t * (3 - 2 * t);
      const at = eased * (walker.route.length - 1);
      const index = Math.min(walker.route.length - 2, Math.floor(at));
      const a = walker.route[index];
      const b = walker.route[index + 1];
      if (a !== undefined && b !== undefined) {
        const f = at - index;
        walker.x = a[0] + (b[0] - a[0]) * f;
        walker.y = a[1] + (b[1] - a[1]) * f;
        // A flight of stairs is one node on each floor at the same tile: on
        // that step nothing moves but the floor, which changes at the midpoint.
        walker.floor = f < 0.5 ? a[2] : b[2];
        if (a[0] !== b[0] || a[1] !== b[1]) {
          walker.heading = Math.atan2(b[0] - a[0], b[1] - a[1]);
        }
      }
      if (t >= 1) {
        walker.walking = false;
        walker.route = null;
        if (walker.routeToZone !== null) {
          walker.zone = walker.routeToZone;
          walker.visible = walker.routeToZone !== "home";
        }
      } else {
        moving++;
      }
    }
    return moving;
  }

  // -- the idle replay -----------------------------------------------------

  /**
   * When nothing has moved for a few seconds — the daemon is paused, or it is
   * night, or it has reached its horizon — replay the last sim-hour of recorded
   * movement on a loop, so the town is never a still image. It is a replay of
   * real recorded movement and the page says so; when a live move arrives it
   * stops at once and the true positions are restored.
   */
  private maybeReplay(now: number): void {
    if (this.history.length === 0) return;
    if (!this.replaying) {
      const patience = this.seenLive ? STALL_WHILE_LIVE_MS : STALL_BEFORE_FIRST_EVENT_MS;
      if (now - this.lastAdvanceAt < patience) return;
      const ticks = [...new Set(this.history.map((m) => m.tick))].sort((a, b) => a - b);
      this.replayTicks = ticks.slice(-REPLAY_TICKS);
      if (this.replayTicks.length === 0) return;
      this.replaying = true;
      this.replayCursor = 0;
      this.replayNextAt = now;
    }
    if (now < this.replayNextAt) return;
    const tick = this.replayTicks[this.replayCursor];
    if (tick === undefined) {
      // End of the loop: put everyone back where the server says they are,
      // pause a beat, go again.
      this.restoreTruth();
      this.replayCursor = 0;
      this.replayNextAt = now + 900;
      return;
    }
    for (const move of this.history) {
      if (move.tick === tick) this.walk(move, now);
    }
    this.replayCursor++;
    this.replayNextAt = now + REPLAY_TICK_MS;
  }

  private stopReplay(now: number): void {
    this.replaying = false;
    this.replayNextAt = now;
    this.restoreTruth();
  }

  private restoreTruth(): void {
    for (const [id, agent] of this.truth) {
      const walker = this.walkers.get(id);
      if (walker === undefined) continue;
      walker.walking = false;
      walker.route = null;
      this.settle(walker, agent);
    }
  }

  // -- the crowd -----------------------------------------------------------

  /**
   * Counterparties are demand flows, not people with positions. They are drawn
   * as a sampled crowd: the count is real (last tick's arrivals), the spots are
   * a stable shuffle so dots do not jump about between frames. `counts` is
   * keyed by zone — each social firm's id and the plaza — and so is the map's
   * `crowd_spots`, all of which are on the ground floor.
   */
  private layoutCrowd(counts: Record<string, number>): void {
    const map = this.map;
    if (map === null) return;
    const dots: CrowdDot[] = [];
    for (const [zone, count] of Object.entries(counts)) {
      const spots = map.crowd_spots[zone] ?? [];
      const order = spots
        .map((spot, i) => ({ spot, key: hash(`${zone}:${i}`) }))
        .sort((a, b) => a.key - b.key);
      for (const { spot, key } of order.slice(0, Math.min(count, order.length))) {
        dots.push({
          x: spot[0] + (key - 0.5) * 0.5,
          y: spot[1] + (hash(`${key}`) - 0.5) * 0.5,
          phase: key * Math.PI * 2,
          tint: key,
        });
      }
    }
    this.crowd = dots;
  }

  // -- picking -------------------------------------------------------------

  /**
   * The person nearest a screen point, by projected position.
   *
   * Not a raycast against instanced meshes: there are a few hundred people at
   * most, an instanced mesh's cached bounds go stale as instances move, and
   * this way a click resolves identically with no GPU at all. Somebody on an
   * upper floor is projected from that floor's height, as they are drawn; and
   * somebody the level cut hides cannot be clicked.
   */
  pick(
    px: number,
    py: number,
    project: (x: number, height: number, y: number) => { x: number; y: number },
    radius = 26,
  ): Walker | null {
    let best: Walker | null = null;
    let bestDistance = radius * radius;
    for (const walker of this.walkers.values()) {
      if (!walker.visible || !this.shown(walker)) continue;
      const p = project(walker.x, 0.7 + walker.floor * STOREY, walker.y);
      const d = (p.x - px) ** 2 + (p.y - py) ** 2;
      if (d < bestDistance) {
        bestDistance = d;
        best = walker;
      }
    }
    return best;
  }

  zoneAt(tileX: number, tileY: number): string | null {
    const row = this.map?.zones[Math.floor(tileY)];
    return row?.[Math.floor(tileX)] ?? null;
  }

  snapshot(): {
    seq: number;
    tick: number;
    label: string;
    replaying: boolean;
    live: boolean;
    visible: number;
    walking: number;
    /** The minute of the sim day the scene is lit for, and the light at it. */
    minute: number;
    sky: string;
    sunIntensity: number;
    lamps: number;
    agents: {
      id: string;
      x: number;
      y: number;
      floor: number;
      zone: string;
      visible: boolean;
      walking: boolean;
    }[];
  } {
    const sky = skyAt(this.minute);
    const agents = [...this.walkers.values()].map((w) => ({
      id: w.id,
      x: Math.round(w.x * 100) / 100,
      y: Math.round(w.y * 100) / 100,
      floor: w.floor,
      zone: w.zone,
      visible: w.visible,
      walking: w.walking,
    }));
    return {
      seq: this.seq,
      tick: this.tick,
      label: this.label,
      replaying: this.replaying,
      live: this.live,
      visible: agents.filter((a) => a.visible).length,
      walking: [...this.walkers.values()].filter((w) => w.walking).length,
      minute: this.minute,
      sky: sky.top,
      sunIntensity: Math.round(sky.sunIntensity * 1000) / 1000,
      lamps: Math.round(sky.lamps * 1000) / 1000,
      agents,
    };
  }
}
