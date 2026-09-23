/** Numbers as every report writes them. */

export const fmt = (n: number) => Math.round(n).toLocaleString("en-US");
export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;
/** Money is integer cents on the wire; a report writes whole dollars. */
export const usd = (cents: number) => `$${fmt(cents / 100)}`;
