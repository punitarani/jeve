/**
 * The town replay: the sim's own map, drawn isometric on a 2D canvas, with an
 * average weekday replayed from measured rates.
 *
 * Not the voxel world (WEB-0002). That renders where everyone *is*; this
 * renders what they *tend to do* — how often each person heads to the cafe,
 * how long the queue gets by hour, what people talk about — so it is rebuilt
 * from aggregates, not recorded frames, and it has to run on a page full of
 * charts without a GPU. Deterministic: every coin toss is a hash of who and
 * which tick (CORE-0009 in miniature), so a scrub back and forth replays the
 * same day.
 *
 * Imperative on purpose. A frame is a full repaint sixty times a second; the
 * React wrapper owns the markup and hands this the elements it paints into.
 */

export type Tile = readonly [number, number];

export type CastMember = {
	id: string;
	name: string;
	org_id: string;
	role: string;
	seat: Tile;
	spot?: Tile;
	path: readonly Tile[];
};

export type TownBuilding = {
	/** Cash on hand, in dollars. */
	cash: number;
	/** A red pill under the label, e.g. "payroll held". */
	flag?: string;
	/** The status line in the building's tooltip. */
	note?: string;
};

export type TownData = {
	/** tiles[y][x] is a tile kind, as world/map.py names them. */
	tiles: readonly (readonly string[])[];
	cast: readonly CastMember[];
	queue: readonly Tile[];
	/** Per person: share of ticks at the cafe and stopping to talk (0–100), mean mood (0–3). */
	people: Readonly<Record<string, { cafe: number; talk: number; mood: number }>>;
	/** Office staff's share at the cafe, by hour of the day. */
	cafeShare: Readonly<Record<number, number>>;
	/** Cafe arrivals (sales and walkouts), by hour of the day. */
	arrivals: Readonly<Record<number, number>>;
	/** Encounter topics and their share, most common first. */
	topics: readonly (readonly [string, number])[];
	buildings: Readonly<Record<string, TownBuilding>>;
	/**
	 * An illustrative outage of a module the cafe runs on, in replay ticks,
	 * raised over coffee: `name` for the HUD ("POS"), `label` for the cafe's
	 * pill ("POS down"), `shout` for its staff's bubbles ("pos is down!").
	 */
	outage: { from: number; to: number; name: string; label: string; shout: string } | null;
	/** The HUD's day label, e.g. "d232 replay". */
	day: string;
	/** Tooltip label for a building's cash, e.g. "cash at d232". */
	cashLabel: string;
};

export type TownEls = {
	canvas: HTMLCanvasElement;
	clock: HTMLElement;
	note: HTMLElement;
	scrub: HTMLInputElement;
	play: HTMLButtonElement;
};

export type TownHandlers = {
	tip: (pageX: number, pageY: number, body: TownTip) => void;
	hideTip: () => void;
	/** A building label was clicked. */
	open: (org: string) => void;
};

export type TownTip =
	| { kind: "person"; name: string; role: string; org: string; stats: { cafe: number; talk: number; mood: number } | null }
	| { kind: "building"; name: string; cash: number; cashLabel: string; note?: string };

export const TICKS = 32;
const MW = 40;
const MH = 28;
const MONO = '"JetBrains Mono", ui-monospace, monospace';

const PAL: Record<string, { wall: string; floor: string; body: string; accent: string }> = {
	tallybird: { wall: "#5b78d6", floor: "#c9d4f5", body: "#7c9cff", accent: "#2b3f8c" },
	halloran: { wall: "#a8871f", floor: "#efe3b8", body: "#c9a227", accent: "#5e4a0c" },
	ledgerline: { wall: "#3f9470", floor: "#cdebdc", body: "#5bb98c", accent: "#1f4d3a" },
	thirdrail: { wall: "#b9555c", floor: "#f6d3d5", body: "#e0757c", accent: "#6b2227" },
};
const pal = (org: string) => PAL[org] ?? PAL.tallybird!;

