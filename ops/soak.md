# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 8 of 8 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 112 ticket(s) opened in the last 14 days against 23 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 20 monthly close(s) completed for 10 clients |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $1,513,250 and spent $61,382 at the tills |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 57 reached / 41 decided, of 80, ledgerline 55 reached / 33 decided, of 80, thirdrail 200 reached / 200 decided, of 200, brightwater 119 reached / 119 decided, of 120, meridian 17 reached / 14 decided, of 30, pemberton 150 reached / 150 decided, of 150, quill 60 reached / 60 decided, of 60, ironworks 150 reached / 150 decided, of 150 |
| every retailer sold something | yes | thirdrail 8661 sale(s), brightwater 609 sale(s), pemberton 1759 sale(s), ironworks 5423 sale(s) |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $420,000 | $425,270 | $429,970 | $439,195 | $443,295 | $447,815 |
| halloran | $240,000 | $309,588 | $352,114 | $312,799 | $272,419 | $367,367 |
| ledgerline | $170,000 | $240,752 | $260,743 | $237,663 | $209,703 | $215,720 |
| keystone | $120,000 | $112,170 | $103,740 | $94,755 | $86,505 | $78,855 |
| thirdrail | $30,000 | $28,933 | $30,014 | $30,935 | $32,999 | $33,708 |
| brightwater | $90,000 | $88,472 | $89,883 | $90,599 | $91,324 | $92,908 |
| meridian | $120,000 | $220,095 | $241,906 | $209,476 | $177,976 | $367,106 |
| commonwealth | $900,000 | $904,550 | $908,920 | $913,290 | $917,840 | $922,030 |
| pemberton | $40,000 | $43,359 | $47,041 | $50,714 | $55,265 | $59,348 |
| quill | $200,000 | $200,280 | $200,400 | $202,758 | $203,058 | $203,178 |
| ironworks | $28,000 | $36,178 | $44,840 | $53,124 | $62,068 | $70,524 |
| northfield | $45,000 | $43,120 | $42,020 | $40,230 | $39,130 | $38,030 |
| households | $180,000 | $470,208 | $760,606 | $1,050,729 | $1,340,877 | $1,631,868 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 80 | 38 | 0 | 0 | $351,738 | -0.2 |
| ledgerline | 98 | 55 | 0 | 0 | $183,680 | +0.7 |
| meridian | 22 | 12 | 0 | 0 | $318,760 | -0.4 |
| quill | 135 | 70 | 0 | 0 | $3,390 | +0.5 |
| tallybird | 227 | 120 | 0 | 0 | $5,590 | +0.3 |
| thirdrail | 43 | 33 | 0 | 0 | $2,280 | -0.1 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 45 | 45 | 2 |
| 1 | 44 | 44 | 11 |
| 2 | 39 | 39 | 1 |
| 3 | 52 | 52 | 5 |
| 4 | 52 | 50 | 2 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 205060 | 90.0% |
| `catering.order` | rules | 80 | 0.0% |
| `close.signoff` | rules | 20 | 0.0% |
| `credit.decision` | rules | 110 | 0.0% |
| `file.ticket` | rules | 526 | 0.2% |
| `payment.timing` | rules | 506 | 0.2% |
| `payroll.release` | rules | 60 | 0.0% |
| `retail.purchase` | rules | 19733 | 8.7% |
| `ticket.answer` | rules | 1051 | 0.5% |
| `ticket.confirm` | rules | 417 | 0.2% |
| `ticket.triage` | rules | 244 | 0.1% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 40588 |
| `catering.delivered` | 43 |
| `catering.ordered` | 43 |
| `close.completed` | 20 |
| `credit.issued` | 44 |
| `encounter` | 15328 |
| `incident.ended` | 52 |
| `incident.started` | 52 |
| `income.outside` | 30 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 180 |
| `month.end` | 2 |
| `payment.deferred` | 56 |
| `payment.made` | 322 |
| `payroll.paid` | 60 |
| `retail.sale` | 16452 |
| `retail.walkout` | 3281 |
| `ticket.answered` | 265 |
| `ticket.closed` | 263 |
| `ticket.escalated` | 38 |
| `ticket.opened` | 232 |
| `ticket.reopened` | 21 |
| `ticket.triaged` | 244 |
