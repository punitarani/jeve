# Session 3 — stopped early, on the owner's instruction (usage limit)

Session 3 was planned as a 13-14 h build. It was stopped after roughly two hours
of work because the owner has limited usage credits and asked for the branch to be
left mergeable. **Most of the plan was not done.** This section says exactly what
was, what was not, and what is measured.

## What shipped (all on `feat/mvp-overnight`, PR #1)

| Item | State | Evidence |
|---|---|---|
| Daemon survives its model (SIM-0002, LLM-0006) | done | `tests/test_daemon.py`: a 520, a timeout and a malformed response mid-tick leave an event log byte-identical to an untroubled run; heartbeat and `health` on `/state` |
| Cache key v2 (DECIDE-0004) | done | `tests/test_call_key.py`: reorder, reword and new model build are all misses; a different build halts the run |
| Randomness keyed by entity (CORE-0009) | done | `test_economy.py` walks the source for `tick_seq` in a seed path; counterfactual in `ops/soak.md` shows invoice amounts identical across arms while cash differs |
| The economy closes (WORLD-0005) | done | `make soak`: 35 rules-days, 8 invariants, PASS; `ops/soak.live.md`: 10 live days decided by Jev, PASS, $0.0069 per sim-day |
| Gates in one module, scheduler registry, `OrgSpec` data | done | `decide/gates.py`, `world/scheduler.py`, `core/orgs.py` |
| Look: sun shadows, baked AO, four sky states, four distinct buildings, people with heads/hats, lit windows and lamps at night | merged from `ui/look` | `apps/web/decisions/WEB-0004`, `docs/audit/2026-09-22/ui-agent/NOTES.md`; 61 fps on the real GPU in the agent's own shots |
| CI runs against Postgres 18; record confirmations run in a job that has the tools | done | see the PR's checks |

## What was NOT done (cut, not deferred silently)

