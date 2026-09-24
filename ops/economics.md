# Measured unit economics

Golden fixture, 5 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 2145 |
| decisions | 3805 |
| of those, decided by a model | 3047 |
| distinct model calls those decisions needed | 1078 |
| input tokens billed | 788,588 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.033121** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `typesafe/jev-1.13-20260917` | 3047 | 1078 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `agent.tick` | jev | 1891 | 785 | $0.025615 |
| `cafe.purchase` | jev | 559 | 6 | $0.000095 |
| `cafe.purchase` | rules | 740 | 0 | $0.000000 |
| `catering.accept` | jev | 1 | 1 | $0.000015 |
| `catering.order` | jev | 6 | 5 | $0.000093 |
| `close.order` | jev | 1 | 1 | $0.000021 |
| `close.signoff` | jev | 2 | 2 | $0.000036 |
| `credit.decision` | jev | 4 | 4 | $0.000083 |
| `deploy.decision` | jev | 2 | 2 | $0.000031 |
| `dispute.resolution` | jev | 5 | 2 | $0.000036 |
| `eng.allocation` | jev | 1 | 1 | $0.000019 |
| `episode.round` | jev | 167 | 161 | $0.005113 |
| `escalation.handoff` | jev | 5 | 3 | $0.000048 |
| `file.ticket` | jev | 76 | 5 | $0.000120 |
| `file.ticket` | rules | 3 | 0 | $0.000000 |
| `founder.review` | jev | 4 | 4 | $0.000091 |
| `invoice.dispute` | jev | 17 | 8 | $0.000124 |
| `payment.timing` | jev | 25 | 5 | $0.000081 |
| `payment.timing` | rules | 11 | 0 | $0.000000 |
| `payroll.release` | jev | 4 | 1 | $0.000017 |
| `supplier.order` | jev | 1 | 1 | $0.000017 |
| `ticket.answer` | jev | 84 | 18 | $0.000290 |
| `ticket.confirm` | jev | 53 | 6 | $0.000100 |
| `ticket.confirm` | rules | 4 | 0 | $0.000000 |
| `ticket.triage` | jev | 35 | 11 | $0.000220 |
| `time.log` | jev | 20 | 10 | $0.000150 |
| `vendor.trust` | jev | 84 | 36 | $0.000706 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.001562 | $0.003780 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.016560 | $0.040065 | ok |
| per 1000 events | $1.00 | $0.015441 | $0.037357 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.006624 | $0.016026 | ok |

**Sharing.** 64.6% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 3047 decisions asked of the model, 1904 answered from the cache, 1078 live call(s) costing $0.033121.

## Verdict

**MET.** 80.1% of decisions were made by a model, and every target holds even with sharing ignored.

