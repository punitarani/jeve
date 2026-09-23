/** Numbers, days and firms as every report writes them. Money in cents is
 * `money()` from lib/api, the one place cents are formatted. */

export const fmt = (n: number) => Math.round(n).toLocaleString("en-US");
export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;
export const pad2 = (h: number) => String(h).padStart(2, "0");
/** A sim-day on an axis ("d12"), or in a tooltip ("day 12"). */
export const dayfmt = (d: number, tip?: boolean) => (tip ? `day ${d}` : `d${d}`);
/** Whole dollars on an axis: "$48k", "$619". */
export const dollars = (v: number) => (Math.abs(v) >= 1000 ? `$${Math.round(v / 1000)}k` : `$${Math.round(v)}`);

/** Each firm's colour token in report.css. */
export const ORG_COLOR: Record<string, string> = {
	tallybird: "--tb",
	halloran: "--hp",
	ledgerline: "--ll",
	thirdrail: "--tr",
};
