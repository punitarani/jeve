# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 8 of 8 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 50 ticket(s) opened in the last 14 days against 12 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 6 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $147,800 and spent $4,365 at the cafe |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 24 reached / 13 decided, of 100, ledgerline 38 reached / 19 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |
| the outage moves money without re-rolling it | yes | invoice amounts identical across arms and cash different |

## Counterfactual: the same world without the month-end outage

| | outage | no outage |
|---|---:|---:|
| month-end client invoices issued | 41 | 41 |
| issued in both arms | 41 | 41 |
| of those, same amount in both arms | 41 | 41 |
| of those, issued at a different time | 15 | 15 |
| tallybird cash at the end | $7,900.00 | $8,170.00 |
| halloran cash at the end | $78,580.91 | $89,825.43 |
| ledgerline cash at the end | $75,154.50 | $98,004.48 |
| thirdrail cash at the end | $35,768.76 | $35,059.10 |

**Invoice amounts constant across arms:** yes (41 of 41). **Cash differs across arms:** yes.

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $33,820 | $18,860 | $8,620 | $8,260 | $7,900 |
| halloran | $96,000 | $107,959 | $108,161 | $98,761 | $88,041 | $78,581 |
| ledgerline | $41,000 | $84,869 | $95,070 | $87,884 | $82,954 | $75,154 |
| thirdrail | $9,400 | $14,635 | $20,573 | $25,794 | $30,092 | $35,769 |
| households | $20,000 | $54,535 | $89,012 | $123,563 | $143,455 | $163,435 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 9 | 0 | 0 | $52,642 | +0.0 |
| ledgerline | 50 | 23 | 0 | 0 | $92,468 | +0.5 |
| tallybird | 212 | 109 | 0 | 0 | $5,155 | +0.3 |
| thirdrail | 19 | 15 | 0 | 0 | $1,200 | -0.6 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 44 | 44 | 1 |
| 1 | 7 | 7 | 0 |
| 2 | 40 | 40 | 2 |
| 3 | 24 | 24 | 1 |
| 4 | 25 | 23 | 0 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 22320 | 70.6% |
| `cafe.purchase` | rules | 7608 | 24.1% |
| `catering.order` | rules | 30 | 0.1% |
| `close.signoff` | rules | 6 | 0.0% |
| `credit.decision` | rules | 46 | 0.1% |
| `file.ticket` | rules | 347 | 1.1% |
| `payment.timing` | rules | 253 | 0.8% |
| `payroll.release` | rules | 24 | 0.1% |
| `ticket.answer` | rules | 616 | 1.9% |
| `ticket.confirm` | rules | 224 | 0.7% |
| `ticket.triage` | rules | 149 | 0.5% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 4059 |
| `cafe.sale` | 6902 |
| `cafe.walkout` | 706 |
| `catering.delivered` | 19 |
| `catering.ordered` | 19 |
| `close.completed` | 6 |
| `credit.issued` | 16 |
| `encounter` | 2072 |
| `incident.ended` | 28 |
| `incident.started` | 28 |
| `insolvency.warning` | 7 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 68 |
| `month.end` | 2 |
| `payment.deferred` | 41 |
| `payment.made` | 152 |
| `payroll.held` | 1 |
| `payroll.paid` | 18 |
| `ticket.answered` | 154 |
| `ticket.closed` | 152 |
| `ticket.escalated` | 16 |
| `ticket.opened` | 140 |
| `ticket.reopened` | 5 |
| `ticket.triaged` | 149 |

### Insolvency warnings

| when | firm | cash | weekly wages | overdue to them | cause |
|---|---|---:|---:|---:|---|
| d18 Fri 10:00 | tallybird | $23,220 | $14,600 | $0 | thin_reserves |
| d25 Fri 10:00 | tallybird | $8,260 | $14,600 | $0 | thin_reserves |
| d28 Mon 09:00 | tallybird | $8,260 | $14,600 | $0 | spending_exceeds_income |
| d29 Tue 09:00 | tallybird | $8,260 | $14,600 | $0 | spending_exceeds_income |
| d30 Wed 09:00 | tallybird | $8,260 | $14,600 | $0 | spending_exceeds_income |
| d31 Thu 09:00 | tallybird | $8,080 | $14,600 | $0 | spending_exceeds_income |
| d32 Fri 09:00 | tallybird | $8,080 | $14,600 | $0 | spending_exceeds_income |
