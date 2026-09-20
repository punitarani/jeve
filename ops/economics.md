# Measured unit economics

Golden fixture, 7 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 1165 |
| decisions | 1351 |
| of those, decided by a model | 1163 |
| distinct model calls those decisions needed | 54 |
| input tokens billed | 21,811 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.000916** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `typesafe/jev-1.13-20260917` | 1163 | 54 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `cafe.purchase` | jev | 856 | 18 | $0.000289 |
| `file.ticket` | jev | 107 | 3 | $0.000049 |
| `file.ticket` | rules | 186 | 0 | $0.000000 |
| `payment.timing` | jev | 98 | 5 | $0.000077 |
| `payment.timing` | rules | 2 | 0 | $0.000000 |
| `ticket.answer` | jev | 64 | 16 | $0.000262 |
| `ticket.triage` | jev | 38 | 12 | $0.000240 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.000031 | $0.000628 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.000327 | $0.006660 | ok |
| per 1000 events | $1.00 | $0.000786 | $0.016008 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.000131 | $0.002664 | ok |

**Sharing.** 95.4% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 1163 decisions asked of the model, 1163 answered from the cache, 0 live call(s) costing $0.000000.

## Verdict

**MET.** 86.1% of decisions were made by a model, and every target holds even with sharing ignored.

