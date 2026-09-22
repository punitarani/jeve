# Environment Variables

Only variables the code actually reads are listed here — if a name is not in
this table, setting it does nothing. Sources: `py/src/jeve/config.py`,
`py/src/jeve/db.py`, `py/src/jeve/sim/daemon.py`, `py/src/jeve/sim/runner.py`,
`py/src/jeve/tracing.py`, `py/src/jeve/telemetry.py`.

## Database

| Variable | Read by | Default | Notes |
|---|---|---|---|
| `JEVE_DATABASE_URL` | everything | `postgresql://jeve:jeve@127.0.0.1:55432/jeve` | The **direct** DSN. The daemon's writer lock and migrations require it — never a transaction-mode pooler. |
| `DATABASE_URL` | everything | — | Fallback; `fly postgres attach` writes this. |
| `JEVE_DATABASE_POOLED_URL` | api | falls back to `DATABASE_URL` then `JEVE_DATABASE_URL` | Pooled reads for HTTP requests. |
| `JEVE_PG_PORT` | `db.dsn()` | `55432` | Local-only default port when no URL is set. |

## Money (`jeve.llm`, LLM-0004/LLM-0007)

| Variable | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | unset | Required for any live call; absent means replay-only. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | The decisions endpoint is resolved as its sibling (`/api/alpha/decisions`). |
| `JEVE_RUN_CAP_USD` | `1` | Per-process cap; **`<= 0` disables** — set `0` in production. |
| `JEVE_EXPLORE_CEILING_USD` | `12` | Past this, `explore` calls are refused. |
| `JEVE_HALT_CEILING_USD` | `16` | Past this, all calls are refused (the handoff rung). |
| `JEVE_HARD_CEILING_USD` | `20` | Projection may not cross it, ever. |

The ladder is the guardrail; OpenRouter's account cap is the stop. A 402
puts the daemon into `waiting_on_budget`, not a crash (SIM-0003).

**These defaults are the development ones and they halt a long run.**
`JEVE_RUN_CAP_USD=1` stops one process dead at a dollar, and the ladder is
measured against *lifetime* ledger spend, so `JEVE_HALT_CEILING_USD=16` halts
every future process too. `fly.toml` and `docker-compose.prod.yml` set the cap
to `0` and the ladder to `10000` for exactly this reason; anything running for
more than an afternoon wants the same, plus an account cap at OpenRouter.

## Daemon (`python -m jeve.sim`)

| Variable | Flag | Default | Notes |
|---|---|---|---|
| `JEVE_POLICY` | `--policy` | `jev` | `rules` runs the world free, for soak tests. |
| `JEVE_CALLS` | `--calls` | `replay` | `record` for production — replay is the deterministic dev mode. |
| `JEVE_CASSETTE` | `--cassette` | `py/fixtures/cassettes/golden.jsonl` | `off`/`none` disables the file; production uses the `model_calls` table. |
| `JEVE_SIM_DAY_MINUTES` | `--day-minutes` | `24` | Wall minutes per sim day; `0` is flat-out (fixtures). |
| `JEVE_NIGHT_SPEEDUP` | `--night-speedup` | `10` | How much faster than the open hours dead time passes (SIM-0004). Must be positive. At `60` a weeknight is 13 real seconds instead of 78, and costs nothing — nothing calls a model while the town is shut. |
| `JEVE_DAILY_BUDGET_USD` | `--daily-budget` | `2` | Governor pauses the clock when the window's spend exceeds it. |
| `JEVE_BUDGET_WAIT_S` | `--budget-wait` | `900` | Seconds between retries while OpenRouter says 402. |

## API (`uvicorn jeve.api.app:app`)

| Variable | Default | Notes |
|---|---|---|
| `JEVE_CORS_ORIGINS` | unset → localhost any port | Comma-separated origins; production is `https://jeve.punitarani.com`. |
| `JEVE_DIALOGUE_GENERATE` | `on` | `off`/`0`/`false`: `/encounters/{seq}/dialogue` serves the typed record and cached prose only — no spend. |
| `JEVE_OPS_DIR` | repo `ops/` | Where the `spend.json` checkpoint and `discrepancies.jsonl` land. |

