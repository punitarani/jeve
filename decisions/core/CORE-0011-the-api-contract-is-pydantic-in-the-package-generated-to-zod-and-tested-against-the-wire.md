---
id: "CORE-0011"
title: "The API contract is pydantic in the package, generated to zod, and tested against the wire"
status: "accepted"
date: 2026-09-21
deciders: ["claude"]
scope: ["py/src/jeve/api/contracts.py", "tools/contract-gen/**", "packages/contracts/src/index.ts", "py/tests/test_api.py"]
tags: ["contracts", "tooling", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0008", "API-0001"]
confirmation: "cd py && uv run pytest tests/test_api.py -k contract"
---

# CORE-0011 — The API contract is pydantic in the package, generated to zod, and tested against the wire

## Context and Problem Statement

CORE-0008 records that browser contracts are "written by hand and checked
against the API in tests; nothing is generated from pydantic." The build went
the other way — zod schemas are generated — and for a while the generator read
a *second* copy of the models in `tools/contract-gen/models.py`, kept in step
with the API by nothing but memory, patched by an override table inside the
generator. A "single source of truth" that is actually a hand-maintained
mirror is the worst of both worlds: it looks enforced and is not. A future
engineer could also plausibly delete the pydantic models as unused — they are
not `response_model`s on any endpoint — which would silently sever the
contract the browser parses with.

## Considered Options

* **Models inside the package + a conformance test** — taken.
* **FastAPI `response_model=` on every endpoint** — rejected: FastAPI then
  *strips* fields the model does not declare, hiding additions instead of
  surfacing them. The contract should describe the wire, not censor it.
* **Keep the mirror in `tools/`, enforce via drift check only** — rejected:
  the drift check only proves the generated file matches the mirror; nothing
  proves the mirror matches the API.
* **Hand-written zod checked by tests (what CORE-0008 described)** — rejected
  as built reality: the generated path exists and is one way to do it; two
  descriptions of the same contract is the thing this record removes.

## Decision Outcome

`py/src/jeve/api/contracts.py` is the one source of truth for what the API
serves: real pydantic models inside the `jeve` package, where `mypy --strict`
and the layering test see them. `tools/contract-gen/generate_zod.py` renders
`packages/contracts/src/index.ts` from them; `test_api.py` validates live
endpoint responses against the same models, so the models cannot drift from
the SQL without a failing test. Field descriptions and docstrings carry the
comments into the generated file — no override table. A field the API omits
rather than sends as JSON null is `X | None` with a default (`.optional()`);
a key that is present and null is required `X | None` (`.nullable()`).

### Consequences

* Good: drift fails in three different places — mypy on the models, pytest on
  the wire, and `contracts:check-drift` on the generated file — and there is
  exactly one description of each shape to keep.
* Bad: the models duplicate the SELECT lists in `app.py`; adding a column to
  a response means touching both. The conformance test fails if you forget.
* What would reverse it: adopting `response_model=` wholesale and accepting
  its field-stripping, or generating the TypeScript from FastAPI's OpenAPI
  once that output is complete enough to lose nothing.
