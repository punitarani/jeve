---
id: "CORE-0010"
title: "Nx Python integration via @nxlv/python plugin"
status: "proposed"
date: 2026-09-21
deciders: ["punitarani"]
scope: ["nx.json", "py/project.json", "apps/api/project.json", "apps/sim/project.json"]
tags: ["nx", "python", "tooling", "monorepo"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0006"]
confirmation: "npx nx show projects"
---

# CORE-0010 — Nx Python integration via @nxlv/python plugin

## Context and Problem Statement

The monorepo needed Python projects integrated into Nx's task graph for unified orchestration, caching, and affected detection. CORE-0006 had previously rejected third-party Python plugins due to single-maintainer risk, opting for manual Makefile coordination. However, this left Python tasks outside Nx's dependency graph, preventing `nx affected` from working correctly and requiring duplicate task definitions.

## Considered Options

* **@nxlv/python plugin** — Active plugin with uv support, aligns with Nx 23.x, provides proper project inference and caching.
* **@mgwilt/nx-uv plugin** — Simpler alternative but less mature (v1.0.0 vs 23.1.1).
* **Manual project.json files only** — Fallback approach, but misses automatic target generation and dependency inference.
* **Local Nx plugin** — More control but higher maintenance burden.

## Decision Outcome

Use @nxlv/python plugin for Nx Python integration, with fallback to manual project.json configuration if the plugin becomes unmaintained.

The plugin provides automatic Python project detection, uv integration, and proper caching inputs while maintaining compatibility with existing Makefile workflows. The decision to use a third-party plugin is justified by the active maintenance (version 23.1.1 matches Nx version) and significant functionality gains over manual configuration.

### Consequences

* Good: Unified task orchestration across TypeScript and Python, proper `nx affected` support, caching for Python tasks, automatic project detection.
* Bad: External dependency on plugin maintenance, potential breaking changes with Nx updates.
* What would reverse it: Plugin abandonment, breaking changes that can't be resolved, or maintenance burden exceeding benefits.

## Implementation

* Plugin registered in `nx.json` with uv package manager configuration
* Python projects (py, api, sim) automatically detected with proper targets
* Caching enabled for Python lint, typecheck, and test tasks
* Maintains compatibility with existing Makefile commands
* Fallback: Remove plugin and manually configure project.json files

## Verification

```bash
# Verify plugin detects Python projects
npx nx show projects | grep -E '^(py|api|sim)$'

# Verify caching works
npx nx run py:lint  # First run
npx nx run py:lint  # Should be cache hit

# Verify affected detection
touch py/src/jeve/config.py && npx nx affected -t lint --base=main
```
