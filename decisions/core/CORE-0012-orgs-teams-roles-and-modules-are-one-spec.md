---
id: CORE-0012
title: Orgs, teams, roles and modules are one spec in core; nothing else names a firm
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/core/orgs.py", "py/src/jeve/core/names.py", "py/src/jeve/core/clock.py", "py/tests/test_orgs.py", "py/migrations/0009_district.sql", "tools/contract-gen/generate_zod.py"]
tags: ["world", "data", "roster", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0001", "WORLD-0005", "WORLD-0006", "CORE-0009", "CORE-0011"]
confirmation: "cd py && uv run pytest tests/test_orgs.py"
---

# CORE-0012 — Orgs, teams, roles and modules are one spec in core; nothing else names a firm

## Context and Problem Statement

The street had four firms, and the four were four string literals in about a
hundred and forty places: the engine stamped every incident `org_id="tallybird"`,
the flows knew the cafe's id, the question sets carried their own table of
what to call each firm, the map keyed its layouts by a `Zone` enum, the
database checked `orgs.kind` against a list, and the API compared `org_id` to
`'tallybird'` in SQL to decide whose tickets were whose. `orgs.py` already
carried a `headcount` nobody read. Growing to twelve firms, with teams inside
them and two hundred and twenty-five staff, would have meant thirty more copies
of each fact, or one place that owns them.

## Considered Options

- **Keep the literals and add eight more firms by hand.** Every rule that
  says "the vendor" or "the cafe" is rewritten once per new firm and drifts
  independently. Loses: the first missed site is a firm that never pays rent.
- **A firm table in Postgres as the source of truth.** The roster is then
  visible only with a connection: the map, the question words, the layering
  test and the contract generator all need it at import time, with no
  database. Loses.
- **One frozen spec in `jeve.core.orgs`, read by every layer; a test that
  walks the source for firm ids.** Taken.

## Decision Outcome

`jeve.core.orgs` describes each firm once — what it is called, what it is,
how a question set refers to it, who works there and on which floor, what
hours it keeps, what it subscribes to, what it sells, who keeps its books,
who its landlord and supplier and caterer are — and every other layer reads
the spec; a firm's id may appear in code only in that file, in the seed's
name overrides, and in tests.

The spec is plain data in `core` because every layer needs it and it depends
on nothing. Relationships are derived, never declared twice: `clients_of` is
a scan for `accountant`, `module_owner` a scan of vendors' modules,
`modules_of(org, category)` the one product a firm uses in a category, so a
customer depends on *a* till, whoever sells it. A `RoleSpec` carries a
role's words and wage; a `TeamSpec` is a floor. Staff ids are
`org.team.role.n` and traits are drawn from `("traits", pid)` (CORE-0009),
so adding a person to a team moves nobody else's dice. Hours are per firm,
and the district's day is their union, computed, so `anything_open` needs no
second list of who opens when. `test_orgs.py` asserts the spec is whole and
greps the package for any firm id outside the allowed files.

### Consequences

- Good: the thirteenth firm is a data change — one `OrgSpec`, and the map,
  seed, schedule, flows, question words, API and contracts follow.
- Good: `orgs.kind` and `positions.zone` lose their CHECK constraints; the
  vocabulary has one owner, not two.
- Bad: the spec is 700 lines of tuples, and a wrong wage or hour is a quiet
  error until the soak reports a firm sinking. The integrity test catches
  dangling references, not bad numbers.
- Bad: the migration backfills `modules.org_id` with a literal, because a
  database from before this record has no other way to know.
- Reverse it if: a firm needs behaviour no field can express, and the
  archetype switch in the flows grows a branch per firm. That is the
  literals coming back under another name.
