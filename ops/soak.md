# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 12 of 12 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 29 ticket(s) opened in the last 14 days against 6 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 5 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $177,000 and spent $163,674 |
| no cash account is ever overdrawn | yes | none |
| an insolvency warning is answered by the head of the firm | yes | 0 warning(s) with no review within a week |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 24 reached / 24 decided, of 100, ledgerline 38 reached / 38 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |
| every week has friction in it | yes | every week |
| an escalation handed on is decided within the hour | yes | 31 handoff(s) decided, 0 still queued past due |
| every loop on a calendar decides something | yes | eng.allocation, deploy.decision, time.log, supplier.order, founder.review, invoice.dispute, payment.timing, payroll.release, close.order |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $30,000 | $15,400 | $57,801 | $43,201 | $24,601 |
| halloran | $96,000 | $102,459 | $102,241 | $91,746 | $82,466 | $73,617 |
| ledgerline | $50,000 | $90,189 | $100,390 | $95,940 | $88,410 | $93,168 |
| thirdrail | $18,000 | $19,013 | $22,163 | $22,834 | $24,908 | $23,546 |
| households | $53,100 | $55,773 | $58,485 | $61,148 | $63,844 | $66,426 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 15 | 0 | 0 | $59,003 | -0.4 |
| ledgerline | 49 | 28 | 1 | 0 | $74,743 | -0.1 |
| tallybird | 209 | 107 | 0 | 0 | $56,966 | +0.2 |
| thirdrail | 12 | 9 | 0 | 0 | $780 | -0.7 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 38 | 38 | 5 |
| 1 | 18 | 18 | 1 |
| 2 | 9 | 9 | 0 |
| 3 | 10 | 10 | 2 |
| 4 | 14 | 6 | 3 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 9423 | 48.7% |
| `cafe.purchase` | rules | 7576 | 39.2% |
| `catering.accept` | rules | 13 | 0.1% |
| `catering.order` | rules | 30 | 0.2% |
| `chase.invoice` | rules | 1 | 0.0% |
| `close.order` | rules | 2 | 0.0% |
| `close.signoff` | rules | 5 | 0.0% |
| `cover.shift` | rules | 1 | 0.0% |
| `credit.decision` | rules | 22 | 0.1% |
| `deploy.decision` | rules | 10 | 0.1% |
| `dispute.resolution` | rules | 2 | 0.0% |
| `eng.allocation` | rules | 5 | 0.0% |
| `episode.round` | rules | 647 | 3.3% |
| `escalation.handoff` | rules | 31 | 0.2% |
| `file.ticket` | rules | 246 | 1.3% |
| `founder.review` | rules | 8 | 0.0% |
| `invoice.dispute` | rules | 58 | 0.3% |
| `payment.timing` | rules | 218 | 1.1% |
| `payroll.release` | rules | 20 | 0.1% |
| `retention.offer` | rules | 16 | 0.1% |
| `subscription.renew` | rules | 36 | 0.2% |
| `supplier.order` | rules | 5 | 0.0% |
| `ticket.answer` | rules | 347 | 1.8% |
| `ticket.confirm` | rules | 156 | 0.8% |
| `ticket.triage` | rules | 98 | 0.5% |
| `time.log` | rules | 99 | 0.5% |
| `vendor.trust` | rules | 271 | 1.4% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 3837 |
| `cafe.sale` | 6987 |
| `cafe.walkout` | 589 |
| `catering.declined` | 1 |
| `catering.delivered` | 12 |
| `catering.ordered` | 13 |
| `close.completed` | 5 |
| `close.queued` | 2 |
| `credit.issued` | 7 |
| `deploy.held` | 4 |
| `deploy.shipped` | 6 |
| `dispute.resolved` | 2 |
| `encounter` | 1197 |
| `eng.allocated` | 5 |
| `episode.closed` | 102 |
| `episode.opened` | 102 |
| `episode.round` | 221 |
| `escalation.dropped` | 15 |
| `escalation.relayed` | 16 |
| `fact.passed` | 55 |
| `firm.reviewed` | 8 |
| `households.spent` | 20 |
| `incident.ended` | 13 |
| `incident.prioritised` | 9 |
| `incident.started` | 13 |
| `invoice.blocked` | 2 |
| `invoice.chased` | 1 |
| `invoice.disputed` | 2 |
| `invoice.issued` | 60 |
| `month.end` | 2 |
| `outage.heard` | 27 |
| `outage.workaround` | 237 |
| `payment.deferred` | 14 |
| `payment.made` | 158 |
| `payroll.paid` | 20 |
| `postmortem.debt` | 1 |
| `prices.raised` | 1 |
| `promise.broken` | 1 |
| `promise.made` | 8 |
| `rent.paid` | 8 |
| `shift.covered` | 1 |
| `shock.client_dispute` | 1 |
| `shock.large_catering` | 1 |
| `shock.outage` | 2 |
| `shock.rumour` | 1 |
| `shock.sick` | 4 |
| `shock.supplier_price` | 1 |
| `subscription.cancelled` | 3 |
| `supplier.paid` | 5 |
| `ticket.answered` | 111 |
| `ticket.closed` | 103 |
| `ticket.escalated` | 8 |
| `ticket.opened` | 89 |
| `ticket.reopened` | 13 |
| `ticket.triaged` | 98 |
| `time.logged` | 68 |
| `trust.revised` | 153 |
