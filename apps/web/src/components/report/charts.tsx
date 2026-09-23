"use client";

/**
 * The report's four chart forms, as React over SVG.
 *
 * Ported from the first field report's hand-rolled charts rather than swapped
 * for a charting library: the look *is* those charts — end labels instead of a
 * legend box, annotations drawn as the town's own speech bubbles, a crosshair
 * that reads every series at once — and none of it needs more than a path and
 * a scale. The viewBox is the element's own width, so text is drawn at true
 * size at any width instead of being scaled down with the chart.
 *
 * Colours are CSS variable names (`--tb`, `--mark`) and are painted through
 * `var()`, so the palette in report.css stays the only place a colour is set.
 */
import {
	type ReactNode,
	type RefObject,
	useId,
	useLayoutEffect,
	useRef,
	useState,
} from "react";
import { useTip } from "./tip";

/** JetBrains Mono's advance at 11.5px: enough to size a margin to its labels. */
const CW = 6.95;
export const MONO = '"JetBrains Mono", ui-monospace, monospace';
const paint = (token: string) => ({ fill: `var(${token})` });
const ink = (token: string) => ({ stroke: `var(${token})` });

export function niceTicks(max: number, n = 4): number[] {
	const safe = max > 0 ? max : 1;
	const raw = safe / n;
	const p = 10 ** Math.floor(Math.log10(raw));
	const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? p * 10;
	const out: number[] = [];
	for (let v = 0; v <= safe + 1e-9; v += step) out.push(+v.toFixed(10));
	const last = out[out.length - 1] ?? 0;
	if (last < safe) out.push(last + step);
	return out;
}

/** The element's width, kept current. Zero until it has been laid out. */
function useWidth(): [RefObject<HTMLDivElement | null>, number] {
	const ref = useRef<HTMLDivElement>(null);
	const [width, setWidth] = useState(0);
	useLayoutEffect(() => {
		const el = ref.current;
		if (el === null) return;
		const measure = () => setWidth(el.clientWidth);
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(el);
		return () => observer.disconnect();
	}, []);
	return [ref, width];
}

/** The sim's speech bubble, as a chart annotation. */
function Bubble({ W, x, y, text }: { W: number; x: number; y: number; text: string }) {
	const w = text.length * 6.7 + 18;
	const h = 21;
	const bx = Math.max(2, Math.min(W - w - 2, x - w / 2));
	const by = y - h - 10;
	return (
		<g>
			<rect x={bx + 2} y={by + 2} width={w} height={h} rx={10.5} fill="#000" opacity={0.3} />
			<rect x={bx} y={by} width={w} height={h} rx={10.5} style={paint("--bubble")} />
			<path d={`M${x - 4} ${by + h - 0.5}L${x + 4} ${by + h - 0.5}L${x} ${by + h + 6}Z`} style={paint("--bubble")} />
			<text
				x={bx + w / 2}
				y={by + 14.5}
				textAnchor="middle"
				fontSize="11"
				fontWeight="700"
				fontFamily={MONO}
				style={paint("--bubble-ink")}
			>
				{text}
			</text>
		</g>
	);
}

/** A legend swatch, for tooltips and legends alike. */
export function Dot({ color }: { color: string }) {
	return <i className="dot" style={{ background: `var(${color})` }} />;
}

export type Series = {
	name: string;
	color: string;
	values: number[];
	hidden?: boolean;
};

type LineProps = {
	series: Series[];
	xs: number[];
	yfmt: (v: number, forTip?: boolean) => string;
	xfmt: (x: number, forTip?: boolean) => string;
	aria: string;
	yMin?: number;
	yTicks?: number[];
	area?: boolean;
	h?: number;
	ml?: number;
	mt?: number;
	endLabels?: boolean;
	vlines?: number[];
	notes?: { i: number; v: number; text: string }[];
};

