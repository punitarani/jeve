# Blocked

Append-only. Each entry: symptom, what was tried, best hypothesis, next step.

---

## B1 — Jev is unreachable: account allowed-providers excludes `typesafe`

**Status:** open, needs Punit. Not fixable from here.
**Found:** 2026-09-20 ~02:30, gate 1a smoke.
**Blocks:** step 3b (the Jev swap) and everything that measures typed-decision
economics. Does **not** block 1b, 2, 3a, 4, 5 — those have no model calls.

**Symptom.** `POST https://openrouter.ai/api/alpha/decisions` → 404:

```
No allowed providers are available for the selected model.
Providers serving typesafe/jev-1.13-20260917: typesafe,
but your account's allowed-providers setting permits only:
meta, baidu, google-vertex, novita, openai, baseten, gmicloud,
anthropic, streamlake, google-ai-studio.
To change your allowed providers, visit: https://openrouter.ai/settings/privacy.
```

**What was tried.**

1. Fixed a real bug this surfaced: the client was posting to
   `/api/v1/api/alpha/decisions`, because the Decisions endpoint is a *sibling*
   of `/api/v1`, not a child. After the fix the request reaches OpenRouter and
   the error changes from a bare `Not Found` to the one above.
2. Per-request `provider.only` / `provider.order` — **cannot work.** OpenRouter
   documents that a request-level list "is merged with your account-wide allowed
   provider settings", so it can narrow the allowlist but never widen it.
3. Looked for an API to read or change the setting. The Management API key is
   documented as `/api/v1/keys` only — "management keys cannot be used to make
   API calls to OpenRouter's completion endpoints … exclusively for
   administrative operations" — and no endpoint for account provider
   preferences is documented. So there is no scripted path, and the standing
   instruction was to prefer per-request routing anyway.
4. Confirmed the blast radius is Jev alone: `typesafe` is the sole provider for
   `typesafe/jev-1.13`, whereas GLM 5.3 Flash is served by novita, baseten,
   gmicloud and streamlake — all already permitted. The chat path works.

**Hypothesis.** Not a data-policy or early-access problem, and nothing to do
with the alpha endpoint being alpha. The account simply has an explicit
provider allowlist that predates Jev's existence, and TypeSafe is a new
provider that was never added to it.

**Next step (Punit, ~1 minute).** At <https://openrouter.ai/settings/privacy>,
either add `typesafe` to allowed providers or clear the allowlist. Nothing else
changes. The current list is recorded verbatim in
`ops/provider-settings.before.json` so it can be restored exactly; I did not
modify it.

**If it is still closed by morning.** Step 3b runs against a flash-LLM typed
adapter behind the same `DecisionModel` port, the economics gate is reported as
missed with the reason, and the Jev comparison moves to a later session. That is
a finding, not a workaround — it will be labelled as such in `HANDOFF.md`.

**Resolved 2026-09-20 ~11:05 PDT.** Punit added `typesafe` to the allowlist.
`make smoke` now returns all three primitives with distributions (206 ms,
$0.000023, 548 input tokens), and `make providers` reaches Jev and all five
escape-hatch models — see `ops/providers.md`. The status line above is left as
written; this file is append-only.
