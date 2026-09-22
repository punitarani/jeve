---

id: OPS-0003
title: Deploy the web app after the backend, never before it
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: [".github/workflows/ci.yml", "scripts/check_deploy_order.py"]
tags: ["deployment", "ci", "contracts", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0001", "OPS-0002", "CORE-0011", "WEB-0005"]
confirmation: "python3 scripts/check_deploy_order.py"

---

# OPS-0003 — Deploy the web app after the backend, never before it

## Context and Problem Statement

The site broke on a live deploy, showing "The API is not reachable" over a zod
error: `/state` had no `health.tracing`, where the contract said `boolean`.

Nothing was wrong with either side. `tracing` is a required field the API does
send. The web app was simply live before the API that sends it. The two deploy
jobs were independent — `deploy-web` needed `[web, contracts]` and went out
about forty seconds into the run, while `deploy-backend` needed `[python,
docker]` and waited for the whole suite. Across three consecutive pushes to
main the page was ahead of its API by 7m34s, 17m17s and 18m43s.

The window is not a race that happens to be lost sometimes. It is structural:
the zod schema is compiled into the static export at build time (WEB-0005), so
a browser validates against whatever the contract said when the *page* was
built, no matter what the API is running. Contracts are generated from pydantic
(CORE-0011), so every new required field arrives in the API first and in the
page second. Ship the page first and every such field breaks the window.

## Considered Options

- **Both deploys in parallel, after the suite.** Rejected: still a race, and
  not a fair one. `deploy-web` takes 37–49s, `deploy-backend` 48–77s, and the
  API serves new code only at the end of that, because `fly.toml`'s
  `release_command` migrates before the machines roll. The page usually wins.
- **Ship every new contract field `.optional()`, tighten it a deploy later.**
  Rejected: two deploys per field, and nothing enforces the discipline. The
  ordering is one edit and enforces itself.
- **`deploy-web` runs only after `deploy-backend` succeeds.** Taken.

## Decision Outcome

`deploy-web` needs `[web, contracts, deploy-backend]`, so the page ships only
once the API it talks to is live.

`deploy-backend` already needs `[python, docker]`, so the web deploy now waits
on the suite as well, transitively. A failed backend deploy holds the page
back, which is the point: a frontend newer than its API is the state that
broke. The backend-first direction is the safe one for an additive change,
which is the only kind the generated contract produces.

`scripts/check_deploy_order.py` is the confirmation, because on a pull request
both deploy jobs skip and CI never observes the ordering at all — a static
check of the job graph is the only thing that can prove it before a push to
main reaches production. It tests reachability rather than matching a literal
`needs` list, so a rearrangement that still orders the two correctly passes,
and it fails loudly if either job is renamed away rather than passing on a
graph it no longer understands.

### Consequences

- Good: the API always carries a field before the page demands it. The measured
  7–19 minute window closes.
- Bad: a Fly outage now also holds back a pure frontend change, and a main
  deploy is about seventy seconds longer.
- Reverse it if: the backend deploy becomes the unreliable one, so that
  coupling the page to it costs more availability than the skew it prevents.