## Observability (`jeve.tracing`, LLM-0008)

| Variable | Default | Notes |
|---|---|---|
| `BRAINTRUST_API_KEY` | unset | The only switch. Absent, `jeve.tracing` never imports the SDK and opens no socket — CI and a clean clone trace nothing. Unset it to turn tracing off. |
| `BRAINTRUST_PROJECT_ID` | unset | Which project spans land in; unset falls back to a project named `jeve`. An id rather than a name, so renaming the project does not strand its spans. |

Spans carry OpenRouter's reported cost as `metrics.estimated_cost`, so a trace
and the `spend_entries` ledger price a call the same way. A tracing failure is
never fatal: it prints one line and latches off for the process.

## Observability (`jeve.telemetry`, CORE-0012)

Errors, traces, metrics and structured logs to Sentry. One project per
process; the DSN is the only switch, and the same three rules as Braintrust
apply — unset means no import and no socket, a failure prints one line and
latches off, nothing on the wire changes.

| Variable | Read by | Default | Notes |
|---|---|---|---|
| `SENTRY_DSN_API` | api | unset | The API's project. `/state`'s `health.sentry` says whether it is present. |
| `SENTRY_DSN_SIM` | sim | unset | The daemon's project. |
| `SENTRY_DSN` | both | unset | Fallback when the per-service one is unset — a compose stack, or one project for everything. Never the other service's DSN. |
| `SENTRY_ENVIRONMENT` | both | `development` | `fly.toml` sets `production`. |
| `SENTRY_RELEASE` | both | `FLY_IMAGE_REF`, else unset | Names the deploy that is running. |

Traces run in Sentry's stream mode: one root span per tick (`sim.tick`) with
the model calls nested under it, one per API request named by route template
(`/causal/{seq}`). `/health` and `/stream` are never traced. The daemon's
prints are unchanged; `sim_meta.status` transitions are the structured log
(`sim status: …`), halts are issues tagged `sim.exit_code`, and weather
(SIM-0002) is a count, never an issue.

## Test hooks

| Variable | Read by | Notes |
|---|---|---|
| `JEVE_TEST_DIE_AT_EVENT` | `world/engine.py` | Crash-injection: raise inside the tick at this event seq. Used by `test_resume.py`; never set it in production. |

## Web (`apps/web`)

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_JEVE_API` | `http://127.0.0.1:8000` | **Build-time inlined** (WEB-0005). Production: `https://jeve-api.punitarani.com`. |
| `NEXT_PUBLIC_SENTRY_DSN` | unset | **Build-time inlined** (CORE-0012). The browser's project; unset, the SDK is a no-op and no request leaves the page. Public by nature — it ships in the bundle. |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `development` | Build-time; CI sets `production`. |
| `SENTRY_ORG`, `SENTRY_PROJECT` | unset | Build-time, `next.config.ts` only: where source maps are uploaded. Nothing happens without `SENTRY_AUTH_TOKEN`. |

## CI/CD credentials (GitHub secrets / Doppler `infra`)

`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `FLY_API_TOKEN`. Nothing in
the codebase reads them; they authenticate the deploy jobs. `SENTRY_AUTH_TOKEN`
is read by `next.config.ts` during the `deploy-web` build to upload source
maps; without it (the `web` and `docker` jobs, `make e2e`) no source maps are
generated at all, so `out/` never carries a `.map`.

## Doppler layout

Three projects, matching the `.env.*.example` files:

* **app** — `NEXT_PUBLIC_JEVE_API`, `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_ORG`,
  `SENTRY_PROJECT` (build-time only; in CI they are repository `vars`)
* **worker** — everything above for api + sim, `SENTRY_DSN_API` and
  `SENTRY_DSN_SIM` included; synced to `fly secrets`
* **infra** — the CI/CD credentials, `SENTRY_AUTH_TOKEN` included

```bash
doppler run --project worker --config dev -- make api
doppler run --project infra  --config prd -- make deploy
```