type Bld = {
	zone: string;
	org: string;
	name: string;
	x0: number;
	y0: number;
	x1: number;
	y1: number;
	h: number;
	hit?: [number, number, number, number];
};
// world/map.py's BUILDINGS, with a wall height each so the four read apart.
const BLD: readonly Bld[] = [
	{ zone: "software_office", org: "tallybird", name: "Tallybird Software", x0: 2, y0: 2, x1: 15, y1: 10, h: 1.6 },
	{ zone: "law_office", org: "halloran", name: "Halloran & Pike LLP", x0: 24, y0: 2, x1: 37, y1: 10, h: 2.0 },
	{ zone: "accounting_office", org: "ledgerline", name: "Ledgerline Accounting", x0: 2, y0: 17, x1: 15, y1: 25, h: 1.45 },
	{ zone: "cafe", org: "thirdrail", name: "Third Rail Cafe", x0: 24, y0: 17, x1: 37, y1: 25, h: 1.2 },
];

const hx = (h: string) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const toHex = (a: number[]) =>
	`#${a.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;
const blend = (a: string, b: string, t: number) => {
	const A = hx(a);
	const B = hx(b);
	return toHex(A.map((v, i) => v + ((B[i] ?? 0) - v) * t));
};
const shade = (c: string, f: number) => toHex(hx(c).map((v) => v * f));
function hash(...n: number[]): number {
	let h = 2166136261;
	for (const v of n) {
		h ^= Math.imul(v | 0, 2654435761);
		h = Math.imul(h, 16777619);
		h ^= h >>> 13;
	}
	return ((h >>> 0) % 100000) / 100000;
}
const jitter = (c: string, amt: number, ...k: number[]) => shade(c, 1 + (hash(...k) - 0.5) * 2 * amt);
const mute = (c: string, t: number) => blend(c, "#8a8a8a", t);

const SKIN = ["#f1c9a5", "#d9a57c", "#b87a52", "#8d5a3b", "#e8b894", "#6e4630"];
const HAIR = ["#2b1d14", "#5a3a22", "#8a5a2b", "#c9a15f", "#1a1a1a", "#7b3f2a"];
const TROU = ["#2f3542", "#3d4558", "#4a3b2f", "#2f3a34"];
const pick = (list: string[], i: number, salt: number) => list[Math.floor(hash(i, salt) * list.length)] ?? list[0]!;

const SKY: [number, string, string][] = [
	[9, "#86bbea", "#ffe6c2"],
	[12, "#58a6ea", "#d4ecfb"],
	[15, "#62a8e4", "#e9eedb"],
	[16.5, "#5a7fc0", "#f6c9a0"],
	[17, "#4a4a9a", "#ffa46c"],
];
function skyAt(hour: number): [string, string] {
	let a = SKY[0]!;
	let b = SKY[SKY.length - 1]!;
	for (let i = 0; i < SKY.length - 1; i++) {
		if (hour >= SKY[i]![0] && hour <= SKY[i + 1]![0]) {
			a = SKY[i]!;
			b = SKY[i + 1]!;
			break;
		}
	}
	const t = b[0] === a[0] ? 0 : (hour - a[0]) / (b[0] - a[0]);
	return [blend(a[1], b[1], t), blend(a[2], b[2], t)];
}

export function hhmm(t: number): string {
	const m = 9 * 60 + Math.floor(t) * 15;
	return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

type Actor = CastMember & {
	i: number;
	cafePct: number;
	talk: number;
	skin: string;
	hair: string;
	trou: string;
	at: boolean[];
};

/** Paint the town into `els` and animate it; returns the teardown. */
export function mountTown(els: TownEls, data: TownData, on: TownHandlers): () => void {
	const cv = els.canvas;
	const ctx = cv.getContext("2d");
	if (ctx === null) return () => {};
	const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
	const kindAt = (x: number, y: number) => (x < 0 || y < 0 || x >= MW || y >= MH ? null : (data.tiles[y]?.[x] ?? null));
	const bldAt = (x: number, y: number) => BLD.find((b) => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1);
	const inside = (b: Bld, x: number, y: number) => x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1;
	const blds: Bld[] = BLD.map((b) => ({ ...b }));
	const cashOf = (org: string) => data.buildings[org]?.cash ?? 0;

	let W = 0;
	let H = 0;
	let tw = 0;
	let th = 0;
	let hz = 0;
	let ox = 0;
	let oy = 0;
	let dpr = 1;
	let ground: HTMLCanvasElement | null = null;
	const P = (x: number, y: number, z: number): [number, number] => [ox + ((x - y) * tw) / 2, oy + ((x + y) * th) / 2 - z * hz];
	function poly(pts: [number, number][], fill: string) {
		ctx!.beginPath();
		ctx!.moveTo(pts[0]![0], pts[0]![1]);
		for (let i = 1; i < pts.length; i++) ctx!.lineTo(pts[i]![0], pts[i]![1]);
		ctx!.closePath();
		ctx!.fillStyle = fill;
		ctx!.fill();
	}
	function box(x: number, y: number, z: number, w: number, d: number, h: number, c: string) {
		poly([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)], shade(c, 0.8));
		poly([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)], shade(c, 0.66));
		poly([P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)], c);
	}
	const cbox = (cx: number, cy: number, z: number, w: number, d: number, h: number, c: string) =>
		box(cx - w / 2, cy - d / 2, z, w, d, h, c);
	function floorOf(b: Bld, x: number, y: number) {
		const p = pal(b.org);
		switch (b.zone) {
			case "software_office":
				return jitter(blend("#8d97ab", p.floor, 0.25), 0.05, x >> 1, y >> 1, 31);
			case "law_office":
				return jitter("#a9784a", 0.09, (x + y) >> 1, y, 32);
			case "accounting_office":
				return jitter(blend("#b9c4b2", p.floor, 0.3), 0.04, x, y, 33);
			default:
				return jitter((x + y) % 2 === 0 ? "#e4d3bd" : "#b8705a", 0.04, x, y, 34);
		}
	}

	// Static solids: built once, drawn each frame in depth order with the people.
	const SOLIDS: { d: number; fn: () => void }[] = [];
	const add = (d: number, fn: () => void) => SOLIDS.push({ d, fn });
	for (let y = 0; y < MH; y++) {
		for (let x = 0; x < MW; x++) {
			const k = kindAt(x, y);
			const cx = x + 0.5;
			const cy = y + 0.5;
			const dep = cx + cy;
			const b = bldAt(x, y);
			switch (k) {
				case "wall": {
					if (!b) break;
					const front = y === b.y1 || x === b.x1; // cut away the walls that face the camera
					const h = front ? 0.42 : b.h * 0.72;
					const p = pal(b.org);
					const c = jitter(blend(mute(p.wall, 0.15), "#e6dfd0", 0.42), 0.06, x, y, 7);
					const cap = blend(p.wall, p.accent, 0.45);
					add(dep, () => {
						box(x, y, 0, 1, 1, h, c);
						box(x, y, h, 1, 1, 0.07, cap);
					});
					break;
				}
				case "desk":
					add(dep, () => {
						cbox(cx, cy, 0, 0.9, 0.62, 0.45, jitter("#b98a55", 0.06, x, y));
						cbox(cx + 0.05, cy - 0.12, 0.45, 0.46, 0.07, 0.3, "#23262f");
						cbox(cx + 0.05, cy - 0.08, 0.5, 0.38, 0.01, 0.2, "#9fd0ff");
					});
					break;
				case "chair":
					add(dep, () => cbox(cx, cy, 0, 0.36, 0.36, 0.3, "#7d5a36"));
					break;
				case "table":
					add(dep, () => {
						cbox(cx, cy, 0, 0.12, 0.12, 0.4, "#5f4331");
						cbox(cx, cy, 0.4, 0.74, 0.74, 0.07, "#eadfca");
					});
					break;
				case "counter":
					add(dep, () => {
						cbox(cx, cy, 0, 1, 0.72, 0.8, jitter("#8b5a3c", 0.06, x, y));
						cbox(cx, cy, 0.8, 1, 0.84, 0.09, "#eadfca");
					});
					break;
				case "conference":
					add(dep, () => cbox(cx, cy, 0, 1, 0.9, 0.46, "#6b4a2f"));
					break;
				case "bookshelf":
					add(dep - 0.3, () => {
						cbox(cx, cy - 0.28, 0, 0.98, 0.42, 1.4, "#6b4a2f");
						for (let s = 0; s < 3; s++)
							cbox(cx, cy - 0.06, 0.2 + s * 0.42, 0.84, 0.02, 0.26, ["#8a2430", "#2f4a7a", "#c9a227"][(x + s) % 3]!);
					});
					break;
				case "server_rack":
					add(dep, () => {
						cbox(cx, cy, 0, 0.84, 0.8, 1.5, "#262932");
						for (let i = 0; i < 4; i++)
							cbox(cx - 0.25 + i * 0.17, cy + 0.41, 0.35 + (i % 2) * 0.5, 0.07, 0.02, 0.06, ["#5dff8a", "#5dc8ff", "#ffb84d"][i % 3]!);
					});
					break;
				case "filing":
					add(dep - 0.2, () => cbox(cx, cy - 0.18, 0, 0.92, 0.58, 1.1, jitter("#b7b2a4", 0.05, x, y)));
					break;
				case "partition":
					add(dep, () => cbox(cx, cy, 0, 0.94, 0.1, 1.05, "#9fb8c4"));
					break;
				case "kitchen":
					add(dep - 0.1, () => {
						cbox(cx, cy - 0.12, 0, 1, 0.72, 0.9, "#b9bec4");
						cbox(cx, cy - 0.12, 0.9, 1, 0.76, 0.05, "#d9dde1");
					});
					break;
				case "whiteboard":
					add(dep - 0.4, () => cbox(cx, cy - 0.4, 0.3, 0.96, 0.06, 0.66, "#f6f8fa"));
					break;
				case "plant":
					add(dep, () => {
						cbox(cx, cy, 0, 0.42, 0.42, 0.36, "#b5673f");
						cbox(cx, cy, 0.36, 0.52, 0.52, 0.46, jitter("#3f8f4f", 0.1, x, y, 6));
					});
					break;
				case "planter":
					add(dep, () => {
						cbox(cx, cy, 0, 0.92, 0.92, 0.4, "#9c968a");
						cbox(cx, cy, 0.4, 0.8, 0.8, 0.24, jitter("#4f9a52", 0.1, x, y, 7));
						cbox(cx + 0.15, cy - 0.1, 0.64, 0.12, 0.12, 0.12, "#f2e27a");
					});
					break;
				case "lamp":
					add(dep, () => {
						cbox(cx, cy, 0, 0.12, 0.12, 2.2, "#2c2f38");
						cbox(cx, cy, 2.2, 0.42, 0.42, 0.18, "#fff1c4");
					});
					break;
				case "bench":
					add(dep, () => cbox(cx, cy, 0, 0.98, 0.46, 0.24, "#a9825a"));
					break;
				case "tree":
					add(dep, () => {
						cbox(cx, cy, 0, 0.26, 0.26, 0.9, "#6f4d31");
						cbox(cx, cy, 0.75, 1.1, 1.1, 1.05, jitter("#3d8a4b", 0.1, x, y, 4));
						cbox(cx - 0.12, cy - 0.12, 1.8, 0.62, 0.62, 0.4, jitter("#57a35c", 0.1, x, y, 5));
					});
					break;
			}
		}
	}
	add(40.5, () => {
		cbox(20, 14, 0, 2, 2, 0.32, "#cfc6b2");
		cbox(20, 14, 0.32, 1.7, 1.7, 0.02, "#7cc4e8");
		cbox(20, 14, 0.32, 0.24, 0.24, 0.75, "#cfc6b2");
		cbox(20, 14, 1.07, 0.5, 0.5, 0.08, "#9fd8f2");
	});

	function paintGround() {
		ground = document.createElement("canvas");
		ground.width = Math.round(W * dpr);
		ground.height = Math.round(H * dpr);
		const g = ground.getContext("2d");
		if (g === null) return;
		g.setTransform(dpr, 0, 0, dpr, 0, 0);
		const gp = (pts: [number, number][], fill: string) => {
			g.beginPath();
			g.moveTo(pts[0]![0], pts[0]![1]);
			for (let i = 1; i < pts.length; i++) g.lineTo(pts[i]![0], pts[i]![1]);
			g.closePath();
			g.fillStyle = fill;
			g.fill();
		};
		gp([P(0, MH, 0), P(MW, MH, 0), P(MW, MH, -0.9), P(0, MH, -0.9)], "#6a5238"); // the diorama's soil edges
		gp([P(MW, 0, 0), P(MW, MH, 0), P(MW, MH, -0.9), P(MW, 0, -0.9)], "#56422c");
		for (let y = 0; y < MH; y++) {
			for (let x = 0; x < MW; x++) {
				const k = kindAt(x, y);
				const b = bldAt(x, y);
				let c: string;
				if (b && inside(b, x, y)) c = floorOf(b, x, y);
				else if (k === "grass" || k === "tree") c = jitter("#6fae58", 0.07, x, y, 1);
				else if (k === "path" || k === "door") c = jitter("#e3dac6", 0.03, x, y, 2);
				else c = jitter("#cfc6b2", 0.05, x >> 1, y >> 1, 3);
				gp([P(x, y, 0), P(x + 1, y, 0), P(x + 1, y + 1, 0), P(x, y + 1, 0)], c);
			}
		}
	}

	// People, and their day.
	const staff: Actor[] = data.cast.map((s, i) => ({
		...s,
		i,
		cafePct: data.people[s.id]?.cafe ?? 0,
		talk: data.people[s.id]?.talk ?? 0,
		skin: pick(SKIN, i, 11),
		hair: pick(HAIR, i, 12),
		trou: pick(TROU, i, 13),
		at: [],
	}));
	const office = staff.filter((s) => s.org_id !== "thirdrail");
	const meanPct = office.reduce((a, s) => a + s.cafePct, 0) / Math.max(1, office.length) || 1;
	// Deterministic, keyed by the person and their own tick, a little sticky so nobody bounces.
	for (const s of office) {
		let prev = false;
		for (let k = 0; k < TICKS; k++) {
			const hour = 9 + Math.floor(k / 4);
			let p = Math.min(0.95, ((data.cafeShare[hour] ?? 0) * s.cafePct) / meanPct);
			if (prev) p = Math.min(0.92, p * 2.2 + 0.2);
			prev = hash(s.i, k, 99) < p;
			s.at.push(prev);
		}
	}
	const maxArr = Math.max(1, ...Object.values(data.arrivals));

	function along(path: readonly Tile[], f: number): [number, number] {
		const first = path[0] ?? [0, 0];
		if (path.length < 2) return [first[0] + 0.5, first[1] + 0.5];
		const L = (path.length - 1) * Math.max(0, Math.min(1, f));
		const i = Math.min(path.length - 2, Math.floor(L));
		const t = L - i;
		const a = path[i]!;
		const b = path[i + 1]!;
		return [a[0] + 0.5 + (b[0] - a[0]) * t, a[1] + 0.5 + (b[1] - a[1]) * t];
	}
	function personAt(s: Actor, t: number) {
		if (s.org_id === "thirdrail" || !s.spot)
			return { x: s.seat[0] + 0.5, y: s.seat[1] + 0.5, walking: false, atCafe: s.org_id === "thirdrail" };
		const k = Math.min(TICKS - 1, Math.floor(t));
		const f = Math.min(1, t - k);
		const now = s.at[k] ?? false;
		const before = k > 0 ? (s.at[k - 1] ?? false) : false;
		if (now === before) {
			const p = now ? s.spot : s.seat;
			return { x: p[0] + 0.5, y: p[1] + 0.5, walking: false, atCafe: now };
		}
		const g = Math.min(1, f / 0.72);
		const [x, y] = along(s.path, now ? g : 1 - g);
		return { x, y, walking: g < 1, atCafe: now && g >= 1 };
	}
	function figure(x: number, y: number, s: Actor | null, bob: number) {
		const z = bob ? Math.abs(Math.sin(bob)) * 0.06 : 0;
		const body = s ? pal(s.org_id).body : "#a9a5a0";
		const skin = s ? s.skin : "#d2cec8";
		const hair = s ? s.hair : "#8a8782";
		const trou = s ? s.trou : "#6d6f76";
		const k = 1.45; // toy scale: people read at a glance
		cbox(x, y, z, 0.28 * k, 0.2 * k, 0.34 * k, trou);
		cbox(x, y, z + 0.34 * k, 0.36 * k, 0.24 * k, 0.36 * k, body);
		cbox(x, y, z + 0.7 * k, 0.26 * k, 0.26 * k, 0.26 * k, skin);
		cbox(x, y, z + 0.96 * k, 0.28 * k, 0.28 * k, 0.07 * k, hair);
	}
	function bubble(x: number, y: number, text: string, strong: boolean) {
		const fs = Math.max(9, Math.min(12, tw * 0.34));
		ctx!.font = `700 ${fs}px ${MONO}`;
		const w = ctx!.measureText(text).width + fs * 1.2;
		const h = fs * 1.9;
		const bx = Math.max(4, Math.min(W - w - 4, x - w / 2));
		const by = y - h - 7;
		ctx!.fillStyle = "rgba(0,0,0,.18)";
		ctx!.beginPath();
		ctx!.roundRect(bx + 2, by + 2, w, h, h / 2);
		ctx!.fill();
		ctx!.fillStyle = strong ? "#fde3e6" : "#f7f4ec";
		ctx!.beginPath();
		ctx!.roundRect(bx, by, w, h, h / 2);
		ctx!.fill();
		ctx!.beginPath();
		ctx!.moveTo(x - 4, by + h - 0.5);
		ctx!.lineTo(x + 4, by + h - 0.5);
		ctx!.lineTo(x, by + h + 6);
		ctx!.closePath();
		ctx!.fill();
		ctx!.fillStyle = strong ? "#9b1c2c" : "#1a1d23";
		ctx!.textBaseline = "middle";
		ctx!.fillText(text, bx + fs * 0.6, by + h / 2 + 0.5);
	}
	function label(b: Bld, extra: string | null) {
		const [x, y] = P((b.x0 + b.x1 + 1) / 2, b.y0 + 0.5, b.h * 0.72 + 1.2);
		const fs = Math.max(9, Math.min(12.5, tw * 0.36));
		ctx!.font = `700 ${fs}px ${MONO}`;
		const name = W < 620 ? (b.name.split(" ")[0] ?? b.name) : b.name;
		const cash = `$${(cashOf(b.org) / 1000).toFixed(1)}k`;
		const t1 = ctx!.measureText(name).width;
		const t2 = ctx!.measureText(cash).width;
		const pad = fs * 0.7;
		const dot = fs * 0.7;
		const w = pad + dot + 6 + t1 + fs * 0.8 + t2 + pad;
		const h = fs * 2.1;
		const lx = Math.max(4, Math.min(W - w - 4, x - w / 2));
		const ly = Math.max(4, y - h);
		const p = pal(b.org);
		ctx!.fillStyle = "rgba(14,17,22,.88)";
		ctx!.beginPath();
		ctx!.roundRect(lx, ly, w, h, 7);
		ctx!.fill();
		ctx!.strokeStyle = `${p.body}aa`;
		ctx!.lineWidth = 1;
		ctx!.stroke();
		ctx!.fillStyle = p.body;
		ctx!.fillRect(lx + pad, ly + h / 2 - dot / 2, dot, dot);
		ctx!.textBaseline = "middle";
		ctx!.fillStyle = "#dfe5ec";
		ctx!.fillText(name, lx + pad + dot + 6, ly + h / 2 + 0.5);
		ctx!.fillStyle = data.buildings[b.org]?.flag ? "#e0757c" : "#8b96a5";
		ctx!.fillText(cash, lx + pad + dot + 6 + t1 + fs * 0.8, ly + h / 2 + 0.5);
		b.hit = [lx, ly, w, h];
		if (extra && W >= 480) {
			ctx!.font = `700 ${fs * 0.9}px ${MONO}`;
			const ew = ctx!.measureText(extra).width + fs * 1.2;
			const ex = Math.max(4, Math.min(W - ew - 4, x - ew / 2));
			const ey = ly + h + 4;
			ctx!.fillStyle = "#e0757c";
			ctx!.beginPath();
			ctx!.roundRect(ex, ey, ew, fs * 1.75, fs * 0.87);
			ctx!.fill();
			ctx!.fillStyle = "#1d1113";
			ctx!.fillText(extra, ex + fs * 0.6, ey + fs * 0.875 + 0.5);
		}
	}

	let tNow = 16.3;
	let playing = false;
	let hold = 0;
	let screenPeople: { s: Actor; sx: number; sy: number }[] = [];
	const outage = data.outage;

	function frame() {
		if (!ground) return;
		const [top, bot] = skyAt(Math.min(17, 9 + tNow / 4));
		ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
		const gr = ctx!.createLinearGradient(0, 0, 0, H);
		gr.addColorStop(0, top);
		gr.addColorStop(1, bot);
		ctx!.fillStyle = gr;
		ctx!.fillRect(0, 0, W, H);
		ctx!.drawImage(ground, 0, 0, W, H);
		const k = Math.min(TICKS - 1, Math.floor(tNow));
		const f = tNow - k;
		const down = outage !== null && k >= outage.from && k < outage.to;
		const items = SOLIDS.slice();
		const talkers: { s: Actor; sx: number; sy: number }[] = [];
		screenPeople = [];
		for (const s of staff) {
			const p = personAt(s, tNow);
			items.push({ d: p.x + p.y + 0.01, fn: () => figure(p.x, p.y, s, p.walking ? tNow * 18 + s.i : 0) });
			const [sx, sy] = P(p.x, p.y, 1.55);
			screenPeople.push({ s, sx, sy });
			if (p.atCafe) talkers.push({ s, sx, sy });
		}
		const hour = 9 + Math.floor(tNow / 4);
		const q = Math.round(1 + (5 * (data.arrivals[hour] ?? 0)) / maxArr);
		for (let i = 0; i < q && data.queue.length; i++) {
			const [x, y] = along(data.queue, i / (data.queue.length * 2));
			const xx = x + (hash(i, hour, 5) - 0.5) * 0.3;
			items.push({ d: xx + y, fn: () => figure(xx, y, null, 0) });
		}
		items.sort((a, b) => a.d - b.d);
		for (const it of items) it.fn();
		for (const b of blds) {
			const flag = data.buildings[b.org]?.flag ?? null;
			label(b, flag ?? (b.org === "thirdrail" && down && outage ? outage.label : null));
		}
		if (f > 0.1 && f < 0.92 && tNow < TICKS) {
			let shown = 0;
			let escalated = false;
			const cap = W < 560 ? 2 : 4;
			for (const { s, sx, sy } of talkers) {
				if (shown >= cap) break;
				let text: string | null = null;
				let strong = false;
				if (down && outage && s.org_id === "thirdrail" && hash(s.i, k, 3) < 0.5) {
					text = outage.shout;
					strong = true;
				} else if (down && s.org_id === "tallybird" && !escalated) {
					text = "on it · escalating";
					strong = true;
					escalated = true;
				} else if (hash(s.i, k, 1) < Math.min(0.8, (s.talk / 100) * 1.6)) {
					const r = hash(s.i, k, 2);
					let acc = 0;
					text = "other";
					for (const [n, p] of data.topics) {
						acc += p;
						if (r < acc) {
							text = n;
							break;
						}
					}
					if (down && r < 0.6) text = "the outage";
				}
				if (text) {
					bubble(sx, sy, text, strong);
					shown++;
				}
			}
		}
		const time = document.createElement("b");
		time.textContent = hhmm(Math.min(tNow, TICKS));
		els.clock.replaceChildren(time, ` · ${data.day}`);
		els.note.textContent =
			tNow >= TICKS
				? "offices close · night skipped"
				: down && outage
					? `${outage.name} outage · raised in the cafe`
					: hour >= 12 && hour < 14
						? "lunch rush"
						: "an average weekday";
		els.scrub.value = String(tNow);
	}

	let last = 0;
	let visible = true;
	let raf = 0;
	function loop(ts: number) {
		raf = 0;
		if (!visible || document.hidden) return;
		const dt = Math.min(0.1, (ts - (last || ts)) / 1000);
		last = ts;
		if (playing) {
			if (tNow >= TICKS) {
				hold += dt;
				if (hold > 1.8) {
					hold = 0;
					tNow = 0;
				}
			} else tNow = Math.min(TICKS, tNow + dt / 1.35);
		}
		frame();
		if (playing) raf = requestAnimationFrame(loop);
	}
	function kick() {
		if (!raf && playing && visible && !document.hidden) {
			last = 0;
			raf = requestAnimationFrame(loop);
		}
	}
	function resize() {
		const parent = cv.parentElement;
		const nw = parent?.clientWidth ?? 0;
		if (!nw) return;
		W = nw;
		tw = W / (W < 560 ? 30 : 33.5);
		th = tw / 2;
		hz = th * 1.15;
		const top = Math.max(W < 560 ? 44 : 58, 2.6 * hz + 26); // room for the HUD chips and the tallest walls
		H = Math.round(top + 17 * tw + 0.9 * hz + 14); // the whole diorama, soil edge included
		dpr = Math.min(2, devicePixelRatio || 1);
		cv.width = Math.round(W * dpr);
		cv.height = Math.round(H * dpr);
		cv.style.height = `${H}px`;
		ox = W / 2 - 3 * tw;
		oy = top;
		paintGround();
		frame();
	}
	function setPlaying(v: boolean) {
		playing = v;
		els.play.textContent = v ? "❚❚" : "▶";
		els.play.setAttribute("aria-label", v ? "Pause the replay" : "Play the replay");
		if (v && tNow >= TICKS) tNow = 0;
		kick();
	}

	const ro = new ResizeObserver(resize);
	if (cv.parentElement) ro.observe(cv.parentElement);
	const io = new IntersectionObserver((es) => {
		visible = es[0]?.isIntersecting ?? true;
		kick();
	});
	io.observe(cv);
	document.addEventListener("visibilitychange", kick);
	const onPlay = () => setPlaying(!playing);
	els.play.addEventListener("click", onPlay);
	const onScrub = () => {
		setPlaying(false);
		tNow = +els.scrub.value;
		hold = 0;
		frame();
	};
	els.scrub.addEventListener("input", onScrub);
	// Open on the lunch rush, the town's busiest frame, then start the day unless motion is unwelcome.
	const autoplay = reduce
		? 0
		: window.setTimeout(() => {
				if (!playing && tNow === 16.3) setPlaying(true);
			}, 2500);

	const hitBuilding = (mx: number, my: number) =>
		blds.find((b) => b.hit && mx >= b.hit[0] && mx <= b.hit[0] + b.hit[2] && my >= b.hit[1] && my <= b.hit[1] + b.hit[3]);
	const onMove = (e: PointerEvent) => {
		const r = cv.getBoundingClientRect();
		const mx = e.clientX - r.left;
		const my = e.clientY - r.top;
		let best: (typeof screenPeople)[number] | null = null;
		let bd = 16;
		for (const o of screenPeople) {
			const dd = Math.hypot(o.sx - mx, o.sy + tw * 0.35 - my);
			if (dd < bd) {
				bd = dd;
				best = o;
			}
		}
		cv.style.cursor = "default";
		if (best) {
			const s = best.s;
			const b = BLD.find((x) => x.org === s.org_id);
			on.tip(r.left + scrollX + best.sx, r.top + scrollY + best.sy, {
				kind: "person",
				name: s.name,
				role: s.role.replace(/_/g, " "),
				org: b?.name ?? s.org_id,
				stats: data.people[s.id] ?? null,
			});
			return;
		}
		const b = hitBuilding(mx, my);
		if (b?.hit) {
			cv.style.cursor = "pointer";
			on.tip(r.left + scrollX + b.hit[0] + b.hit[2] / 2, r.top + scrollY + b.hit[1], {
				kind: "building",
				name: b.name,
				cash: cashOf(b.org),
				cashLabel: data.cashLabel,
				note: data.buildings[b.org]?.note,
			});
			return;
		}
		on.hideTip();
	};
	const onLeave = () => on.hideTip();
	const onClick = (e: MouseEvent) => {
		const r = cv.getBoundingClientRect();
		const b = hitBuilding(e.clientX - r.left, e.clientY - r.top);
		if (b) on.open(b.org);
	};
	cv.addEventListener("pointermove", onMove);
	cv.addEventListener("pointerleave", onLeave);
	cv.addEventListener("click", onClick);
	resize();
	if (document.fonts) void document.fonts.ready.then(frame);

	return () => {
		ro.disconnect();
		io.disconnect();
		document.removeEventListener("visibilitychange", kick);
		els.play.removeEventListener("click", onPlay);
		els.scrub.removeEventListener("input", onScrub);
		cv.removeEventListener("pointermove", onMove);
		cv.removeEventListener("pointerleave", onLeave);
		cv.removeEventListener("click", onClick);
		window.clearTimeout(autoplay);
		if (raf) cancelAnimationFrame(raf);
		playing = false;
		on.hideTip();
	};
}
