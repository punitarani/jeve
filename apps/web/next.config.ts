import type { NextConfig } from "next";

const config: NextConfig = {
  // The contracts package ships TypeScript source, not a build artefact:
  // one less build step between changing a schema and seeing it fail.
  transpilePackages: ["@jeve/contracts"],
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
};

export default config;
