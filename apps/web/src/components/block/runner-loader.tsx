"use client";

/**
 * The world-loading state: a jeve person running laps on a pocket diorama.
 *
 * Drawn in the same isometric projection and the same stacked-box figure as
 * the town replay (report/town.ts), so the loader is the world in miniature —
 * and imperative for the same reason: a frame is a full repaint.
 */
import { useEffect, useRef } from "react";

const TAU = Math.PI * 2;
const LAP_S = 2.1; // seconds a lap
const STEPS = 8; // footfalls a lap — a jog, not a sprint

type Puff = { x: number; y: number; born: number };

const hx = (h: string) => [
	parseInt(h.slice(1, 3), 16),
	parseInt(h.slice(3, 5), 16),
	parseInt(h.slice(5, 7), 16),
];
const shade = (c: string, f: number) =>
	`#${hx(c)
		.map((v) => Math.max(0, Math.min(255, Math.round(v * f))).toString(16).padStart(2, "0"))
		.join("")}`;

function mount(cv: HTMLCanvasElement, size: number): () => void {
	const ctx = cv.getContext("2d");
	if (ctx === null) return () => {};
	const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
	const dpr = Math.min(2, devicePixelRatio || 1);
	cv.width = Math.round(size * dpr);
	cv.height = Math.round(size * dpr);

	// town.ts's projection, scaled so the diorama fills `size`.
	const tw = size / 4.1;
	const th = tw / 2;
	const hz = th * 1.15;
	const ox = size / 2;
	const oy = size * 0.56;
	const P = (x: number, y: number, z: number): [number, number] => [
		ox + ((x - y) * tw) / 2,
		oy + ((x + y) * th) / 2 - z * hz,
	];
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
	const ell = (x: number, y: number, rx: number, ry: number, fill: string) => {
		ctx!.beginPath();
		ctx!.ellipse(x, y, rx, ry, 0, 0, TAU);
		ctx!.fillStyle = fill;
		ctx!.fill();
	};

	// Colours: the plaza stone and soil of the town's diorama slice; the runner
	// wears the accent, as the loaders before it ramped to --mark.
	const STONE = "#cfc6b2";
	const SOIL = "#56422c";
	const TRACK = "#9b917c";
	const BODY = "#a78bfa";
	const TROU = "#2f3542";
	const SKIN = "#f1c9a5";
	const HAIR = "#2b1d14";

	const R_DISC = 2.0; // tiles
	const R_TRACK = 1.35;
	const K = 1.9; // a touch over town.ts's toy scale — one runner, no crowd

	const discRx = R_DISC * tw * 0.707;
	const discRy = discRx / 2;
	const trackRx = R_TRACK * tw * 0.707;
	const trackRy = trackRx / 2;

	const puffs: Puff[] = [];
	let raf = 0;
	let t0 = -1;
	let lastFoot = 0;

	function frame(ts: number) {
		raf = 0;
		if (t0 < 0) t0 = ts;
		const t = (ts - t0) / 1000;
		const u = reduce ? Math.PI * 0.3 : (t / LAP_S) * TAU; // counter-clockwise laps
		const stepPhase = u * (STEPS / 2);

		// The runner on the track, with the tangent its forward and the outward
		// normal its left/right — a figure axis-aligned like the town's, but
		// leaning and scissoring along the way it actually runs.
		const px = R_TRACK * Math.cos(u);
		const py = R_TRACK * Math.sin(u);
		const tx = -Math.sin(u);
		const ty = Math.cos(u);
		const nx = Math.cos(u);
		const ny = Math.sin(u);
		const s = Math.sin(stepPhase);
		const bob = Math.abs(s) * 0.08 * K;
		const lean = 0.14 * K;
		const swing = 0.26;

		// A puff per footfall, just behind the runner.
		const foot = Math.floor(stepPhase / Math.PI);
		if (!reduce && foot !== lastFoot) {
			lastFoot = foot;
			puffs.push({ x: px - tx * 0.3, y: py - ty * 0.3, born: t });
			if (puffs.length > 7) puffs.shift();
		}
		while (puffs.length && t - puffs[0]!.born > 0.6) puffs.shift();

		ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx!.clearRect(0, 0, size, size);

		// The diorama: a soil edge, a stone disc, the dashed lap it runs.
		ell(ox, oy + hz * 0.5, discRx, discRy, SOIL);
		ell(ox, oy + hz * 0.22, discRx, discRy, "#6a5238");
		ell(ox, oy, discRx, discRy, STONE);
		ctx!.save();
		ctx!.beginPath();
		ctx!.ellipse(ox, oy, trackRx, trackRy, 0, 0, TAU);
		ctx!.strokeStyle = TRACK;
		ctx!.lineWidth = Math.max(1.5, tw * 0.05);
		ctx!.setLineDash([tw * 0.2, tw * 0.16]);
		ctx!.stroke();
		ctx!.restore();

		// Dust, then the shadow, then the figure — ground order.
		for (const p of puffs) {
			const age = (t - p.born) / 0.6;
			const [sx, sy] = P(p.x, p.y, 0.05 + age * 0.2);
			ctx!.globalAlpha = 0.5 * (1 - age);
			ell(sx, sy, tw * (0.07 + age * 0.15), th * (0.07 + age * 0.15), "#9a8f76");
		}
		ctx!.globalAlpha = 1;
		{
			const [sx, sy] = P(px, py, 0);
			ctx!.globalAlpha = 0.28;
			ell(sx, sy, tw * 0.3 * K, th * 0.3 * K, "#1a140d");
			ctx!.globalAlpha = 1;
		}

		// Legs: one planted, one swinging, alternating with the stride — the
		// shoe on each foot is what makes the scissor read at this size.
		for (const side of [1, -1]) {
			const ph = s * side;
			const lift = Math.max(0, ph) * 0.16 * K;
			const cx = px + tx * ph * swing + nx * side * 0.08 * K;
			const cy = py + ty * ph * swing + ny * side * 0.08 * K;
			cbox(cx, cy, lift, 0.14 * K, 0.2 * K, 0.34 * K - lift, TROU);
			cbox(cx + tx * 0.03 * K, cy + ty * 0.03 * K, lift, 0.16 * K, 0.24 * K, 0.07 * K, "#1d212b");
		}
		// Arms counter the same-side leg; torso, head, hair ride the lean.
		for (const side of [1, -1]) {
			const ph = -s * side;
			cbox(
				px + tx * (lean * 0.7 + ph * swing) + nx * side * 0.26 * K,
				py + ty * (lean * 0.7 + ph * swing) + ny * side * 0.26 * K,
				bob + 0.42 * K,
				0.11 * K,
				0.11 * K,
				0.24 * K,
				shade(BODY, 0.85),
			);
		}
		const bx = px + tx * lean;
		const by = py + ty * lean;
		cbox(bx, by, bob + 0.34 * K, 0.36 * K, 0.24 * K, 0.36 * K, BODY);
		cbox(bx + tx * 0.12 * K, by + ty * 0.12 * K, bob + 0.7 * K, 0.26 * K, 0.26 * K, 0.26 * K, SKIN);
		cbox(bx + tx * 0.12 * K, by + ty * 0.12 * K, bob + 0.96 * K, 0.28 * K, 0.28 * K, 0.07 * K, HAIR);

		if (!reduce) raf = requestAnimationFrame(frame);
	}

	raf = requestAnimationFrame(frame);
	return () => {
		if (raf) cancelAnimationFrame(raf);
	};
}

export function RunnerLoader({ size = 112 }: { size?: number }) {
	const ref = useRef<HTMLCanvasElement>(null);

	useEffect(() => {
		if (!ref.current) return;
		return mount(ref.current, size);
	}, [size]);

	return (
		<canvas
			ref={ref}
			role="img"
			aria-label="A person running laps on a small plaza while the world loads"
			style={{ width: size, height: size }}
		/>
	);
}
