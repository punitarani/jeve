# ADR-002 — Backpressure

Status: proposed · 2026-09-20 · Depends on ADR-001, ADR-003.

## Decision

**Slow the clock.** The tick is a barrier: sim time does not advance past T until every
decision due at T has an answer from the decision model. If the model is slow, the world is
slow. If the model is down, the world is paused. **No decision is ever defaulted, skipped, or
fabricated.**

This is nearly free because the world runs on its own clock (ADR-001). Nobody inside it can
tell.

Concretely:

1. **Jev calls are on the barrier.** Per-attempt timeout 3s (the SDK default of 10s is too
   patient for a 0.3s service), 2 retries, honouring `Retry-After`. All decisions due in a
   tick are issued concurrently under a permit pool and a token bucket sized to the published
   limits.
2. **A circuit breaker pauses the world.** Five consecutive failures or a 429/529 storm opens
   it; the sim enters `waiting_on_model`, shown on the dashboard, and probes with exponential
   backoff up to 5 minutes. Responses already received are already persisted (ADR-009), so
   the tick resumes where it stopped and nothing is paid for twice.
3. **No LLM call is ever on the barrier.** LLM end-to-end latency is 2–5s at P50 and 40–220s
   at P99 (00 §4). Typed escalation, prose rendering, and ontology proposals are durable
   asynchronous jobs.
4. **Escalation latency becomes deliberation time.** A decision that qualifies for tier 1
   escalation (ADR-005) is not blocked on; the agent *hesitates* — its decision point is
   rescheduled one tick later and the escalated answer arrives as an event. Still missing
   after 3 ticks → the agent acts on Jev's original distribution and the miss is logged. Low
   confidence costing the agent time is behaviour, not an artefact.
5. **Job backlog feeds the governor.** If the async queue exceeds a depth or age bound, the
   pacing governor lowers speed. Still the same policy.

## Why not the other two

**Degrade** (substitute "continue current task" or the rule-based default when the model is
late). This silently converts infrastructure weather into behaviour. A Jev brownout becomes a
wave of idling, which then trips the degeneracy detectors and enters the permanent record as
something the agents did. workbench has the cautionary tale: an engine error leaked into
agent memory and "over thirty recorded days the firm built a shared story of a platform
outage that never existed" (00 §6.5). In jeve, where outages are the headline mechanic, a
phantom one poisons the main result. It also corrupts the research measurement directly: the
share of decisions handled by typed answers would include decisions handled by nobody.

**Queue** (let ticks proceed and apply late decisions when they land). A decision made about
the world at T applied to the world at T+3 is a wrong decision with a correct timestamp. And
an unbounded queue in a process meant to run forever is a memory leak with extra steps.

## Consequences

- Wall-clock smoothness is sacrificed. Under provider trouble the dashboard stutters or
  stops. It says why.
- Availability of the decision model bounds availability of the sim. Mitigated by the
  OpenRouter decisions endpoint as a configured standby behind the same port (00 §2).
- The permit pool's width should equal the cohort width: workbench measured that useful
  concurrency was exactly that (00 §6.5).
- Staggered wake-ups matter twice: they smooth token bursts, and they keep a tick from
  waiting on its slowest of 24 members. workbench's stagger was broken in a way that put 21
  personas on identical wake timestamps; jeve tests for it.

## Reverse if

- The world spends > 5% of wall time in `waiting_on_model` over a week, *with* the standby
  configured → move Jev decisions to the same hesitation mechanism LLM calls use (decisions
  in flight, agents visibly "thinking"). Still not degrade.
- Jev's real P99 from your machine is > 2s (M0 measures it) → same change, sooner.
