# Soak: 10 sim-days, decided by `jev`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 8 of 8 invariants hold. Distinct model calls behind this run: 1780 ($0.0695, $0.0069 per sim-day).

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 36 ticket(s) opened in the last 14 days against 7 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 1 month-end(s) in 10 days (expected 1); 3 monthly close(s) completed |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $35,400 and spent $636 at the cafe |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 88 decided, of 100, halloran 18 reached / 9 decided, of 100, ledgerline 24 reached / 19 decided, of 100, thirdrail 100 reached / 100 decided, of 100 |
| the outage moves money without re-rolling it | yes | invoice amounts identical across arms and cash different |

## Counterfactual: the same world without the month-end outage

| | outage | no outage |
|---|---:|---:|
| month-end client invoices issued | 15 | 15 |
| issued in both arms | 15 | 15 |
| of those, same amount in both arms | 15 | 15 |
| of those, issued at a different time | 15 | 15 |
| tallybird cash at the end | $34,000.00 | $34,000.00 |
| halloran cash at the end | $114,319.72 | $114,499.72 |
| ledgerline cash at the end | $99,031.68 | $99,031.68 |
| thirdrail cash at the end | $18,070.17 | $17,818.72 |

**Invoice amounts constant across arms:** yes (15 of 15). **Cash differs across arms:** yes.

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d10 |
|---|---:|---:|---:|
| tallybird | $48,000 | $34,000 | $34,000 |
| halloran | $96,000 | $107,959 | $114,320 |
| ledgerline | $41,000 | $83,634 | $99,032 |
| thirdrail | $9,400 | $13,328 | $18,070 |
| households | $20,000 | $55,010 | $54,764 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 18 | 8 | 0 | 0 | $30,087 | +0.0 |
| ledgerline | 29 | 18 | 0 | 0 | $31,403 | +0.3 |
| tallybird | 107 | 4 | 0 | 0 | $5,185 | -5.1 |
| thirdrail | 2 | 2 | 0 | 0 | $0 | -1.4 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 27 | 27 | 1 |
| 1 | 7 | 5 | 0 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | jev | 6984 | 72.8% |
| `cafe.purchase` | jev | 1102 | 11.5% |
| `cafe.purchase` | rules | 1113 | 11.6% |
| `catering.order` | jev | 9 | 0.1% |
| `close.signoff` | jev | 3 | 0.0% |
| `credit.decision` | jev | 12 | 0.1% |
| `file.ticket` | jev | 109 | 1.1% |
| `file.ticket` | rules | 2 | 0.0% |
| `payment.timing` | jev | 62 | 0.6% |
| `payroll.release` | jev | 4 | 0.0% |
| `ticket.answer` | jev | 77 | 0.8% |
| `ticket.confirm` | jev | 50 | 0.5% |
| `ticket.confirm` | rules | 21 | 0.2% |
| `ticket.triage` | jev | 42 | 0.4% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 740 |
| `cafe.sale` | 1832 |
| `cafe.walkout` | 383 |
| `catering.delivered` | 2 |
| `catering.ordered` | 2 |
| `close.completed` | 3 |
| `credit.issued` | 6 |
| `encounter` | 966 |
| `incident.ended` | 7 |
| `incident.started` | 7 |
| `invoice.blocked` | 2 |
| `invoice.issued` | 21 |
| `month.end` | 1 |
| `payment.deferred` | 6 |
| `payment.made` | 30 |
| `payroll.paid` | 4 |
| `ticket.answered` | 44 |
| `ticket.closed` | 43 |
| `ticket.escalated` | 6 |
| `ticket.opened` | 34 |
| `ticket.reopened` | 2 |
| `ticket.triaged` | 42 |
