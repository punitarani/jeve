# Measured unit economics

Golden fixture, 5 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 1744 |
| decisions | 5340 |
| of those, decided by a model | 5198 |
| distinct model calls those decisions needed | 1090 |
| input tokens billed | 991,285 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.041634** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `typesafe/jev-1.13-20260917` | 5198 | 1090 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `agent.tick` | jev | 3960 | 1021 | $0.040411 |
| `cafe.purchase` | jev | 920 | 18 | $0.000289 |
| `catering.order` | jev | 6 | 5 | $0.000092 |
| `close.signoff` | jev | 3 | 3 | $0.000053 |
| `credit.decision` | jev | 10 | 8 | $0.000168 |
| `file.ticket` | jev | 84 | 3 | $0.000049 |
| `file.ticket` | rules | 140 | 0 | $0.000000 |
| `payment.timing` | jev | 122 | 5 | $0.000077 |
| `payment.timing` | rules | 2 | 0 | $0.000000 |
| `payroll.release` | jev | 4 | 1 | $0.000017 |
| `ticket.answer` | jev | 54 | 11 | $0.000180 |
| `ticket.triage` | jev | 35 | 15 | $0.000299 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.001964 | $0.006658 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.020817 | $0.070578 | ok |
| per 1000 events | $1.00 | $0.023873 | $0.080938 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.008327 | $0.028231 | ok |

**Sharing.** 79.0% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 5198 decisions asked of the model, 5198 answered from the cache, 0 live call(s) costing $0.000000.

## Verdict

**MET.** 97.3% of decisions were made by a model, and every target holds even with sharing ignored.

