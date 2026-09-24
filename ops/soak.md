# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 7 of 7 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 43 ticket(s) opened in the last 14 days against 12 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 6 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $147,800 and spent $4,575 at the cafe |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 24 reached / 13 decided, of 100, ledgerline 38 reached / 19 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $33,820 | $19,040 | $9,670 | $8,170 | $8,170 |
| halloran | $96,000 | $107,959 | $108,161 | $97,621 | $88,101 | $78,821 |
| ledgerline | $41,000 | $84,869 | $95,310 | $88,980 | $83,930 | $75,770 |
| thirdrail | $9,400 | $14,596 | $20,087 | $24,841 | $29,202 | $34,801 |
| households | $20,000 | $54,541 | $89,045 | $123,490 | $143,357 | $163,225 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 9 | 0 | 0 | $52,642 | +0.0 |
| ledgerline | 50 | 23 | 0 | 0 | $92,468 | +0.6 |
| tallybird | 212 | 109 | 0 | 0 | $5,125 | +0.3 |
| thirdrail | 14 | 10 | 0 | 0 | $720 | -0.9 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 46 | 46 | 2 |
| 1 | 11 | 11 | 0 |
| 2 | 35 | 35 | 1 |
| 3 | 16 | 16 | 1 |
| 4 | 24 | 22 | 1 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 22320 | 69.2% |
| `cafe.purchase` | rules | 7635 | 23.7% |
| `catering.order` | rules | 30 | 0.1% |
| `close.signoff` | rules | 6 | 0.0% |
| `credit.decision` | rules | 46 | 0.1% |
| `episode.round` | rules | 668 | 2.1% |
| `file.ticket` | rules | 339 | 1.1% |
| `payment.timing` | rules | 242 | 0.8% |
| `payroll.release` | rules | 24 | 0.1% |
| `ticket.answer` | rules | 588 | 1.8% |
| `ticket.confirm` | rules | 204 | 0.6% |
| `ticket.triage` | rules | 141 | 0.4% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 4054 |
| `cafe.sale` | 6914 |
| `cafe.walkout` | 721 |
| `catering.delivered` | 14 |
| `catering.ordered` | 14 |
| `close.completed` | 6 |
| `credit.issued` | 18 |
| `encounter` | 1969 |
| `episode.closed` | 115 |
| `episode.opened` | 115 |
| `episode.round` | 259 |
| `fact.passed` | 56 |
| `incident.ended` | 28 |
| `incident.started` | 28 |
| `insolvency.warning` | 7 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 63 |
| `month.end` | 2 |
| `outage.heard` | 50 |
| `payment.deferred` | 39 |
| `payment.made` | 146 |
| `payroll.held` | 1 |
| `payroll.paid` | 18 |
| `promise.made` | 7 |
| `ticket.answered` | 147 |
| `ticket.closed` | 145 |
| `ticket.escalated` | 20 |
| `ticket.opened` | 132 |
| `ticket.reopened` | 6 |
| `ticket.triaged` | 141 |

### Insolvency warnings

| when | firm | cash | weekly wages | overdue to them | cause |
|---|---|---:|---:|---:|---|
| d18 Fri 10:00 | tallybird | $24,270 | $14,600 | $0 | thin_reserves |
| d25 Fri 10:00 | tallybird | $8,170 | $14,600 | $0 | thin_reserves |
| d28 Mon 09:00 | tallybird | $8,170 | $14,600 | $0 | spending_exceeds_income |
| d29 Tue 09:00 | tallybird | $8,170 | $14,600 | $0 | spending_exceeds_income |
| d30 Wed 09:00 | tallybird | $8,170 | $14,600 | $0 | spending_exceeds_income |
| d31 Thu 09:00 | tallybird | $8,170 | $14,600 | $0 | spending_exceeds_income |
| d32 Fri 09:00 | tallybird | $8,170 | $14,600 | $0 | spending_exceeds_income |
