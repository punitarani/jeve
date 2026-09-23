---
id: "OPS-0004"
title: "A confirmation never re-runs the suite"
status: "accepted"
date: 2026-09-23
deciders: ["claude"]
scope: ["scripts/run-confirmations.py", "scripts/test_run_confirmations.py"]
tags: ["ci", "cost", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0002", "WEB-0006"]
confirmation: "cd scripts && uv run --directory ../py python -m pytest test_run_confirmations.py"
---
# OPS-0004 — A confirmation never re-runs the suite

## Context and Problem Statement

OPS-0002 runs the suite once per CI run and then runs each record's
confirmation, collapsing a confirmation that is nothing but `cd py && uv run
pytest <paths>` to a collection so the suite is not run twice. One record's
confirmation does not have that shape: WEB-0006's is `make check && cd
apps/web && pnpm exec next build && test -d out`, and `make check` runs the
whole suite again, single-process, without xdist.

At four firms that cost about ten minutes and nobody noticed. At twelve firms
and 225 staff the suite is the long pole, and running it twice took the
`python` job past its budget: GitHub *cancels* a job at `timeout-minutes`
rather than failing it, so three heads in a row reported a cancelled job with
no failing test in the log. Raising the budget to 35, then to 60, only moved
where the cancellation landed.

## Considered Options

- **Rewrite the command in the runner** — the runner already rewrites plain
  pytest confirmations in collect mode; a `make check` prefix is the same
  problem one shape further out, and the rule lands in one place for every
  record written from here on.
- **Edit WEB-0006's confirmation** — one line, but records are immutable, and
  the next record to reach for `make check` reintroduces it.
- **Raise the timeout again** — pays the cost twice for ever and hides it.

## Decision Outcome

In collect mode the runner strips a leading `make check &&` from a
confirmation, because the suite that command would run is the one CI has
already run; a confirmation that is nothing but `make check` becomes a no-op.

The record it belongs to is untouched: what WEB-0006 asks for — the component
layer builds and exports — still runs, and the part of its command that was a
duplicate of OPS-0002's own step does not. In `--pytest run` mode, which is
what a developer gets locally, nothing is stripped and `make check` means what
it says.

### Consequences

- Good: the `python` job runs the suite once. The budget can be set from the
  suite's real cost instead of twice it.
- Bad: a confirmation that opens with `make check` no longer proves in CI that
  `make check` passes — which is what the job's own step is for.
- What would reverse it: a confirmation whose `make check` is not a duplicate,
  because the job stopped running the suite itself.
