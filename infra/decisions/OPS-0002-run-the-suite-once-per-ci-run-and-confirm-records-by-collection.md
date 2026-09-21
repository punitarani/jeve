---

id: OPS-0002
title: Run the suite once per CI run, and confirm records by collection
status: accepted
date: 2026-09-21
deciders: ["claude"]
scope: [".github/workflows/ci.yml", "scripts/run-confirmations.py", "scripts/test_run_confirmations.py", "scripts/ci-needs-python.sh", "py/tests/conftest.py"]
tags: ["ci", "testing", "cost", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0001", "CORE-0001", "SIM-0001"]
confirmation: "python3 scripts/test_run_confirmations.py"

---

# OPS-0002 — Run the suite once per CI run, and confirm records by collection

## Context and Problem Statement

CI ran the Python suite three times over. The `python` job ran it whole
(10m27s), then re-ran `test_api.py` and `test_daemon.py` as the `api` and
`sim` nx targets; the `confirmations` job then ran nineteen more pytest
subsets of the same files, taking seventeen minutes on its own — WORLD-0005
alone re-ran `test_world`, `test_flows` and `test_soak` for 7m08s. Every push
to a branch with an open pull request did all of that twice, because `push`
and `pull_request` both fired on the same commit. A run cost about 32
runner-minutes and held a merge for seventeen.

CORE-0001 is why the confirmations exist: one nobody runs is a comment. That
still holds. What does not follow is that it must be a second execution of
tests the same run has already executed.

## Considered Options

- **Keep executing every confirmation literally.** Honest, and fifteen
  minutes of re-running tests that passed four minutes earlier.
- **Shard the confirmations across jobs.** Hides the wall clock, pays the
  same runner-minutes, adds a matrix to maintain.
- **Run the suite once, in parallel, and confirm records by collection.**
  Taken.

## Decision Outcome

The suite runs once per CI run under `pytest -n auto --dist loadfile`, each
xdist worker on a database of its own, and `scripts/run-confirmations.py`
then runs each record's `confirmation` once — in `--pytest collect` mode a
command that is nothing but `cd py && uv run pytest <paths>` is collected
rather than re-executed.

Collection is the right proof for those. What a pytest confirmation asserts
is that the record still points at tests that exist and are selected; whether
they pass was settled by the suite run minutes earlier in the same job.
Pytest exits non-zero on a missing file, an import error, and a `-k` that
matches nothing, so a record that has rotted still fails. Confirmations that
are not plain pytest — ruff and mypy, the two `tsc` runs, the Next build, the
generator check, the fly config parse — run verbatim, because each verifies
something the suite does not.

A database per worker is not a tuning knob. Every heavy module seeds,
truncates or write-locks the one database behind `JEVE_DATABASE_URL`; the
daemon pins itself singleton with a session advisory lock, which is scoped per
database (SIM-0001); `test_db` drops the schema outright. Workers sharing one
database would wipe each other mid-run. The hook writes `os.environ` rather
than monkeypatching, because the daemon subprocesses inherit it.

### Consequences

- Good: one run per change, and the suite parallel within it. On four cores
  it goes from 5m16s to 2m10s; CI's serial run of the same suite took 10m27s.
  The run should fall from ~17 minutes and ~32 runner-minutes to about 6
  and 9.
- Bad: a confirmation's subset is no longer proven to pass *in isolation*,
  only to collect, and the whole suite to pass. A test that works only
  because an earlier module left state behind would not be caught here.
- Bad: `pytest -n` locally leaves `jeve_gw0..N` on the Compose Postgres.
  Harmless; worldcache stamps persist per database.
- Reverse it if: a confirmation subset ever fails in isolation while the full
  run passes. That is the failure this trades away, and it is a real one.
