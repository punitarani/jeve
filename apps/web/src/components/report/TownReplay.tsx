"use client";

import { type ReactNode, useEffect, useRef } from "react";
import { Dot } from "./charts";
import { TipRow, useTip } from "./tip";
import { mountTown, TICKS, type TownData, type TownTip } from "./town";

const LEGEND: [string, string][] = [
	["--tb", "Tallybird"],
	["--hp", "Halloran & Pike"],
	["--ll", "Ledgerline"],
	["--tr", "Third Rail"],
];

function tipBody(t: TownTip): ReactNode {
	if (t.kind === "person") {
		return (
			<>
				<b>{t.name}</b>{" "}
				<span className="m">
					{t.role}, {t.org}
				</span>
				{t.stats && (
					<>
						<TipRow label="ticks at the cafe">{t.stats.cafe.toFixed(1)}%</TipRow>
						<TipRow label="stops to talk">{t.stats.talk.toFixed(1)}%</TipRow>
						<TipRow label="mean mood">{t.stats.mood.toFixed(2)} / 3</TipRow>
					</>
				)}
			</>
		);
	}
	return (
		<>
			<b>{t.name}</b>
			<TipRow label={t.cashLabel}>${Math.round(t.cash).toLocaleString("en-US")}</TipRow>
			{t.note && (
				<div className="r">
					<span className="m">status</span>
					<b className="bad">{t.note}</b>
				</div>
			)}
			<div className="m">click for the books ↓</div>
		</>
	);
}

/**
 * The town, replaying an average weekday from `data`'s rates. Clicking a
 * building scrolls to `booksId`, where its cash is charted.
 */
export function TownReplay({
	data,
	clock,
	booksId,
	children,
}: {
	data: TownData;
	/** The HUD's opening clock, before the first frame paints. */
	clock: string;
	booksId: string;
	/** The caption under the town. */
	children: ReactNode;
}) {
	const canvas = useRef<HTMLCanvasElement>(null);
	const clockEl = useRef<HTMLSpanElement>(null);
	const note = useRef<HTMLSpanElement>(null);
	const scrub = useRef<HTMLInputElement>(null);
	const play = useRef<HTMLButtonElement>(null);
	const tip = useTip();

	useEffect(() => {
		if (!canvas.current || !clockEl.current || !note.current || !scrub.current || !play.current) return;
		return mountTown(
			{ canvas: canvas.current, clock: clockEl.current, note: note.current, scrub: scrub.current, play: play.current },
			data,
			{
				tip: (x, y, t) => tip.show(x, y, tipBody(t)),
				hideTip: tip.hide,
				open: () => {
					const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
					document.getElementById(booksId)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
				},
			},
		);
	}, [data, tip, booksId]);

	return (
		<>
			<div className="town" data-testid="town">
				<canvas
					ref={canvas}
					role="img"
					aria-label="Isometric view of jeve's town: four firms around a plaza, with staff walking to the cafe as the day plays out"
				/>
				<div className="hud">
					<span className="chip" ref={clockEl}>
						<b>13:00</b> · {clock}
					</span>
					<span className="chip" ref={note}>
						an average weekday
					</span>
				</div>
			</div>
			<div className="town-bar">
				<button ref={play} type="button" aria-label="Play the replay">
					▶
				</button>
				<input
					ref={scrub}
					type="range"
					min={0}
					max={TICKS}
					step={0.25}
					defaultValue={16}
					aria-label="Time of day, 09:00 to 17:00"
				/>
				<div className="town-leg">
					{LEGEND.map(([color, name]) => (
						<span key={name}>
							<Dot color={color} />
							{name}
						</span>
					))}
					<span>
						<i className="dot dot-crowd" />
						customers
					</span>
				</div>
			</div>
			<p className="cap">{children}</p>
		</>
	);
}