export function LineChart(o: LineProps) {
	const [host, width] = useWidth();
	const tip = useTip();
	const [hover, setHover] = useState<number | null>(null);
	const W = Math.max(300, width);
	const h = o.h ?? 280;
	const vis = o.series.filter((s) => !s.hidden);
	const endW = o.endLabels ? Math.max(...o.series.map((s) => s.name.length)) * CW + 24 : 16;
	const m = { l: o.ml ?? 50, r: endW, t: o.mt ?? 36, b: 26 };
	const iw = W - m.l - m.r;
	const ih = h - m.t - m.b;
	const yMin = o.yMin ?? 0;
	const ticks = o.yTicks ?? niceTicks(Math.max(1, ...vis.flatMap((s) => s.values)));
	const top = ticks[ticks.length - 1] ?? 1;
	const span = Math.max(1, o.xs.length - 1);
	const X = (i: number) => m.l + iw * (i / span);
	const Y = (v: number) => m.t + ih * (1 - (v - yMin) / (top - yMin));
	const at = (s: Series, i: number) => s.values[i] ?? 0;
	const last = o.xs.length - 1;

	const paths = vis.map((s) =>
		s.values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(""),
	);

	const ends = o.endLabels
		? vis.map((s) => ({ s, y: Y(at(s, s.values.length - 1)) })).sort((a, b) => a.y - b.y)
		: [];
	for (let i = 1; i < ends.length; i++) {
		const prev = ends[i - 1];
		const cur = ends[i];
		if (prev && cur && cur.y - prev.y < 15) cur.y = prev.y + 15;
	}
	const xLabels = [...new Set([0, 0.2, 0.4, 0.6, 0.8, 1].map((fr) => Math.round(fr * last)))];

	const move = (ev: React.PointerEvent<SVGRectElement>) => {
		const svg = ev.currentTarget.ownerSVGElement;
		if (!svg || !host.current) return;
		const r = svg.getBoundingClientRect();
		const sc = r.width / W;
		const px = (ev.clientX - r.left) / sc;
		const i = Math.max(0, Math.min(last, Math.round(((px - m.l) / iw) * span)));
		setHover(i);
		const rows = vis
			.slice()
			.sort((a, b) => at(b, i) - at(a, i))
			.map((s) => (
				<div className="r" key={s.name}>
					<span>
						<Dot color={s.color} /> {s.name}
					</span>
					<b>{o.yfmt(at(s, i), true)}</b>
				</div>
			));
		const y = Math.min(...vis.map((s) => Y(at(s, i))));
		tip.showIn(host.current, X(i) * sc, y * sc, (
			<>
				<b>{o.xfmt(o.xs[i] ?? i, true)}</b>
				{rows}
			</>
		));
	};

	return (
		<div className="chart" ref={host}>
			{width > 0 && (
				<svg viewBox={`0 0 ${W} ${h}`} role="img" aria-label={o.aria}>
					<g className="gridl">
						{ticks.map((t) => (
							<line key={t} x1={m.l} x2={W - m.r + 4} y1={Y(t)} y2={Y(t)} />
						))}
					</g>
					<g className="axis">
						{ticks.map((t) => (
							<text key={t} x={m.l - 8} y={Y(t) + 4} textAnchor="end">
								{o.yfmt(t)}
							</text>
						))}
						{xLabels.map((i) => (
							<text
								key={i}
								x={X(i)}
								y={h - 6}
								textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"}
							>
								{o.xfmt(o.xs[i] ?? i)}
							</text>
						))}
					</g>
					{(o.vlines ?? []).map((i) => (
						<line key={i} x1={X(i)} x2={X(i)} y1={m.t - 4} y2={m.t + ih} strokeDasharray="3 4" style={ink("--dim")} />
					))}
					{vis.map((s, k) => {
						const d = paths[k] ?? "";
						return (
							<g key={s.name}>
								{o.area && (
									<path
										d={`${d}L${X(s.values.length - 1)} ${Y(yMin)}L${X(0)} ${Y(yMin)}Z`}
										opacity={0.12}
										style={paint(s.color)}
									/>
								)}
								<path d={d} fill="none" strokeWidth={2} strokeLinejoin="round" style={ink(s.color)} />
								<circle
									cx={X(s.values.length - 1)}
									cy={Y(at(s, s.values.length - 1))}
									r={4}
									strokeWidth={2}
									style={{ fill: `var(${s.color})`, stroke: "var(--panel)" }}
								/>
							</g>
						);
					})}
					{ends.map((e) => (
						<text key={e.s.name} x={W - m.r + 10} y={e.y + 4} fontSize="11.5" fontFamily={MONO} style={paint("--text")}>
							{e.s.name}
						</text>
					))}
					{(o.notes ?? []).map((n) => (
						<Bubble key={n.text} W={W - m.r + 8} x={X(n.i)} y={Y(n.v)} text={n.text} />
					))}
					{hover !== null && (
						<g pointerEvents="none">
							<line x1={X(hover)} x2={X(hover)} y1={m.t} y2={m.t + ih} opacity={0.6} style={ink("--muted-foreground")} />
							{vis.map((s) => (
								<circle
									key={s.name}
									cx={X(hover)}
									cy={Y(at(s, hover))}
									r={4.5}
									strokeWidth={2}
									style={{ fill: `var(${s.color})`, stroke: "var(--panel)" }}
								/>
							))}
						</g>
					)}
					<rect
						x={m.l}
						y={m.t}
						width={Math.max(0, iw)}
						height={Math.max(0, ih)}
						fill="transparent"
						onPointerMove={move}
						onPointerLeave={() => {
							setHover(null);
							tip.hide();
						}}
					/>
				</svg>
			)}
		</div>
	);
}

