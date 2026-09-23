---
id: "WORLD-0007"
title: "Run episodes in every world, with no switch"
status: "accepted"
date: 2026-09-23
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/world/episodes.py", "py/src/jeve/world/engine.py", "py/src/jeve/sim/daemon.py", "py/src/jeve/sim/soak.py", "py/tests/test_episodes.py"]
tags: ["episodes", "defaults", "encounters", "resolution"]
supersedes: ["WORLD-0006"]
superseded-by: null
relates-to: ["WORLD-0003", "MEM-0002", "DECIDE-0004", "CORE-0004", "SIM-0001"]
confirmation: "cd py && uv run pytest tests/test_episodes.py"
---

# WORLD-0007 — Run episodes in every world, with no switch

## Context and Problem Statement

WORLD-0006 built episodes — a meeting with a stake gets up to three rounds of
typed requests — and shipped them off by default. The one-shot encounter was the
control arm, the docking test had failed (the proxy escalates 0.10 of outage
meetings, episodes 0.72), and `episode.round` asked questions the golden cassette
did not hold. That left the running world without the mechanism, behind a daemon
flag (`--episodes`, `JEVE_EPISODES`), a make variable and a second soak report.
The project owner decided the richer world is the product.

## Considered Options

- **Keep them off behind a flag.** WORLD-0006's evidence position; the shipped
  world never uses the mechanism, and the switch is one more thing to remember.
- **On by default, flag kept as a kill switch.** Two worlds to keep working, and
  the one nobody runs goes stale.
- **On everywhere, no switch.** Taken.

## Decision Outcome

Episodes run in every world the daemon runs, with no flag, environment variable
or make variable. The mechanism is WORLD-0006's, with the outage stake corrected
(below).

The engine keeps an `episodes` argument only because `make episodes` needs a
control arm — the standing `encounters` and `spatial` already have, and the
daemon exposes neither of them. The soak, the fixture and the golden cassette all
describe the one world that ships.

### Consequences

- Good: one world. What the daemon runs, the soak checks and the fixture replays
  are the same, and no switch can drift out of step with the others.
- Good: word of mouth, promises to pay and escalations from real stakes reach the
  economy in the world people watch.
- Good: running them everywhere put them under tests written for the one-shot, and
  `test_space` found the outage stake counting a second Tallybird employee as a
  customer stuck on the outage, so the vendor could press itself. Askers are now
  customers only. WORLD-0006's figures included the bug; five seeds after the fix
  give a mean gap of +0.51 and about a fifth fewer outage minutes.
- Bad: base rates move. Per the docking gap, outages are escalated more often than
  under the one-shot, so `ops/economics.md`, measured before this record,
  describes a different world until it is re-measured.
- Bad: the golden cassette must hold `episode.round` answers, which only a live
  run can record; until then strict replay misses. Recording them is part of
  shipping this.
- Bad: about 2% more decisions, so about 2% more spend at the measured per-call
  cost.
- Bad: the running world predates MEM-0002, so its outages have no facts, and the
  first upgraded tick died on a foreign key. The engine writes them when it starts,
  under the writer lock, not in migration 0009: production migrates while the old
  daemon still writes. `test_episodes.py` replays that upgrade.
- Reverse it if: WORLD-0006's condition holds — the gap survives recalibrating
  the one-shot's wording, or a live run shows no macro effect beyond the A/A
  floor. Then delete the mechanism; do not switch it off.
