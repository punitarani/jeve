"use client";

/**
 * One tooltip for a whole report page.
 *
 * Every chart, table and the town share it, as the artifact's single `#tip`
 * did: a pointer can only be in one place, so one element with page
 * coordinates is simpler than a portal per mark. Only the provider re-renders
 * on a move — the context value is stable, so the charts that call `show` do
 * not.
 */
import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";

type Tip = {
	/** Page coordinates: the tip's bottom-centre sits just above this point. */
	show: (pageX: number, pageY: number, body: ReactNode) => void;
	/** `host`-relative coordinates, for marks drawn inside an element. */
	showIn: (host: Element, x: number, y: number, body: ReactNode) => void;
	hide: () => void;
};

const TipContext = createContext<Tip | null>(null);

type Shown = { x: number; y: number; body: ReactNode } | null;

export function TipProvider({ children }: { children: ReactNode }) {
	const [shown, setShown] = useState<Shown>(null);
	const [nudge, setNudge] = useState(0);
	const el = useRef<HTMLDivElement>(null);

	const show = useCallback((x: number, y: number, body: ReactNode) => {
		setNudge(0);
		setShown({ x, y, body });
	}, []);
	const tip = useMemo<Tip>(
		() => ({
			show,
			showIn: (host, x, y, body) => {
				const r = host.getBoundingClientRect();
				show(r.left + scrollX + x, r.top + scrollY + y, body);
			},
			hide: () => setShown(null),
		}),
		[show],
	);

	// Keep the tip on screen: measured after it renders at the raw position,
	// then shifted by however far it overhangs either edge.
	useLayoutEffect(() => {
		if (shown === null || el.current === null || nudge !== 0) return;
		const r = el.current.getBoundingClientRect();
		const pad = 8;
		if (r.left < pad) setNudge(pad - r.left);
		else if (r.right > innerWidth - pad) setNudge(innerWidth - pad - r.right);
	}, [shown, nudge]);

	return (
		<TipContext.Provider value={tip}>
			{children}
			<div
				ref={el}
				className="tip"
				role="tooltip"
				style={
					shown === null
						? undefined
						: { left: shown.x + nudge, top: shown.y, opacity: 1 }
				}
			>
				{shown?.body}
			</div>
		</TipContext.Provider>
	);
}

export function useTip(): Tip {
	const tip = useContext(TipContext);
	if (tip === null) throw new Error("useTip outside a TipProvider");
	return tip;
}

/** A tooltip row: a muted label on the left, a bold value on the right. */
export function TipRow({ label, children }: { label: ReactNode; children: ReactNode }) {
	return (
		<div className="r">
			<span className="m">{label}</span>
			<b>{children}</b>
		</div>
	);
}
