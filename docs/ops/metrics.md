# Metrics and evals: the catalogue

Every number jeve measures about its own realism, what it means, where it comes
from, and what the 60-day trial said about it. The definitions live in code;
this page is the map.

| Instrument | Where | When it runs |
| --- | --- | --- |
| Eval harness: one world measured after its horizon | `py/src/jeve/evals/metrics.py`, bands in `priors.py` | `make evals`, `python scripts/evals.py measure/report` |
| Field-report detectors: the live warnings | `py/src/jeve/api/detectors.py` (API-0004) | `GET /report`, and in the harness as `detector_*` |
| Soak invariants | `py/src/jeve/sim/soak.py` | `make soak`, and every harness world at its horizon |
| Believability judge | `py/src/jeve/evals/judge.py` (EVAL-0001, EVAL-0003) | `scripts/evals.py judge`, `judge-validate` |
| Persona judge: one moment, two casts | `py/src/jeve/evals/casts.py` (EVAL-0004) | `judge-validate --casts`, `scripts/prompt_lab.py casts` |
| Persona in routed conversations | `scripts/persona_gradients.py` (DECIDE-0008) | by hand, free |
| The PR's bar, from committed JSON | `scripts/bar_check.py`, `scripts/band_power.py` | by hand, free |
| Probes: one question, controlled states | `scripts/persona_probe.py`, `scripts/situation_probe.py` | by hand, cents |

Every world is measured into `ops/evals/runs/<arm>-<seed>.json`, and
`ops/evals.md` is rendered from those files. A figure a world cannot answer is
absent (`None`), never zero.

## The 60-day trial, on the final code

Three trial seeds (20261201–03) and three confirmation seeds (20261301–03)
nobody had run. Each cell is mean ± sd over seeds, and the count is the seeds in
band. The rules twin ran at 84a759a and Jev alone at 42dcce7. The production
world (Jev, with conversations routed to GLM and the person from Jev,
DECIDE-0008) ran at 2f4b620. Its worlds halted when the OpenRouter account ran
out of credits, and `evals.py run --resume` carried them on. The world code
did not change between those commits. The whole table, contrasts included, is
`ops/evals.md`. The bar is checked by `scripts/bar_check.py` into
`ops/evals/bar.json`.

| measure | band | rules, trial | rules, confirmation | Jev, trial | Jev, confirmation | production, trial | production, confirmation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `invoice_late_share` | 0.3–0.6 | 0.444 ± 0.038 (3/3) | 0.485 ± 0.025 (3/3) | 0.364 ± 0.043 (3/3) | 0.427 ± 0.012 (3/3) | 0.357 ± 0.039 (3/3) | 0.432 ± 0.021 (3/3) |
| `days_late_mean` | 4.5–20 | 5.70 ± 0.58 (3/3) | 5.88 ± 0.27 (3/3) | 6.37 ± 0.92 (3/3) | 6.42 ± 0.33 (3/3) | 6.61 ± 0.50 (3/3) | 6.57 ± 0.72 (3/3) |
| `late_reason_cash_flow` | 0.2–0.5 | 0.346 ± 0.059 (3/3) | 0.341 ± 0.058 (3/3) | 0.247 ± 0.041 (3/3) | 0.234 ± 0.057 (2/3) | 0.253 ± 0.029 (3/3) | 0.234 ± 0.059 (2/3) |
| `cafe_peak_hour` | 8–10 | 8 (3/3) | 8 (3/3) | 8 (3/3) | 8 (3/3) | 8 (3/3) | 8 (3/3) |
| `ticket_close_hours_median` | 0.5–72 | 31.2 ± 13.7 (3/3) | 23.3 ± 0.6 (3/3) | 23.7 ± 1.8 (3/3) | 24.1 ± 0.2 (3/3) | 24.8 ± 2.3 (3/3) | 23.7 ± 0.4 (3/3) |
| `subscription_churn_monthly` | 0.005–0.061 | 0.025 ± 0.007 (3/3) | 0.024 ± 0.010 (3/3) | 0.027 ± 0.003 (3/3) | 0.021 ± 0.010 (3/3) | 0.025 ± 0.005 (3/3) | 0.017 ± 0.007 (3/3) |
| `staff_turnover_monthly` | 0–0.035 | 0.035 ± 0.024 (2/3) | 0.042 ± 0.021 (1/3) | 0.035 ± 0.024 (2/3) | 0.042 ± 0.021 (1/3) | 0.042 ± 0.021 (1/3) | 0.042 ± 0.021 (1/3) |

No soak invariant failed on any of these eighteen worlds.

