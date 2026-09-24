---
id: "WORLD-0014"
title: "Calibrate to cited data, and make a monthly base rate a hazard, not a question"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/engine.py", "py/src/jeve/world/economy.py", "py/src/jeve/world/customers.py", "py/src/jeve/decide/policy.py", "py/src/jeve/evals/priors.py", "py/tests/test_loops.py"]
tags: ["calibration", "economy", "hazards", "typed-decisions", "evals", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0005", "WORLD-0010", "WORLD-0011", "MEM-0003", "WORLD-0013", "EVAL-0001", "DECIDE-0002"]
confirmation: "cd py && uv run pytest tests/test_loops.py tests/test_field_report.py tests/test_evals.py"
---

# WORLD-0014 — Calibrate to cited data, and make a monthly base rate a hazard, not a question

## Context and Problem Statement

The eval harness (EVAL-0001) found the biggest plausibility gaps in the
rules, not the decisions. Four clients in five paid by standing instruction,
so bills were about 0.5 days late against 7.8 in the US (Xero). The cafe
peaked at noon, not 8–10am (Square). Nobody quit a healthy firm, and every
client could always pay.

Filling those gaps meant new monthly decisions: whether staff stay, and whether
every subscriber renews. The first 60-day trial showed what a model does with a
month's base rate. Jev put renewal at 0.56 for a customer who fully trusted
the vendor, and resignation at about 0.10 for a contented, paid employee. The
result was 41% of subscribers and 8.7% of staff lost a month (three seeds),
against bands of 0.5–6.1% and 0–3.5%. Jev reads the question literally and has
no way to know how rare "this month" makes it.

## Considered Options

- **Calibrate each rule to a cited source. Ask a model only when something
  in the situation pushes. Give everyone else a hazard at the observed base
  rate, keyed by subject and month.** Taken.
- **Ask everyone, reworded until Jev's answers come out rare.** Loses: the
  wording would set the rate, not the situation.
- **Leave turnover and liquidity out.** Loses: that is the gap found.

## Decision Outcome

Rates are set from cited data. A month's base rate for people with nothing
pushing them is a rule hazard. Jev is asked only when something in the
situation pushes.

- **Paying.** Half of clients pay by standing instruction (`AUTOPAY_ABOVE =
  0.5`; Atradius US 2025: 52% of B2B value paid on time). A client's cash
  buffer is drawn from the JPMorgan Chase Institute distribution (median 27
  days, P25 13, P75 62: lognormal, σ 1.16), keyed by client and month. Under 5
  days, a bill cannot be paid.
- **The cafe.** Arrivals per hour peak at 8am (Square: busiest 8–10am).
- **Quitting.** Staff with something pushing them are asked `career.review`:
  wages late, a colleague they have fallen out with, a swamped desk, a firm in
  trouble, a bad month. The rest face their industry's quit rate (BLS JOLTS,
  seasonally adjusted, March–July 2026): 4.0% a month at the cafe, 2.0% at the
  others. Their reasons are drawn from Pew's 2022 mix.
- **Renewing.** Only customers at risk are asked, as MEM-0003 has it. The
  rest lapse at 1% a month (SaaS Capital 2025: ~90% of revenue kept a year on
  small contracts).
- **Disputes.** "Larger than expected" means half as much again as the
  payer's last bill from that firm, or for a first bill, the firm's median.
  It had been a fixed $2,000, which two-thirds of bills crossed, and Jev
  queried 52–67% of those.
- **Friction.** A payment deferred past its date counts as friction in the
  soak, as a late rent does.

This extends design/005's rule. A low-stakes propensity whose base rate is
monthly and small goes to the rules, not to a model. The model gets the cases
where the situation, not the calendar, carries the decision.

### Consequences

- Good: on the first trial's Jev worlds (3 seeds × 60 days), all three
  seeds were in band for late share (0.354), days late (5.7) and the reason
  mix (cash flow 0.35). The cafe peaked at 8 on every seed. The final trial's
  numbers are in `ops/evals.md` and `docs/ops/metrics.md`.
- Bad: two decisions most people used to face (renew, stay) are now faced
  only by the few with a reason. The content majority's choice is a coin with
  a cited weight, not a judgement.
- Bad: the sources are US surveys of far larger firms: plausibility
  envelopes, the lowest rung of validation.
- Reverse if: a model answers a monthly base-rate question within its band
  without wording tuned to the band. Then ask everyone again.
