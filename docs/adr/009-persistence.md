# ADR-009 — Persistence schema and read pattern

Status: proposed · 2026-09-20

## Decision

**Postgres. One transaction per tick. An append-only event log with causal links, beside
typed current-state tables whose invariants are database constraints. No Redis.**

The shape is workbench's run store (`events`, `scheduled`, `snapshots`, `run_meta`, one
commit per engine step — 00 §6.5), ported from SQLite and extended for a process that never
ends and has a second process reading it.

## Schema

**Control**

| Table | Purpose |
|---|---|
| `sim_meta` | Singleton: run id, root seed, `sim_time`, `tick_seq`, status (`running`, `paused`, `waiting_on_model`, `halted`), engine git sha, governor state. |
| `scheduled` | The discrete-event queue, durable: `(due_sim_time, ord)`, kind, agent, payload. |
| `jobs` | Async work (tier 1 escalation, rendering, ontology proposals): status, lease, attempts, idempotency key. Claimed with `FOR UPDATE SKIP LOCKED`. |
| `spend_ledger` | Per call: provider, tokens, dollars. The governor's input; persisted so a restart does not reset the budget (workbench's per-process budget did, 00 §6.5). |

**The record — append-only, partitioned by sim-month**

| Table | Purpose |
|---|---|
| `events` | `seq bigserial`, `sim_time`, `tick_seq`, `kind`, `actor_id`, `org_id`, `payload jsonb` (a closed discriminated union defined in `py-contracts`), **`causes bigint[]`** — the seqs of the events that led to this one — and `decision_id`. |
| `decisions` | Agent, `decision_seq`, tick, question-set version, model-call hash, all returned distributions, PRNG path, draws, chosen, the rule that chose, escalation, flags (ADR-007 §4). |
| `model_calls` | Content hash PK; provider, resolved model version, request (nullable after retention), response, tokens, latency, cost (ADR-007 §3). **Committed as each response arrives, outside the tick transaction.** |
| `belief_history` | Every belief-slot change with its evidence refs. |

`causes` is the most important column in the schema. Every event an agent produces is linked
to the inbox items its decision read; every event the world produces is linked to what
triggered it. A cascade is then a recursive query, not an inference — which is what lets the
UI *show* "outage → tickets → late invoices → cash trough" rather than ask the viewer to
notice it.

**Current state — typed columns, real constraints**

`orgs` (incl. `policy jsonb`: the org's rules as data, ADR-004) · `agents` (role, persona,
status, current task, `decision_seq`, `beliefs jsonb`, schedule) · `accounts` ·
`ledger_entries` (double-entry; a deferred constraint trigger enforces Σ = 0 per
transaction) · `engagements` · `work_items` · `invoices` · `payments` · `tickets` ·
`incidents` · `orders` · `messages` (typed speech acts; `rendered_text` nullable and filled
lazily, with `rendered_by`) · `memories`.

Domain tables are relational, not JSONB, because 02 §3.1's hard invariants — referential
integrity, no negative inventory, work-item conservation — are cheapest and most trustworthy
as foreign keys and check constraints.

**Observation**

`metrics_daily` (sim-day, scope, metric, value) · `alerts` · `snapshots` (sim time, seq,
storage ref) · `studies` / `study_runs` for interventional forks.

## Write path — what makes `kill -9` safe

1. **Decide phase, outside any transaction.** Build state, call Jev concurrently. Each
   response is written to `model_calls` by content hash the moment it arrives.
2. **Commit phase, one transaction.** Domain mutations, `events`, `decisions`, `scheduled`
   inserts and removals, agent updates, memory writes, and the `sim_meta` advance — together
   or not at all.
3. **On restart.** Acquire the lease. Read `sim_meta`. Re-run the tick it names: every model
   call already answered is found by hash, so nothing is paid for twice and the outcome is
   identical. Jobs whose lease has expired are re-queued; their idempotency keys make
   re-execution harmless.

