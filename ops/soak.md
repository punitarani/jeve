# Soak: 35 sim-days, decided by `rules`

Written by `make soak`. Invariants, not outcomes: a firm may fail here; it may not fail unexplained (WORLD-0005).

**PASS** — 12 of 12 invariants hold.

| invariant | holds | evidence |
|---|---|---|
| the ledger balances | yes | sum of all entries = 0 |
| tickets end, and support is still hearing from people | yes | 62 ticket(s) opened in the last 14 days against 22 incident(s); 0 answered ticket(s) left open more than four days |
| months recur | yes | 2 month-end(s) in 35 days (expected 2); 20 monthly close(s) completed for 10 clients |
| every overdue bill is being answered | yes | 0 overdue bill(s) nobody has been asked about in five days; 0 more than 63 days past due and not written off |
| wages come back as demand | yes | households were paid $1,513,250 and spent $39,047 at the tills |
| a firm running out of money was seen running out, with a cause | yes | none unexplained |
| the economy reaches more than one month's clients | yes | tallybird 100 reached / 100 decided, of 100, halloran 57 reached / 41 decided, of 80, ledgerline 55 reached / 33 decided, of 80, thirdrail 200 reached / 200 decided, of 200, brightwater 119 reached / 119 decided, of 120, meridian 17 reached / 14 decided, of 30, pemberton 150 reached / 150 decided, of 150, quill 60 reached / 60 decided, of 60, ironworks 150 reached / 150 decided, of 150 |
| every retailer sold something | yes | thirdrail 7661 sale(s), brightwater 609 sale(s), pemberton 1759 sale(s), ironworks 4128 sale(s) |
| every tenant paid rent | yes | tallybird 1, halloran 1, ledgerline 1, thirdrail 1, brightwater 1, meridian 1, commonwealth 1, pemberton 1, quill 1, ironworks 1, northfield 1 |
| every shop restocked | yes | thirdrail 5 delivery(s), pemberton 6 delivery(s) |
| every line of credit is repaid, serviced, or its borrower was seen going under | yes | 1 line(s) drawn, 0 repaid, 1 open |
| both vendors had an incident and triaged a ticket about it | yes | tallybird 119 triaged, quill 62 triaged |

## Measures (reported, not asserted)

### Cash, by week

| firm | d0 | d7 | d14 | d21 | d28 | d35 |
|---|---:|---:|---:|---:|---:|---:|
| tallybird | $420,000 | $425,270 | $420,610 | $429,258 | $433,958 | $438,478 |
| halloran | $240,000 | $309,588 | $345,034 | $304,654 | $265,654 | $360,782 |
| ledgerline | $170,000 | $239,852 | $255,243 | $233,093 | $204,563 | $215,672 |
| keystone | $120,000 | $112,170 | $162,840 | $154,410 | $146,760 | $138,690 |
| thirdrail | $30,000 | $27,795 | $24,579 | $70,582 | $63,520 | $61,831 |
| brightwater | $90,000 | $88,472 | $85,083 | $85,889 | $86,614 | $88,378 |
| meridian | $120,000 | $220,995 | $236,586 | $204,336 | $173,076 | $362,386 |
| commonwealth | $900,000 | $904,550 | $902,920 | $860,670 | $865,220 | $869,590 |
| pemberton | $40,000 | $43,359 | $43,441 | $47,221 | $47,804 | $42,864 |
| quill | $200,000 | $200,310 | $194,190 | $196,728 | $197,028 | $197,148 |
| ironworks | $28,000 | $32,404 | $33,390 | $38,264 | $44,005 | $49,552 |
| northfield | $45,000 | $43,120 | $38,220 | $36,430 | $44,935 | $52,903 |
| households | $180,000 | $475,070 | $770,043 | $1,064,723 | $1,359,258 | $1,654,203 |

### Receivables

| issuer | issued | paid | chased | written off | outstanding | paid, mean days after due |
|---|---:|---:|---:|---:|---:|---:|
| halloran | 80 | 38 | 0 | 0 | $351,738 | -0.2 |
| keystone | 22 | 11 | 0 | 0 | $59,100 | -0.2 |
| ledgerline | 98 | 56 | 0 | 0 | $178,768 | +0.7 |
| meridian | 22 | 12 | 0 | 0 | $318,760 | -0.4 |
| northfield | 11 | 4 | 0 | 0 | $25,179 | -0.9 |
| quill | 135 | 70 | 0 | 0 | $3,390 | +0.5 |
| tallybird | 218 | 120 | 0 | 0 | $5,149 | +0.3 |
| thirdrail | 28 | 19 | 0 | 0 | $1,860 | -0.5 |

### Tickets, by week opened

| week | opened | closed | reopened |
|---:|---:|---:|---:|
| 0 | 42 | 42 | 1 |
| 1 | 37 | 37 | 5 |
| 2 | 34 | 34 | 12 |
| 3 | 34 | 34 | 3 |
| 4 | 22 | 20 | 0 |

### Decisions

| question set | decided by | n | share |
|---|---|---:|---:|
| `agent.tick` | rules | 53018 | 73.3% |
| `catering.order` | rules | 80 | 0.1% |
| `close.signoff` | rules | 20 | 0.0% |
| `credit.approve` | rules | 1 | 0.0% |
| `credit.decision` | rules | 107 | 0.1% |
| `credit.draw` | rules | 1 | 0.0% |
| `file.ticket` | rules | 408 | 0.6% |
| `payment.timing` | rules | 502 | 0.7% |
| `payroll.release` | rules | 60 | 0.1% |
| `retail.purchase` | rules | 16916 | 23.4% |
| `subscription.switch` | rules | 21 | 0.0% |
| `supply.order` | rules | 20 | 0.0% |
| `ticket.answer` | rules | 678 | 0.9% |
| `ticket.confirm` | rules | 319 | 0.4% |
| `ticket.triage` | rules | 181 | 0.3% |

### Events

| kind | n |
|---|---:|
| `agent.moved` | 28429 |
| `catering.delivered` | 28 |
| `catering.ordered` | 28 |
| `close.completed` | 20 |
| `credit.applied` | 1 |
| `credit.issued` | 52 |
| `encounter` | 6234 |
| `incident.ended` | 50 |
| `incident.started` | 50 |
| `income.outside` | 30 |
| `invoice.blocked` | 4 |
| `invoice.issued` | 198 |
| `loan.drawn` | 1 |
| `maintenance.visited` | 14 |
| `month.end` | 2 |
| `payment.deferred` | 60 |
| `payment.made` | 321 |
| `payroll.paid` | 60 |
| `retail.sale` | 14157 |
| `retail.walkout` | 2759 |
| `subscription.switched` | 9 |
| `supply.delivered` | 11 |
| `supply.ordered` | 11 |
| `supply.repriced` | 1 |
| `ticket.answered` | 202 |
| `ticket.closed` | 200 |
| `ticket.escalated` | 33 |
| `ticket.opened` | 169 |
| `ticket.reopened` | 21 |
| `ticket.triaged` | 181 |

### Word of the price rise, by day

| day | people who know |
|---:|---:|
| 9 | 3 |
| 15 | 4 |
| 17 | 5 |
| 18 | 6 |
| 21 | 7 |
| 28 | 9 |
| 29 | 11 |
| 30 | 12 |
| 31 | 13 |
| 32 | 14 |

### Subscribers who switched vendor

| from | to | n |
|---|---|---:|
| tallybird | quill | 9 |
