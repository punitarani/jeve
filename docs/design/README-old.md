# Architecture decision records

Read in dependency order, not numeric order. The cost model came first; the clock and
backpressure decisions fall out of it.

| # | Decision | One line |
|---|---|---|
| [003](003-cost-model.md) | Cost model | Jev is ~80% of spend and spend is linear in clock speed. Budget first, speed second. |
| [001](001-time-model.md) | Time model | Sim clock, discrete-event, **budget-governed** pacing. Process down = world paused. |
| [002](002-backpressure.md) | Backpressure | **Slow the clock.** The tick is a barrier. No LLM call is ever on it. |
| [004](004-question-sets.md) | Jev batching | One request carries the whole decision surface — **per decision point, not per tick**. |
| [005](005-escalation.md) | Confidence-gated escalation | Two tiers. Tier 1 stays typed. Flat propensity distributions are *not* escalated. |
| [006](006-memory.md) | Memory over unbounded time | Relational retrieval, typed belief revision, SQL rollups. No embeddings, no generated summaries. |
| [007](007-determinism.md) | Determinism and seeding | Exact replay from the log; never from re-querying. Path-derived PRNG, no RNG state. |
| [008](008-monorepo.md) | nx + uv, language split, DSPy | Nx 23 + pnpm + one uv workspace, plugin used shallowly. Python owns the sim. DSPy for the generative minority only. |
| [009](009-persistence.md) | Persistence | Postgres, one transaction per tick, append-only events with causal links. No Redis. |
| [010](010-frontend.md) | Frontend | State/event dashboard with a causal timeline. No map. |

Format: decision · context · alternatives rejected · consequences · what would reverse it.
Facts are sourced in `docs/research/`; ADRs cite section numbers rather than repeat evidence.
