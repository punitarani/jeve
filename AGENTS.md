# jeve

A continuously-running simulation of a small interconnected economy: four firms
on one street — Tallybird Software (whose product the others use), Halloran &
Pike LLP, Ledgerline Accounting, Third Rail Cafe.

The research question: how much of a Smallville/Concordia-style agent loop can
be replaced by *typed decisions* — boolean-with-probability, choice-from-enum,
numeric scale — instead of generated text. Typed decisions come from TypeSafe's
Jev; prose generation is the rare exception, and no causal path in the
simulation ever reads generated text.

## Layout

| Path | What |
|---|---|
| `py/src/jeve/` | The simulation. `core → llm → decide → world → sim`, with `gen` and `api` on the outside. `tests/test_layering.py` enforces it |
| `py/src/jeve/decide/` | The `Policy` seam: `JevPolicy`, its rules twin, question sets, J/P/H sampling, the call cache |
| `py/src/jeve/world/` | Engine, the ten flows, the scheduler registry, the town map, encounters and episodes |
| `py/src/jeve/memory/` | What persists between meetings: facts, who knows them, promises (MEM-0002) |
| `py/src/jeve/sim/` | `python -m jeve.sim`: the one run loop, for fixture, daemon and soak alike |
| `py/src/jeve/gen/` | Prose rendered from typed state. **Nothing that computes the world may import it** |
| `py/fixtures/cassettes/` | Recorded Jev responses, keyed by content hash of `(model, state, questions)`. What makes `make e2e` free |
| `apps/api/` | FastAPI application entry point (implementation in `py/src/jeve/api/`) |
| `apps/sim/` | Simulation worker entry point (implementation in `py/src/jeve/sim/`) |
| `apps/web/` | The hero on `/`, the explorer at `/world`, and the causal timeline |
| `packages/world/` | The voxel town: a GL-free scene model with three.js as a view over it |
| `packages/contracts/` | zod schemas for everything the API serves (generated from pydantic) |
| `tools/contract-gen/` | pydantic → zod contract generation |
| `decisions/` | Decision records and their generated index |
| `docs/research/` | Ground truth on Jev, prior-art mapping, validation survey, the recursive-micro-simulation survey |
| `docs/design/` | Long-form analysis behind the decision records |
| `ops/` | Runtime state (spend ledger) and tracked measurements (`economics.md`, `soak.md`, `persona-probe.md`, `providers.md`) |
| `tools/` | Contract generation and utility scripts |

## Decisions

Architecture decisions are recorded, not remembered. Before changing anything
structural:

1. Read `decisions/INDEX.md` — one row per decision, with the globs it governs.
2. Open **only** the records whose `scope` covers the files you are about to
   change. Do not read them all.
3. If you are making a consequential architectural choice that no record
   covers, write one: `python3 scripts/gen-decisions.py --new PREFIX "title"`,
   fill it in, then run `python3 scripts/gen-decisions.py`.

Records are **immutable**. Never edit the substance of an accepted decision —
write a new record and set `superseded-by` on the old one. Filling in `scope`
once the code exists is metadata, not substance, and is fine.

Write a record only when the choice was contested, the obvious answer was wrong
for a non-obvious reason, or a future engineer would plausibly undo it. Cite
the ID at the enforcement point in code (`# CORE-0005: seeds are path-derived`).

Records written autonomously carry `deciders: ["claude"]` and the tag
`agent-decided` until a human has reviewed them.

## Standards

* One way to do each thing. No parallel abstractions "in case".
* Every module testable without network. Real model calls live in `jeve.llm`
  and in tests marked `live`.
* Prefer deleting code to adding configuration.
* Comments explain *why*, and carry the incident that justified the code.

### Nested Configuration

This project uses nested AGENTS.md files for area-specific standards:

* `py/AGENTS.md` - Python development standards (type hints, uv, pydantic, ruff, mypy)
* `apps/web/AGENTS.md` - Web development standards (TypeScript, React, Next.js)
* `packages/AGENTS.md` - Shared packages standards (workspace management, Zod schemas)

## Tooling

