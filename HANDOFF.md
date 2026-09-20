# Handoff

> **Session 2 is in progress.** Status blocks are appended here at each phase
> gate, newest first. The session-1 handoff follows unchanged below them, and
> the whole file is rewritten in that format at the end of the night.

## Status — 2026-09-20 11:40 PDT — Phase 0 and Phase 1 gates passed

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

# Session 1 handoff — overnight session, 2026-09-20

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
