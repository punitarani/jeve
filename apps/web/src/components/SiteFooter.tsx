"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const PLACES: [string, string][] = [
	["/", "timeline"],
	["/world", "the world"],
	["/reports", "reports"],
];

/**
 * The foot of every page that scrolls: whatever the page wants to say about
 * itself on the left, and the site's three places on the right.
 */
export function SiteFooter({ children }: { children?: ReactNode }) {
	// A static export serves /reports as /reports/ or /reports.html depending on
	// the host, so the trailing slash is not part of the match.
	const here = usePathname().replace(/\/$/, "") || "/";
	return (
		<footer className="site-foot" data-testid="site-footer">
			{children}
			<nav aria-label="Site">
				{PLACES.map(([href, label]) => (
					<Link key={href} href={href} aria-current={here === href || (href !== "/" && here.startsWith(`${href}/`)) ? "page" : undefined}>
						{label}
					</Link>
				))}
			</nav>
		</footer>
	);
}
