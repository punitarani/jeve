# Soak: 35 sim-days, decided by `rules`, with episodes

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 7 of 7 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 51 ticket(s) opened in the last 14 days against 12 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 6 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $147,800 and spent $4,441 at the cafe |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 24 reached / 18 decided, of 100, ledgerline 38 reached / 24 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $48,000 | $33,955 | $19,175 | $8,215 | $7,795 | $7,615 |
| halloran | $96,000 | $107,959 | $108,161 | $97,681 | $88,401 | $89,900 |
| ledgerline | $41,000 | $84,734 | $94,934 | $90,934 | $82,954 | $91,514 |
| thirdrail | $9,400 | $14,533 | $20,291 | $24,265 | $30,207 | $35,990 |
| households | $20,000 | $54,604 | $89,081 | $123,501 | $143,398 | $163,359 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 26 | 12 | 0 | 0 | $41,862 | -0.2 |
| ledgerline | 50 | 28 | 0 | 0 | $75,689 | +0.0 |
| tallybird | 212 | 109 | 0 | 0 | $5,125 | +0.2 |
| thirdrail | 17 | 13 | 0 | 0 | $960 | -0.6 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 44 | 44 | 3 |
| 1 | 14 | 14 | 0 |
| 2 | 36 | 36 | 1 |
| 3 | 26 | 26 | 2 |
| 4 | 22 | 20 | 0 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 22320 | 69.2% |
| `cafe.purchase` | rules | 7655 | 23.7% |
| `catering.order` | rules | 30 | 0.1% |
| `close.signoff` | rules | 6 | 0.0% |
| `credit.decision` | rules | 46 | 0.1% |
| `episode.round` | rules | 602 | 1.9% |
| `file.ticket` | rules | 349 | 1.1% |
| `payment.timing` | rules | 269 | 0.8% |
| `payroll.release` | rules | 24 | 0.1% |
| `ticket.answer` | rules | 599 | 1.9% |
| `ticket.confirm` | rules | 226 | 0.7% |
| `ticket.triage` | rules | 151 | 0.5% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 4086 |
| `cafe.sale` | 6893 |
| `cafe.walkout` | 762 |
| `catering.delivered` | 17 |
| `catering.ordered` | 17 |
| `close.completed` | 6 |
| `credit.issued` | 22 |
| `encounter` | 1955 |
| `episode.closed` | 95 |
| `episode.opened` | 95 |
| `episode.round` | 225 |
| `fact.passed` | 48 |
| `incident.ended` | 28 |
| `incident.started` | 28 |
| `insolvency.warning` | 7 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 66 |
| `month.end` | 2 |
| `outage.heard` | 39 |
| `payment.deferred` | 43 |
| `payment.made` | 156 |
| `payroll.held` | 1 |
| `payroll.paid` | 18 |
| `promise.made` | 10 |
| `ticket.answered` | 158 |
| `ticket.closed` | 156 |
| `ticket.escalated` | 21 |
| `ticket.opened` | 142 |
| `ticket.reopened` | 7 |
| `ticket.triaged` | 151 |

### Insolvency warnings

| when | firm | cash | weekly wages | overdue to them | cause |
|---|---|---:|---:|---:|---|
| d18 Fri 10:00 | tallybird | $23,715 | $14,600 | $0 | thin_reserves |
| d25 Fri 10:00 | tallybird | $7,795 | $14,600 | $0 | thin_reserves |
| d28 Mon 09:00 | tallybird | $7,795 | $14,600 | $0 | spending_exceeds_income |
| d29 Tue 09:00 | tallybird | $7,795 | $14,600 | $0 | spending_exceeds_income |
| d30 Wed 09:00 | tallybird | $7,795 | $14,600 | $0 | spending_exceeds_income |
| d31 Thu 09:00 | tallybird | $7,795 | $14,600 | $0 | spending_exceeds_income |
| d32 Fri 09:00 | tallybird | $7,615 | $14,600 | $0 | spending_exceeds_income |
