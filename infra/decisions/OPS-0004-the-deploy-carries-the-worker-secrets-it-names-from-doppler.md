---
id: "OPS-0004"
title: "The deploy carries the worker secrets it names from Doppler"
status: "accepted"
date: 2026-09-23
deciders: ["claude"]
scope: [".github/workflows/ci.yml", "scripts/stage-worker-secrets.sh", "scripts/verify-tracing.sh", "scripts/test_deploy_secrets.py", "docs/deployment.md"]
tags: ["deployment", "ci", "doppler", "secrets", "observability", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0001", "OPS-0003", "LLM-0008"]
confirmation: "python3 scripts/test_deploy_secrets.py"
---
# OPS-0004 — The deploy carries the worker secrets it names from Doppler

## Context and Problem Statement

Tracing shipped (LLM-0008) and nothing was traced. `BRAINTRUST_API_KEY` and
`BRAINTRUST_PROJECT_ID` were in Doppler `worker/prd`, but `fly secrets list`
did not show them. With no key, `jeve.tracing` is a silent no-op by design, so
nothing complained.

OPS-0001 says secrets "land as Fly secrets", but nothing in the tree made that
happen:

- The only credential CI holds is `DOPPLER_TOKEN`, a service token for
  `infra/ci`. A Doppler service token can read only the one config it was
  created for, so CI cannot see `worker/prd` at all.
- `flyctl deploy` sets no secrets.

Every name in `worker` that reached Fly got there by a hand-run
`fly secrets set`, a path the operator has ruled out: CI/CD or nothing.

## Considered Options

- **Doppler's Fly Config Sync.** Rejected: two dashboards, outside the tree
  and review — and what the docs already implied, unnoticed, was not there.
- **A `DOPPLER_TOKEN` that reads every project.** Rejected: a personal or
  workplace-wide credential where a scoped one does today.
- **Sync all of `worker/prd`.** Rejected: it pushes the database URLs, which
  differ per process group and are right on Fly already, and makes every
  future `worker` name an unreviewed deploy-time change.
- **A second read-only token for `worker/prd`, stored in `infra/ci`, used to
  fetch an allowlist of names.** Taken.

## Decision Outcome

Before `flyctl deploy`, `deploy-backend` reads exactly the names in
`scripts/stage-worker-secrets.sh` from `worker/prd`, using
`DOPPLER_WORKER_TOKEN`, and stages them on the app. The deploy then rolls them
out in its one restart. Today those names are `BRAINTRUST_API_KEY` and
`BRAINTRUST_PROJECT_ID`.

The storage and the rules around it:

- **Where the token lives.** The token sits in `infra/ci` next to
  `FLY_API_TOKEN`, so GitHub still holds a single secret, and rotating a token
  in Doppler is still the whole rotation. The request names only the
  allowlisted secrets, so nothing else in `worker/prd` leaves Doppler.
- **Doppler is the truth for the allowlisted names.** A name set there is set
  on Fly. A name deleted there is unset on Fly. A name listed without a
  readable value stops the staging before anything on Fly changes, because an
  unreadable value is not an absent one.
- **A missing grant is an error, not a failure.** The code has passed the suite
  and still ships. `scripts/verify-tracing.sh` then fails the run unless `/state`
  reports `health.tracing: true`. It only warns if no span reaches Braintrust
  within five minutes, because spans also depend on Braintrust and on the
  daemon having a tick to run.
- **`workflow_dispatch` on main deploys the backend.** A rotation then ships
  without a commit to carry it.

Growing the allowlist is a one-line change to the script. A name should go on
it only if Doppler is where it is edited.

### Consequences

- Good: no hand-run command, and tracing can no longer be silently off in
  production. `scripts/test_deploy_secrets.py` runs both scripts against stub
  `doppler`/`flyctl`/`curl` — the only check before main, since the deploy
  jobs skip on a pull request.
- Bad: a person must create the `worker/prd` token once; until then every
  backend deploy is red, and under OPS-0003 that holds back `deploy-web` too.
- Bad: a main deploy waits up to seven minutes longer.
- Reverse it if: Doppler gains a token scope that spans two configs, or the Fly
  sync moves into the tree. Either one retires the second token.