Two misses are worth reading closely:

- **Turnover** is a count of one or two departures among 24 staff. A
  perfectly calibrated world passes the band on one seed with probability
  0.77, and on six seeds with probability 0.20 (`scripts/band_power.py`,
  `ops/evals/band-power.json`). The draw is keyed by person and month, so the
  arms miss on the same seeds. Production also lost a pushed senior
  accountant on 20261202.
- **Cash flow** as the reason a bill is late falls below the band on
  20261301, for Jev alone (0.168) and for production (0.173). Payments are
  Jev's in both. Jev gives cash flow for tight-cash payers about half the
  time. For payers whose cash is only thin it almost never does (0.036).
  `prompt_lab.py cash` found wording that moves it (+0.58 on held-out
  states). That wording needs a world A/B of its own.

## Plausibility: against a cited band

Each band was set from its source before the world was measured against it.
PASS/FAIL/ABSENT per seed; ABSENT is never counted as a pass.

| Measure | Definition | Band | Source |
| --- | --- | --- | --- |
| `invoice_late_share` | Of bills due inside the run: paid a day or more after the due date, or still unpaid a day past it | 0.30–0.60 | Atradius Payment Practices Barometer, US 2025: 43% of B2B value overdue, 52% on time |
| `days_late_mean` | Mean whole days late, among bills paid late | 4.5–20 | Xero Small Business Insights, US, Dec quarter 2025: 7.8 days (4.5–9.7 across five countries); Atradius US: ~20 days to collect overdue |
| `late_reason_cash_flow` | Share of late bills whose payer's last reason was cash (including the no-cash gate) | 0.20–0.50 | Atradius US 2025 top reasons: liquidity 45% of respondents, 35% of mentions |
| `cafe_peak_hour` | Hour with the most cafe sales | 8–10 | Square POS data: busiest 8–10am (US) |
| `ticket_close_hours_median` | Median calendar hours, ticket opened to closed | 0.5–72 | Freshworks Customer Service Benchmark 2024-25 |
| `subscription_churn_monthly` | Subscriptions cancelled over subscriptions, per 30 days (ABSENT under 28 days) | 0.005–0.061 | ChartMogul 2022 (2.2–6.1% logo churn by ARPA); SaaS Capital 2025 (~0.9% a month) |
| `staff_turnover_monthly` | Staff who left over staff, per 30 days (ABSENT under 28 days) | 0–0.035 | BLS JOLTS quits, 2026: 1.8–2.2% professional services, 3.5–4.2% food service |

## Plausibility: reported, no primary source for a band

| Measure | Definition |
| --- | --- |
| `ticket_escalation_share` | Outage escalations (in person or relayed) per ticket opened |
| `cafe_morning_share`, `cafe_lunch_share` | Share of sales before 11, and 11–14 |
| `cafe_walkout_share` | Walkouts over walkouts plus sales |
| `dispute_share` | Services invoices disputed. An AR vendor's "healthy" target is under 5%; that is advice, not data |
| `late_reason_{routine,approval,query,forgot,other_bills}` | The rest of the reason mix (WORLD-0013) |
| `days_to_collect_mean` | Mean days from issue to payment. Xero US: 27.9–29.3 days, but on mostly net-30 terms, and jeve's mix (7, 14, 30) is shorter |
| `receivables_open_share` | Share of invoiced value unpaid and not written off at the horizon |

## Health: does the economy hold up?

| Measure | Definition |
| --- | --- |
| `insolvency_warnings` | `insolvency.warning` events |
| `firms_failed` | `firm.failed` events (four paydays behind; absorbing) |
| `payroll_held_or_missed` | Paydays held (no timesheets) or missed (no cash) |
| `staff_left`, `subscriptions_cancelled` | Counts over the run |
| `detectors_firing` | Field-report detectors firing in the last week |

## Depth: does who someone is, what they remember and whom they meet change what they do?

