---
id: CORE-0006
title: One Python distribution with layered subpackages, inside an Nx workspace
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["py/pyproject.toml", "py/src/jeve/**"]
tags: ["monorepo", "tooling", "python"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0001"]
confirmation: "cd py && uv run ruff check . && uv run mypy"
---

# CORE-0006 — One Python distribution with layered subpackages, inside an Nx workspace

## Context and Problem Statement

The stack is fixed: Nx, pnpm, Next.js, FastAPI, uv, Postgres. Nx and uv are a
known-awkward pair. The obvious reading — one uv workspace package per module —
needs a community Nx plugin with a single maintainer to infer Python→Python
graph edges, which is the most fragile part of the whole arrangement.

## Considered Options

- **Seven uv workspace packages + `@nxlv/python`.** Rejected: the plugin's only
  real contribution is graph edges between Python packages; having no such
  packages removes the need for it entirely.
- **Drop Nx** for a pnpm workspace plus a justfile. Genuinely sufficient at
  this size, but Nx was a stated constraint.
- **One distribution, layered subpackages.** Taken — workbench's shape.

## Decision Outcome

Python is a single `jeve` distribution whose subpackages are layered
(`contracts → world → decide/memory → gen → sim/api`), with an import-layering
test as the boundary, and Nx sees three projects: `py`, `web`, `contracts`.

Python owns the simulation and every model call; TypeScript owns the browser.
That split is forced by the ground truth, not chosen: the typed-escalation
adapter is Python-only, DSPy is Python-only, and the Python SDK has pydantic
response models. pydantic is the single source of truth for contracts and
generates the TypeScript types and zod schemas.

### Consequences

- Good: no third-party Nx plugin on the critical path; its failure mode was a
  silently missing graph edge.
- Good: one `uv sync`, one venv, one place for editor and type-checker config.
- Bad: package boundaries are a test, not a packaging guarantee — a lazy import
  across layers fails CI rather than being impossible.
- Reverse it if: a Python module needs to ship or deploy independently.

Long form (including the plugin evaluation): `docs/design/008-monorepo.md`.
