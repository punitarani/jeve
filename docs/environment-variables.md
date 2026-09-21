# Environment Variables

Only variables the code actually reads are listed here — if a name is not in
this table, setting it does nothing. Sources: `py/src/jeve/config.py`,
`py/src/jeve/db.py`, `py/src/jeve/sim/daemon.py`, `py/src/jeve/sim/runner.py`,
`py/src/jeve/tracing.py`.

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

## Daemon (`python -m jeve.sim`)

| Variable | Flag | Default | Notes |
|---|---|---|---|
| `JEVE_POLICY` | `--policy` | `jev` | `rules` runs the world free, for soak tests. |
| `JEVE_CALLS` | `--calls` | `replay` | `record` for production — replay is the deterministic dev mode. |
| `JEVE_CASSETTE` | `--cassette` | `py/fixtures/cassettes/golden.jsonl` | `off`/`none` disables the file; production uses the `model_calls` table. |
| `JEVE_SIM_DAY_MINUTES` | `--day-minutes` | `24` | Wall minutes per sim day; `0` is flat-out (fixtures). |
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
| `BRAINTRUST_API_KEY` | unset | The switch. Absent, `jeve.tracing` never imports the SDK and opens no socket — CI and a clean clone trace nothing. |
| `BRAINTRUST_PROJECT` | `jeve` | The Braintrust project spans land in. |
| `JEVE_TRACING` | `on` | `off`/`0`/`false`: never trace, even with a key set — killing telemetry without rotating a secret. |
| `BRAINTRUST_API_URL` | unset | Self-hosted Braintrust only. Read by the SDK itself, not by `Settings`. |

Spans carry OpenRouter's reported cost as `metrics.estimated_cost`, so a trace
and the `spend_entries` ledger price a call the same way. A tracing failure is
never fatal: it prints one line and latches off for the process.

## Test hooks

| Variable | Read by | Notes |
|---|---|---|
| `JEVE_TEST_DIE_AT_EVENT` | `world/engine.py` | Crash-injection: raise inside the tick at this event seq. Used by `test_resume.py`; never set it in production. |

## Web (`apps/web`)

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_JEVE_API` | `http://127.0.0.1:8000` | **Build-time inlined** (WEB-0005). Production: `https://jeve-api.punitarani.com`. |

## CI/CD credentials (GitHub secrets / Doppler `infra`)

`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `FLY_API_TOKEN`. Nothing in
the codebase reads them; they authenticate the deploy jobs.

## Doppler layout

Three projects, matching the `.env.*.example` files:

* **app** — `NEXT_PUBLIC_JEVE_API` (build-time only)
* **worker** — everything above for api + sim; synced to `fly secrets`
* **infra** — the CI/CD credentials

```bash
doppler run --project worker --config dev -- make api
doppler run --project infra  --config prd -- make deploy
```
