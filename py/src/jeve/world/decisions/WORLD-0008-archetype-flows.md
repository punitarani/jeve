---
id: WORLD-0008
title: Archetype flows — rent, supplies and stock, credit lines, and a second vendor
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/world/flows.py", "py/migrations/0011_archetypes.sql", "py/tests/test_flows.py"]
tags: ["flows", "ledger", "economy", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0004", "WORLD-0005", "CORE-0012", "CORE-0009", "DECIDE-0003"]
confirmation: "cd py && uv run pytest tests/test_flows.py"
---

# WORLD-0008 — Archetype flows — rent, supplies and stock, credit lines, and a second vendor

## Context and Problem Statement

Twelve firms on the roster and only the flows written for four of them: the
landlord had no rent to collect, the supplier nothing to deliver, the bank
nothing to lend, and a shop sold from a shelf that never emptied. In the
first thirty-five-day soak the landlord and the supplier drifted down a
thousand dollars a week with nothing coming in, and a firm that ran out of
money fell off a cliff: `payroll.held`, a warning, nothing anyone could do.
The archetypes were data with no rules behind them.

## Considered Options

- **Give the landlord, the supplier and the bank outside income and leave it
  there.** Solvent, and meaningless: three firms whose only relationship to
  the street is a weekly deposit. Loses.
- **Ask the model to run each flow end to end** — how much rent, how big an
  order, whether to lend. Amounts and eligibility are ledger facts; asking
  for them invites numbers. Loses (WORLD-0004 said the same).
- **Four flows in which the model decides a judgement and the rules move the
  money.** Taken.

## Decision Outcome

Rent is a fact, supplies are a judgement, credit is a judgement on each side
and a rule to repay, and every one of them runs on the ledger through the
same `bill`, `post` and daily `payment.timing` as before; a sale takes a
unit of stock, and a second vendor's outage reaches its own customers' tills.

- **Rent.** On the first working day of the month the landlord bills every
  tenant its `rent_cents` on seven-day terms, answered by the daily payment
  question like any bill; once a month somebody from the landlord comes
  round, on a day drawn from `(landlord, tenant, month)` (CORE-0009).
- **Supplies and stock.** A retailer with a supplier sells from
  `orgs.stock_units`; a bare shelf is a gate (`no_stock`), never a question.
  Its buyer is asked `supply.order` on Mondays and Thursdays — none, small
  (four days of ordinary demand) or large (nine) — told the stock level, the
  runway, and whether the supplier has just put its prices up. Delivery is
  next morning on foot (a driver then standing in the shop), stock goes up,
  and a net-fifteen `supplies` invoice follows at forty percent of the
  average basket per unit. `supply.reprice` in week two is the story's
  second shock: on rules a buyer told of it stops ordering large.
- **Credit.** Once a day at their own hour, when runway is under fourteen
  days and no line is open, a tenant firm's bill-payer is asked
  `credit.draw` (`risk_appetite` finally reaches a question). The bank's
  lending officer answers `credit.approve` next tick — the bank cannot lend
  what it does not have, a gate — told the applicant's runway, overdue
  bills, held payrolls and existing debt. A line is four weeks of payroll at
  nine percent, four legs on the ledger, interest monthly, cleared by rule
  the day the firm holds four weeks of wages beyond the balance.
- **The second vendor.** Data since CORE-0012; the tests and the soak check
  that Quill's register failing slows the gym's till and not the cafe's.

### Consequences

- Good: every archetype on the roster now has a flow that moves money for a
  reason, and the landlord and the supplier are paid by the street rather
  than by a deposit.
- Good: a cascade has a second shock (a price rise) and a second vendor, so
  the counterfactual arms have more than one outage to differ on.
- Bad: three more question sets, each with a rules twin to keep honest, and
  the bank's rule of thumb (no second line, decline a firm holding payroll
  with four bills overdue) is a guess.
- Bad: stock is one count of units for everything a shop sells.
- Reverse it if: the soak shows lines of credit propping up firms that
  should have failed — a loan never repaid and never warned about — or a
  retailer's stock dynamics dominate its till more than the outage does.