* **Tool versions**: `mise.toml` manages Node.js, Python, uv, and pnpm versions
* **Task runner**: Nx orchestrates TypeScript and Python tasks with caching
* **Contract generation**: `make contracts` generates zod schemas from pydantic models; `make contracts-check` verifies they are in sync
* **Dependency management**: `pnpm` for TypeScript, `uv` for Python

## Money

**Every model call goes through `jeve.llm`.** Nothing else may import `httpx`;
ruff enforces it. The gateway reserves worst-case cost before issuing, settles
at the real cost, and refuses past the ceiling. Thresholds: $12 stops
exploratory work, $16 halts everything and triggers the handoff, $20 is the
backstop. State is the `spend_entries` table in Postgres (LLM-0007), shared by
the daemon and the API and durable across restarts — do not add a second path
to a model, and do not reset the ledger. `ops/spend.json` is a read-only
checkpoint for humans; the table wins any argument.

## Verify

```
make check            # lint, types (mypy + tsc), tests, decision records
make confirm          # every decision record's confirmation command, for real
make contracts        # generate zod schemas from pydantic models
make contracts-check  # verify contracts are in sync (drift detection)
make e2e              # the whole stack, strict replay: free, no key, ~5 min
make soak             # 35 sim-days on rules, on its own database: invariants, ~1 min
LIVE=1 make e2e       # hit-or-call; the only thing that rewrites ops/economics.md
make smoke            # one real call, under a cent
make sim              # the ever-running world. Spends money, slowly
```

### Deployment

```
make deploy-web       # Deploy web app to Cloudflare Workers
make deploy-api       # Deploy API to Fly.io
make deploy-sim       # Deploy simulation worker to Fly.io
make deploy           # Deploy all services
```

### Nx Commands

```
npx nx show projects           # List all projects
npx nx run py:lint             # Lint Python code
npx nx run py:test             # Run Python tests
npx nx run api:start           # Start API server
npx nx run sim:run             # Run simulation
npx nx run contracts:generate  # Generate contracts
npx nx affected -t lint        # Lint only affected projects
```

Four things that will otherwise cost you an evening:

* **Wording is a cache key — and so is order, and so is the model build.** The
  key is the exact bytes sent plus the dated build that answered. Edit a
  sentence, reorder a question's options, or move `DECISION_PIN`, and those calls
  are re-recorded and the run changes. Re-record with `LIVE=1 make e2e` and
  commit the cassette. A build other than the pin answering is a halt, on purpose.
* **Nothing in the world may be keyed by the tick.** Randomness is about an
  entity and its own calendar (CORE-0009); rates are per hour. A test walks the
  source for `tick_seq` in a seed path.
* **A tick must own its transaction.** In psycopg 3, `conn.transaction()` inside
  an already-open transaction is a savepoint. `Engine.tick()` commits first for
  that reason (WORLD-0002); do not "simplify" it.
* **A connection that only reads must be autocommit** if another process will
  `TRUNCATE`. An open read transaction holds a lock the daemon waits on for ever.

<!-- GENERATED by scripts/gen-decisions.py. Do not edit this section. -->

## Decision Records

Architecture decisions are recorded as immutable MADR 4.0 records. This section is auto-generated from the canonical records in `decisions/`. Consult `decisions/INDEX.md` for the full index and links to detailed records.

