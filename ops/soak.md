# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 12 of 12 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 79 ticket(s) opened in the last 14 days against 23 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 20 monthly close(s) completed for 10 clients |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $1,513,250 and spent $38,839 at the tills |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 57 reached / 41 decided, of 80, ledgerline 55 reached / 33 decided, of 80, thirdrail 200 reached / 200 decided, of 200, brightwater 119 reached / 119 decided, of 120, meridian 17 reached / 14 decided, of 30, pemberton 150 reached / 150 decided, of 150, quill 60 reached / 60 decided, of 60, ironworks 150 reached / 150 decided, of 150 |
| every retailer sold something | yes | thirdrail 7662 sale(s), brightwater 609 sale(s), pemberton 1734 sale(s), ironworks 4095 sale(s) |
| every tenant paid rent | yes | tallybird 1, halloran 1, ledgerline 1, thirdrail 1, brightwater 1, meridian 1, commonwealth 1, pemberton 1, quill 1, ironworks 1, northfield 1 |
| every shop restocked | yes | thirdrail 5 delivery(s), pemberton 6 delivery(s) |
| every line of credit is repaid, serviced, or its borrower was seen going under | yes | 1 line(s) drawn, 0 repaid, 1 open |
| both vendors had an incident and triaged a ticket about it | yes | tallybird 154 triaged, quill 66 triaged |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $420,000 | $425,270 | $420,610 | $429,482 | $434,182 | $438,702 |
| halloran | $240,000 | $309,588 | $344,854 | $304,639 | $265,099 | $359,807 |
| ledgerline | $170,000 | $239,852 | $255,243 | $233,093 | $204,743 | $215,672 |
| keystone | $120,000 | $112,170 | $162,660 | $154,230 | $146,400 | $138,570 |
| thirdrail | $30,000 | $27,773 | $24,463 | $70,179 | $64,822 | $61,480 |
| brightwater | $90,000 | $88,472 | $85,083 | $85,844 | $86,389 | $87,973 |
| meridian | $120,000 | $220,995 | $236,586 | $204,291 | $173,391 | $362,701 |
| commonwealth | $900,000 | $904,550 | $902,920 | $860,490 | $864,620 | $868,570 |
| pemberton | $40,000 | $43,359 | $43,441 | $47,113 | $46,641 | $46,190 |
| quill | $200,000 | $200,310 | $194,610 | $197,268 | $197,148 | $196,848 |
| ironworks | $28,000 | $32,545 | $33,546 | $38,599 | $43,599 | $49,184 |
| northfield | $45,000 | $43,120 | $38,220 | $36,385 | $44,890 | $51,218 |
| households | $180,000 | $474,952 | $769,864 | $1,064,616 | $1,359,386 | $1,654,411 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 80 | 38 | 0 | 0 | $351,738 | -0.2 |
| keystone | 22 | 11 | 0 | 0 | $59,100 | -0.4 |
| ledgerline | 98 | 56 | 0 | 0 | $178,768 | +0.8 |
| meridian | 22 | 12 | 0 | 0 | $318,760 | -0.4 |
| northfield | 11 | 4 | 0 | 0 | $26,818 | -0.8 |
| quill | 135 | 70 | 0 | 0 | $3,278 | +0.5 |
| tallybird | 220 | 120 | 0 | 0 | $5,367 | +0.3 |
| thirdrail | 39 | 29 | 0 | 0 | $2,760 | -0.1 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 43 | 43 | 2 |
| 1 | 44 | 44 | 8 |
| 2 | 49 | 49 | 9 |
| 3 | 36 | 36 | 2 |
| 4 | 36 | 35 | 2 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 52925 | 71.0% |
| `catering.order` | rules | 80 | 0.1% |
| `close.signoff` | rules | 20 | 0.0% |
| `credit.approve` | rules | 1 | 0.0% |
| `credit.decision` | rules | 108 | 0.1% |
| `credit.draw` | rules | 1 | 0.0% |
| `episode.round` | rules | 1781 | 2.4% |
| `file.ticket` | rules | 503 | 0.7% |
| `payment.timing` | rules | 534 | 0.7% |
| `payroll.release` | rules | 60 | 0.1% |
| `retail.purchase` | rules | 16948 | 22.7% |
| `subscription.switch` | rules | 13 | 0.0% |
| `supply.order` | rules | 20 | 0.0% |
| `ticket.answer` | rules | 919 | 1.2% |
| `ticket.confirm` | rules | 388 | 0.5% |
| `ticket.triage` | rules | 220 | 0.3% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 28391 |
| `catering.delivered` | 39 |
| `catering.ordered` | 39 |
| `close.completed` | 20 |
| `credit.applied` | 1 |
| `credit.issued` | 41 |
| `encounter` | 6059 |
| `episode.closed` | 275 |
| `episode.opened` | 275 |
| `episode.round` | 563 |
| `fact.passed` | 165 |
| `incident.ended` | 51 |
| `incident.started` | 51 |
| `income.outside` | 30 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 209 |
| `loan.drawn` | 1 |
| `maintenance.visited` | 14 |
| `month.end` | 2 |
| `outage.heard` | 58 |
| `payment.deferred` | 56 |
| `payment.made` | 334 |
| `payroll.paid` | 60 |
| `promise.broken` | 2 |
| `promise.made` | 7 |
| `retail.sale` | 14100 |
| `retail.walkout` | 2848 |
| `subscription.switched` | 7 |
| `supply.delivered` | 11 |
| `supply.ordered` | 11 |
| `supply.repriced` | 1 |
| `ticket.answered` | 243 |
| `ticket.closed` | 242 |
| `ticket.escalated` | 30 |
| `ticket.opened` | 208 |
| `ticket.reopened` | 23 |
| `ticket.triaged` | 220 |

### Word of the price rise, by day

| day | people who know |
|---:|---:|
| 9 | 2 |
| 11 | 3 |
| 15 | 4 |
| 18 | 5 |
| 23 | 7 |
| 28 | 10 |
| 29 | 12 |
| 30 | 13 |
| 31 | 14 |
| 32 | 16 |

### Subscribers who switched vendor

| from | to | n |
|---|---|---:|
| tallybird | quill | 7 |
