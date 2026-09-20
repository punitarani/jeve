# ADR-008 — nx + uv interop, the language split, and where DSPy belongs

Status: proposed · 2026-09-20 · Versions below checked against the npm registry and this
machine today; config snippets from the research are **untested**.

## Decision

1. **Nx 23 + pnpm 10 + one uv workspace** (root `uv.lock`, single `.venv`), with the
   community plugin **`@nxlv/python` used shallowly**: for Python→Python graph edges and
   scaffolding only. Every run, test, lint, and codegen target is a plain
   `uv run --no-sync …` command in `project.json`.
2. **The fallback is deleting one line.** Remove the plugin entry from `nx.json`, add
   `implicitDependencies` to the Python projects, and everything still runs. About half an
   hour. If that ever feels too manual, Nx's own docs teach a ~100-line local graph plugin
   with uv as the worked example.
3. **Python owns the simulation and every model call. TypeScript owns the browser.** Forced
   by the ground truth: the typed-escalation adapter is Python-only, DSPy is Python-only, the
   Python SDK has pydantic response models (00 §3).
4. **pydantic is the single source of truth for contracts.** pydantic → OpenAPI 3.1
   components → `@hey-api/openapi-ts` (exact pin, zod v4 plugin) → committed TS types and zod
   schemas. CI fails on drift.
5. **Python 3.14.** It is what is installed here, what workbench pins, and workbench code uses
   PEP 758 `except A, B:` syntax that will not parse on anything older (00 §6.5).
6. **DSPy is confined to one package** (`py-gen`) serving the generative minority. The sim
   core must not import it.

## Verified today

| | |
|---|---|
| `nx` | 23.2.1 (published 2026-09-18) |
| `@nxlv/python` | 23.1.1 (2026-09-19), peer `@nx/devkit >=22.0.0` |
| `@nx/python` | **404 — no first-party Python plugin exists** |
| `@nx/next` / `next` | 23.2.1 / 16.3.5 |
| `@hey-api/openapi-ts` | 0.99.0 (pre-1.0; pin exactly) |
| This machine | uv 0.11.10 · Python 3.14 · node 24.15.0 · pnpm 10.32.1 · bun 1.3.0 |

**A correction to the research.** The agent's sample `pyproject.toml` pins
`required-version = ">=0.12,<0.13"` and `uv_build>=0.12,<0.13`. uv here is **0.11.10** — that
config would refuse to run. Pin to what is installed, or upgrade uv first, deliberately.
Likewise its `requires-python = ">=3.12"` should be `>=3.14`.

## Why the plugin, and why shallowly

The version numbers above are mine, checked today. **Everything else in this section —
release cadence, contributor counts, how the plugin builds the graph, its open issues — comes
from a research agent that read the plugin's repo and source without installing or running
anything. I did not re-check it.**

