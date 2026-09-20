# ADR-001 — Time model

Status: proposed · 2026-09-20 · Depends on ADR-003.

## Decision

**A simulation clock, advanced by a discrete-event scheduler, paced by a budget governor.
Wall-clock time has no meaning inside the world.**

- **Sim time** is an integer count of sim-seconds from a seeded epoch, stored in Postgres and
  advanced only inside the tick transaction (ADR-009). Nothing in the sim core may read the
  wall clock (lint-enforced, ADR-007).
- **Scheduler quantum: 15 sim-minutes.** This is when the scheduler looks for due work, not
  when agents think. Agents are evaluated at *decision points* (ADR-004). Code-only processes
  that need finer resolution — cafe foot traffic, SLA clocks — sub-step inside a tick with no
  model calls.
- **Pacing.** During active periods the scheduler sleeps between ticks so that
  `speed = min(speed_max, budget_per_real_day ÷ rolling_cost_per_sim_second)`, recomputed
  hourly from the spend ledger. Defaults: budget $2.00 per real day, `speed_max` 60×. Speed
  is a **ceiling, not a schedule** — if decisions are slow, the world is slow (ADR-002).
- **Dead time is skipped, visibly.** When no agent is awake and no code process has an event
  before sim-time T, the clock runs to T at a fixed fast rate: a sim-night takes about a
  real minute. It costs nothing because nothing calls a model. Not instantaneous, so a
  viewer sees that a night happened.
- **Process down = world paused.** On restart the clock resumes from the persisted sim time.
  There is no catch-up and no notion of missed time.
- **Calendar.** Five-day work week; the cafe adds Saturday. Month-end, biweekly payroll,
  quarterly review. No holidays, seasons, or ageing in the MVP.

## What happens overnight, and over a month of uptime

Real nights are invisible to the sim. At the ADR-003 target cost, $2 per day yields ≈ 25
sim-workdays per real day: **a sim-week every ≈ 5 real hours, a sim-year every ≈ 10 real
days, ≈ 3 sim-years per real month.** At the tick-driven cost it is ≈ 1.2 sim-years per month.

Consequences, all intended:

- A viewer who checks in twice a day returns to two or three sim-weeks of history. The UI's
  primary job is therefore "what happened and why", not live motion (ADR-010).
- Month-end occurs roughly every real day, so calendar-driven behaviours are observed
  hundreds of times per real month — which is what makes the validation plan feasible.
- Memory compaction is mandatory from day one, not a later optimisation (ADR-006).
- The event log grows by tens of thousands of rows per real day (ADR-009).

## Alternatives rejected

| Alternative | Why not |
|---|---|
| **Wall clock, 1:1** | Offices are closed whenever the viewer's evening is. A sim-week takes a real week, so checking "is this cascade visible within one sim-week?" takes a week per attempt. Cost would be trivial ($0.06 per day); iteration speed is fatal. |
| **Fixed multiplier** | Spend becomes an uncontrolled function of world busyness and peaks during incident spirals. The governor keeps dollars flat and lets speed float — the right way round for an unattended process. |
| **As fast as possible** | Unbounded spend, unwatchable, and guaranteed to find the rate limit. Correct for headless validation replicas, and only there. |
| **Smallville's 10-sim-second step** | 8,640 steps per sim-day to model people sitting at desks, and its end-of-action checks only work when the step divides 60 seconds (01 §2). |
| **Coarser quantum (60 min)** | Cafe service and ticket-response dynamics live below an hour. workbench found that coarsening the clock "bought nothing" — tick count matters less than tail latency. |
| **Pure next-event time advance, no quantum** | Cleaner in theory; harder to pace for a viewer, and harder to batch decisions for a parallel barrier. The quantum is a batching window. |

## Consequences

- Speed varies through the day. The dashboard shows current speed, sim time, and today's
  spend at all times.
- Validation replicas ignore pacing and the governor and run against a per-study cap.
- A manual override exists: pause, single-step, and a fixed speed for demos.

## Reverse if

- Viewers find floating speed disorienting → fixed speed with a hard daily cap that *pauses*
  the world when reached.
- Measured cost is so low that the governor never binds at `speed_max` → delete the governor,
  keep the cap.
- Dead-time skipping hides something worth seeing (e.g. overnight on-call incidents become a
  real mechanic) → the on-call agent is simply awake, and the period is no longer dead.
