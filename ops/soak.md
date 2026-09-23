# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 7 of 7 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 40 ticket(s) opened in the last 14 days against 12 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 6 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $147,800 and spent $4,541 at the cafe |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 24 reached / 13 decided, of 100, ledgerline 38 reached / 19 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $33,955 | $19,175 | $8,500 | $8,140 | $7,720 |
| halloran | $96,000 | $107,959 | $108,161 | $97,666 | $88,386 | $79,106 |
| ledgerline | $41,000 | $84,734 | $94,934 | $90,934 | $82,714 | $74,914 |
| thirdrail | $9,400 | $14,562 | $20,269 | $23,978 | $30,129 | $35,745 |
| households | $20,000 | $54,576 | $89,071 | $123,477 | $143,345 | $163,259 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 9 | 0 | 0 | $52,642 | +0.0 |
| ledgerline | 50 | 23 | 0 | 0 | $92,468 | +0.2 |
| tallybird | 212 | 109 | 0 | 0 | $5,125 | +0.2 |
| thirdrail | 17 | 13 | 0 | 0 | $960 | -1.3 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 43 | 43 | 3 |
| 1 | 18 | 18 | 1 |
| 2 | 34 | 34 | 1 |
| 3 | 18 | 18 | 1 |
| 4 | 20 | 19 | 1 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 22320 | 69.6% |
| `cafe.purchase` | rules | 7669 | 23.9% |
| `catering.order` | rules | 30 | 0.1% |
| `close.signoff` | rules | 6 | 0.0% |
| `credit.decision` | rules | 47 | 0.1% |
| `episode.round` | rules | 544 | 1.7% |
| `file.ticket` | rules | 322 | 1.0% |
| `payment.timing` | rules | 240 | 0.7% |
| `payroll.release` | rules | 24 | 0.1% |
| `ticket.answer` | rules | 485 | 1.5% |
| `ticket.confirm` | rules | 225 | 0.7% |
| `ticket.triage` | rules | 142 | 0.4% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 4123 |
| `cafe.sale` | 6907 |
| `cafe.walkout` | 762 |
| `catering.delivered` | 17 |
| `catering.ordered` | 17 |
| `close.completed` | 6 |
| `credit.issued` | 21 |
| `encounter` | 2017 |
| `episode.closed` | 90 |
| `episode.opened` | 90 |
| `episode.round` | 210 |
| `fact.passed` | 51 |
| `incident.ended` | 29 |
| `incident.started` | 29 |
| `insolvency.warning` | 7 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 66 |
| `month.end` | 2 |
| `outage.heard` | 42 |
| `payment.deferred` | 38 |
| `payment.made` | 149 |
| `payroll.held` | 1 |
| `payroll.paid` | 18 |
| `promise.made` | 10 |
| `ticket.answered` | 150 |
| `ticket.closed` | 149 |
| `ticket.escalated` | 23 |
| `ticket.opened` | 133 |
| `ticket.reopened` | 8 |
| `ticket.triaged` | 142 |

### Insolvency warnings

| when | firm | cash | weekly wages | overdue to them | cause |
|---|---|---:|---:|---:|---|
| d18 Fri 10:00 | tallybird | $23,100 | $14,600 | $0 | thin_reserves |
| d25 Fri 10:00 | tallybird | $8,140 | $14,600 | $0 | thin_reserves |
| d28 Mon 09:00 | tallybird | $8,140 | $14,600 | $0 | spending_exceeds_income |
| d29 Tue 09:00 | tallybird | $7,720 | $14,600 | $0 | spending_exceeds_income |
| d30 Wed 09:00 | tallybird | $7,720 | $14,600 | $0 | spending_exceeds_income |
| d31 Thu 09:00 | tallybird | $7,720 | $14,600 | $0 | spending_exceeds_income |
| d32 Fri 09:00 | tallybird | $7,720 | $14,600 | $0 | spending_exceeds_income |
