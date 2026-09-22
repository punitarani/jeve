# Deployment

How jeve runs in production (OPS-0001), and how to operate it.

## Topology

| Piece | Where | Notes |
|---|---|---|
| Web (`apps/web`) | Cloudflare Workers static assets | `output: "export"` → `out/`; no Worker script, no SSR (WEB-0005) |
| API (`py/src/jeve/api`) | Fly.io process group `api` | uvicorn on a `psycopg_pool`; public at `jeve-api.punitarani.com` |
| Daemon (`py/src/jeve/sim`) | Fly.io process group `sim` | No ingress; the only writer, on the direct DSN |
| Postgres | Fly Postgres (or any managed PG) | us-east-1; app region `iad` |
| Secrets | Doppler → `fly secrets` / GitHub Actions | Nothing sensitive in `fly.toml`/`wrangler.toml` |

```mermaid
flowchart LR
    browser -->|HTTPS| cf[Workers static assets<br/>jeve.punitarani.com]
    browser -->|GET /state, /stream| api[api process group<br/>jeve-api.punitarani.com]
    api --> pool[JEVE_DATABASE_POOLED_URL]
    sim[sim process group<br/>python -m jeve.sim] --> direct[JEVE_DATABASE_URL]
    pool --> pg[(Postgres)]
    direct --> pg
    sim -->|OpenRouter| or[OpenRouter]
```

Why two database URLs: the daemon's writer lock is a *session-level*
advisory lock, which a transaction-mode pooler silently drops. `sim` uses
`JEVE_DATABASE_URL` (direct); `api` uses `JEVE_DATABASE_POOLED_URL` when set
and falls back to the direct DSN. `DATABASE_URL` (what `fly postgres attach`
writes) is accepted as a fallback for both.

The store must be Postgres, whoever hosts it: the writer lock and the spend
ledger both ride `pg_advisory_xact_lock`, migrations use Postgres SQL
(`FILTER`, `jsonb`, advisory locks), and the driver is psycopg. PlanetScale's
Postgres product can satisfy that; its Vitess/MySQL line cannot — and a
non-Postgres store is a new decision record and a storage-port, not a config
change (LLM-0007).

## First deploy

```bash
# Postgres (or point JEVE_DATABASE_URL at an external provider)
fly postgres create --name jeve-db --region iad
fly postgres attach jeve-db --app jeve-backend   # sets DATABASE_URL

fly secrets set OPENROUTER_API_KEY=...           # the only billable path
fly secrets set JEVE_DATABASE_URL=postgresql://...@jeve-db.internal:5432/jeve
# Optional. Without a key, jeve.tracing is a no-op and nothing is traced —
# silently, by design (LLM-0008). Nothing in CI sets these: `flyctl deploy`
# does not read Doppler, so they arrive by `fly secrets set` or a Doppler
# Config Sync. `/state`'s `health.tracing` says whether the app has the key.
fly secrets set BRAINTRUST_API_KEY=...
fly secrets set BRAINTRUST_PROJECT_ID=...        # unset: a project named jeve
# Optional, if you front Postgres with a transaction-mode pooler:
fly secrets set JEVE_DATABASE_POOLED_URL=postgresql://...:6432/jeve

fly deploy            # release_command runs migrations, then api + sim
cd apps/web && NEXT_PUBLIC_JEVE_API=https://jeve-api.punitarani.com \
    pnpm exec next build && wrangler deploy
```

CI does the same on push to `main` (`deploy-backend`, `deploy-web` in
`.github/workflows/ci.yml`), gated on tests, contracts drift and image builds.

## Production bootstrap (what the first real deploy needed)

PlanetScale Postgres gives two roles: a DDL-capable migration role and a
read-write app role with `SELECT`/`INSERT`/`UPDATE`/`DELETE` — no `CREATE`,
no `TRUNCATE`, no sequence ownership. That shaped three things:

