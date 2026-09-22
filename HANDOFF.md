# Handoff

Jeve is a continuously-running simulation of a twelve-firm district economy
(two software vendors, a law firm, an accountancy, a landlord, a cafe, a
dental clinic, an architecture studio, a credit union, a hardware store, a
gym and a provisions supplier; the roster is `py/src/jeve/core/orgs.py`).
Agents act through *typed* decisions from Jev over OpenRouter; prose
is a projection, never an input. State lives in Postgres; the browser reads
it through a FastAPI on Fly.io and renders a voxel town from a static
Cloudflare site.

## Verified state (branch `claude/simulation-entity-expansion-b9bh1k`, PR #15)

* `make check` — ruff, `mypy --strict` (69 files), 397 tests, contracts in
  sync, 52 decision records. `make soak` — 35 sim-days on rules, 12 of 12
  invariants (`ops/soak.md`): rent paid, shelves restocked, every line of
  credit serviced, both vendors triaged, churn and the price rise's
  diffusion measured. Playwright passes against a rules stack
  (`JEVE_E2E_POLICY=rules make e2e`) on the installed Chromium.
* **No cassette.** The district changed every wire byte, and this box has no
  `OPENROUTER_API_KEY`, so `py/fixtures/cassettes/golden.jsonl` is gone until
  `LIVE=1 make e2e` runs on a machine with a key (three phases' worth of
  wording, one recording, ~$0.10). Until then `make e2e` needs
  `JEVE_E2E_POLICY=rules`, and `ops/economics.md` describes the four-firm
  street.
* Production topology runs locally: `docker compose -f docker-compose.prod.yml
  up` brings postgres → migrate → api+sim → web up in order; the daemon
  ticks with live Jev decisions and the API serves `/state`, `/events`,
  `/stream` with seq cursors.
* Restart recovery is real: `kill -9` mid-tick, restart, events stay
  contiguous with no duplicates and the ledger still balances.
* `fly config validate` and `wrangler deploy --dry-run` are clean.
* 36 audit screenshots in `docs/audit/shots/` at ~61fps on SwiftShader.

## Not yet done

* **Nothing is deployed.** Fly app, Cloudflare site, and secrets exist only
  as configuration. `docs/deployment.md` is the checklist: `fly postgres
  create` + `attach`, `fly secrets set OPENROUTER_API_KEY` +
  `JEVE_DATABASE_URL`, `fly deploy`, then `wrangler deploy` with
  `NEXT_PUBLIC_JEVE_API` baked in.
* `JEVE_POLICY=jev` in production spends real money continuously. The
  guardrail ladder is env-tunable (`JEVE_*_CEILING_USD`, `JEVE_RUN_CAP_USD=0`
  in prod); the hard stop is the OpenRouter account cap — set it.
* The store must be Postgres (advisory locks, `FILTER`, psycopg) — the
  engine is the constraint, not the host; see `docs/deployment.md`.

## Where things live

| What | Where |
|---|---|
| Run loop | `python -m jeve.sim` (`py/src/jeve/sim`) |
| API | `py/src/jeve/api/app.py` |
| Spend ledger | `spend_entries` table (LLM-0007); `ops/spend.json` is a mirror |
| Frontend | `apps/web` → static `out/` → `wrangler deploy` |
| Deploy config | `fly.toml`, `apps/web/wrangler.toml`, `docker-compose.prod.yml` |
| Loop ledger | `docs/ops/current-loop.md` |

Rules of the house are in `AGENTS.md`; the immutable architecture decisions
are indexed in `decisions/INDEX.md`.