- **104 embodied staff.** `core/orgs.py` already carries the headcounts (44/24/20/16) and a test-asserted total, and `ui/look` has layouts that fit them, but `world/map.py` is still the 40x28 town and `seed_world.py` still seeds 24 staff. The map sizes and roster are drafted, not applied.
- **Plans, beliefs, encounter outcomes (P3):** no `plans` or `beliefs` tables, no `agent.plan`, no typed knowledge. `agent.tick` is still one Jev call per staff per open tick. Encounters still change exactly one thing (escalation). DECIDE-0001, CORE-0002, WORLD-0003 and MEM-0001 are **not** superseded and MEM-0001 remains unimplemented.
- **5-minute tick:** stayed at 15 minutes. **Quintile trait words, `vocality`/`risk_appetite` rendering:** not done.
- **UI:** `apps/web` is unchanged except the timeline opening on the newest events. No shared client store, no hero camera reframing, no ticker, no bubble work, no `/lab` split, no design tokens, no before/after screenshot set. The UI agent stopped on a usage limit; its uncommitted follow-up (`people.ts`, `people.test.ts`) is still in `.claude/worktrees/` and is not on any branch.
- **P2:** no fault-injection gate over a whole soak (the daemon's survival is unit-tested, not soaked); no eviction of a malformed cached row; the cassette was not pruned.
- **P6:** no README, `.env.example`, `make web`/`make dev`, per-question-set max-p in `ops/economics.md`, or org-as-data design doc. The scheduled ADR reconciliation (CORE-0004 / DECIDE-0002) was not done.

## Findings worth your attention

- **Money circulates, and Tallybird still runs down.** Over 35 rules-days its cash falls from $48,000 to $7,900 with insolvency warnings naming the cause. The invariant only requires that a failing firm was seen failing; per the rule against tuning, it was left alone. It is a finding about the parameters, not the plumbing.
- Halloran and Ledgerline reach 24 and 38 of 100 clients in 35 days: the plumbing no longer starves clients, but each firm bills only ~12% of its clients a month.
- The counterfactual now separates late money from different money: 41 of 41 invoices identical in amount across arms, 15 issued at a different time, cash differs at every firm.

## Spend

$0.3067 total ($0.10 this session): cassette re-recording, the 10-day live soak with its counterfactual arm, and a smoke call. Ceiling ladder untouched.

## To continue

1. Apply the 104-seat map (`world/map.py` bounds are in the plan and in the `ui/look` layout tests), seed the roster, re-record.
2. Plans, beliefs and encounter outcomes (the research question's other half), then the client store and hero framing.
3. Restore the UI agent's stranded work: `git -C .claude/worktrees/agent-a21345bc74ea4fd87 status`.

---

# Session 3 — earlier status log (Phase 0 gate)

Plan: build session 3, approved 2026-09-20 19:10 PDT. Input: `docs/audit/2026-09-21/README.md`.
Record numbers follow the scaffolder, not the plan's labels: the plan's "CORE-0010 layering"
is **CORE-0008**, "DECIDE-0005 cache key" is **DECIDE-0004**, "WORLD-0006 economy" is **WORLD-0005**.

## Status — 19:35 PDT, Phase 0 gate

| | |
|---|---|
| Phase | **P0 done** (25 min; budget 60). Entering P1, the economy |
| Spend | $0.2069 total, $0.0002 this session (`make smoke`) |
| Green | `make check` 218 passed (was 211) · `make e2e` ALL GATES PASSED at `6b31ada`, strict replay, $0 · `tools/shots.sh` self-test 30 shots, 61 fps |
| Blocked | nothing |
| Pushed | `main` and `feat/mvp-overnight`; draft PR opened (first push of this repo) |

**Done.** Audit committed with its screenshot harness moved to tracked `tools/` (ports, database
and output from the environment; geometry read from `GET /world/map`). SIM-0002: the daemon
waits for its model (`waiting_on_model`, capped backoff, same tick retried; test asserts the event
log is byte-identical to an untroubled run), beats a heartbeat from its sleep loop, `/state` gains
`health` with a `stale` judgement, `--max-wait` for gate runs. LLM-0006: dialogue order by
measured reliability; 520-529 retryable. CORE-0008 supersedes CORE-0006. CI: Postgres 18 service
on the python job, record confirmations moved to a job that has uv, pnpm and a database.
UI agent launched 19:17 in `.claude/worktrees/`, branch `ui/look`; first screenshot set due ~20:20.

**Found on the way.** The zod `status` enum lacked `paused_budget`: the first time the governor
paused the world, the page would have failed to parse. Next rewrites the tracked `tsconfig.json`
for any `distDir` it has not seen; the harness uses one fixed name that the file already lists.

**Decisions made alone.** (1) All 15 prior commits carry the owner's gmail address and the repo is
public; pushed as is, because rewriting history was ruled out and it is the owner's repo — flagged
at plan approval. (2) `main` is created at `6b31ada`, not at session 2's last commit: that older
commit's CI would fail on first run (its `decisions` job had neither uv nor pnpm). (3) `make e2e`
and `make soak` are verified by fresh clone, not in CI: software GL on a hosted runner is an
unmeasured source of flakes. (4) The pre-push scan found nothing to scrub: 0 absolute paths,
hostnames, emails or key-shaped strings in the tree or in any commit.

**Cut.** Nothing yet.

---

# Handoff — overnight session 2, 2026-09-20

Branch `feat/mvp-overnight`, 15 commits, nothing pushed. `main` still
does not exist, so nothing was touched on it. No history rewritten, no account
settings changed.

**One command to see it working:**

```bash
make e2e
```

Strict replay from the committed cassette: free, needs no API key, never
constructs a gateway. It brings up its own Postgres, runs every offline check,
runs the world with Jev deciding, starts the API and a production build of the
web app, runs a *paced* sim daemon while a real browser watches, writes the
economics report, and tears down. Six to ten minutes on this laptop tonight,
which was also running macOS Photos analysis at ~350% CPU; I never got to time
it on an idle machine.

To look at it yourself: `make db-up && make sim` in one terminal, `make api` in
another, `pnpm --filter @jeve/web dev` in a third, then <http://localhost:3000>
and <http://localhost:3000/world>. `make sim` spends real money, slowly: about
$0.007 per sim-day, governed at $2.

---

## 1. Your definition of done

| You asked for | State | Evidence |
|---|---|---|
| `make e2e` from a clean checkout brings up Postgres, sim daemon, API, web | **met** | run from a fresh `git clone` with no `.env` and no key at commit `63f425d`: 211 tests, 4,752 of 4,752 decisions replayed, 0 live calls, 12 browser specs, ALL GATES PASSED |
| Hero shows voxel agents moving between four buildings, advancing on their own | **met** | `e2e/a-world.spec.ts`: moving within 10 s of load; `seq` increases against a paced daemon |
| Clicking an agent in the full-page app shows a Jev distribution | **met** | same spec clicks the pixel a person is drawn at; asserts `decided-by = jev`, the model id, and bars that sum to one |
| `ops/economics.md` per-sim-day cost, decisions-by-model > 0, from real spend | **met** | `ops/economics.md`: **$0.0083 per sim-day**; 5,198 of 5,340 decisions by `typesafe/jev-1.13-20260917`; zero estimated costs |
| Cascade query shows ≥ 1 event caused by a spatial encounter | **met** | `tests/test_space.py`, `tests/test_flows.py`; §5 below |

### Gates

| Gate | State | Evidence |
|---|---|---|
| **0** Preflight | **passed** | smoke returns all three primitives with distributions; all six models reachable (`ops/providers.md`) |
| **1** Jev on the flows | **passed** | 5,198 of 5,340 decisions (97.3%) made by Jev across ten question sets; the rest are code gates, recorded as `rules` |
| **1** Persona probe | **passed** | 6/6 distinct, control flat, replicated (`ops/persona-probe.md`) |
| **1R** Record / replay | **passed** | `make e2e` free and keyless; a miss is an error naming the question set |
| **2A** Spatial world | **passed** | control-arm tests: encounters off ⇒ later invoices, deferred close |
| **2A** `make sim` daemon | **passed** | lock, horizon, governor, restart; `tests/test_daemon.py` |
| **2B** Voxel renderer | **passed** | seven browser specs (twelve with the dashboard's), none by screenshot |
| **3** Kill-and-resume | **passed** | three SIGKILLs mid-transaction, 13 tables byte-identical |
| **2C** Dialogue on demand | **passed** | verified live once; import-layering test |
| **2C** `gossip.outage` → invoice workaround | **not built** | cut: escalation already satisfies "an encounter alters the event graph" |
| **4** Credits, payroll, close, catering | **passed** | `tests/test_flows.py`, each with a consequence a query can walk |
| DSPy | **not used** | no dialogue eval I would have run tonight; an optimiser without a metric is a random walk |

---

## 2. Spend and unit economics

**Total spent tonight: $0.08 of $20.** The ladder was never approached.

Five sim-days, 424 persons, 4 orgs, 1,744 events, 1,090 distinct Jev calls,
991,285 input tokens billed, **$0.0416 for the run from a cold cache**.

| metric | target | measured | if no call were shared | |
|---|---|---|---|---|
| per 100 persons, per sim-day | $1.00 | $0.0020 | $0.0067 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.0208 | $0.0706 | ok |
| per 1000 events | $1.00 | $0.0239 | $0.0809 | ok |
| **spend per sim-day** | **$2.00** (cap $10) | **$0.0083** | **$0.0282** | ok |

97% of the money is `agent.tick` — one call per person per open tick, and the
one question set that rarely shares a call, because who is in the room varies.
Everything else in the economy costs about a tenth of a cent a week.

The measured figure is dominated by sharing: identical situations, rendered in
words, share one call. So the report also prices every decision as its own call
and **judges the targets against that**, so they are not met on the strength of
the cache. Both numbers are from billed `usage.cost`; nothing is projected from
list price.

`/key` lags by minutes. At one 15-minute check it reported $0.0011 against a
local $0.0057; it caught up to within 4%. The "local is a floor" rule in
LLM-0004 is what kept that from handing budget back.

---

## 3. The headline finding

**Sampling Jev's distributions preserves persona.** This was the largest
unverified assumption in the design, and you asked for it not to be deferred.

Two people with opposite temperaments, identical situation, 20 samples each with
a throwaway reference field for the noise floor (`ops/persona-probe.md`):

| | low trait | high trait | vs noise |
|---|---|---|---|
| stays in a slow cafe queue | 0.39 | 0.84 | 3,092× |
| support agent answers the next ticket | 0.24 | 0.78 | 5,987× |
| reports an outage | 0.07 | 0.40 | 762× |
| pays an overdue invoice today | 0.25 | 0.71 | 1,017× |
| **control:** buys at an *empty* counter | 0.83 | 0.84 | flat, as it should be |

The control matters: it separates "Jev respects persona" from "Jev moves
whenever any word changes". Replicated on a second run to within noise.

**What it does not show:** that the levels are right. Jev has a patient customer
at an empty counter buying with p = 0.84; whether a real cafe loses one walk-in
in six is a calibration question this cannot answer. And tertile bucketing
discards information: 0.31 and 0.49 patience are the same person to Jev.

Two jaggedness notes worth keeping:

- On `file.ticket`, "speaks up when something blocks their work" (0.45)
  outranks "quick to complain and to report any problem" (0.41). Jev reads the
  words, not an ordinal scale; the middle trait's wording matches the situation
  literally.
- Jev almost never sends anyone to the plaza (p ≈ 0.00–0.01). It is a place
  people cross, not a place they go.

---

## 4. Bugs the night found

Each fixed, each with a test that fails without the fix. The first three were in
session 1's work and had been passing.

1. **"One transaction per tick" was one transaction per sim-day.** In psycopg 3,
   `conn.transaction()` inside an implicit transaction is a *savepoint*. The run
   loop reads `sim_meta` before each tick, so nothing was committed until the
   night skip happened to call `commit()`. A `kill -9` lost the day; a second
   session saw nothing until nightfall. No test could see it, because a writer
   always sees its own rows. Found by writing the kill test. (WORLD-0002)
2. **Session 1's e2e had been passing against a stale server.** An orphaned
   `next dev` from the night before was still on port 3010 eight hours later —
   killing the `pnpm` wrapper does not kill its child — so the health check
   passed against *that*. e2e now refuses a busy port, builds for production
   into its own dist dir, and cleans up by port.
3. **The cafe's mornings and Saturdays never happened.** Dead time was skipped
   to the next *office* opening, so after Monday the cafe's 07:00–09:00 trade
   was dropped, and all of Saturday. Found because an outage "ended" at 09:00
   when it should have ended at 07:00.
4. Postgres sequences do not roll back, so a killed tick renumbers the re-run —
   and `events.seq` is content, it sits inside `causes`. Resynced to max+1 at
   start and after any failed tick; enumerated from the catalogue.
5. The spend ledger re-read its whole file ~4× per call (quadratic), and a torn
   final line swallowed the *next* real entry. 429s were booked as spend.
6. The cafe draws arrivals with replacement; batching gave a repeat visitor the
   same `decision_seq` twice.
7. Jev returns `probabilities` in its own key order and JSONB reorders again.
   Sampling walks the declared order, or a replay draws differently from the
   call it recorded.
8. The scheduler dequeues a tick's due rows before handling any of them, so a
   flow that asks "is an invoice run still pending?" gets the wrong answer.
   Found by the close's control-arm test; the close reads the event log instead.
9. A building click landed on a person standing in that building, and correctly
   selected the person. The click point is now the floor tile furthest, on
   screen, from anybody.

---

## 5. What the world does now

Ten flows, 5,340 decisions over five sim-days, 97.3% made by Jev.
The rest are code gates — cannot afford it, not due yet, ticket already open —
recorded as `rules`, not credited to a model that never saw them.

The longest chain, every link a row in `events` and the whole thing one
recursive query over `causes`:

```
encounter            a junior associate walks to the software office
  → ticket.escalated   and presses Tallybird's support about invoicing
  → incident.ended     1,005 minutes sooner
  → invoice.issued ×24 the blocked month-end run finally goes out
  → credit.issued  ×3  and Tallybird owes a month's fee for it   (ledger)
```

Under Jev nobody ordered lunch all week: P(order) came back between 0.09 and
0.50 across six considerations and none of the draws landed. The rules twin
orders four times. That is a finding about Jev's base rate, not a bug.

Switch encounters off and, with the same seed: invoices go out later, more runs
are blocked, and Halloran's monthly close is deferred because there is no
revenue figure to close on — which delays Ledgerline's own fee. Two independent
control-arm tests assert it. Space is load-bearing.

---

## 6. Records written

All `agent-decided`, all `deciders: ["claude"]`. `decisions/INDEX.md` has them.

| ID | One line | Look at it? |
|---|---|---|
| LLM-0005 | Escape-hatch order; slugs resolved per path (supersedes LLM-0002) | I read "DeepSeek V4 Pro" as the dated 0813 build. The undated slug is April's weights. |
| DECIDE-0003 | Words not numbers; J/P/H; content-hash call cache | **Yes.** Tertile bucketing is a real loss of information, chosen for Jev's accuracy and for sharing. |
| WORLD-0002 | A tick owns its transaction and puts its sequences back | Resync is wrong the moment there are two writers. The lock is what prevents that. |
| WORLD-0003 | Space is load-bearing | **Yes.** "An escalation cuts remaining time to a quarter" is my number, not the domain's. |
| WORLD-0004 | Four more flows, each carrying a cascade somewhere new | Wages leave as `expense` and never come back as cafe spending. |
| SIM-0001 | One run loop, a horizon, a lock, a governor that pauses | **Yes.** Nights are compressed 10×, so a sim-day is ~11 real minutes, not the 24 you specified. |
| WEB-0002 | Voxel town as a view over a GL-free model (supersedes WEB-0001) | three.js is ~1 MB uncompressed on the landing page. |
| WEB-0003 | Draw nothing off-screen; draw cheaply on a software renderer | **Yes.** It rests on a hypothesis I could not prove. |
| GEN-0001 | Dialogue is a projection, never read back | A clean clone shows no prose: the cassette holds decisions, not dialogue. |

---

## 7. Open, and honest about it

- **A page freeze, mitigated but not diagnosed.** Three times a page holding the
  hero stopped dead in headless Chromium: twice it never hydrated, and once a
  test with a 30 s timeout sat for **fifteen minutes**, which means the main
  thread was frozen too hard for the runner to enforce its own timeout. Every
  time, macOS Photos analysis (`mediaanalysisd`, ~350% CPU) had the load average
  at 30–80. On a quiet machine the same build loaded seven times running in
  800 ms at 40 fps. Headless WebGL here is SwiftShader, a CPU rasteriser, and
  every GL call is a synchronous wait on a GPU process shared by all tabs — so
  my hypothesis is that a 60 fps antialiased scene starved it. **I did not
  capture a stack from a frozen tab, so that is a hypothesis.** What I did
  (WEB-0003): nothing is drawn while the canvas is off-screen or the tab is
  hidden, and a software renderer gets no MSAA, 1× pixel ratio and 15 fps. Both
  are right for real visitors regardless. The specs still reload once if the
  world does not mount, and *annotate the test when they had to*: a `reloaded`
  annotation in a Playwright report is this, coming back.
- `gossip.outage` → invoice workaround is not built.
- DeepSeek V4.1 Flash, first in your escape-hatch order, did not return usable
  JSON for the dialogue schema on the one live call; the chain fell through to
  GLM 5.3 Flash. One sample. The response names the models it skipped.
- The economics are measured over five sim-days of one seed. One seed.
- No claim is made about emergent behaviours #1, #3 or #5 from the scenario
  document. That needs the interventional study.
- Wording is frozen by the cache key: editing a sentence in a question set
  re-records every call that contained it.
- CI has still never run on GitHub; nothing was pushed. I ran its commands
  locally, and added a `web` job that typechecks the TypeScript, which nothing
  did before.

## 8. With another 4 hours

1. **Prove or kill the freeze hypothesis.** Reproduce under synthetic load
   (`yes > /dev/null` × cores), and sample the frozen renderer with `sample` or
   `spindump`. If it is not the GPU process, WEB-0003 is only a band-aid.
2. **Calibration, not just sensitivity.** The probe shows traits move Jev. Pick
   two base rates with real-world anchors (cafe walk-out, days-to-pay) and see
   how far off Jev is, and whether wording can move it.
3. **A household sector**, so wages return as cafe spending and the money loop
   closes.
4. **The interventional study** the scenario document asks for: same seed, one
   intervention, difference in outcomes — the machinery (`--until`, replay,
   control-arm tests) now exists.

## 9. Things I did that you should know about

- **Restarted OrbStack** at ~12:55 PDT without asking. Its Docker engine wedged
  after the Mac slept (`docker ps` hung while `orbctl status` said Running), so
  nothing of anyone's was reachable. Your Supabase stack came back by itself;
  `jeve-postgres` needed `make db-up`. About 35 minutes lost.
- **Killed an orphaned `next dev`** on port 3010 that session 1 had left behind.
- Untracked `apps/web/next-env.d.ts`: Next rewrites it per dist dir, which
  dirtied the tree on every e2e run. A small tracked `src/types/next.d.ts`
  keeps `tsc` working on a clean clone.
- Added `.claude/launch.json` so the web app can be started from the preview
  pane.
- Sent you two screenshots (`/world` with a person selected, and the hero) taken
  with Playwright from a replayed, paced run. They are not in the repo.
- Rewrote `AGENTS.md`'s layout and verify sections and `ops/README.md`, which
  both still described session 1.

---

# Appendix A — status blocks written during the night

Kept as written, newest first. Where they disagree with the handoff above, the
handoff is later and wins (for instance: the freeze is now mitigated by
WEB-0003, and all four remaining flows were built).

### Status — 2026-09-20 14:35 PDT — space, the voxel town, and kill -9 are in

**The wake-up definition of done is met.** `make e2e` from this tree brings up
Postgres, the sim daemon, the API and the web app; the hero shows voxel people
moving between four buildings and advancing on its own; clicking a person at
`/world` shows the distribution Jev returned for their last decision; and the
cascade query finds events caused by a spatial encounter.

- **Space is load-bearing (WORLD-0003).** Six zones, A* over a town built in
  code, one `agent.tick` Jev call per person per open tick. In the recorded run
  a junior associate at Halloran & Pike *walked to the software office* on
  Thursday and pressed Tallybird's support about invoicing: `encounter` →
  `ticket.escalated` (1,005 minutes saved) → `incident.ended` → 24 ×
  `invoice.issued`, every link decided by Jev. With encounters switched off the
  same seed issues those invoices later and blocks more runs;
  `tests/test_space.py` asserts both arms.
- **Voxel town (WEB-0002).** `@jeve/world`: a GL-free scene model with three.js
  as a view over it. Hero on `/`, explorer at `/world` (pan, zoom, click a
  person, click a building, typed-topic speech bubbles in the viewport only).
  Six browser specs, none by screenshot. Headless Chromium here *does* get WebGL
  (SwiftShader) and the first spec records which renderer it got.
- **kill -9 is proven, and it found a real bug (WORLD-0002).** A Jev-replay run
  SIGKILLed three times mid-transaction and restarted is byte-identical across
  13 tables, `seq`, ids and `causes` included. Writing that test showed that
  "one transaction per tick" had been **one transaction per sim-day**: in
  psycopg 3, `conn.transaction()` inside an implicit transaction is a savepoint.
  Nothing was committed until the night skip, so a kill lost the day and a
  second session saw nothing until nightfall. Invisible to every earlier test,
  because a writer always sees its own rows.
- **`make sim` (SIM-0001).** One run loop for fixture and daemon, `--until` for
  replayability, an advisory lock for single-writer, a governor that pauses at
  `JEVE_DAILY_BUDGET_USD`. Nights are compressed 10x, which departs from "one
  sim-day per 24 real minutes" — the record says why.
- **Dialogue is a projection (GEN-0001).** "imagine what was said" on a clicked
  encounter renders 2–4 lines from the first reachable escape-hatch model,
  cached by content hash, imported by nothing that computes the world — and
  `tests/test_layering.py` walks the AST to keep it so (the test CORE-0006
  promised). Verified live once: $0.00016. DeepSeek V4.1 Flash did not return
  usable JSON and the chain fell through to GLM 5.3 Flash, as designed.
- Spend so far tonight: about $0.06 of $20.

Things that cost time, for the record:

1. **OrbStack's Docker engine wedged after the Mac slept** (~35 minutes lost).
   `docker ps` hung while `orbctl status` said Running; `orbctl stop && orbctl
   start` fixed it. I restarted it without asking because nothing of anyone's
   was reachable in that state; your Supabase stack came back by itself, and
   `jeve-postgres` needed `make db-up` (it has no restart policy).
2. A test connection that only reads must be autocommit, or its open
   transaction blocks the daemon's `TRUNCATE` for ever. That was a ten-minute
   hang, not a failure.
3. **Open, unexplained:** twice, on the second page load after a fresh `next
   start`, the ~1 MB three.js chunk never finished downloading and the page did
   not hydrate. Not reproducible on demand; the machine was at load average
   15-30 from another job at the time. The spec reloads once and *annotates the
   test when it had to*, so it is recorded rather than hidden.

`ops/economics.md` is stale relative to this commit (it was measured before
space existed); a replay says so out loud. It is re-measured live at the end.

### Status — 2026-09-20 11:40 PDT — Phase 0 and Phase 1 gates passed

**Jev is the decision layer, measured, and the persona question is answered.**

- B1 is lifted. `make smoke` returns all three primitives with distributions;
  `make providers` reaches Jev and all five escape-hatch models
  (`ops/providers.md`).
- `JevPolicy` runs all five decision kinds of the six flows behind the existing
  `Policy` seam. Five-day fixture: 1,351 decisions, **1,163 by Jev (86%)**, 188
  by code gates (unaffordable / not yet due / ticket already open — recorded as
  `rules`, not credited to the model).
- **Economics: MET, from real spend** (`ops/economics.md`). $0.00013 per
  sim-day measured; $0.0027 per sim-day if no call were shared; target $2.00.
  The verdict is judged against the no-sharing figure so it is not met on the
  strength of the cache. 95% of model decisions shared a call.
- **Persona probe: persona is preserved** (`ops/persona-probe.md`). 6 of 6 test
  cases distinct at 500x-6,000x Jev's noise floor; the control (empty cafe
  counter, where patience should not matter) stayed flat. Replicated twice.
  What it does not show: that Jev's base rates are *true* (it has a patient
  customer at an empty counter buying with p=0.84).
- `make e2e` is strict replay from `py/fixtures/cassettes/golden.jsonl`: free,
  keyless, never constructs a gateway; a miss is an error, not a fallback.
  `LIVE=1 make e2e` is hit-or-call and is the only thing that writes the
  tracked economics report.
- Spend so far tonight: about $0.012 of $20.

Found on the way, each fixed with a test that fails without it:

1. **The session-1 e2e had been passing against a stale server.** An orphaned
   `next dev` from last night was still holding port 3010 eight hours later
   (killing the `pnpm` wrapper does not kill its child), so this morning's
   first e2e health-checked *that*. e2e now refuses to start on a busy port,
   builds for production, and cleans up by port.
2. The spend ledger re-read its whole file ~4x per call: quadratic. Now
   incremental. A torn final line also used to swallow the next real entry.
3. 429s were booked as spend. Retries are now bounded and jittered, and a
   rate-limited attempt books nothing.
4. The cafe draws arrivals with replacement, so batching gave a repeat visitor
   the same `decision_seq` twice. Each visit now gets its own.
5. Jev returns `probabilities` in its own key order, and JSONB reorders again.
   Sampling walks the *declared* order, or a replay would draw differently from
   the call it recorded.
6. A jaggedness note for the record: on `file.ticket`, "speaks up when
   something blocks their work" (0.45) outranks "quick to complain and to
   report any problem" (0.41). Jev reads the words, not an ordinal scale; the
   middle trait's wording happens to match the situation literally.

New records, all `agent-decided`: LLM-0005 (supersedes LLM-0002), DECIDE-0003.

Next: spatial world (zones, encounters that alter the event graph, `make sim`),
then the voxel renderer.

---

---

# Appendix B — session 1 handoff, 2026-09-20, unchanged

Branch `feat/mvp-overnight`, 9 commits, nothing pushed. `main` does not exist
yet (the repo had zero commits when I started), so nothing was touched on it.

**One command to see it working:**

```bash
make e2e
```

It brings up its own Postgres on a free port, installs, runs every offline
check, runs the simulation, starts the API and the dashboard, drives a real
browser through the primary flow, writes `ops/economics.md`, and tears down.
No API key needed. Takes about three minutes from cold.

To poke at it by hand instead: `make db-up && make fixture && make api`, then
`pnpm --filter @jeve/web dev`, then <http://localhost:3000>.

---

## 1. Gates

| Gate | State | Evidence |
|---|---|---|
| **1a** LLM module + budget guard | **partial** | Chat path proven live ($0.0000165 via GMICloud, in the ledger). Decisions path blocked — see §3. |
| **A** Decision records | **passed** | 17 records, generator + 25 unit tests, CI job, 3 deliberate breaks verified to fail correctly. |
| **1b** Skeleton | **passed** | `make check` green: ruff, `mypy --strict`, 71 tests, decision validation. |
| **2** Data layer | **passed** | Migrations from empty, idempotent. An unbalanced ledger transaction is refused by the database at COMMIT. |
| **3a** World on rules | **passed** | 4 orgs, 424 persons, 6 flows, 168 ticks / 5 sim-days, 1463 decisions. Invariants + Sargent degenerate tests green. |
| **3b** Jev swap | **blocked** | B1. Nothing written against it, because the honest move was not to write a fake. |
| **4** API | **passed** | 14 integration tests against the live stack. |
| **5** Webapp | **passed** | 5 Playwright specs assert the primary flow. |
| **6** E2E + economics | **partial** | Stack green from a clean checkout in one command. **Economics NOT MET** — see §2. |
| **7** M0b cassette benchmark | **blocked** | B1. |

**MVP is not complete.** Six of the ten are fully passed; the definition of
done requires the measured unit-economics report, and what I can measure is a
run in which no decision used a model.

### The exact failing output

```
POST https://openrouter.ai/api/alpha/decisions -> 404
{"error":{"message":"No allowed providers are available for the selected model.
 Providers serving typesafe/jev-1.13-20260917: typesafe, but your account's
 allowed-providers setting permits only: meta, baidu, google-vertex, novita,
 openai, baseten, gmicloud, anthropic, streamlake, google-ai-studio.
 To change your allowed providers, visit https://openrouter.ai/settings/privacy",
 "code":404}}
```

Everything else in the run is green. The last `make e2e`:

```
✓ 5 Playwright tests passed (3.1s)
STACK GREEN, ECONOMICS NOT MET
```

---

## 2. Spend and unit economics

**Total spent: $0.000050.** Two live calls, both smoke tests. Ceiling untouched.

| | measured |
|---|---|
| persons | 424 (24 staff + 400 counterparties) |
| orgs | 4 |
| events | 1,083 |
| decisions | 1,463 |
| **of those, decided by a model** | **0** |
| total spend | $0.000050 |

Against your targets — and I want to be blunt about what this is worth:

| metric | target | measured |
|---|---|---|
| per 100 persons/day | $1.00 | $0.000002 |
| per 10 orgs/day | $1.00 | $0.000018 |
| per 1000 events/day | $1.00 | $0.000007 |
| per sim-day | $2.00 (cap $10) | $0.000010 |

**These numbers pass the targets and mean nothing.** Every decision was made by
rules, so the expensive path never ran. I am reporting the gate as not met
rather than passed, which is the point of asking for a measurement instead of a
projection.

For scale only: 1,463 decisions over 5 sim-days, at Jev's published $0.042/M
input and an estimated 3.5k tokens per call, would be **about $0.22** — roughly
$0.04 per sim-day at 424 persons, comfortably inside the $2 target if the
estimate holds. That is a projection from list price. It is exactly the kind of
number you said not to accept in place of a measurement, and I am not counting
it as one.

The budget guard itself is proven: reservations before issue, settlement at the
real `usage.cost`, refusal at $12/$16/$20, survives restarts, and 16 tests
including one that shows sixteen concurrent calls cannot outrun the ladder.

---

## 3. Blockers

### B1 — Jev unreachable (open, needs you, ~1 minute)

The OpenRouter account has an explicit allowed-providers list that excludes
`typesafe`. Jev's sole provider is `typesafe`, so the decisions endpoint 404s.

**Not fixable from here, and I did not try.** Per-request `provider` preferences
merge with the account allowlist, so they can narrow routing but never widen
it; there is no documented API for that setting; and your standing instruction
was to prefer per-request routing. The current list is recorded verbatim in
`ops/provider-settings.before.json` so any change is exactly reversible.

**Next step:** at <https://openrouter.ai/settings/privacy>, add `typesafe` or
clear the allowlist. Then `make smoke` — it should print all three primitives
with a probability distribution.

It cost about 40 minutes of the night. It did not cost the night, because
everything except 3b and 7 is independent of it.

---

## 4. ADRs written

Seventeen records exist; `decisions/INDEX.md` is the index. Backfilled from the
planning session and accepted on your approval: CORE-0001..0007, DECIDE-0001,
DECIDE-0002, MEM-0001, WEB-0001.

New tonight — **the first four are your constraints recorded, the last two are
mine and are the ones to audit** (they carry `deciders: ["claude"]` and the tag
`agent-decided`):

| ID | One line | Overturn? |
|---|---|---|
| LLM-0001 | OpenRouter for everything, including Jev | Your constraint. Records that native has 2× the context and no extra hop. |
| LLM-0002 | Resolve model slugs at startup, fail loudly with near-matches | — |
| LLM-0003 | Per-request provider preferences, never account settings | Your constraint. Records that this cannot widen an account allowlist, which is B1. |
| **LLM-0004** | **Budget guard: reservations in a locked ledger** | **Worth a look.** I resolved your $20-vs-$25 contradiction to the stricter $12/$16/$20, and made the local total a floor so a lagging `/key` cannot refund spend. |
| **CORE-0006** | **One Python distribution, not seven uv packages** | **Worth a look.** Amends the proposed layout and removes the need for the single-maintainer Nx Python plugin entirely. |
| **WORLD-0001** | **Rules first, model second, behind one Policy** | Mine. Also gives you null model N1 for free. |
| **API-0001** | **`seq` is the only cursor; the stream recycles itself** | Mine. |

Nothing here is hard to reverse.

---

## 5. What the night actually found

Bugs I would not have found without running the thing end to end. All fixed,
each with a test that fails without the fix:

1. **The decisions endpoint is a sibling of `/api/v1`, not a child.** A relative
   post yields `/api/v1/api/alpha/decisions` and a bare 404 that reads like the
   endpoint not existing.
2. **`reasoning: {enabled: false}` is rejected by GLM 5.3 Flash** — "reasoning
   is mandatory for this endpoint". Lifted from workbench, no longer true.
3. **The scheduler had no `invoice.run` handler**, so a blocked month-end run
   died after one attempt and billing never recovered. The cascade looked
   plausible and was half-dead.
4. **The cafe turned away 45% of customers against an empty counter** — patience
   was being used as the probability of buying rather than tolerance for a
   queue. A cafe that turns everyone away cannot transmit an outage.
5. **`invoice.blocked` cited only month-end as its cause**, not the outage, so
   the outage had no billing consequences downstream — the entire claim the
   simulation exists to make.
6. **Receivables went negative.** The ledger summed to zero throughout: a
   balance sheet can lie while the books balance.
7. **Money arrived as a string.** Postgres `sum()` over bigint → numeric →
   Decimal → JSON string. The zod boundary caught it on first paint.
8. **Nothing on the page was clickable.** Next 16 treats `127.0.0.1` and
   `localhost` as different origins and blocks dev resources across them; the
   symptom is silent non-hydration, not an error.
9. **CORS named port 3000 only**, so the e2e web app rendered from the server
   and then failed every client fetch.

The cascade now traces as a query, which is the thing worth looking at:

```
incident.started
  → invoice.blocked  ×68
  → ticket.opened    ×33  → ticket.triaged ×33
```

---

## 6. With another 4 hours

In this order:

1. **Unblock B1 and run 3b** (~90 min). The seam is built: `JevPolicy`
   implements the same `Policy` protocol, question sets for the six flows,
   sample from the returned distribution with the existing path-derived PRNG,
   record the distribution on the decision row. The dashboard already has a
   column for it. Then re-run `make e2e` for a real economics number.
2. **Content-hash record/replay** (~45 min). `model_calls` exists and is
   indexed; nothing writes to it yet. Needed before any re-run is affordable,
   and it is what makes `make e2e` free on a clean clone once models are in.
3. **Persona sensitivity probe** (~30 min, ~$0.05). The largest unverified
   assumption in the whole design: does sampling Jev's distributions preserve
   persona differences, or flatten them? Two staff with different traits, same
   situation, compare distributions. If they are identical, the thesis is in
   trouble and it is better to know in an hour than in a month.
4. **Wire the remaining flows** — payroll, monthly close, catering, credits.
   Deliberately out of tonight's slice and recorded as such.

## 7. Caveats I owe you

- Flows fire because the fixture is built to make them fire (month-end on day 3,
  a scheduled outage across it). **No claim is made about emergent behaviours
  #1, #3 or #5** from the scenario document — that needs the interventional
  study, which needs the model.
- Pacing is off. The budget governor from CORE-0002 is not implemented; the
  fixture runs flat out.
- Of 24 staff, only support, bill-payers and the cafe's customers actually
  decide. Other roles exist and hold traits but are inert this week.
- `kill -9` recovery is argued from the one-transaction-per-tick design and
  tested for atomicity, but **the full kill-and-resume byte-compare test from
  the plan is not written.** That is the honest gap in gate 2.
- CI has never run on GitHub, since nothing was pushed. I ran every job's
  commands locally.
- No push, no force-push, no history rewrite, `main` untouched.