| Measure | Definition |
| --- | --- |
| `persona_signal` | Mean gap in an act's rate between a trait's top and bottom tertiles, over five trait→act pairs (the live detector fires when no pair clears z 2) |
| `identifiability_ratio` | Mean distance between two people's `agent.tick` profiles over the mean distance between one person's two halves (Jensen–Shannon). Above 1: people are told apart beyond noise. Grows with horizon, so compare like with like |
| `persona_retest_jsd` | The noise floor: one person's two halves |
| `action_entropy` | Mean normalised entropy of 15 main acts; a collapsed act reads 0 |
| `role_information` | Bits of destination explained by role, over bits of destination |
| `episodes_per_day` | Episodes closed a day |
| `episode_settled_share`, `episode_stalled_share` | How conversations end: resolved, or everyone repeating their last act |
| `episode_rounds_mean`, `episode_moved_share` | Rounds per episode; share that pressed, promised, refused or passed news |
| `knowledge_secondhand_share`, `knowledge_max_hops` | Share of knowledge heard from someone else, and the longest chain |
| `promises_per_week`, `promise_kept_share` | Commitments to pay, and the share kept |
| `trust_spread` | Standard deviation of subscribers' trust in the vendor |
| `negative_events` | Friction events per sim-day |
| `ontology_gaps` | Share of modelled choices putting at least 0.35 on "other" (design/005's line is 5%) |
| `repeat_meeting_share` | Share of encounters between people who had met before |
| `meetings_top10_pair_share`, `distinct_pairs_met` | How concentrated meetings are, and on how many pairs |
| `drift_first_last_week` | Jensen–Shannon distance of the town's `agent.tick` profile, first week against last |

## Signal: what each record says (WORLD-0013)

| Measure | Definition |
| --- | --- |
| `event_payload_fields_mean` | Mean fields in an event's payload |
| `event_caused_share` | Share of events naming at least one cause |
| `causal_depth_mean`, `causal_depth_max` | Depth of the cause graph: an event is one deeper than its deepest cause |
| `decision_facts_share`, `decision_facts_fields_mean` | Share of decisions that kept their inputs, and how many |
| `late_bill_reason_share` | Share of late bills carrying a typed reason |
| `late_bill_reminded_share` | Share of late bills raised in person |
| `late_bill_chases_mean` | Chases per late bill |

## Cost and integrity

| Measure | Definition |
| --- | --- |
| `cost_per_day_usd` | Every distinct call the world's decisions rest on, priced once as billed, per sim-day (cold cache) |
| `decisions_per_day`, `model_share`, `llm_share` | Decisions a day; share made by a model; share by a general-purpose LLM |
| `money_velocity` | Share of the town's cash that changes hands in a week |
| `invariants_failed` | Soak invariants failing at the horizon (below) |
| digest | Hash of the event log: the same digest is the same world |

## Soak invariants

Checked by `make soak` over 35 days, and on every harness world at its horizon:

- the ledger balances
- tickets end, and support is still hearing from people
- months recur
- every overdue bill is being answered
- wages come back as demand
- no cash account is ever overdrawn
- an insolvency warning is answered by the head of the firm
- a firm running out of money was seen running out, with a cause
- the economy reaches more than one month's clients
- every week has friction in it
- an escalation handed on is decided within the hour
- every loop on a calendar decides something
- the outage moves money without re-rolling it

## The field report's detectors (API-0004)

Eight readings over the last week, each with the line past which it fires:
idle staff with a backlog (30%), action entropy, role information (0.05),
negative events, money velocity (0.05), persona signal (z 2), ontology gaps
(5%), and tier-1 second opinions that only ever agree.

## Believability: the judge

Two judges from different families compare episodes of the same shape (stake,
rounds, people: EVAL-0003) from two arms, both orders. The episodes are rendered from typed records by one template, and
any episode a judge's own family answered is excluded. GPT-5.6 Luna was
validated on planted defects before use: 0.98 on 40 pairs, 0.50 on identical
pairs, and 50/50 unchanged on retest. Claude Haiku 4.5 is the second judge.

Both judges prefer a shorter account. Against an episode with one
unremarkable exchange added, Luna chose the shorter copy 0.88 of the time and
Haiku 0.93, which is why arms are compared at equal length.

On the final trial, production against the world before this PR, 40 pairs a
seed (`ops/evals/judge/before-vs-jev-llm-rounds-*.json`), the share of
verdicts preferring production, with its Wilson interval:

| round | Luna | Haiku |
| --- | --- | --- |
| trial (20261201–03) | 0.535 [0.45, 0.62] | 0.446 [0.36, 0.54] |
| confirmation (20261301–03) | 0.479 [0.39, 0.57] | 0.458 [0.37, 0.55] |

Neither judge sees a difference either way. The before world already routed
conversations to GLM. What changed since then is mostly in the economy and
the records, which an episode does not show.

## Believability: the persona judge

Each side shows one real moment twice, with the person deciding described as
outspoken and sociable, then as quiet and reserved, and what that person did
in each (EVAL-0004). The judge must catch planted *flattened* and *swapped*
casts: Luna caught 0.975 and Sonnet 5 0.95. Haiku caught 0.61 and is not used.
