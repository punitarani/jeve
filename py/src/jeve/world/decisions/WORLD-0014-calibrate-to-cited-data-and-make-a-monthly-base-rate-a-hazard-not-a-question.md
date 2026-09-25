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
rules: bills about 0.5 days late against 7.8 (Xero), a cafe peaking at noon
not 8–10am (Square), nobody quitting a healthy firm, every client able to pay.

Filling those gaps meant new monthly decisions: whether staff stay, and whether
every subscriber renews. The first 60-day trial showed what a model does with a
month's base rate. Jev put renewal at 0.56 for a customer who fully trusted
the vendor, and resignation at about 0.10 for a contented, paid employee. The
result was 41% of subscribers and 8.7% of staff lost a month (three seeds),
against bands of 0.5–6.1% and 0–3.5%. Jev reads the question literally and has
no way to know how rare "this month" makes it.

## Considered Options

- **Calibrate each rule to a cited source. Everyone faces the observed
  base rate. Only people something pushes are asked, and Jev judges how much
  likelier than an ordinary month they are, not the chance outright.** Taken.
- **Ask everyone, reworded until Jev's answers come out rare.** Loses: the
  wording would set the rate, not the situation.
- **Leave turnover and liquidity out.** Loses: that is the gap found.

## Decision Outcome

Rates are set from cited data. A month's base rate is a rule hazard, keyed
by subject and month. Jev judges only how the situation moves it, for the
people something pushes.

- **Paying.** Half of clients pay by standing instruction (`AUTOPAY_ABOVE =
  0.5`; Atradius US 2025: 52% of B2B value paid on time). A client's cash
  buffer is drawn from the JPMorgan Chase Institute distribution (median 27
  days, P25 13, P75 62: lognormal, σ 1.16), keyed by client and month. Under 5
  days, a bill cannot be paid.
- **The cafe.** Arrivals per hour peak at 8am (Square: busiest 8–10am).
- **Quitting.** Everyone faces their industry's quit rate (BLS JOLTS,
  seasonally adjusted, March–July 2026): 4.0% a month at the cafe, 2.0%
  elsewhere. Staff something pushes (wages late, a colleague fallen out with,
  a swamped desk, a firm in trouble, a bad month) are asked `career.review`,
  which scores their risk against an ordinary month on four levels (×0.5, ×1,
  ×2, ×4). The expected multiplier scales the rate, drawn with the same key a
  content person's month uses. Reasons come from Pew's 2022 mix.
- **Renewing.** Only customers at risk are asked, as MEM-0003 has it, and in
  the same relative terms. The ordinary month is 1% (SaaS Capital 2025: ~90%
  of revenue kept a year on small contracts).
- **Relative, not absolute.** Asked the chance outright, even of pushed
  staff and at-risk customers only, Jev gave 11–22% a month for someone whose
  one trouble was a colleague, and ~45% for an at-risk customer. Asked the
  relative question, it ordered risks sensibly: pushed staff 1.0×, made
  content 0.6×; at-risk customers 2.3×, made content 1.5× (30 states each).
- **Disputes.** "Larger than expected" means half as much again as the
  payer's last bill from that firm, or for a first bill, the firm's median.
  It had been a fixed $2,000, which two-thirds of bills crossed, and Jev
  queried 52–67% of those.
- **Friction.** A payment deferred past its date counts as friction in the
  soak, as a late rent does.

This extends design/005's rule. A small monthly base rate goes to the rules.
The model judges direction and size, which it can read off a situation.

### Consequences

- Good: late share, days late and the cafe's peak moved into band
  (`ops/evals.md`, `docs/ops/metrics.md`).
- Bad: the content majority's month is a coin with a cited weight, and the
  multipliers (×0.5–×4) are this record's choice, not a source's. The sources
  are US surveys of far larger firms: plausibility envelopes only.
- Reverse if: a model answers a monthly base-rate question within its band
  without wording tuned to the band.
