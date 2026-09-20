---
id: LLM-0003
title: Route with per-request provider preferences, never account settings
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["py/src/jeve/llm/protocol.py"]
tags: ["openrouter", "routing", "operations"]
supersedes: []
superseded-by: null
relates-to: ["LLM-0001"]
confirmation: null
---

# LLM-0003 — Route with per-request provider preferences, never account settings

## Context and Problem Statement

One model is served by many providers at different prices, speeds and
quantizations. OpenRouter allows a request-level `provider` block and an
account-level allow/ignore list. Privacy does not matter here; cheap, fast and
reliable do.

## Considered Options

- **Account-level provider settings** via the management key. Rejected as the
  default: invisible in a diff, global to every project on the account, and not
  scoped to this work.
- **Per-request `provider` preferences.** Taken.

## Decision Outcome

Routing preferences are set per request in the body — ordering, sort, ignore
list — and account-level settings are left alone; if one ever must change, the
before-state is written to `ops/provider-settings.before.json` first.

A limit worth knowing before relying on this: a request-level list is *merged*
with the account-wide allowlist, so it can narrow routing but never widen it.
When the account's allowlist excluded TypeSafe, no per-request setting could
reach Jev — the request 404s with an explanatory body, and only a human can
fix it. That is a property of the mechanism, not a bug.

One model-specific rule: Jev declares `supported_parameters: []`, so
`require_parameters` must never be sent with it or the request routes to
nothing. The gateway strips it for models that accept no parameters.

### Consequences

- Good: routing is visible in the diff and scoped to this project.
- Good: reversible by editing code, with no account state to restore.
- Bad: cannot recover from an account-level block; that needs a human.
- Reverse it if: a provider policy can only be expressed account-wide.
