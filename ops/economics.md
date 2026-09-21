# Measured unit economics

Golden fixture, 5 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 2082 |
| decisions | 5823 |
| of those, decided by a model | 5182 |
| distinct model calls those decisions needed | 1137 |
| input tokens billed | 1,038,611 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.043622** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `typesafe/jev-1.13-20260917` | 5182 | 1137 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `agent.tick` | jev | 4200 | 1064 | $0.042345 |
| `cafe.purchase` | jev | 690 | 15 | $0.000241 |
| `cafe.purchase` | rules | 619 | 0 | $0.000000 |
| `catering.order` | jev | 6 | 5 | $0.000092 |
| `close.signoff` | jev | 3 | 3 | $0.000053 |
| `credit.decision` | jev | 6 | 6 | $0.000125 |
| `file.ticket` | jev | 91 | 6 | $0.000098 |
| `file.ticket` | rules | 2 | 0 | $0.000000 |
| `payment.timing` | jev | 40 | 8 | $0.000128 |
| `payroll.release` | jev | 4 | 1 | $0.000017 |
| `ticket.answer` | jev | 62 | 10 | $0.000163 |
| `ticket.confirm` | jev | 44 | 6 | $0.000100 |
| `ticket.confirm` | rules | 20 | 0 | $0.000000 |
| `ticket.triage` | jev | 36 | 13 | $0.000259 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.002058 | $0.006922 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.021811 | $0.073378 | ok |
| per 1000 events | $1.00 | $0.020952 | $0.070488 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.008724 | $0.029351 | ok |

**Sharing.** 78.1% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 5182 decisions asked of the model, 5121 answered from the cache, 55 live call(s) costing $0.002061.

## Verdict

**MET.** 89.0% of decisions were made by a model, and every target holds even with sharing ignored.

