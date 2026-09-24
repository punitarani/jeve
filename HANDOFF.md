# Handoff

Jeve is a continuously-running simulation of a four-firm street economy
(Tallybird Software, Halloran & Pike LLP, Ledgerline Accounting, Third Rail
Cafe). Agents act through *typed* decisions from Jev over OpenRouter; prose
is a projection, never an input. State lives in Postgres; the browser reads
it through a FastAPI on Fly.io and renders a voxel town from a static
Cloudflare site.

## Verified state (local `main`, not pushed)

* `make check` — ruff, `mypy --strict` (62 files), 259 tests, contracts in
  sync, 39 decision records. `make e2e` — full stack on cassette replay,
  14/14 Playwright, $0.00 spend. `make soak` — 35 sim-days on rules, all
  invariants, counterfactual arms diverge.
* Production topology runs locally: `docker compose -f docker-compose.prod.yml
  up` brings postgres → migrate → api+sim → web up in order; the daemon
  ticks with live Jev decisions and the API serves `/state`, `/events`,
  `/stream` with seq cursors.
* Restart recovery is real: `kill -9` mid-tick, restart, events stay
  contiguous with no duplicates and the ledger still balances.
* `fly config validate` and `wrangler deploy --dry-run` are clean.
* 36 audit screenshots in `docs/audit/shots/` at ~61fps on SwiftShader.

## Since then: episodes (WORLD-0006, WORLD-0007, WORLD-0008, MEM-0002)

A meeting with a stake between the people in it can now get up to three rounds
instead of one shot, and has somewhere to write the result: facts that travel,
promises that are scored. **On in every world the daemon runs**, with no flag
(WORLD-0007); the one-shot encounter still resolves every meeting without a
stake, and is the control arm `make episodes` compares against.

* WORLD-0008, from the first live episodes: rounds are told what happened in
  the last one, each person says whether they have had their say, a round that
  repeats the last ends the episode as `stalled`, and recursion goes two deep —
  news ripples a table further, and a pair with a second matter between them
  takes it aside. Hearsay distance reaches the decision to report an outage, and
  a broken promise reaches the next conversation about a bill.
* `make episodes` plays the same 21 sim-days twice, with and without, and writes
  `ops/episodes.md`. Over five seeds on rules: episodes cut total outage minutes
  by about a quarter (2,703 → 2,058) and bring the first services invoice
  forward about 7 hours, at +2.4% decisions — and the two resolutions
  **disagree** about how often a conversation gets an outage escalated (mean gap
  +0.47; +0.59 live in production before WORLD-0008), so the dial moves base
  rates too. That gap was an upper bound until the episodes-off arm began
  recording each encounter's shadow stake (below); read the default world's
  escalation rate as a property of this resolution, not a finding. (The first, one-seed figures — ~16h, 0.72 — were inflated by a
  Tallybird employee counting as a customer stuck on the outage; fixed with
  WORLD-0007.)
* The survey behind it is `docs/research/03-recursive-micro-simulation.md`; the
  design analysis is `docs/design/011-episodes.md`.
* `GET /episodes` and `GET /episodes/{id}` serve the typed record, its rounds,
  and what it caused. No prose, and none is rendered on request.

## Since then: the field report's review (WORLD-0009 to WORLD-0012, MEM-0003, DECIDE-0005, API-0004)

golden-20260920's field report found a world whose mechanics held and whose
economy and perception did not. The review fixed its defects and built what it
found missing. `ops/field-report-v2.md` sets the base commit against the result,
30 sim-days each on rules.

* **Decision points (WORLD-0009).** `agent.tick` is asked at arrival, away, in
  company, on a change of mind, through lunch and on the hour; a room is at most
  three firms; money reaches what is on somebody's mind.
* **Economy (WORLD-0010).** Rent, stock, tax, household spending per employer,
  seat pricing, departures after missed paydays, monthly reviews, hiring, loans
  and failure. A running world gets all of it at engine start (`economy.install`),
  under the writer lock: no reseed.
* **Loops (WORLD-0011).** Engineering debt and deploys, trust and churn,
  workarounds, disputes, logged hours, the cafe's cover, stock and catering,
  Ledgerline's close queue, and a shock deck.
* **Escalation routing (WORLD-0012).** An engineer acts at once; anyone else
  decides whether to relay; procedure halves an outage, a face quarters it.
* **Memory (MEM-0003).** Trust is a typed belief; late payroll, insolvency,
  churn and broken promises travel; a rumour can be false.
* **Tier 1 (DECIDE-0005).** Uncertain medium- and high-stakes Jev answers are
  asked again of a flash model in the same typed shape. Production runs it in
  **shadow**; a set acts on it only when named in `JEVE_ESCALATION_LIVE`.
* **Detectors (API-0004).** Eight on `/report`, each tested by breaking a
  healthy world. The soak holds 12 invariants.
* **The docking gap, split.** Over five seeds the one-shot encounter and the
  episode disagree by +0.36 about how often a meeting escalates an outage, and
  almost all of it is resolution, not selection (`ops/episodes.md`): three
  rounds escalate what one shot does not. Recalibrating the one-shot question
  is the open item.

### Needs a key, and a person

* **Re-record the golden cassette** with `LIVE=1 make e2e`: nearly every
  question set's wording changed, so replay tests skip and `make e2e` in replay
  exits early until it is committed.
* `make situation-probe` (does the situation now move Jev as much as the
  person?), `make providers` (can each model return a typed tier-1 answer?),
  and after a week of shadow, `make escalation-report` before naming any set
  live. `make judge-panel LIVE=1` puts cached contexts to three model families
  (under $1).

## Not yet done

* **Deploys are CI's.** A push to `main` ships api + sim to Fly and then the
  site to Cloudflare (OPS-0003). Worker secrets live in Doppler `worker/prd`,
  which Doppler's Fly.io sync keeps on the app; nobody runs
  `fly secrets set`. The site's API host is baked in at build time from the
  GitHub repository variable `NEXT_PUBLIC_JEVE_API`. `docs/deployment.md` is
  the runbook.
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
