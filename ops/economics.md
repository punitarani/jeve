# Measured unit economics

Golden fixture, 5 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 2261 |
| decisions | 3948 |
| of those, decided by a model | 3184 |
| distinct model calls those decisions needed | 1088 |
| input tokens billed | 800,178 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.050283** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `typesafe/jev-1.13-20260917` | 3184 | 998 |
| `z-ai/glm-5.3-flash` | 96 | 90 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `agent.tick` | jev | 2087 | 772 | $0.025782 |
| `cafe.purchase` | jev | 545 | 6 | $0.000095 |
| `cafe.purchase` | rules | 734 | 0 | $0.000000 |
| `catering.accept` | jev | 1 | 1 | $0.000015 |
| `catering.order` | jev | 6 | 3 | $0.000055 |
| `close.order` | jev | 1 | 1 | $0.000031 |
| `close.signoff` | jev | 2 | 2 | $0.000036 |
| `credit.decision` | jev | 4 | 4 | $0.000134 |
| `deploy.decision` | jev | 2 | 2 | $0.000031 |
| `dispute.resolution` | jev | 2 | 1 | $0.000027 |
| `eng.allocation` | jev | 1 | 1 | $0.000028 |
| `episode.round` | llm | 96 | 91 | $0.021642 |
| `escalation.handoff` | jev | 15 | 2 | $0.000032 |
| `file.ticket` | jev | 80 | 9 | $0.000215 |
| `file.ticket` | rules | 5 | 0 | $0.000000 |
| `founder.review` | jev | 4 | 4 | $0.000211 |
| `invoice.dispute` | jev | 17 | 8 | $0.000124 |
| `payment.timing` | jev | 33 | 13 | $0.000316 |
| `payment.timing` | rules | 10 | 0 | $0.000000 |
| `payroll.release` | jev | 4 | 1 | $0.000017 |
| `supplier.order` | jev | 1 | 1 | $0.000024 |
| `ticket.answer` | jev | 85 | 16 | $0.000258 |
| `ticket.confirm` | jev | 50 | 6 | $0.000100 |
| `ticket.confirm` | rules | 15 | 0 | $0.000000 |
| `ticket.triage` | jev | 39 | 11 | $0.000321 |
| `time.log` | jev | 20 | 11 | $0.000165 |
| `vendor.trust` | jev | 89 | 32 | $0.000622 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.002372 | $0.004983 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.025141 | $0.052825 | ok |
| per 1000 events | $1.00 | $0.022239 | $0.046727 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.010057 | $0.021130 | ok |

**Sharing.** 65.8% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 3184 decisions asked of the model, 3184 answered from the cache, 0 live call(s) costing $0.000000.

## Verdict

**MET.** 80.6% of decisions were made by a model, and every target holds even with sharing ignored.

