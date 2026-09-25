# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 12 of 12 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 45 report(s) in the last 14 days against 6 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 5 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $177,000 and spent $164,162 |
| no cash account is ever overdrawn | yes | none |
| an insolvency warning is answered by the head of the firm | yes | 0 warning(s) with no review within a week |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 99 reached / 99 decided, of 100, halloran 24 reached / 24 decided, of 100, ledgerline 38 reached / 38 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |
| every week has friction in it | yes | every week |
| an escalation handed on is decided within the hour | yes | 34 handoff(s) decided, 0 still queued past due |
| every loop on a calendar decides something | yes | eng.allocation, deploy.decision, time.log, supplier.order, founder.review, invoice.dispute, payment.timing, payroll.release, close.order |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $30,000 | $15,400 | $48,206 | $40,350 | $23,318 |
| halloran | $96,000 | $96,059 | $95,841 | $85,481 | $76,201 | $70,829 |
| ledgerline | $50,000 | $75,722 | $96,500 | $94,128 | $87,498 | $90,553 |
| thirdrail | $18,000 | $19,178 | $22,172 | $22,770 | $24,919 | $23,140 |
| households | $53,100 | $55,590 | $58,198 | $60,763 | $63,317 | $65,938 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 12 | 1 | 0 | $61,688 | +2.3 |
| ledgerline | 49 | 27 | 6 | 0 | $78,498 | +2.1 |
| tallybird | 207 | 106 | 12 | 0 | $55,596 | +2.1 |
| thirdrail | 11 | 8 | 0 | 0 | $1,020 | -0.6 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 35 | 35 | 5 |
| 1 | 19 | 19 | 1 |
| 2 | 29 | 29 | 0 |
| 3 | 8 | 8 | 2 |
| 4 | 19 | 11 | 3 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 9512 | 47.7% |
| `cafe.purchase` | rules | 7552 | 37.9% |
| `catering.accept` | rules | 12 | 0.1% |
| `catering.order` | rules | 30 | 0.2% |
| `chase.invoice` | rules | 48 | 0.2% |
| `close.order` | rules | 2 | 0.0% |
| `close.signoff` | rules | 5 | 0.0% |
| `cover.shift` | rules | 1 | 0.0% |
| `credit.decision` | rules | 26 | 0.1% |
| `deploy.decision` | rules | 10 | 0.1% |
| `dispute.resolution` | rules | 2 | 0.0% |
| `eng.allocation` | rules | 5 | 0.0% |
| `episode.round` | rules | 761 | 3.8% |
| `escalation.handoff` | rules | 34 | 0.2% |
| `file.ticket` | rules | 261 | 1.3% |
| `founder.review` | rules | 8 | 0.0% |
| `invoice.dispute` | rules | 57 | 0.3% |
| `payment.timing` | rules | 448 | 2.2% |
| `payroll.release` | rules | 20 | 0.1% |
| `retention.offer` | rules | 15 | 0.1% |
| `subscription.renew` | rules | 37 | 0.2% |
| `supplier.order` | rules | 5 | 0.0% |
| `ticket.answer` | rules | 394 | 2.0% |
| `ticket.confirm` | rules | 179 | 0.9% |
| `ticket.triage` | rules | 119 | 0.6% |
| `time.log` | rules | 99 | 0.5% |
| `vendor.trust` | rules | 300 | 1.5% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 3837 |
| `cafe.sale` | 7051 |
| `cafe.walkout` | 501 |
| `catering.declined` | 1 |
| `catering.delivered` | 11 |
| `catering.ordered` | 12 |
| `close.completed` | 5 |
| `close.queued` | 2 |
| `credit.issued` | 12 |
| `deploy.held` | 3 |
| `deploy.shipped` | 7 |
| `dispute.resolved` | 2 |
| `encounter` | 1182 |
| `eng.allocated` | 5 |
| `episode.closed` | 137 |
| `episode.opened` | 137 |
| `episode.round` | 283 |
| `escalation.dropped` | 19 |
| `escalation.relayed` | 15 |
| `fact.passed` | 74 |
| `firm.reviewed` | 8 |
| `households.spent` | 20 |
| `incident.ended` | 15 |
| `incident.prioritised` | 10 |
| `incident.started` | 15 |
| `invoice.blocked` | 2 |
| `invoice.chased` | 22 |
| `invoice.disputed` | 2 |
| `invoice.issued` | 59 |
| `month.end` | 2 |
| `outage.heard` | 14 |
| `outage.workaround` | 253 |
| `payment.deferred` | 54 |
| `payment.made` | 151 |
| `payroll.paid` | 20 |
| `postmortem.debt` | 1 |
| `prices.raised` | 1 |
| `promise.broken` | 2 |
| `promise.made` | 6 |
| `relationship.soured` | 12 |
| `rent.paid` | 8 |
| `shift.covered` | 1 |
| `shock.client_dispute` | 1 |
| `shock.large_catering` | 1 |
| `shock.outage` | 2 |
| `shock.rumour` | 1 |
| `shock.sick` | 4 |
| `shock.supplier_price` | 1 |
| `subscription.cancelled` | 4 |
| `supplier.paid` | 5 |
| `ticket.answered` | 132 |
| `ticket.closed` | 124 |
| `ticket.escalated` | 9 |
| `ticket.opened` | 110 |
| `ticket.reopened` | 13 |
| `ticket.triaged` | 119 |
| `time.logged` | 68 |
| `time.lost` | 1 |
| `trust.revised` | 160 |