type ColProps = {
	cats: string[];
	values: number[];
	yfmt: (v: number) => string;
	tipf: (i: number) => ReactNode;
	aria: string;
	color?: string;
	colors?: string[];
	ticks?: number[];
	h?: number;
	mt?: number;
	valLabels?: string[];
	/** An obligation, not an entity: hatched so it can't be mistaken for a firm's colour. */
	hatch?: number;
	notes?: { i: number; text: string }[];
};

export function ColChart(o: ColProps) {
	const [host, width] = useWidth();
	const tip = useTip();
	const hatchId = useId().replace(/:/g, "");
	const W = Math.max(280, width);
	const h = o.h ?? 230;
	const m = { l: 46, r: 6, t: o.mt ?? 34, b: 24 };
	const iw = W - m.l - m.r;
	const ih = h - m.t - m.b;
	const ticks = o.ticks ?? niceTicks(Math.max(0, ...o.values));
	const top = ticks[ticks.length - 1] ?? 1;
	const Y = (v: number) => m.t + ih * (1 - v / top);
	const bw = iw / Math.max(1, o.cats.length);
	const gap = Math.max(3, bw * 0.24);
	const colour = (i: number) => o.colors?.[i] ?? o.color ?? "--mark";

	return (
		<div className="chart" ref={host}>
			{width > 0 && (
				<svg viewBox={`0 0 ${W} ${h}`} role="img" aria-label={o.aria}>
					<g className="gridl">
						{ticks.map((t) => (
							<line key={t} x1={m.l} x2={W - m.r} y1={Y(t)} y2={Y(t)} />
						))}
					</g>
					<g className="axis">
						{ticks.map((t) => (
							<text key={t} x={m.l - 8} y={Y(t) + 4} textAnchor="end">
								{o.yfmt(t)}
							</text>
						))}
						{o.cats.map((cat, i) =>
							bw > 26 || i % 2 === 0 ? (
								<text key={cat} x={m.l + i * bw + bw / 2} y={h - 6} textAnchor="middle">
									{cat}
								</text>
							) : null,
						)}
					</g>
					{o.hatch !== undefined && (
						<defs>
							<pattern id={hatchId} width={7} height={7} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
								<rect width={7} height={7} opacity={0.14} style={paint(colour(o.hatch))} />
								<line x1={0} y1={0} x2={0} y2={7} strokeWidth={2.4} style={ink(colour(o.hatch))} />
							</pattern>
						</defs>
					)}
					{o.cats.map((cat, i) => {
						const v = o.values[i] ?? 0;
						const x = m.l + i * bw + gap / 2;
						const w = bw - gap;
						const y = Y(v);
						const hh = m.t + ih - y;
						const r = Math.min(4, hh, w / 2);
						const d = `M${x} ${m.t + ih}V${y + r}a${r} ${r} 0 0 1 ${r} ${-r}H${x + w - r}a${r} ${r} 0 0 1 ${r} ${r}V${m.t + ih}Z`;
						return (
							<g key={cat}>
								{hh > 0.5 &&
									(o.hatch === i ? (
										<path d={d} fill={`url(#${hatchId})`} strokeWidth={1.5} style={ink(colour(i))} />
									) : (
										<path d={d} style={paint(colour(i))} />
									))}
								{o.valLabels && (
									<text
										x={x + w / 2}
										y={y - 8}
										textAnchor="middle"
										fontSize="12"
										fontWeight="700"
										fontFamily={MONO}
										style={paint("--text")}
									>
										{o.valLabels[i]}
									</text>
								)}
								<rect
									x={m.l + i * bw}
									y={m.t}
									width={bw}
									height={ih}
									fill="transparent"
									onPointerMove={(ev) => {
										const R = ev.currentTarget.ownerSVGElement?.getBoundingClientRect();
										if (!R || !host.current) return;
										const sc = R.width / W;
										tip.showIn(host.current, (x + w / 2) * sc, y * sc, o.tipf(i));
									}}
									onPointerLeave={tip.hide}
								/>
							</g>
						);
					})}
					<line x1={m.l} x2={W - m.r} y1={m.t + ih} y2={m.t + ih} style={ink("--dim")} />
					{(o.notes ?? []).map((n) => (
						<Bubble key={n.text} W={W} x={m.l + (n.i + 0.5) * bw} y={Y(o.values[n.i] ?? 0)} text={n.text} />
					))}
				</svg>
			)}
		</div>
	);
}

