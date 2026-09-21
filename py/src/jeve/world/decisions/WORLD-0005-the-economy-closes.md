---
id: WORLD-0005
title: The economy closes - tickets end, months recur, bills get answered, wages come back
status: accepted
date: 2026-09-20
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/world/**", "py/src/jeve/decide/questions.py", "py/src/jeve/decide/policy.py", "py/migrations/**"]
tags: ["economy", "flows", "soak", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0001", "WORLD-0004", "CORE-0009", "DECIDE-0002"]
confirmation: "cd py && uv run pytest tests/test_world.py tests/test_flows.py tests/test_soak.py"
---

# WORLD-0005 — The economy closes: tickets end, months recur, bills get answered, wages come back

## Context and Problem Statement

Nothing ran the world past eight days until the audit did
(`docs/audit/2026-09-21/README.md` B1, B6, B8). Over thirty it winds down.
Tickets are answered and never closed, so everyone who ever filed one is
"already open" for ever and support receives three tickets in the last 26 days.
Month-end fires once. Clients are asked about one bill in eight, a quarter of
the time, so $104k of receivables is never collected and 251 of 400
counterparties never act at all. Wages leave the firms and arrive nowhere.
Tallybird's cash falls from 48k to 3.5k. An outage that delays billing by a day
leaves every firm's cash bit-identical, so the behaviours the project exists to
show cannot occur.

The owner's rule: decline from *mechanics* is a bug; decline from *behaviour* is
a finding. Fix the plumbing; do not tune outcomes.

## Considered Options

- **Tune rates until the firms survive.** Rejected by the rule above.
- **Close each loop with the smallest mechanism that makes it a loop**, and
  let the soak report whatever then happens. Taken.

## Decision Outcome

- **Tickets end.** An answered ticket is confirmed by its reporter (a decision)
  once the module is back, or closes by rule after two days. The same person
  hitting the same module within three days reopens it rather than filing anew.
- **Months recur.** `month.end`, `close.run`, payroll and catering reschedule
  themselves; scheduled work is a registry of handlers, each marked
  `office_hours_only` or not, replacing a nine-branch `if`.
- **Every bill is answered once a day.** From two days before it is due, each
  unpaid invoice gets one `payment.timing` question per sim-day, at an hour that
  belongs to the payer (CORE-0009), sampled once — not a per-tick hazard. The
  per-tick `LIMIT` windows go, and with them 1,591 `payment.deferred` events
  that recorded a die being rolled. A bill seven days late is chased by its
  issuer (`chase.invoice`, where `vocality` finally reaches a question). Clients
  in the four prompter quintiles pay by standing instruction on the due date: a
  gate, not a question.
- **Wages come back.** Staff are paid into a household account and spend from it
  at the cafe. Households are accounts without an org, funded by an opening
  balance against `external`; payroll is four legs.
- **The books open mid-story.** The seed includes last month's invoices falling
  due in the first week, so collection is visible inside a ten-day run. Initial
  conditions, not outcomes.
- **Gates are written once** (`decide/gates.py`) and read by both policies:
  not due, cannot afford, already open.
- **`make soak`** runs 35 days on rules and asserts invariants, not outcomes:
  the ledger balances; tickets opened in week five; a second month-end and its
  close; no receivable older than sixty days unanswered; every firm that trends
  to zero has an `insolvency.warning` that names why; every counterparty segment
  acts. It writes `ops/soak.md`. If behaviour sinks a firm, that is reported.

### Consequences

- Good: money moves in a circle, so an outage that delays billing moves cash.
- Good: the 35-day horizon is tested, on every `make soak`.
- Bad: payer behaviour changes shape (daily sampled, not per-tick hazard); the
  rules twin changes with it and old economics numbers stop being comparable.
- Reverse it if: the soak shows a loop that closes only because of a constant
  chosen to make it close. That is tuning, and it should be deleted.