`@nxlv/python` is healthy today — six releases since late July, the latest yesterday — and it
tracks Nx majors. It is also one maintainer (209 commits to the next human's 4), had a
five-month release gap in late 2025, and took about twelve weeks to support Nx 22. It exports
only `createDependencies`: it infers graph edges from `[tool.uv.sources]` workspace entries
resolved through `uv.lock`, and nothing else. Every Python project needs a `project.json`
regardless.

So the plugin's entire contribution is *edges*. Depending on its executors as well would buy
a little convenience and a hard dependency on one person's release schedule. Using it for
edges alone means its failure mode is a missing edge, and its removal is trivial.

Known sharp edges from the research (not re-checked): a stale `uv.lock` yields missing edges;
the generator does not support glob workspace members; `build` ignores `uv_build`
`module-name`. List workspace members explicitly — and never `apps/*`, since `apps/web` has
no `pyproject.toml`.

## Hermetic tasks in a shared venv

`uv run` locks and syncs before every command; parallel Nx tasks would race on the one
`.venv`. So: a single `py-env:sync` target runs `uv sync --all-packages --frozen`, every
other Python target `dependsOn` it and uses `uv run --no-sync`. CI adds `uv lock --check`.
`.venv` is never an Nx output. pytest runs with `-p no:cacheprovider`; any target that calls
a paid model has `cache: false`.

Named inputs make `nx affected` correct for Python: `{projectRoot}/**/*.py`, the project's
`pyproject.toml`, and `{workspaceRoot}/uv.lock`. A lockfile change marks every Python project
affected — coarse, correct.

## Contracts

| Pipeline | Verdict |
|---|---|
| **pydantic → OpenAPI 3.1 → TS + zod** (hey-api or orval) | **Chosen.** pydantic emits discriminated unions as `oneOf` + `discriminator.mapping` and numeric constraints as min/max. Least lossy direction. |
| pydantic → JSON Schema → zod via `json-schema-to-zod` | Dead: that package was archived in March 2026. |
| zod → JSON Schema → pydantic | `z.toJSONSchema()` emits `oneOf` without a `discriminator`, so the tag is lost; refinements and transforms cannot cross; generated pydantic classes cannot carry validators, and DSPy wants real classes. |
| TypeSpec / protobuf | A third language, and still needs a pydantic generator. |

Wiring: `py-contracts:export-schema` writes a deterministic, sorted, components-only OpenAPI
file → `contracts:codegen` depends on it with `dependentTasksOutputFiles` as input →
generated files are committed → CI fails if `git status --porcelain` is non-empty for them.
Keep contract models free of defaults, or set FastAPI's `separate_input_output_schemas=False`,
to avoid split `X-Input`/`X-Output` schemas.

**Unverified:** hey-api's zod output for pydantic's discriminated unions. jeve's event payload
is exactly that shape. M1 includes a spike on one real union; orval, whose handling is
documented, is the alternative.

## pnpm, not bun

pnpm 10.32.1 is already here. Bun 1.4's lockfile v2 made every Nx command fail until Nx
23.1.2; Nx Agents' templates do not support bun; an issue with Next.js + TypeScript failing to
start inside Bun workspaces is still open. pnpm 12 (2026-08-26) also broke Nx briefly — stay
on 10.x via the `packageManager` field and move deliberately. For a project that values
boring reliability this is not close.

## Is Nx earning its place? A requirement worth questioning

You asked for an nx monorepo, so this is one. But at this size — one web app, two Python
apps, three or four libraries — Nx is a convenience, not a necessity. What it buys: cached,
dependency-ordered contract codegen; one `nx run-many` dev command with continuous tasks;
correct `affected` in CI. What it costs: the awkward half of this ADR. **A pnpm workspace + a
uv workspace + a `justfile` would lose very little.** Nothing in the architecture depends on
Nx; if it costs more than an hour a month, drop it without ceremony. Turborepo's native uv
workspace support is the thing to watch — currently flagged experimental.

## Layout

```
jeve/
├─ nx.json · package.json · pnpm-workspace.yaml · pyproject.toml · uv.lock · .python-version · ruff.toml
├─ apps/
│  ├─ web/      Next.js 16 — dashboard only
│  ├─ api/      FastAPI — read endpoints, SSE, control endpoints (localhost)
│  └─ sim/      the long-running simulation process
├─ packages/
│  ├─ py-contracts/   pydantic models: events, decisions, API payloads → schema/*.json (committed)
│  ├─ py-world/       ledger, domain rules, scheduler, tick transaction — NO model imports
│  ├─ py-decide/      DecisionModel port, Jev/OpenRouter/replay adapters, question sets, sampling
│  ├─ py-memory/      memories, retrieval, beliefs, compaction
│  ├─ py-gen/         LLM port, DSPy signatures, rendering, ontology proposals, tier 1 adapter glue
│  ├─ py-metrics/     invariants, detectors, canary, study runner
│  └─ contracts/      generated TS + zod (committed)
└─ tools/py-env/      sync + lock-check targets
```

**`api` and `sim` are separate processes.** A uvicorn reload or a second worker would kill or
duplicate a simulation living in-process; the sim must hold a single-writer lease (ADR-009);
and the API should stay up and explain itself while the sim is paused or restarting.

The package boundaries are the swap points the brief asks for: routing policy lives wholly in
`py-decide`; the memory implementation wholly in `py-memory`; an org's rules are data read by
`py-world` and `py-decide` (ADR-004). An import-layering test, as in workbench, keeps
`py-world` free of any model dependency.

## DSPy: where it pays and where it does not

Evidence from your own repo (00 §6.5): in workbench DSPy earns its place as **typed
signatures, a parser, and a swappable instruction surface**. Its optimisation loop did not —
the best candidate "quoted the evaluation day verbatim (reward hacking)" and nothing generic
shipped.

| Use | Verdict |
|---|---|
| Signatures for rendering prose from typed acts, and for ontology proposals | **Yes.** Structured in, structured out, instructions swappable without touching code. |
| Optimisers (GEPA, MIPRO, …) | **Not in the MVP.** There is no eval set and no metric to optimise against until M8 has logged a few hundred rendered examples and a grounding/consistency judge exists. An optimiser with no metric is a random walk. |
| Jev question sets | **No.** Jev is not an LM program: no prompt to optimise, no text out. Question quality is managed by lint, golden tests, and shadow agreement (ADR-004, ADR-005). |
| Tier 1 typed escalation | **No.** TypeSafe's adapter already does exactly this and returns the SDK's own types. |
| The sim core | **Never.** DSPy pulls in litellm; workbench needed a `litellm<1.95` constraint just to get a cp314 wheel. That weight stays in `py-gen`. |

## Reverse if

- A new Nx major is > 4 weeks old with no compatible plugin release, or a plugin graph-time
  exception blocks `nx` commands → take the fallback.
- Nx ships first-party Python support (it is on the 2026 roadmap, undated) → adopt it.
- The hey-api spike mangles discriminated unions → orval.
