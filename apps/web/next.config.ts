import type { NextConfig } from "next";

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
	// A static export has no server to read env from at request time, and this
	// build does not inline NEXT_PUBLIC_* references either — `env` is the
	// compile-time define that bakes the API origin into the bundle.
	...(process.env.NEXT_PUBLIC_JEVE_API
		? { env: { NEXT_PUBLIC_JEVE_API: process.env.NEXT_PUBLIC_JEVE_API } }
		: {}),
};

export default config;