* `fly.toml`'s `release_command` exports `MIGRATIONS_DB_URL` as
  `JEVE_DATABASE_URL`, so migrations run under the DDL role while the app
  keeps the least-privilege DSN.
* `db.applied()` checks `to_regclass` before `CREATE TABLE` — `IF NOT EXISTS`
  still requires `CREATE` privilege, so the sim cannot boot against a
  migrated schema without it.
* The world was seeded once under the migration role
  (`JEVE_DATABASE_URL=$MIGRATIONS_DB_URL` + `seed()`). The daemon's own
  `not seeded → seed()` path needs `TRUNCATE ... RESTART IDENTITY`, and
  `RESTART IDENTITY` requires sequence *ownership*, which identity columns
  cannot hand out. The app role holds a `TRUNCATE` grant (plus
  `ALTER DEFAULT PRIVILEGES` for future tables), but a wipe-and-reseed is
  an operator action under the migration role, not something the daemon
  can do alone.

Machine topology is 1 api + 1 sim — `fly deploy --ha=false` in CI keeps it
that way; the default creates a spare machine per group, and a second sim
can never write anyway (the advisory lock is the single writer, SIM-0001).

## What production runs with

The sim group's command is
`sh /app/sim-entrypoint.sh --policy jev --calls record --cassette off`:

* **`--calls record`** — every model response is stored in `model_calls`,
  which is the replayable cache. Production never replays.
* **`--cassette off`** — the golden cassette is a dev artifact. In a
  container it would be an unbounded append on ephemeral disk.
* **The entrypoint maps deliberate halts (exit 4–7) to exit 0.** Fly's
  default `on-fail` policy restarts non-zero exits only, so a crash comes
  back and a halt stays down until you redeploy or `fly machines start`.

Budgets (LLM-0007): `JEVE_RUN_CAP_USD=0` disables the per-process cap — the
old default ($1) would have halted the daemon every few days. The
$12/$16/$20 ladder is a development guardrail measured against *lifetime*
ledger spend: left at its defaults it would halt the daemon permanently at
$16 cumulative, so `fly.toml` sets `JEVE_{EXPLORE,HALT,HARD}_CEILING_USD` to
$10k — high enough never to bind in a real run, still a backstop if the
account cap were ever unset. OpenRouter's own cap is the real ceiling.

**Telemetry (OBS-0001)** is off until `AXIOM_TOKEN` is set. `fly.toml`
carries the three non-secret settings (`AXIOM_DOMAIN`, `AXIOM_DATASET`,
`AXIOM_METRICS_DATASET`); the token is a secret. With it unset the processes
run exactly as they did before — no exporter, no thread, no socket — so
turning it on and off is a `fly secrets` call, not a redeploy of different
code.

## Statuses worth knowing

`sim_meta.status`, surfaced by `GET /state` as `clock.status` + `health`:

| Status | Meaning | Operator action |
|---|---|---|
| `running` | ticking | — |
| `waiting_on_model` | provider outage; tick rolls back and retries | none — it heals |
| `waiting_on_budget` | OpenRouter answered 402 (cap spent); retries every `JEVE_BUDGET_WAIT_S` (default 15 min) | top up credit, or wait out the window |
| `paused_budget` | `JEVE_DAILY_BUDGET_USD` spent for the window; clock resumes at rollover | raise the budget or wait |
| `paused` | `--until` horizon reached | — |
| `halted` | deliberate stop (replay miss, cap, model drift) | read `last_error`, fix, redeploy |

`health.stale` goes true whenever the heartbeat is older than 30 s — a
`running` written by a dead process is not alive.

## Endpoints

`GET /health` — 200 only when Postgres answers. `GET /state`, `/events`,
`/world/*`, `/causal/{seq}`, `/economics` — pooled reads.
`GET /stream?after=<seq>` — SSE; one shared poller fans out to subscribers.
`GET /encounters/{seq}/dialogue` — typed record always; prose only from the
cache in production (`JEVE_DIALOGUE_GENERATE=off`), because the endpoint is
unauthenticated and can spend.

