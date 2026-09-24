# Measured unit economics

Golden fixture, 5 sim-days, seed-fixed, pacing off. Every figure is what OpenRouter billed (`usage.cost`), recorded against the call that incurred it. Nothing is projected from list price.

| | measured |
| --- | --- |
| persons | 424 |
| orgs | 4 |
| events | 2100 |
| decisions | 3743 |
| of those, decided by a model | 2983 |
| distinct model calls those decisions needed | 1072 |
| input tokens billed | 770,948 |
| calls whose cost was estimated, not billed | 0 |
| **total cost of this run, from a cold cache** | **$0.134391** |

## Decisions by model

| model | decisions | distinct calls |
| --- | --- | --- |
| `google/gemini-3.8-flash` | 19 | 19 |
| `typesafe/jev-1.13-20260917` | 2983 | 985 |
| `z-ai/glm-5.3-flash` | 68 | 68 |

## By question set

| question set | decided by | decisions | distinct calls | cost |
| --- | --- | --- | --- | --- |
| `agent.tick` | jev | 1902 | 768 | $0.025043 |
| `cafe.purchase` | jev | 556 | 6 | $0.000095 |
| `cafe.purchase` | rules | 740 | 0 | $0.000000 |
| `catering.order` | jev | 6 | 4 | $0.000074 |
| `close.order` | jev | 1 | 1 | $0.000021 |
| `close.signoff` | jev | 2 | 2 | $0.000036 |
| `credit.decision` | jev | 4 | 4 | $0.000083 |
| `deploy.decision` | jev | 2 | 2 | $0.000031 |
| `dispute.resolution` | jev | 5 | 2 | $0.000036 |
| `eng.allocation` | jev | 1 | 1 | $0.000019 |
| `episode.round` | llm | 87 | 87 | $0.106962 |
| `escalation.handoff` | jev | 6 | 2 | $0.000032 |
| `file.ticket` | jev | 79 | 8 | $0.000192 |
| `file.ticket` | rules | 3 | 0 | $0.000000 |
| `founder.review` | jev | 4 | 4 | $0.000091 |
| `invoice.dispute` | jev | 17 | 8 | $0.000124 |
| `payment.timing` | jev | 25 | 5 | $0.000081 |
| `payment.timing` | rules | 11 | 0 | $0.000000 |
| `payroll.release` | jev | 4 | 1 | $0.000017 |
| `supplier.order` | jev | 1 | 1 | $0.000017 |
| `ticket.answer` | jev | 83 | 16 | $0.000258 |
| `ticket.confirm` | jev | 55 | 6 | $0.000100 |
| `ticket.confirm` | rules | 6 | 0 | $0.000000 |
| `ticket.triage` | jev | 37 | 11 | $0.000220 |
| `time.log` | jev | 20 | 9 | $0.000135 |
| `vendor.trust` | jev | 86 | 37 | $0.000725 |

## Against the targets

| metric | target | measured | if nothing were shared | |
| --- | --- | --- | --- | --- |
| per 100 persons, per sim-day | $1.00 | $0.006339 | $0.008583 | ok |
| per 10 orgs, per sim-day | $1.00 | $0.067195 | $0.090984 | ok |
| per 1000 events | $1.00 | $0.063996 | $0.086652 | ok |
| spend per sim-day | $2.00 (cap $10.00) | $0.026878 | $0.036394 | ok |

**Sharing.** 64.1% of model-made decisions reused a call another decision had already paid for: the situation, rendered in words, was identical, so the distribution is too — only the draw differs, and the draw is per person. *Measured* is what this run costs from a cold cache. *If nothing were shared* prices every decision as its own call; it is an upper bound computed from measured per-call costs, not something that was run, and the verdict column is judged against it so the targets are not met on the strength of the cache.

**This invocation** ran in `record` mode: 2983 decisions asked of the model, 1933 answered from the cache, 1091 live call(s) costing $0.151133.

## Verdict

**MET.** 79.7% of decisions were made by a model, and every target holds even with sharing ignored.