### API-0001: Make the event seq the only cursor the client tracks

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/api/app.py`, `apps/web/src/lib/api.ts`  
**Tags**: api, streaming, agent-decided

Every endpoint that returns events also returns the `seq` it is current as of, and `/stream` takes `after=<seq>`, so a reconnect is exactly "give me what comes after this" with no gap and no duplicate.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### API-0002: Page the seq cursor both ways, and read the timeline newest first

**Status**: accepted (2026-09-21)  
**Scope**: `py/src/jeve/api/app.py`, `py/src/jeve/api/contracts.py`, `apps/web/src/lib/api.ts`, `apps/web/src/components/Dashboard.tsx`  
**Tags**: api, web, pagination, agent-decided

`/events` takes `before=<seq>` as well as `after=<seq>`, and every page carries a cursor at each end — `seq` (newest) and `oldest` — plus `more`, which says whether another page exists in the direction this one travelled. Rows come back ascending whichever way the window was taken; the timeline reverses once, where it renders.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### CORE-0001: Record architecture decisions as immutable per-file records

**Status**: accepted (2026-09-20)  
**Scope**: `decisions/**`, `**/decisions/*.md`, `scripts/gen-decisions.py`  
**Tags**: process, documentation, agents

Decisions are MADR 4.0 records, one per file, named `<PREFIX>-NNNN-kebab.md`, with machine-readable front matter; `INDEX.md`, `index.jsonl`, `schema.json` and the AGENTS.md decision section are generated from them and never hand-edited.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### CORE-0004: Slow the clock under backpressure; never default a decision

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/llm/**`  
**Tags**: backpressure, reliability, clock

The tick is a barrier: sim time does not advance until every decision due at that tick has a real answer, so a slow model means a slow world and a dead model means a paused world.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### CORE-0008: The layering the test enforces is the layering

**Status**: accepted (2026-09-20)  
**Scope**: `py/pyproject.toml`, `py/src/jeve/**`, `py/tests/test_layering.py`  
**Tags**: monorepo, tooling, python, layering, agent-decided

One `jeve` distribution; its packages are layered `core -> llm -> decide -> world -> sim`, with `gen` and `api` on the outside. `py/tests/test_layering.py` is the definition: its `FORBIDDEN` table is the layering, walked over the real import graph, lazy imports included. Two rows carry the weight. Nothing that computes the world may import `gen` (sim state never depends on generated text), and `world` may not import `llm` (the engine reaches a model only through the `Policy` seam).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### CORE-0009: Randomness is keyed by what it is about, never by when it was drawn

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/**`, `py/src/jeve/core/seed.py`, `py/tests/test_world.py`  
**Tags**: determinism, randomness, counterfactuals, agent-decided

A seed path names the thing the draw is *about* and, where the thing recurs, its own period: an invoice amount is `(issuer, client, billing month)`; whether a subscriber notices an outage is `(person, incident)`; the hour a payer sits down to their bills is `(person, day)`; the hazard is `(module, day, slot)`; where someone stands is `(person, zone, arrival)`. `tick_seq` and event sequence numbers never appear in a seed path, and a test walks the source to keep it so.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### CORE-0011: The API contract is pydantic in the package, generated to zod, and tested against the wire

**Status**: accepted (2026-09-21)  
**Scope**: `py/src/jeve/api/contracts.py`, `tools/contract-gen/**`, `packages/contracts/src/index.ts`, `py/tests/test_api.py`  
**Tags**: contracts, tooling, agent-decided

`py/src/jeve/api/contracts.py` is the one source of truth for what the API serves: real pydantic models inside the `jeve` package, where `mypy --strict` and the layering test see them. `tools/contract-gen/generate_zod.py` renders `packages/contracts/src/index.ts` from them; `test_api.py` validates live endpoint responses against the same models, so the models cannot drift from the SQL without a failing test. Field descriptions and docstrings carry the comments into the generated file — no override table. A field the API omits rather than sends as JSON null is `X | None` with a default (`.optional()`); a key that is present and null is required `X | None` (`.nullable()`).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### DECIDE-0004: The cache key is the bytes that were sent and the model version that answered

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/llm/protocol.py`, `py/src/jeve/llm/gateway.py`, `py/src/jeve/llm/catalog.py`, `py/src/jeve/decide/jev_policy.py`, `py/src/jeve/decide/recorder.py`, `py/fixtures/cassettes/**`  
**Tags**: cache, replay, determinism, agent-decided

`DecisionRequest.wire_bytes()` is the one place a decision body is built. The gateway posts exactly those bytes; the policy hashes exactly those bytes.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### GEN-0001: Dialogue is a projection — rendered on click, cached by content hash, never read back

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/gen/**`, `py/tests/test_layering.py`, `py/tests/test_dialogue.py`  
**Tags**: prose, escape-hatch, layering, agent-decided

`GET /encounters/{seq}/dialogue` always returns the typed record, and renders two to four lines of dialogue only when asked: from the first reachable escape-hatch model (LLM-0005), cached in `model_calls` under the content hash of the request, and imported by nothing that computes the world.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### LLM-0001: Reach every model through OpenRouter, including Jev

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/llm/gateway.py`, `py/src/jeve/llm/catalog.py`  
**Tags**: openrouter, jev, routing

Everything goes through OpenRouter: chat completions at `/api/v1/chat/completions` and Jev at `/api/alpha/decisions`, under one key with one spend meter.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### LLM-0003: Route with per-request provider preferences, never account settings

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/llm/protocol.py`  
**Tags**: openrouter, routing, operations

Routing preferences are set per request in the body — ordering, sort, ignore list — and account-level settings are left alone; if one ever must change, the before-state is written to `ops/provider-settings.before.json` first.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### LLM-0006: Dialogue model order by measured reliability, and 52x is retryable

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/llm/catalog.py`, `py/src/jeve/llm/gateway.py`  
**Tags**: openrouter, models, retries, agent-decided

The generative order is GLM 5.3 Flash, Gemini 3.8 Flash, GPT-5.6 Luna, DeepSeek V4 Pro (0813), DeepSeek V4.1 Flash. Per-path resolution from LLM-0005 stands: a decision slug that does not resolve is fatal, a generative slug that does not resolve is skipped.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### LLM-0007: the spend ledger lives in Postgres and OpenRouter holds the ceiling

**Status**: accepted (2026-09-21)  
**Scope**: `py/src/jeve/llm/ledger.py`, `py/src/jeve/llm/budget.py`, `py/src/jeve/llm/gateway.py`, `py/migrations/0008_spend_ledger.sql`, `py/tests/test_ledger_and_budget.py`  
**Tags**: cost, safety, deployment, agent-decided

`spend_ledger` is an append-only table; `SpendLedger` keeps its reserve/settle/release/baseline/remote API with `read()` as SQL aggregation, and `authorise` holds a transaction-level advisory lock across read+reserve. Ceilings are env-tunable and set high; OpenRouter's 402 — surfaced as `ProviderBudgetError` — is the real stop, and the daemon answers it with `waiting_on_budget`, not a halt (SIM-0003).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### LLM-0008: trace every model call to braintrust, from one module, off by default

**Status**: accepted (2026-09-21)  
**Scope**: `py/src/jeve/tracing.py`, `py/src/jeve/llm/gateway.py`, `py/src/jeve/decide/jev_policy.py`, `py/src/jeve/api/app.py`, `py/tests/test_tracing.py`  
**Tags**: observability, braintrust, llm, agent-decided

Model calls are traced to Braintrust from a single guarded module, `jeve.tracing`, which is a no-op unless `BRAINTRUST_API_KEY` is set.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### MEM-0002: Facts travel, promises are scored, and both are typed rows

**Status**: accepted (2026-09-22)  
**Scope**: `py/src/jeve/memory/**`, `py/migrations/0009_episodes.sql`, `py/tests/test_episodes.py`  
**Tags**: memory, knowledge, diffusion, commitments, agent-decided

A **fact** is a thing that can be known and passed on, identified by what it is about (`outage:<incident>`, `price_rise:<org>`) rather than minted from a counter, so the same news is the same row in every arm of a counterfactual. **Knowledge** records who holds it, from whom, and at what remove. A **commitment** is a promise to pay a particular bill.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### OPS-0001: deployment topology — fly process groups, workers static assets, doppler secrets

**Status**: accepted (2026-09-21)  
**Scope**: `infra/**`, `fly.toml`, `docker-compose.prod.yml`, `apps/web/wrangler.toml`, `.github/workflows/ci.yml`, `Makefile`  
**Tags**: deployment, fly, cloudflare, doppler, agent-decided

`fly.toml` is one app `jeve-backend` with process groups `api` (the only ingress, on `JEVE_DATABASE_POOLED_URL` when set, else the direct DSN) and `sim` (`sim-entrypoint.sh`, `on-failure` restarts, no service). The web app is an assets-only Worker serving `out/`. Secrets live in Doppler projects `app`/`infra`/`worker` and land as Fly secrets and GitHub secrets; the sim's Postgres URL must be a *direct* connection because the writer lock is a session-level advisory lock. The frontend is read-only, so the dialogue endpoint's spend path is off in production (`JEVE_DIALOGUE_GENERATE=off`).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### OPS-0002: Run the suite once per CI run, and confirm records by collection

**Status**: accepted (2026-09-21)  
**Scope**: `.github/workflows/ci.yml`, `scripts/run-confirmations.py`, `scripts/test_run_confirmations.py`, `scripts/ci-needs-python.sh`, `py/tests/conftest.py`  
**Tags**: ci, testing, cost, agent-decided

The suite runs once per CI run under `pytest -n auto --dist loadfile`, each xdist worker on a database of its own, and `scripts/run-confirmations.py` then runs each record's `confirmation` once — in `--pytest collect` mode a command that is nothing but `cd py && uv run pytest <paths>` is collected rather than re-executed.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### OPS-0003: Deploy the web app after the backend, never before it

**Status**: accepted (2026-09-22)  
**Scope**: `.github/workflows/ci.yml`, `scripts/check_deploy_order.py`  
**Tags**: deployment, ci, contracts, agent-decided

`deploy-web` needs `[web, contracts, deploy-backend]`, so the page ships only once the API it talks to is live.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### SIM-0001: One run loop, a horizon, a single-writer lock, and a governor that pauses

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/sim/**`, `py/scripts/run_fixture.py`  
**Tags**: daemon, pacing, budget, restart-safety, agent-decided

`python -m jeve.sim` is the only run loop; the fixture is that loop with pacing off and a horizon. `--until` makes a wall-clock process replayable, a Postgres advisory lock makes it the only writer, and the budget governor pauses the clock until the window rolls over rather than changing how anything behaves.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### SIM-0002: The daemon outlives its model - wait, say so, retry the tick

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/sim/daemon.py`, `py/src/jeve/sim/runner.py`, `py/src/jeve/api/app.py`, `py/migrations/**`  
**Tags**: daemon, robustness, backpressure, agent-decided

The run loop treats `TransportError`, `ResponseShapeError` and `TimeoutError` as weather. The tick is rolled back, `sim_meta.status` becomes `waiting_on_model` with the error's class and first line in `last_error`, and the same tick is tried again after a jittered backoff that doubles to a cap of two minutes. The first tick that succeeds sets `running` and clears the error. Budget exhaustion and a replay miss keep their own statuses and exits: they are not weather, and retrying them cannot help.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### SIM-0003: waiting on budget is a status, and deliberate halts exit clean

**Status**: accepted (2026-09-21)  
**Scope**: `py/src/jeve/sim/daemon.py`, `py/migrations/0007_waiting_on_budget.sql`, `infra/docker/sim-entrypoint.sh`, `py/tests/test_daemon.py`  
**Tags**: daemon, robustness, cost, agent-decided

A 402 raises `ProviderBudgetError`; the daemon rolls the tick back, writes `waiting_on_budget` to `sim_meta`, beats from the sleep loop, and retries the same tick on a minutes-scale interval (`JEVE_BUDGET_WAIT_S`). In the container, `sim-entrypoint.sh` maps exits 4–7 to 0, so `on-failure` restarts crashes and leaves deliberate halts down; the reason stays in `sim_meta`, which is where an operator looks anyway.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### SIM-0004: the daemon outlives its database, and the night is a dial

**Status**: accepted (2026-09-22)  
**Scope**: `py/src/jeve/sim/daemon.py`, `py/tests/test_daemon.py`  
**Tags**: daemon, robustness, pacing, agent-decided

Dead-time speedup is `JEVE_NIGHT_SPEEDUP` / `--night-speedup`, and losing the database is weather in the sense of SIM-0002: the daemon takes another connection and runs the same tick again, for ever, rather than exiting.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WEB-0002: A voxel town on the landing page, as a view over a GL-free scene model

**Status**: accepted (2026-09-20)  
**Scope**: `packages/world/**`, `apps/web/src/components/WorldHero.tsx`, `apps/web/src/components/WorldExplorer.tsx`, `apps/web/src/app/world/**`, `apps/web/e2e/a-world.spec.ts`  
**Tags**: three.js, rendering, testing, agent-decided

`@jeve/world` exports `mountWorld(container, options)`, used twice: a hero with no controls and an automatic camera, and an explorer with pan, zoom and clicks. Positions, interpolation and picking live in `WorldModel`, which never touches WebGL; `WorldView` renders it with an orthographic isometric camera, one instanced mesh for every static voxel and one per body part, flat-shaded, all geometry procedural.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WEB-0003: Draw nothing off-screen, and draw cheaply on a software renderer

**Status**: accepted (2026-09-20)  
**Scope**: `packages/world/src/render.ts`, `packages/world/src/index.ts`  
**Tags**: three.js, performance, testing, agent-decided

The scene is not drawn while its canvas is off-screen or the tab is hidden, and when WebGL turns out to be a CPU rasteriser it is drawn without antialiasing, at 1x pixel ratio, fifteen times a second. The model advances regardless: positions are what tests and clicks read, and they must not depend on whether anyone is watching.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WEB-0004: The town is lit, shadowed and peopled like a toy, not a diagram

**Status**: accepted (2026-09-20)  
**Scope**: `packages/world/src/render.ts`, `packages/world/src/voxels.ts`, `packages/world/src/sky.ts`, `packages/world/src/model.ts`, `py/src/jeve/world/map.py`, `packages/contracts/src/world.ts`  
**Tags**: three.js, rendering, lighting, characters, agent-decided

The look is computed, not post-processed: occlusion and colour jitter are baked per corner when the voxels are built, sky and sun are a pure function of the sim clock, shadow maps are for real GPUs only, and people are posed from four optional fields on the scene model.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WEB-0005: the site is a static export; nothing server-renders

**Status**: accepted (2026-09-21)  
**Scope**: `apps/web/**`, `scripts/e2e.sh`, `infra/docker/Dockerfile.web`  
**Tags**: nextjs, cloudflare, deployment, agent-decided

`next.config.ts` sets `output: "export"`. `page.tsx` renders a static shell; a client component fetches `fetchState`/`fetchLatestEvents` on mount and the "API is not reachable" copy becomes a client-side state. `NEXT_PUBLIC_JEVE_API` is inlined at build time, so changing it means rebuilding. `wrangler.toml` is assets-only (`directory = "out"`, no `main`, no `binding`).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WEB-0006: UI components are shadcn on Base UI primitives over the app palette

**Status**: accepted (2026-09-21)  
**Scope**: `apps/web/src/components/**`, `apps/web/src/app/globals.css`, `apps/web/src/app/layout.tsx`, `apps/web/components.json`, `apps/web/postcss.config.mjs`, `apps/web/package.json`  
**Tags**: ui, dependencies, agent-decided

The component layer is **shadcn (Base UI preset, nova style), vendored into `src/components/ui/`**, with the app's palette kept as the single token source:

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0001: Build and tune the world on rules before wiring in any model

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/**`, `py/src/jeve/decide/policy.py`  
**Tags**: world, testing, agent-decided

Every agent choice goes through a `Policy`, and `RulesPolicy` — deterministic, free, no network — is the first implementation; the model swap is a second implementation of the same protocol, changing nothing upstream.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0002: A tick owns its transaction, and puts its sequences back

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/engine.py`, `py/src/jeve/db.py`, `py/tests/test_resume.py`, `py/tests/test_daemon.py`  
**Tags**: postgres, restart-safety, determinism, agent-decided

`Engine.tick()` ends any open transaction and then does all of its reads and writes inside one real `BEGIN...COMMIT`, so a tick is durable and visible to other sessions the moment it returns. Every serial column's sequence is reset to `max+1` when an engine starts and after any tick that raises.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0003: Space is load-bearing — zones, encounters, and an escalation that reaches billing

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/space.py`, `py/src/jeve/world/map.py`, `py/migrations/0003_space.sql`, `py/tests/test_space.py`  
**Tags**: space, encounters, causality, jev, agent-decided

Each open tick, each member of staff makes one `agent.tick` decision from where they stand now: where to go next, whether to talk, to whom, about what, their mood, and — only when it is possible — whether to press the vendor about an outage. Encounters resolve among people co-located *now*; then everyone moves.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0004: Four more flows, each built to carry a cascade somewhere new

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/flows.py`, `py/tests/test_flows.py`, `py/src/jeve/core/clock.py`  
**Tags**: flows, ledger, causality, agent-decided

Four flows, behind the same `Policy` seam as the first six, each with a Jev question set, a rules twin, and tests that fail without it. In every one the model decides a judgement; amounts, eligibility and whether the cash exists are rules.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0005: The economy closes - tickets end, months recur, bills get answered, wages come back

**Status**: accepted (2026-09-20)  
**Scope**: `py/src/jeve/world/**`, `py/src/jeve/decide/questions.py`, `py/src/jeve/decide/policy.py`, `py/migrations/**`  
**Tags**: economy, flows, soak, agent-decided

- **Tickets end.** An answered ticket is confirmed by its reporter (a decision) once the module is back, or closes by rule after two days. The same person hitting the same module within three days reopens it rather than filing anew. - **Months recur.** `month.end`, `close.run`, payroll and catering reschedule themselves; scheduled work is a registry of handlers, each marked `office_hours_only` or not, replacing a nine-branch `if`. - **Every bill is answered once a day.** From two days before it is due, each unpaid invoice gets one `payment.timing` question per sim-day, at an hour that belongs to the payer (CORE-0009), sampled once — not a per-tick hazard. The per-tick `LIMIT` windows go, and with them 1,591 `payment.deferred` events that recorded a die being rolled. A bill seven days late is chased by its issuer (`chase.invoice`, where `vocality` finally reaches a question). Clients in the four prompter quintiles pay by standing instruction on the due date: a gate, not a question. - **Wages come back.** Staff are paid into a household account and spend from it at the cafe. Households are accounts without an org, funded by an opening balance against `external`; payroll is four legs. - **The books open mid-story.** The seed includes last month's invoices falling due in the first week, so collection is visible inside a ten-day run. Initial conditions, not outcomes. - **Gates are written once** (`decide/gates.py`) and read by both policies: not due, cannot afford, already open. - **`make soak`** runs 35 days on rules and asserts invariants, not outcomes: the ledger balances; tickets opened in week five; a second month-end and its close; no receivable older than sixty days unanswered; every firm that trends to zero has an `insolvency.warning` that names why; every counterparty segment acts. It writes `ops/soak.md`. If behaviour sinks a firm, that is reported.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0007: Run episodes in every world, with no switch

**Status**: accepted (2026-09-23)  
**Scope**: `py/src/jeve/world/episodes.py`, `py/src/jeve/world/engine.py`, `py/src/jeve/sim/daemon.py`, `py/src/jeve/sim/soak.py`, `py/tests/test_episodes.py`  
**Tags**: episodes, defaults, encounters, resolution

Episodes run in every world the daemon runs, with no flag, environment variable or make variable. The mechanism is WORLD-0006's, with the outage stake corrected (below).

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

### WORLD-0008: Conversations remember their rounds, end when people are done, and recurse two deep

**Status**: accepted (2026-09-23)  
**Scope**: `py/src/jeve/world/episodes.py`, `py/src/jeve/decide/questions.py`, `py/src/jeve/decide/policy.py`, `py/src/jeve/memory/store.py`, `py/migrations/0010_episode_depth_and_stall.sql`, `py/tests/test_episodes.py`  
**Tags**: episodes, recursion, realism, memory, resolution

- **Rounds remember.** Every round's state says what each person did in the round just gone (by the same neutral labels) and how long they have been at it, so round N depends on round N−1. - **People end conversations.** Each person is asked whether they have had their say, not whether the matter is solved. A round in which everyone repeats their last act ends the episode as `stalled`, as the recursion research pre-registered ("rounds continue only on state change"). - **Two deep, by dependency.** `MAX_DEPTH = 2`, in code and in migration 0010. After an episode closes, a pair who have a *different* outage or bill between them take it aside (never a matter an ancestor was about), and news can ripple a second table further. Both count against the daily ceiling. - **Memory is read back.** How someone heard of an outage reaches their first decision to report it; a payer's last kept or broken promise to a firm reaches the next conversation about a bill. Both are appended only when present, so first-hand and first-time questions keep their bytes.

This decision is immutable. To change it, write a new record and set `superseded-by` on this one — do not edit its substance.

---

