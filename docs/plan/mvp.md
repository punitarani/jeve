# MVP plan

Depends on everything in `docs/research/` and `docs/adr/`. Nothing here is built. **M0 is a
go/no-go gate and may invalidate parts of this plan.**

## 1. Architecture

```
                         ┌──────────────────────── apps/sim (one process, holds the lease) ───────────────────────┐
                         │                                                                                          │
  seed + shock deck ───▶ │  scheduler ──▶ wake policy ──▶ build state ──▶ DecisionModel port ──▶ sample / threshold │
  exogenous processes    │  (py-world)     (py-decide)    (py-memory)       │   (py-decide)        (py-decide)      │
                         │       ▲                                          │                         │             │
                         │       │                          ┌───────────────┴──────────────┐          ▼             │
                         │       │                          │ budget ▸ record ▸ rate-limit │     typed intent       │
                         │       │                          │ ▸ retry ▸ { Jev native |     │          │             │
                         │       │                          │   OpenRouter decisions |     │          ▼             │
                         │       │                          │   replay | fake }            │   referee (rules, no   │
                         │       │                          └──────────────────────────────┘   model) — py-world    │
                         │       │                                                                   │             │
                         │       └──────────── ONE TRANSACTION PER TICK ◀────────────────────────────┘             │
                         │                     events(+causes) · decisions · domain tables · scheduled · sim_meta  │
                         │                                                                                          │
                         │  async workers (never on the tick barrier): tier-1 typed escalation · prose rendering ·  │
                         │  ontology proposals — py-gen, via the jobs table                                         │
                         └───────────────────────────────────────┬──────────────────────────────────────────────────┘
                                                                 │
                                                          ┌──────▼──────┐   NOTIFY(seq)   ┌──────────────┐  SSE, tail by seq  ┌──────────┐
                                                          │  Postgres   │ ──────────────▶ │  apps/api    │ ─────────────────▶ │ apps/web │
                                                          └──────▲──────┘                 │  FastAPI     │ ◀── /state, /causal│ Next.js  │
                                                                 │                        └──────────────┘                    └──────────┘
                                         py-metrics: invariants (halt) · detectors · canary · study runner (headless forks)
```

**A tick.** The scheduler pops everything due. The wake policy selects agents at a decision
point. For each, in parallel: retrieve memories and beliefs, render a small `state`, compose
the question set, call the decision model through the port. Answers become typed intents —
J-type by threshold, P-type by a path-derived draw. The referee validates each intent against
the world's rules; a rejection returns to the agent as a memory, with engine faults kept out.
Everything commits in one transaction, and the clock advances. If a call is slow, the clock
waits.

## 2. Module boundaries — the swap points

| Package | Owns | Must not | You can swap… |
|---|---|---|---|
| `py-contracts` | pydantic models for events, decisions, API payloads; schema export | contain logic | — (it is the contract) |
| `py-world` | ledger, domain tables, referee rules, scheduler, tick transaction, exogenous processes, seed loader | **import any model client** — enforced by an import-layering test | **a single org's rules**: policy is data on `orgs.policy`, read here and by `py-decide` |
| `py-decide` | `DecisionModel` port and adapters; decorator stack; question-set registry, composer, linter; sampling; wake policy; escalation *rules* | know what an invoice is beyond its contract type | **the routing policy**: one `RoutingPolicy` interface decides provider, tier, and threshold per question |
| `py-memory` | memory writes, importance, retrieval, beliefs, compaction | call a model except through `py-decide` | **the memory implementation**: one `MemoryStore` interface — `recall(agent, situation) → items`, `observe(...)`, `compact(...)` |
| `py-gen` | `LanguageModel` port, OpenRouter backend, DSPy signatures, rendering, ontology proposals, tier-1 adapter glue | be imported by `py-world`, `py-decide`'s core, or `py-memory` | the LLMs, freely — nothing causal reads their output |
| `py-metrics` | invariants, detectors and their mutation tests, canary suite, fork + study runner | write to the world | — |
| `apps/sim` | process wiring, lease, governor, circuit breaker, workers | contain domain logic | — |
| `apps/api` | read endpoints, SSE, control endpoints | write to the world except via control rows | — |
| `apps/web` + `contracts` | the dashboard; generated TS + zod | hand-write a type that exists in Python | — |