type BarProps = {
	cats: string[];
	values: number[];
	fmt: (v: number) => string;
	tipf: (i: number) => ReactNode;
	aria: string;
	color?: string;
	colors?: string[];
	max?: number;
	rowH?: number;
};

/** Horizontal bars; the margins are measured from the labels so nothing spills. */
export function BarChart(o: BarProps) {
	const [host, width] = useWidth();
	const tip = useTip();
	const W = Math.max(280, width);
	const rowH = o.rowH ?? 30;
	const vals = o.values.map(o.fmt);
	const m = {
		l: Math.min(W * 0.46, Math.max(0, ...o.cats.map((c) => c.length)) * CW + 16),
		r: Math.max(0, ...vals.map((v) => v.length)) * CW + 14,
		t: 2,
		b: 2,
	};
	const H = m.t + m.b + rowH * o.cats.length;
	const iw = W - m.l - m.r;
	const max = o.max ?? Math.max(1e-9, ...o.values);

	return (
		<div className="chart" ref={host}>
			{width > 0 && (
				<svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={o.aria}>
					{o.cats.map((c, i) => {
						const y = m.t + i * rowH;
						const w = Math.max(3, (iw * (o.values[i] ?? 0)) / max);
						const bh = rowH - 12;
						const r = Math.min(4, w / 2);
						return (
							<g key={c}>
								<text
									x={m.l - 10}
									y={y + rowH / 2 + 4}
									textAnchor="end"
									fontSize="11.5"
									fontFamily={MONO}
									style={paint("--muted-foreground")}
								>
									{c}
								</text>
								<rect x={m.l} y={y + 6} width={Math.max(0, iw)} height={bh} rx={3} style={paint("--raise")} />
								<path
									d={`M${m.l} ${y + 6}H${m.l + w - r}a${r} ${r} 0 0 1 ${r} ${r}V${y + 6 + bh - r}a${r} ${r} 0 0 1 ${-r} ${r}H${m.l}Z`}
									style={paint(o.colors?.[i] ?? o.color ?? "--mark")}
								/>
								<text
									x={m.l + iw + 8}
									y={y + rowH / 2 + 4}
									fontSize="11.5"
									fontWeight="700"
									fontFamily={MONO}
									style={paint("--text")}
								>
									{vals[i]}
								</text>
								<rect
									x={0}
									y={y}
									width={W}
									height={rowH}
									fill="transparent"
									onPointerMove={(ev) => {
										const R = ev.currentTarget.ownerSVGElement?.getBoundingClientRect();
										if (!R || !host.current) return;
										const sc = R.width / W;
										tip.showIn(host.current, (m.l + w / 2) * sc, (y + 4) * sc, o.tipf(i));
									}}
									onPointerLeave={tip.hide}
								/>
							</g>
						);
					})}
				</svg>
			)}
		</div>
	);
}

