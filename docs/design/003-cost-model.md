# ADR-003 — Cost model

Status: proposed · 2026-09-20 · Done first; ADR-001 and ADR-002 derive from it.

## Decision

1. **Budget is the independent variable; clock speed is derived from it.** Default ceiling
   **$2.00 per real day** for all model spend, enforced by the pacing governor (ADR-001).
2. **The unit of cost is the decision point, not the tick.** Target ≤ 20 Jev calls per agent
   per sim-workday, ≤ 4k input tokens per call.
3. **Generation is rationed by construction, not by price:** prose is rendered lazily for
   viewers (01 §3), typed escalation is capped at 5% of decisions (ADR-005), ontology
   proposals are weekly.
4. **Validation replicas are a budgeted line item**, not an afterthought: one interventional
   study is priced below.

Every volume number here is an estimate. M0 measures tokens and latency; M4 measures calls
per agent-day. This ADR is re-issued with measurements at both points.

## The arithmetic

Verified prices (00 §1, §4): Jev $0.042/M input, output free. GLM 5.3 Flash $0.15/$0.50 list.
GPT-5.6 Luna $0.20/$1.20.

Per Jev call ≈ 3,500 input tokens ≈ **$0.000147**. Anchors for 3,500: workbench decide
contexts measure 2.2k–3.9k prompt tokens (00 §6.4); TypeSafe's Doom demo implies ≈ 4.6k.

| N = 24 agents | Jev calls / agent / sim-workday | Jev $ / sim-workday | LLM $ / sim-workday | Total |
|---|---|---|---|---|
| **Event-driven target** | 18 | 0.064 | 0.013 (5% typed escalation, weekly ontology, daily digests) | **≈ 0.08** |
| Tick-driven ceiling (every 15-min tick, 85% active, 1.7 calls) | 46 | 0.163 | 0.035 | ≈ 0.20 |
| Pessimistic ceiling (6k tokens, 2.5 calls, 10% escalation) | 68 | 0.411 | 0.047 | ≈ 0.46 |

The event-driven row is anchored on workbench, which measured 7–12 LLM calls per person per
sim-day across two recorded worlds (00 §6.4). jeve can afford more wake-ups than workbench
because each costs a sixth as much; 18 is a deliberate doubling, not a measurement.

**What $2.00 per real day buys** (nights and weekends are skipped, so all wall time is
sim business hours):

| Cost per sim-workday | Sim-workdays per real day | Real minutes per 8-hour sim-workday | Business-hours speed | A sim-week takes |
|---|---|---|---|---|
| $0.08 (target) | 25 | 58 | ≈ 8× | ≈ 4.8 real hours |
| $0.20 (tick-driven) | 10 | 144 | ≈ 3.3× | ≈ 12 real hours |
| $0.46 (pessimistic) | 4.3 | 331 | ≈ 1.4× | ≈ 28 real hours |

**Validation replicas.** The MVP interventional study (02 §3.3): K = 30 seeds × 2 arms ×
H = 5 sim-workdays (one Monday–Friday) × 1 fork state. Content-hash caching plus common
random numbers make every decision untouched by the intervention free in the second arm
(ADR-007); assume 30% of decisions differ, so the second arm costs 0.3 of the first.
30 × 5 × 1.3 = 195 sim-workdays ⇒ **≈ $16 (target) to ≈ $39 (tick-driven)**. The full design
(M = 2 fork states, H = 10) is ≈ 4×. The 30% is a guess; if an outage perturbs most of the
world the saving disappears and the study costs up to 2 × 150 = 300 sim-workdays. Replicas
run headless and outside the daily governor, against an explicit per-study cap.

## Is this a design that only works because Jev is nearly free?

**Partly, and it should be said exactly.**

- The same typed workload on a flash LLM costs 6.6× (GLM) to 12× (Luna) more, because an
  LLM answering ~30 questions with distributions emits ~900 output tokens that Jev does not
  bill for. Not the ~400× on TypeSafe's homepage; that comparison is against frontier
  reasoning models.
- Cross-check against your own spend: workbench's Calder world cost ≈ $30–35 for 140
  sim-days × 17 people on DeepSeek-Flash + Haiku ≈ $0.33 per sim-day scaled to 24 people.
  This model predicts $0.42 for GLM-typed. Same ballpark from independent directions.
- At $0.42 per sim-workday, $2 per day buys ≈ 5 sim-workdays — about real time. **A
  real-time, unvalidated jeve would work on flash LLMs.** workbench is the existence proof.
- What does *not* survive without Jev: (a) faster-than-real-time always-on running inside a
  hobby budget; (b) statistical validation — the MVP-size K = 30 study would cost ≈ $80 on
  GLM and the full design ≈ 4× that;
  (c) the tick barrier — LLM E2E latency is 2–5s at P50 and 40–220s at P99 (00 §4), and
  workbench found "a cohort's wall time is its slowest member."

So: the *existence* of the sim does not depend on Jev's price. Its **speed, its validation
story, and the slow-the-clock backpressure policy do.** TypeSafe itself says of the price:
"We can't prove it isn't subsidized." If it rises 5×, jeve drops to ≈ 2× speed and studies
shrink; it does not stop working.

## Where the money actually goes

Jev is 80–90% of spend in every row. The "expensive exception" is expensive per call (2–3×)
and cheap in aggregate because it is rare; the cheap default is the bill because it is
constant. Three levers, in order of effect:

1. **Don't call.** Wake policy (ADR-004). 46 → 18 calls is a 2.5× saving.
2. **Send less.** State ≤ 2.5k tokens. Also an accuracy requirement (context rot, 00 §1.6).
3. **Go slower.** The governor.

Price is not a lever.

## Rate limits do not bind

Native limits are 1,200 req/min and 250k tok/s, "adjusting dynamically" (00 §1.4). N = 24 at
the tick-driven ceiling is ≈ 35 calls and ≈ 121k tokens per tick burst; the request limit
alone would permit ≈ 500×. A token bucket smooths bursts. Revisit at N ≥ 48, where a
synchronised burst (≈ 243k tokens) touches the per-second limit — another reason to stagger
wake-ups.

## Alternatives rejected

- **Fix the speed and measure the bill.** Spend becomes a function of how busy the world is,
  and spikes during an outage spiral — exactly when the sim is most worth watching.
- **Ignore replica cost until later.** 02 makes replicas the only source of statistical
  claims. A validation plan that is unaffordable is not a plan.
- **Cost per tick as the unit.** Makes cost depend on a scheduler quantum that has no
  behavioural meaning.

## Reverse if

- M0 shows real tokens per call > 8k: the state budget is wrong; redesign state rendering
  before anything else.
- M4 shows > 40 calls per agent-day after the wake policy: the wake policy is wrong.
- Jev's price rises ≥ 10×: tier 1 escalation and Jev converge in cost; reconsider a local
  small model for J-type questions.
