import { withSentryConfig } from "@sentry/nextjs/config";
import type { NextConfig } from "next";

// A static export has no server to read env from at request time, and this
// build does not inline NEXT_PUBLIC_* references either — `env` is the
// compile-time define that bakes each value into the bundle, when it is set.
const defines = (...names: string[]): Record<string, string> =>
	Object.fromEntries(
		names.flatMap((name) => {
			const value = process.env[name];
			return value ? [[name, value]] : [];
		}),
	);

const config: NextConfig = {
	// WEB-0005: the site is a directory of files. Workers static assets serve
	// `out/`; nothing server-renders, so a Next runtime would only add a hop.
	output: "export",
	// The contracts package ships TypeScript source, not a build artefact:
	// one less build step between changing a schema and seeing it fail.
	transpilePackages: ["@jeve/contracts", "@jeve/world"],
	reactStrictMode: true,
	// Next generates its own AGENTS.md/CLAUDE.md describing Next conventions.
	// This repo already tells agents where decisions live and how to read them
	// (see the root AGENTS.md); a second, generated set that does not know about
	// `decisions/` would quietly compete with it.
	agentRules: false,
	// Next 16 treats 127.0.0.1 and localhost as different origins and blocks
	// dev resources across them. The symptom is not an error page: the HTML
	// renders fine and hydration silently never happens, so every click is
	// inert. Naming both hosts means the app works at whichever one a person
	// or a test happens to type.
	allowedDevOrigins: ["127.0.0.1", "localhost"],
	// `make e2e` builds into its own directory, so it can run beside a
	// developer's `next dev` without the two fighting over `.next`.
	distDir: process.env.JEVE_NEXT_DIST ?? ".next",
	env: defines(
		"NEXT_PUBLIC_JEVE_API",
		"NEXT_PUBLIC_SENTRY_DSN",
		"NEXT_PUBLIC_SENTRY_ENVIRONMENT",
	),
};

// CORE-0012. Without SENTRY_AUTH_TOKEN nothing is uploaded and no source maps
// are generated: the wrapper would otherwise force `productionBrowserSourceMaps`
// on, and `out/` is served whole. With a token (the deploy job) the maps are
// uploaded and deleted, and CI scrubs any that survive. `tunnelRoute` is not
// set: it needs a server, and `output: "export"` has none.
export default withSentryConfig(config, {
	org: process.env.SENTRY_ORG,
	project: process.env.SENTRY_PROJECT,
	authToken: process.env.SENTRY_AUTH_TOKEN,
	silent: !process.env.CI,
	telemetry: false,
	widenClientFileUpload: true,
	sourcemaps: {
		disable: !process.env.SENTRY_AUTH_TOKEN,
		deleteSourcemapsAfterUpload: true,
	},
	// A Sentry outage or a stale token must never fail a deploy; the warning
	// is the signal, and the site ships without readable stack traces.
	errorHandler: (error) => {
		console.warn(`[sentry] source map upload skipped: ${error.message}`);
	},
});