export type DumbbellRow = { name: string; esc: number | null; not: number | null };

/** Two values per row on one axis: outage length escalated (violet) and not. */
export function Dumbbell({
	rows,
	tipf,
	ticks: given,
	max: givenMax,
}: {
	rows: DumbbellRow[];
	tipf: (i: number) => ReactNode;
	ticks?: number[];
	max?: number;
}) {
	const [host, width] = useWidth();
	const tip = useTip();
	const W = Math.max(280, width);
	const rowH = 54;
	const m = { l: 92, r: 22, t: 10, b: 26 };
	const H = m.t + m.b + rowH * rows.length;
	const iw = W - m.l - m.r;
	const ticks = given ?? niceTicks(Math.max(1, ...rows.flatMap((r) => [r.esc ?? 0, r.not ?? 0])));
	const top = ticks[ticks.length - 1] ?? 1;
	const max = givenMax ?? top + ((ticks[1] ?? top) - (ticks[0] ?? 0)) / 3;
	const X = (v: number) => m.l + (iw * v) / max;

	return (
		<div className="chart" ref={host}>
			{width > 0 && (
				<svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Mean outage length by module, escalated versus not">
					<g className="gridl">
						{ticks.map((t) => (
							<line key={t} x1={X(t)} x2={X(t)} y1={m.t} y2={H - m.b} />
						))}
					</g>
					<g className="axis">
						{ticks.map((t) => (
							<text key={t} x={X(t)} y={H - 6} textAnchor="middle">
								{t}
							</text>
						))}
					</g>
					{rows.map((r, i) => {
						const y = m.t + i * rowH + rowH / 2 + 6;
						const mid = X(((r.esc ?? r.not ?? 0) + (r.not ?? r.esc ?? 0)) / 2);
						return (
							<g key={r.name}>
								<text x={m.l - 14} y={y + 4} textAnchor="end" fontSize="12" fontFamily={MONO} style={paint("--text")}>
									{r.name}
								</text>
								{r.esc !== null && r.not !== null && (
									<line x1={X(r.esc)} x2={X(r.not)} y1={y} y2={y} strokeWidth={2} style={ink("--dim")} />
								)}
								{r.not !== null && (
									<>
										<circle cx={X(r.not)} cy={y} r={6.5} strokeWidth={2} style={{ fill: "var(--dim)", stroke: "var(--panel)" }} />
										<text x={X(r.not)} y={y - 13} textAnchor="middle" fontSize="11.5" fontFamily={MONO} style={paint("--muted-foreground")}>
											{r.not}
										</text>
									</>
								)}
								{r.esc !== null && (
									<>
										<circle cx={X(r.esc)} cy={y} r={6.5} strokeWidth={2} style={{ fill: "var(--mark)", stroke: "var(--panel)" }} />
										<text
											x={X(r.esc)}
											y={y - 13}
											textAnchor="middle"
											fontSize="11.5"
											fontWeight="700"
											fontFamily={MONO}
											style={paint("--mark")}
										>
											{r.esc}
										</text>
									</>
								)}
								<rect
									x={0}
									y={y - rowH / 2}
									width={W}
									height={rowH}
									fill="transparent"
									onPointerMove={(ev) => {
										const R = ev.currentTarget.ownerSVGElement?.getBoundingClientRect();
										if (!R || !host.current) return;
										const sc = R.width / W;
										tip.showIn(host.current, mid * sc, (y - 14) * sc, tipf(i));
									}}
									onPointerLeave={tip.hide}
								/>
							</g>
						);
					})}
				</svg>
			)}
		</div>
	);
}
