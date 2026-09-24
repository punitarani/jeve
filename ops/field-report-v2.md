# Field report v2: what changed since golden-20260920

The golden-20260920 field report read 232 sim-days of production under Jev and
found a world whose mechanics held and whose economy and perception did not.
This page measures what the review branch changed, on the only footing
available without a key: two worlds on the rules twin, same seed, 30 sim-days
each, one built by the base commit (`1ed0084`) and one by this branch. The
difference is the code and nothing else.

A rules world is not a Jev world. The rules twin is null model N1, so this
measures which situations arise, which loops exist and where the money goes,
not how a model answers them. The Jev numbers need a live run: re-record the
cassette with `LIVE=1 make e2e`, and let the daemon run in tier-1 shadow
(`JEVE_ESCALATION=shadow`, DECIDE-0005) before reading `make escalation-report`.

Rebuild it:

```sh
uv run python scripts/field_compare.py base=<dsn of a base world> now=<dsn of a world from this branch>
```

## Side by side

| measure | base (1ed0084) | this branch |
|---|---:|---:|
| sim-days | 29 | 29 |
| decisions | 28,114 | 16,858 |
| decision kinds asked | 12 | 27 |
| share of decisions that are agent.tick | 69.5% | 49.1% |
| events | 13,456 | 12,561 |
| event kinds | 30 | 55 |
| friction events per week | 0.28 | 4.19 |
| invoices issued | 272 | 265 |
| invoices paid | 151 | 146 |
| invoices disputed | 0 | 1 |
| invoices written off | 0 | 0 |
| subscriptions cancelled | 0 | 3 |
| incidents | 25 | 10 |
| outage hours | 58 | 15 |
| outages escalated | 76.0% | 60.0% |
| escalations raised in the cafe | 73.7% | 100.0% |
| tickets opened | 123 | 85 |
| encounters | 1,781 | 1,047 |
| episodes | 85 | 90 |
| payroll runs held or missed | 1 | 0 |
| households' spending, as a share of wages | 3.1% | 115.2% |
| tallybird cash at the end | $7,720 | $39,201 |
| halloran cash at the end | $88,386 | $76,966 |
| ledgerline cash at the end | $82,714 | $84,910 |
| thirdrail cash at the end | $33,740 | $21,098 |
| cafe sales | 6,023 | 6,105 |
| cafe walkouts | 683 | 513 |

*Friction* is one party failing, refusing or falling out with another
(`engine.FRICTION`): disputes, write-offs, cancellations, refusals, held or
missed payroll, broken promises, departures. Walkouts, insolvency warnings and
outages are left out.

## Against the golden report's findings

| golden-20260920 found | this branch, on rules |
|---|---|
| Tallybird met payroll 5 weeks in 33 and sat near zero from day 30 | Priced per seat, it ends the month with $39k and misses no payroll. It may still fail: failure is absorbing, and each firm's head reviews prices, costs and debts monthly, and at once when warned (WORLD-0010). |
| Households took in $759k and spent $10.6k (1.4%) | Spending is 115% of wages over the month, as households spend down their opening buffer toward 90% of income. Each employer's staff have their own purse. |
| No dispute, write-off or refusal in a month | Four friction events a week: cancellations, disputes, declined catering, dropped escalations, broken promises. The base world had one in the month. |
| `agent.tick` was 99.3% of calls; the roster made 615 contexts into 20,826 | Asked at decision points, and a room is at most three firms: 49% of decisions instead of 70%, and 40% fewer decisions overall. The cache effect is measured by `make census`. |
| Mood moved only with outages | What is on someone's mind now includes unpaid wages, a short payday, a lost customer, a swamped queue and a colleague leaving (WORLD-0009). |
| The help desk is the coffee line: escalation landed on whoever was in the cafe | Only an engineer, or a relay made in person, escalates. Support and the account manager decide whether to pass it on: 12 relayed, 11 dropped this month. Support's own rule and phone relays prioritise instead (6). Every escalation that did reach an engineer was still raised in the cafe, because the relay keeps where the complaint was first made (WORLD-0012). |
| Conversation moved no information (3,370 of 3,371 knowledge rows first-hand) | 45 facts passed this month; late payroll, insolvency, churn, broken promises and a false rumour now travel (MEM-0003). |
| A subscriber's only response to an outage was whether to file a ticket | Each chooses a workaround: of 186, 138 waited, 31 rang their account manager, 12 used another tool, 5 did it by hand and paid for it at the close. |
| Outages were weather with no memory | 135 trust revisions. Debt is live: 6 deploys shipped, 3 held, and outages fell from 25 to 10 as the base hazard was recalibrated and allocation pays debt down (WORLD-0011). |

## What it would cost Jev

`make census` renders every request the rules world would have sent Jev and
counts the distinct ones: the cold-cache bill. Ten sim-days, same seed, run
with each commit's own question sets.

| | base (1ed0084) | this branch |
|---|---:|---:|
| decisions put to a model | 9,051 | 5,146 |
| distinct requests (the bill) | 2,165 | 1,829 |
| `agent.tick` asked | 6,984 | 3,078 |
| `agent.tick` distinct | 1,891 | 1,455 |
| question sets asked | 12 | 24 |

The bill falls by a sixth while the number of question sets doubles:
`agent.tick` is asked less than half as often and a room is described as
firms, not people. The hit rate falls (76% to 65%) because fewer of the asks
were repeats, not because more calls are paid for.

### Finer trait wording costs almost nothing

The outline asked what quintiles would cost for the two traits that carry most
(sociability, promptness). `make census LEVELS=6`, which strictly refines the
tertiles, adds 5 distinct requests to 1,829 (0.3%). Quintiles came out 38
*fewer*, because five bins are not nested in three and two staff in different
tertiles can share a quintile. The bill is set by situations, not by how finely
a person is described. Whether Jev answers finer wording differently is the
persona probe's question, and needs a key; the wording stays in tertiles until
it is asked.

## Degeneracy detectors, last 7 days of each world

| detector | base | this branch |
|---|---|---|
| support away from the desk with a backlog | no backlog of 8 | no backlog of 8 |
| acts that always come out the same | none of 5 collapsed | none of 5 collapsed |
| what a job says about where people go | 0.70 of the entropy | 0.55 |
| friction per week | 1 (payroll held) | 4 |
| share of cash changing hands in a week | 0.087 | 0.178 |
| persona signal (top against bottom tertile) | 0.11, z 6.7 | 0.09, z 5.5 |

The base world trips *friction* in three of its four weeks; this one in none.
Money turns over twice as fast. Role information falls because offices now
spread across more places at lunch and in the afternoon.

## What this cannot tell

- How Jev answers any of the 27 question sets. The golden cassette is retired
  until `LIVE=1 make e2e` re-records it.
- Whether tier 1 agrees with Jev, and where. That is `make escalation-report`,
  after a shadow run, and `make judge-panel LIVE=1` for a panel of three model
  families on the cached contexts.
- One seed is an anecdote. `make calibrate SEED=` and `make episodes` run more.