Two ports, deliberately separate: `DecisionModel.decide(state, questions) → typed answers` and
`LanguageModel.complete(request) → text`. workbench's single text-returning protocol cannot
carry Jev's answers (00 §6.5).

## 3. Milestones — one session each, in dependency order

| # | Milestone | Exit criterion | Needs |
|---|---|---|---|
| **M0a** | **Jev smoke test and measurement.** A script, not an app. Native and OpenRouter. | P50/P95/P99 latency over ≥ 500 calls of ~3.5k tokens and ~30 questions; tokens per call; **are byte-identical requests deterministic?**; effective rate limits; native vs. OpenRouter deltas. Re-issue ADR-003 with real numbers. | **An API key from you.** |
| **M0b** | **Cassette benchmark — GO / NO-GO.** Replay workbench's recorded decide contexts through Jev as `choice` questions (00 §6.3). | Agreement with the recorded LLM choice; confidence-vs-disagreement curves (seed thresholds for ADR-005); **persona sensitivity**: JSD between different personas in matched situations. | M0a. Your OK to read workbench's gitignored recordings. |
| M1 | Repo skeleton. Nx 23 + pnpm + uv workspace; `py-contracts` → TS codegen **spike on one real discriminated union** (hey-api vs. orval); CI: ruff incl. the determinism `banned-api`, pytest, lock check, codegen drift check; compose file for Postgres. | `nx run-many -t lint test` green; a pydantic union round-trips to a zod schema that rejects a bad tag. | — |
| M2 | World kernel. Schema and migrations; double-entry ledger with constraint triggers; `events` with `causes`; durable scheduler; the tick transaction; advisory-lock lease; seeded id minter and path-derived PRNG. | **Kill-and-resume test** (lifted from workbench): `kill -9` at random points, resume, byte-identical event log. Second sim process refuses to start. | M1 |
| M3 | The four orgs on **rules only** — the N1 twin. Seed loader, exogenous populations, shock deck, all inter-org flows, clock with dead-time skipping. | Headless 60 sim-days: all invariants hold; Sargent degenerate tests pass (arrivals > service ⇒ divergence; no customers ⇒ no revenue; permanent outage ⇒ ticket explosion); **an injected Invoicing outage at month-end measurably delays billing**, proving the causal path exists structurally. Seed tuned so every org runs at ρ 0.75–0.9. | M2 |
| M4 | API + dashboard v0, watching the rule-based world. `/state`, `/stream`, `/events`, `/causal`; header strip, org graph, **causal timeline**. | Open the browser, see the four orgs transact, click an outage and see its downstream chain highlighted. Reconnect resumes by `seq` with no gap. | M3 |
| M5 | Decision layer. `DecisionModel` port; Jev-native, OpenRouter, replay, and fake adapters; budget ▸ record ▸ rate-limit ▸ retry stack; question-set registry, composer, and **linter**; `decisions` table; sampling. **One role** on Jev: the Tallybird support agent. | That agent's decisions appear with distributions; replay adapter reproduces a recorded run byte-for-byte; kill-and-resume still passes with model calls in the tick and nothing is paid for twice. | M0 go; M3 |
| M6 | All roles on Jev. Question sets per role and org; wake policy with staggered phases; dampeners (reply depth, thread caps); the hazard-rate rule for irreversible actions; `other` on every verb choice. | ≤ 20 Jev calls per agent per sim-workday measured; ontology-gap rate reported; no two agents share a wake phase. Re-issue ADR-003. | M5 |
| M7 | Memory and beliefs. Importance batched into the decision request; relational retrieval; belief slots with typed revision; commitments; nightly compaction and forgetting. | 90 sim-days headless: live memory rows plateau; state stays ≤ 2.5k tokens; commitment-miss rate reported. | M6 |
| M8 | Running unattended. Spend ledger and **budget governor**; circuit breaker and `waiting_on_model`; supervisor and restart policy; `sim.engine.changed`; agent panel with **distribution bars**; control endpoints. | Runs 24 real hours untouched; spend ≤ budget; pulling the network pauses the world and restoring it resumes with no fabricated decision; `kill -9` mid-tick recovers without intervention. | M4, M7 |
| M9 | Instrumentation. Invariants that halt; entropy, idle-with-backlog, loop, role-information, negative-event, and queue detectors; **a mutation test per detector**; daily canary suite against pinned `jev-1.13.0`; health panel. | Each detector fires on its injected failure and stays silent on a healthy run. | M8 |
| M10 | Async generation. `jobs` workers; **tier-1 typed escalation in shadow mode** with the uniform 2% sample; lazy prose rendering with a grounding check; weekly threshold-tuning job. | Opening a message renders prose within seconds without touching the tick; grounding ≥ 99%; shadow agreement report per question. | M8 |
| M11 | **The proof.** Snapshot and fork; headless study runner; the pre-registered outage study (scenario §5 #1): K = 30, A/A noise floor, dose-response, against the N1 twin. | A written result: mean Δ, CI, effect size, whether it clears the A/A 95th percentile, whether it is monotone in outage duration, and how it differs from the rule-based twin. Whatever it says. | M9 |

Thirteen sessions. M4 deliberately precedes any model: you get something to watch, and the
economy gets tuned, before a cent is spent on decisions.

**After the MVP:** tier 1 live per question once shadow data supports it · ontology extension
· stylized-fact panel · N0/N2/N4 null models with full seed counts · judge and human
spot-checks · path-blocking and negative-control studies · persona classifier and drift tests.

## 4. MVP definition of done

**In the browser**

- [ ] Sim date, time, speed, status, and today's spend against budget, always visible.
- [ ] Four orgs with live cash, backlog, utilisation; Tallybird's three modules with status.
- [ ] Typed flows animating between orgs as they occur.
- [ ] A causal timeline; clicking any event highlights its upstream causes and downstream effects.
- [ ] At least behaviours **#1, #3, and #5** from the scenario observable within one sim-week of a seeded start, without the shock guarantee being what produced them.
- [ ] Any agent: recent decisions with returned distributions as bars, the sampled outcome, the choosing rule; current beliefs; retrieved memories.
- [ ] A message opens to its typed speech act at once, and to rendered prose shortly after.
- [ ] Health panel: every MVP detector from 02 §4, the ontology-gap rate, the escalation shadow rate, alerts.
- [ ] Close the tab for a day; on return, "since you were last here" names the largest causal chains.

**Persisted**

- [ ] Every event with causes; every decision with its distributions, PRNG path, and draw; every model call by content hash with the resolved model version; all world state; memories and belief history; spend; metrics; alerts; engine-version seams.
- [ ] A recorded stretch replays to a byte-identical event log through the replay adapter.

**On `kill -9` and restart**

- [ ] The process restarts under its supervisor with no human action.
- [ ] A second sim process cannot start while one holds the lease.
- [ ] The interrupted tick re-executes; answered model calls are found by hash; **nothing is paid for twice**; the resulting log is identical to an uninterrupted run over the same recorded responses.
- [ ] In-flight async jobs are re-leased and complete once.
- [ ] Sim time resumes where it stopped. No catch-up.
- [ ] The dashboard reconnects and resumes by `seq` with no gap and no duplicate.
- [ ] The rolling budget survives the restart.

**Cost of leaving it running**

- [ ] **Hard ceiling $2.00 per real day** in model spend, enforced by the governor, configurable. Expected ≈ 8× business-hours speed at that ceiling if M6 lands the 18-calls target; ≈ 3× if it does not (ADR-003).
- [ ] Infrastructure: Postgres and three processes on one always-on machine. $0 locally.
- [ ] Interventional studies are separate and capped per study: ≈ $16–39 for the MVP study (ADR-003).
- [ ] Actual spend per real day is on the dashboard and in the database, not estimated.

**Proof it is not a screensaver**

- [ ] The M11 result exists in writing.

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Jev flattens personas** when its probabilities are sampled as behaviour — a use nothing in its docs validates (00 §0) | Unknown | **Fatal to the thesis** | M0b measures it on recorded contexts before any code. If it fails: try richer persona encoding in criteria; then restrict Jev to J-type and let propensity come from code-side persona parameters over Jev's judgments; report the negative result either way. |
| 2 | No TypeSafe access — early-access waitlist | Medium | Blocks M0 | OpenRouter's decisions endpoint is a config switch behind the same port (00 §2). Costs an extra hop and half the context. |
| 3 | API and SDK churn — two breaking SDK releases in the first four days; OpenRouter's path is `/alpha/` | **High** | Medium | Own port; exact version pins; contract tests against recorded responses; the daily canary doubles as an API smoke test. |
| 4 | Jev's price is subsidised and rises ("We can't prove it isn't subsidized") | Medium | Medium | Budget governs speed, so a rise slows the world rather than breaking it. ≥ 10× reopens ADR-003. |
| 5 | Rate limits cut without notice — docs say they float | Medium | Low | Token bucket, `Retry-After`, circuit breaker; at N = 24 there is ~10× headroom. |
| 6 | Silent model drift through aliases | Medium | Medium | Pin `jev-1.13.0`; store the resolved version on every call; canary alert on mean \|Δp\| > 0.05; thresholds keyed by model version. |
| 7 | **The economy will not tune** — frozen, exploding, or too slack to cascade | **High** | High | Tune against the rule-based twin at zero cost in M3, before models. Sargent degenerate tests in CI. ρ targets at seed. |
| 8 | Closed ontology makes the world dull | Medium | High | Emergence is designed into structure (scenario). Ontology-gap rate measures the pressure; post-MVP extension relieves it. |
| 9 | Hazard-rate distortion inflates rare events | Medium | Medium | The hazard-rate rule plus hysteresis (ADR-004); a detector for rates that scale with wake frequency. |
| 10 | Absorbing idle — workbench's LLM chose idle 75% of the time in one world | Medium | High | Sample, do not argmax; idle-with-backlog alert; mandatory timer; per-question sharpening as a last resort. |
| 11 | Validation replicas cost more than estimated — the 30% cache-hit assumption is a guess | Medium | Medium | Per-study cap; the MVP study is sized small; M0a's determinism result decides how effective the cache is. |
| 12 | `@nxlv/python` breaks on an Nx major — single maintainer | Medium | Low | Used for graph edges only; the fallback is one deleted line (ADR-008). |
| 13 | Contract codegen mangles discriminated unions | Medium | Medium | Spiked in M1 on the real event union; orval as the alternative. |
| 14 | Hidden nondeterminism breaks replay | Medium | Medium | `banned-api` lint; path-derived PRNG; the byte-compare resume test in CI from M2 onward. |
| 15 | Engine faults leak into agent memory and the world invents a story — it happened in workbench | Low | High | Two-audience rejections; every event's `causes` must resolve; phantom-event detector. |
| 16 | The viewer cannot follow a floating clock | Medium | Low | Speed always displayed; the timeline is retrospective by design; fixed-speed override. |
| 17 | Log growth | Low | Low | Monthly partitions; body retention on `model_calls`; bounded memory. |
| 18 | Agent-to-agent prompt injection through rendered prose | Low | Medium | Structurally excluded: prose is never read back into decision state (01 §3). |

## 6. Deliberately not in the MVP

Multi-tenancy, auth, accounts (your constraint). A map. Embeddings. DSPy optimisers. Redis.
Live tier-1 escalation — shadow only. Ontology extension. Hiring, firing, ageing, seasons.
More than four orgs. Hosting — the DoD is verified on one machine.

## 7. Questions I need answered at the gate

1. **Access.** Do you hold a TypeSafe API key, or only OpenRouter? M0a cannot start without
   one, and I made no live call in this session.
2. **Budget.** Is $2.00 per real day the right default ceiling? Everything about speed
   follows from it.
3. **Where does "ever-running" run?** Your Mac under a supervisor, or an always-on box?
   Jev is served from the US West Coast, so placement affects the one number the design
   leans on.
4. **workbench recordings.** M0b wants the gitignored `out/` and `cassettes/` recordings. I
   read only the committed cassettes. OK to read the rest?
5. **Drop Qwen3.8 Flash** from the escape-hatch set, as 00 §4 recommends?