## Operations

```bash
fly logs -a jeve-backend --process sim     # the daemon's voice
fly checks list -a jeve-backend            # api health
fly ssh console -a jeve-backend            # a shell inside a machine
fly secrets set JEVE_HALT_CEILING_USD=...  # retune without a redeploy
```

**Rollback**: `fly releases` lists image versions;
`fly deploy --image <previous>` restores one. Migrations are additive, so a
rollback does not need a schema undo. If a migration ever must be reversed,
revert it explicitly rather than replaying history.

**Backup**: Postgres is the whole world — events, decisions, model\_calls,
spend ledger. For Fly Postgres, snapshot the volume:
`fly volumes snapshots list <vol>` / `fly volumes create --snapshot-id`.
Logical copy: `fly proxy 5433:5432 -a jeve-db` then
`pg_dump postgresql://jeve:...@localhost:5433/jeve > backup.sql`.
Restore is a fresh cluster + `psql < backup.sql` + `fly secrets set
JEVE_DATABASE_URL=...`.

**Spend**: `make spend` reads the `spend_entries` table directly (the
`ops/spend.json` checkpoint is a local convenience). The same table backs
`/economics`, so the daemon and the API never disagree.

### Telemetry (OBS-0001)

Turning it on, once:

```bash
# Two datasets in Axiom: `jeve` (an events dataset — traces and logs) and
# `jeve-metrics`, which must be created as a *metrics* dataset. Metrics route
# through X-Axiom-Metrics-Dataset, a different header from the other two.
doppler secrets set AXIOM_TOKEN --project worker --config prd
fly secrets set AXIOM_TOKEN=xaat-... -a jeve-backend   # restarts both groups
```

Then, within a minute:

```kusto
['jeve']         | where ['service.name'] == "jeve-sim" and name == "sim.tick"
['jeve']         | where ['service.name'] == "jeve-api"
['jeve-metrics'] | where name in ("jeve.sim.tick.lag", "jeve.sim.heartbeat.age")
```

`fly logs` is unchanged by design: `obs.log` writes the same line to the same
stream it always did and sends the structured fields only to Axiom, so every
grep in this document still works.

Worth alerting on: `jeve.sim.heartbeat.age` climbing past 30s (the daemon is
gone — the API publishes this, so a dead sim is a *rising* number rather than
a series that stops), `jeve.sim.status.transitions` into `halted`,
`jeve.spend.effective` slope, and `jeve.api.stream.poll.errors` above zero.

Verifying without Axiom — point it at any OTLP collector:

```bash
AXIOM_DOMAIN=http://127.0.0.1:4318 AXIOM_TOKEN=local make obs-probe
```

**Cloudflare**: `apps/web/wrangler.toml` already enables Workers observability
at full sampling. Getting those logs into Axiom is a **Logpush** connection
set up in the Cloudflare and Axiom dashboards — there is no code for it, and
there must not be: the Worker is assets-only (`directory = "out"`, no `main`),
and adding a script would contradict WEB-0005.

## Data growth (measured)

35 sim-days ≈ 14,764 events / 31,623 decisions / 50 MB. At ~60 sim-days per
real day that is ≈86 MB/day, ≈2.6 GB/month, ≈31 GB/year. The decision is to
keep everything — causal history is the research artefact — so size the
Postgres volume for it and snapshot before growing it. If that ever changes,
retention is an `events`/`decisions` prune job, not a schema change.

## Self-hosting alternative

`docker-compose.prod.yml` runs the same topology locally: Postgres (internal
only), a `migrate` one-shot, api on 8000, the static site behind nginx on
3000, and the daemon with the same entrypoint semantics.

```bash
OPENROUTER_API_KEY=... docker compose -f docker-compose.prod.yml up -d --build
```
