---
id: CORE-0008
title: The layering the test enforces is the layering
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/pyproject.toml", "py/src/jeve/**", "py/tests/test_layering.py"]
tags: ["monorepo", "tooling", "python", "layering", "agent-decided"]
supersedes: ["CORE-0006"]
superseded-by: null
relates-to: ["CORE-0001", "GEN-0001"]
confirmation: "cd py && uv run pytest tests/test_layering.py"
---

# CORE-0008 — The layering the test enforces is the layering

## Context and Problem Statement

CORE-0006 chose one Python distribution with layered subpackages and a test as
the boundary. That choice stands. But the record names a layering that was
never built (`contracts -> world -> decide/memory -> gen -> sim/api`, pydantic
generating the TypeScript types, three Nx projects), and the audit
(`docs/audit/2026-09-21/README.md` A11) found the code and the test agree with
each other and disagree with the record. A record that describes a different
system is worse than none: the next engineer fixes the code to match it.

## Considered Options

- **Edit CORE-0006.** Rejected: records are immutable (CORE-0001).
- **Change the code to match the record.** Rejected: the built order is the
  better one. `decide` sits *below* `world` because the engine asks a policy;
  a policy never reaches into the engine.
- **Supersede, and point the record at the test.** Taken.

## Decision Outcome

One `jeve` distribution; its packages are layered
`core -> llm -> decide -> world -> sim`, with `gen` and `api` on the outside.
`py/tests/test_layering.py` is the definition: its `FORBIDDEN` table is the
layering, walked over the real import graph, lazy imports included. Two rows
carry the weight. Nothing that computes the world may import `gen` (sim state
never depends on generated text), and `world` may not import `llm` (the engine
reaches a model only through the `Policy` seam).

Contracts for the browser are zod schemas in `packages/contracts`, written by
hand and checked against the API in tests; nothing is generated from pydantic.
Nx sees `py`, `web`, `contracts` and `world`.

A new top-level package must be added to the table or the test fails.

### Consequences

- Good: one source of truth for the layering, and it executes.
- Bad: the contract between Python and TypeScript is kept in step by tests, not
  by generation. Two hand-written descriptions can drift between test runs.
- Reverse it if: a Python module needs to ship or deploy independently, or
  contract drift causes a second production bug.
