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

## Secrets

Worker secrets are edited in Doppler `worker/prd` and nowhere else. Doppler's
Fly.io sync (`worker` → Syncs → Fly.io, app `jeve-backend`, config `prd`)
pushes the whole config to the app's `fly secrets`; with the sync's restart
option on, the machines restart to pick it up, and otherwise they do at the
next deploy. Nothing in CI or in this repo sets them.

* `worker/prd` holds only what production needs beyond `fly.toml`:
  `OPENROUTER_API_KEY`, `JEVE_DATABASE_URL` (direct), `MIGRATIONS_DB_URL` (the
  DDL role `release_command` migrates with), and optionally
  `JEVE_DATABASE_POOLED_URL`, `JEVE_DAILY_BUDGET_USD` and
  `BRAINTRUST_API_KEY` / `BRAINTRUST_PROJECT_ID`.
  `docs/environment-variables.md` describes each. Don't seed it from
  `.env.worker.example` or `worker/dev`: their local values (a `127.0.0.1`
  database, `JEVE_CALLS=replay`) would become production's.
* Don't `fly secrets set` a worker secret: the next sync overwrites it.
* A Fly secret beats a `fly.toml` `[env]` value of the same name, so a name in
  both `worker/prd` and `[env]` takes Doppler's value. Keep the knobs
  `fly.toml` sets (`JEVE_DIALOGUE_GENERATE=off`, the `JEVE_*_CEILING_USD`
  ladder, `JEVE_NIGHT_SPEEDUP`, `JEVE_OPS_DIR`, …) out of `worker/prd` unless
  you mean to override production: a copied dev value such as
  `JEVE_DIALOGUE_GENERATE=on` would let the public API spend.
* A secret change reaches a running machine only when it restarts: at once
  if the sync's restart option is on, otherwise at the next deploy.
* Without `BRAINTRUST_API_KEY`, `jeve.tracing` is a silent no-op (LLM-0008);
  `/state`'s `health.tracing` says whether the app has the key.

## First deploy

```bash
fly apps create jeve-backend      # the sync and the deploy both target it

# Postgres (or use an external provider). Put its connection string in
# Doppler worker/prd as JEVE_DATABASE_URL rather than `fly postgres attach`,
# which writes DATABASE_URL onto the app outside Doppler.
fly postgres create --name jeve-db --region iad

# Secrets: fill Doppler worker/prd and set up its Fly.io sync (see above).

# --ha=false: one api and one sim; the default adds a spare of each.
fly deploy --ha=false # release_command runs migrations, then api + sim
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
# Retune without a code change: set JEVE_HALT_CEILING_USD (or any knob) in
# Doppler worker/prd. It beats fly.toml's [env], and it takes effect when the
# machines restart: at once with the sync's restart option on, otherwise at
# the next deploy (CI deploys on push to main) or on:
fly secrets deploy -a jeve-backend         # roll out staged secrets now
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
Restore is a fresh cluster + `psql < backup.sql`, then point every database
URL at it in Doppler `worker/prd` — `JEVE_DATABASE_URL`, `MIGRATIONS_DB_URL`
and `JEVE_DATABASE_POOLED_URL` if set — so the daemon, the api and the next
migration all see the same cluster. A `DATABASE_URL` on the app is read only
when `JEVE_DATABASE_URL` is absent.

**Spend**: `make spend` reads the `spend_entries` table directly (the
`ops/spend.json` checkpoint is a local convenience). The same table backs
`/economics`, so the daemon and the API never disagree.

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