**Single-writer lease.** `events.seq` being contiguous assumes one writer. The sim holds a
session-level Postgres advisory lock for its lifetime; a second sim process fails to acquire
it and exits. This is the guard workbench lacks.

The arbiter is workbench's `test_resume_anywhere` (00 §6.5), lifted: kill the process at
random points, resume, and byte-compare the event log with an uninterrupted run over recorded
model responses.

## Read pattern the frontend needs

The browser talks only to FastAPI. Next.js does not touch Postgres; that would put a second
owner on the schema (ADR-008).

| Need | Endpoint | Backed by |
|---|---|---|
| First paint | `GET /state` → orgs, agents, open work, KPIs, clock, speed, spend, **and the `seq` it is current as of** | Current-state tables, one snapshot read |
| Live updates | `GET /stream?after=<seq>` (SSE) | The tick commit issues `NOTIFY` with the new max seq; the API reads `events WHERE seq > last` and pushes. **The client tails `seq`**, so a dropped connection resumes with no gap and no duplicate. |
| "What happened while I was away" | `GET /events?from_sim=&to_sim=&org=&kind=` | `events (kind, sim_time)`, `(org_id, seq)` |
| **Cascade view** | `GET /causal/{seq}?dir=up\|down` | Recursive CTE over `causes`; GIN index on `causes` |
| "Why did she do that?" | `GET /agents/{id}/decisions` | `decisions (agent_id, decision_seq desc)` — distributions rendered as bars |
| Health | `GET /metrics?metric=&scope=` | `metrics_daily` |
| Lazy prose | `GET /messages/{id}/text` | Returns `rendered_text`, or enqueues a render job and returns 202 |
| Control (bound to localhost; no auth, by your constraint) | `POST /control/{pause\|resume\|speed\|shock\|snapshot}` | Writes a control row the sim reads at the next tick boundary |

## Why no Redis

Everything Redis would do here is already done durably:

| Redis role | What does it instead |
|---|---|
| Pub/sub to viewers | `LISTEN/NOTIFY` — one API process, a handful of viewers |
| Job queue | `jobs` + `SKIP LOCKED` — and it **must** survive `kill -9`, which is the requirement Redis is weakest at |
| Response cache | `model_calls` |
| Rate limiter | An in-process token bucket — there is exactly one sim process |

Adding Redis would add a second durability domain to reason about in every crash-recovery
path, in exchange for throughput this system will never need (about ten thousand decisions
per real day). **It is not load-bearing; it is not included.**

## Growth

At the ADR-003 target, roughly 10k decisions and tens of thousands of events per real day —
tens of millions of event rows per year. Monthly partitions keep indexes small; old
partitions can be detached and archived. `model_calls` bodies expire after 30 real days
(ADR-007). Memory is bounded by design (ADR-006). Nothing here is large by Postgres
standards.

## Forks

A fork is a dump of the current-state and control tables at a tick boundary, restored into a
fresh database, run headless by the study runner with pacing off. Crude, sufficient, and
independent of the live world.

## Alternatives rejected

- **SQLite**, as in workbench. Two processes, `LISTEN/NOTIFY`, partitioning, and your
  constraint all point to Postgres.
- **Pure event sourcing** — state only as a fold over the log. workbench's roll-forward
  resume reads the whole log into memory (00 §6.5): fine at 130 days, unbounded for forever.
  jeve keeps the log *and* materialised state, committed atomically, so neither resume nor
  the dashboard ever replays history.
- **State as JSONB blobs per agent or org.** Loses the constraints that make the ledger
  trustworthy.
- **Next.js reading Postgres directly.** Two owners of one schema.

## Reverse if

- More than one API replica or hundreds of concurrent viewers → put a broker behind the SSE
  fan-out. The sim's write path is unaffected.
- Tick commit time becomes a meaningful share of the tick → batch event inserts; then
  reconsider which domain tables truly need synchronous constraints.
