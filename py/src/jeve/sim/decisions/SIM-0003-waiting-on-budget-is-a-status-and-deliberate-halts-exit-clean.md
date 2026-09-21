---

id: SIM-0003
title: waiting on budget is a status, and deliberate halts exit clean
status: accepted
date: 2026-09-21
deciders: ["devin"]
scope: ["py/src/jeve/sim/daemon.py", "py/migrations/0007_waiting_on_budget.sql", "infra/docker/sim-entrypoint.sh", "py/tests/test_daemon.py"]
tags: ["daemon", "robustness", "cost", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["SIM-0002", "LLM-0007", "OPS-0001"]
confirmation: "cd py && uv run pytest tests/test_daemon.py"

---

# SIM-0003 — waiting on budget is a status, and deliberate halts exit clean

## Context and Problem Statement

SIM-0002 sorted failures into weather (wait, retry the tick) and halts (exit
with a status). Deployment added a third thing: OpenRouter answering 402. It
is not weather — a two-minute retry cannot refill credits — and it is not a
halt either, because the cap resets on a billing window and a daemon that
exits needs an operator for something that heals itself. Separately, a
container that restarts every non-zero exit turns deliberate halts (4–7) into
a crash loop that spends on each restart.

## Considered Options

- **Treat 402 as weather.** The default backoff retries every ≤2 min forever,
  indistinguishable from an outage in `last_error` and pointless for hours.
- **Treat 402 as a halt.** Exit 4 discards a recoverable state and pages a
  human for a billing window.
- **Its own status, a long retry.** Taken.

## Decision Outcome

A 402 raises `ProviderBudgetError`; the daemon rolls the tick back, writes
`waiting_on_budget` to `sim_meta`, beats from the sleep loop, and retries the
same tick on a minutes-scale interval (`JEVE_BUDGET_WAIT_S`). In the
container, `sim-entrypoint.sh` maps exits 4–7 to 0, so `on-failure` restarts
crashes and leaves deliberate halts down; the reason stays in `sim_meta`,
which is where an operator looks anyway.

### Consequences

- Good: the world survives a billing window unattended; `on-failure` is the
  only restart policy needed and it is never wrong.
- Bad: a budget-paused world looks stopped to anything not reading
  `sim_meta` — that column exists precisely for this.
- Reverse it if: 402s ever mean "gone for good" rather than "try later".
