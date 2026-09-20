# 00 — Ground truth

Researched 2026-09-20. Jev launched 2026-09-15; everything below is five days old and moving
(SDKs shipped breaking changes on 09-15 and 09-18). Re-verify before building on any number.

**Evidence tags.** `[V]` read first-hand today from the primary source (vendor docs, OpenAPI
spec, or a live public API response). `[D]` vendor claim, not independently tested. `[U]`
unverified or my inference. **No live Jev call was made** — I did not use any API key. Every
behavioural claim about Jev is therefore `[D]` at best until milestone M0 runs the smoke test.

---

## 0. Corrections to your assumptions

| # | You assumed | What's true | Consequence |
|---|---|---|---|
| 1 | "boolean w/ probability, choice-from-enum, scale" | Correct. Exactly three primitives: `noul`, `choice`, `score`. Nothing else. `[V]` | — |
| 2 | Every answer carries calibrated confidence | **`noul` has no `confidence` field** — only the probability. `choice` and `score` return `probabilities` + a derived `confidence`. `[V]` | Escalation rules differ per primitive. A noul gate is a band around 0.5; a choice gate is on `confidence` or top-2 margin. |
| 3 | "evaluates many questions per request in one parallel pass" | Correct, **and the questions are strictly independent**: "one answer does not become context for another question." `[V]` | No conditional chains inside a request. Either speculative fan-out (ask every branch, ignore the irrelevant) or a second request. This shapes the question-set abstraction (ADR-004). |
| 4 | "~70–500ms" | Vendor claim, measured "from our laptops on the West Coast (this is where our service is currently based)". Cookbook observations: 13 q over ~11.8k tok = 0.27s; 16 q = 0.32s; 62 q = 0.51s. `[D]` | You are in PDT, so this is the best case. Still unmeasured by us. |
| 5 | "$0.042/M input, free output" | Correct, same price on OpenRouter. State is billed once per request regardless of question count. `[V]` | Batch aggressively. |
| 6 | "cannot produce prose" | Correct. `[V]` | — |
| 7 | "Jev is nearly free" | **Per call, yes. At always-on scale, no — Jev is ~80% of the bill**, and spend is linear in the clock speed multiplier (§5). Against flash-tier LLMs doing the same typed job the gap is ~6–12×, not the ~400× on TypeSafe's homepage (that figure is vs. frontier reasoning models). `[U]` my estimate | The architecture falls out of `speed × agents`, not out of "Jev is free". See ADR-003. |
| 8 | "GLM 5.3 Flash" | Exists: `z-ai/glm-5.3-flash`. `[V]` | — |
| 9 | "Qwen 3.8 Next Flash" | **Does not exist.** "Next" was the 2025 `qwen3-next-80b-a3b` line. Closest: `qwen/qwen3.8-flash`. `[V]` | And it has the worst latency tail of the three (§4) — I recommend dropping it. |
| 10 | "GPT 5.6 Luna" | Exists: `openai/gpt-5.6-luna`. `[V]` | Its fastest endpoint (Bedrock) lacks structured outputs; see §4. |
| 11 | (implicit) escalation = hand off to a generative model | TypeSafe ships an MIT adapter that makes any OpenAI-compatible LLM answer **the same typed questions in the same response shape**. `[V]` | Escalation can stay typed. Prose generation is a *separate, rarer* path. Two tiers, not one (ADR-005). |

### The risk none of the docs can settle

Jev's probabilities are calibrated estimates that **a judgment about the supplied state is
true** ("does this message request a refund?"). jeve wants to use them as a **behavioural
policy** ("does Priya chase the overdue invoice this morning?") and *sample* from them.
Nothing in the docs validates that use. Calibration is defined over TypeSafe's training
labels; whether `noul = 0.7` for a persona-conditioned propensity question yields
heterogeneous, persona-sensitive behaviour — or flattens every agent toward the same
"reasonable employee" — is an empirical question. The jaggedness page warns that Jev reads
literally and degrades on "a property of a property", which is exactly what
persona-conditioned intent questions are. **This is the single largest technical risk in the
project and it is cheap to test.** M0 must include a persona-sensitivity probe before any
architecture is committed (see `docs/plan/mvp.md`, M0).

---

## 1. Jev / System One — API facts

Sources: `docs.typesafe.ai` (`/api`, `/models`, `/primitives/*`, `/confidence`,
`/concepts/*`, `/patterns/*`, `/model-jaggedness/jev-1.13`, `/sdk/*`, cookbooks),
`typesafe.ai/blog/introducing-system-one-models-and-jev`.

### 1.1 Request `[V]`

`POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <key>`.

```jsonc
{
  "model": "jev-1.13.0",                // or alias jev-latest / jev-preview
  "state": "...",                        // string | object | array — text only
  "questions": {                         // map; you choose the ids
    "<id>": { "type": "noul" | "choice" | "score", "instructions": ..., "criteria": ... }
  }
}
```

| Primitive | `criteria` | Limits |
|---|---|---|
| `noul` | optional `{ "true": ..., "false": ... }` | — |
| `choice` | **required** map `option → description \| null` | ≤ 255 options (above that TypeSafe's demos use a 2-stage score-then-choose, slower) |
| `score` | **required** ordered array of level descriptions | ≥ 2 levels, API accepts ≤ 10 |

- `instructions` and every criteria value may be string, object, or array. Structured
  instructions can carry per-question data; refer to it and to state by backticked path:
  `` `ticket.messages[0].text` ``.
- **Question ids are not sent to the model.** The instruction text must be self-sufficient.
- Score levels are judged **independently of each other**: the model does not see a level's
  index or its neighbours. "Worse than the previous level" is meaningless to it; numeric
  level labels fail (docs show `["0","1","2"]` producing confidence 0.33 on a trivial case).

### 1.2 Response `[V]`

```jsonc
{
  "model": "jev-1.13.0",                 // always the resolved version — log it
  "answers": {
    "a": { "type": "noul",   "noul": 0.95 },
    "b": { "type": "choice", "choice": "billing", "probabilities": {"billing":0.88,...}, "confidence": 0.81 },
    "c": { "type": "score",  "score": 1.05, "legend": {"0":"Calm",...}, "probabilities": {"0":0.0,"1":0.95,"2":0.05}, "confidence": 0.92 }
  },
  "usage": { "input_tokens": 296, "output_tokens": 20 }
}
```

- `choice.choice` is the argmax. `score.score` is the probability-weighted mean of level
  indices — a position, not a magnitude. Docs: do not interpolate numbers from it.
- `confidence` is a **derived statistic of how peaked the distribution is**, nothing more.
  The docs' demo formula for *n* options is `(n·p_max − 1)/(n − 1)`; TypeSafe says its exact
  definition may differ and invites you to compute your own from `probabilities`.
- Errors: 401, 422 (validation, names the field), 429 (rate limit), 529 (overloaded).

### 1.3 What calibration does and does not guarantee `[V]`

- Group-level: "Outcomes assigned 0.8 should occur about 80% of the time … These rates
  describe groups of predictions, not a guarantee about any single answer."
- "confidence 1.0 means the returned distribution puts all its probability on one level.
  This describes the model's answer, not a guarantee that the answer is correct."
- **No structural invariants.** Documented examples: the same question as a noul vs. a
  yes/no choice returned 0.22 vs. 0.01; a noul and its negation summed to 1.19. Docs: "Don't
  carry a threshold tuned on a Noul over to a Choice."
- Calibration was trained against TypeSafe's label distribution, not yours. Thresholds must
  be tuned on our own question sets (docs agree: "Test thresholds by plotting confidence
  against accuracy on your data"; for labels, "use an ensemble of expensive reasoning
  models").

### 1.4 Limits `[V]` (models page; "can change without notice")

| | Native | Via OpenRouter |
|---|---|---|
| Context | 64k tokens per request (state + all questions); 32k for state + the single longest question | `context_length: 32000` |
| Questions per request | No count cap; bounded by tokens | same |
| Rate | 250,000 tok/s and 1,200 req/min | undocumented |
| Input | text only; English best | same |

The primitives page says the budget is "around 32,000 tokens". Treat **32k as the safe
ceiling**; jeve should sit under 8k per call anyway (see 1.6).

### 1.5 Determinism `[V]` that it is undocumented

- No `temperature`, no `seed`, no determinism guarantee anywhere in the docs.
- TypeSafe's self-consistency cookbooks (15 repeats): mean per-question probability std
  ≈ 0.010 (noul and choice), max single-label std 0.0515; the argmax label flipped on 2 of 8
  choice questions. Those runs varied a throwaway `uid` field in the state, and the docs
  admit the setup "cannot separate sensitivity to the irrelevant field from variation that
  would occur on identical requests."
- **Whether byte-identical requests return identical probabilities is unknown. `[U]`** M0
  tests it. Design assumes *no*: replay uses logged distributions, never a re-query (ADR-007).
- Aliases move silently. `jev-latest` → `jev-1.13.0` today; cookbook code still says
  `jev-1.12`. **Pin `jev-1.13.0`.**

### 1.6 Documented failure modes (jev-1.13, reviewed by TypeSafe 2026-09-17) `[V]`

| Failure mode | What it means for jeve |
|---|---|
| Literal reading | Question authoring is an engineering discipline with tests, not prompt vibes. |
| No math, no counting, weak numeric representations | All money, quantities, durations stay in code. Pass **named buckets** ("12 days overdue — moderately late"), never raw numbers to compare. |
| Date/time comparison unreliable | Sim clock comparisons in code only. |
| Indirection / multi-hop degrades | Persona-conditioned questions are one hop of indirection by nature — the M0 probe targets this. |
| **Large state full of irrelevant detail → accuracy falls ("context rot")** | Memory retrieval and filtering must happen *before* the call and be aggressive. A fat "here's everything the agent knows" state is an anti-pattern. |
| Adversarial content in state can steer answers | Agent-generated prose re-entering state is a (mild) injection channel between agents. Keep generated text out of decision state where a structured summary will do. |
| Contradictory instructions vs. criteria | Lint question sets. |
| No structural invariants across questions | Never derive one decision by arithmetic over two answers that "should" be complementary. Ask it one way. |
| Generation | Impossible by design. |

Vendor anti-pattern list, verbatim intent: don't ask what code can compute; don't hide
several judgments in one question; no System-Two tasks; don't over-fill `state`.

### 1.7 SDKs `[V]`

| | Python | JS/TS |
|---|---|---|
| Package | `typesafe-sdk` (`uv add typesafe-sdk`) | `@typesafe-ai/sdk` (Node ≥ 20) |
| Version | 0.7.0 (2026-09-18) — **breaking**: msgspec → pydantic; 0.6.0 (09-15) — **breaking**: score criteria shape | 0.6.0 (2026-09-15) — same breaking change |
| Async | `AsyncTypeSafeClient` | promise-based |
| Typed responses | `response_model=` a pydantic model | answer types inferred from questions |
| Defaults | 10s timeout per attempt; 2 retries; backoff 0.5s→5s, jitter 0.25; retries 408/429/5xx; honours `retry-after` | same |
| Extras | `result.request_id`, `raw_http_response`, `extra_body` passthrough | custom `fetch` |

Two breaking releases in the first four days. **Wrap the SDK behind our own port; pin exact
versions.**

`system-one-adapter` (github.com/typesafe-ai/system-one-adapter-python, MIT, 5 commits):
drop-in `TypeSafeClient` replacement backed by OpenAI-compatible or Anthropic models,
returning the same `SystemOneResponse`. Accepts a custom `base_url`, so it can point at
OpenRouter. Modes: `"probabilities"` or `"discrete"`. **Python only.** LLM-emitted
probabilities are not calibrated (TypeSafe's own launch post says LLMs are overconfident),
so an escalated answer is a second opinion, not a better-calibrated one.

---

## 2. The access question: OpenRouter vs. native

**OpenRouter does not flatten Jev into chat-completions.** It added a dedicated alpha
endpoint and a new `decisions` output modality. `[V]` — from OpenRouter's OpenAPI spec and
live `/api/v1/models?output_modalities=decisions` response.

- `POST https://openrouter.ai/api/alpha/decisions`; SDK `openrouter.alpha.decisions.create`.
- Model ids: `typesafe/jev-1.13` (canonical `typesafe/jev-1.13-20260917`), alias
  `~typesafe/jev-latest`. **Absent from the default `/api/v1/models` listing** — you only
  see it with `?output_modalities=decisions`.
- Same `state` / `questions` / `answers` shapes, same three primitives, same price.

| Difference | Native `/v1/systemone` | OpenRouter `/api/alpha/decisions` |
|---|---|---|
| Stability | v1 | **alpha** path |
| Context | 64k / 32k | 32k |
| `probabilities`, `confidence` | required in response | **optional in schema** — must handle absence |
| noul `criteria` | both keys optional | if present, both `true` and `false` required |
| Extras | `extra_body` forward-compat | `provider`, `session_id`, `trace`, `user`; response adds `id`, `provider`, `usage.cost` |
| Rate limits | 250k tok/s, 1,200 rpm (volatile) | undocumented |
| Latency | direct | extra hop; OpenRouter shows no latency stats for it yet (`null`) |
| Access | early-access waitlist, key from console.typesafe.ai | any OpenRouter key `[U]` — page shows live quickstart and 100% uptime, not tested |

**Recommendation: target native, keep OpenRouter as a configured fallback behind the same
port.** Reasons: (1) latency is Jev's main advantage for a tick loop and an extra hop taxes
every call; (2) native has 2× the context and documented rate limits; (3) the typed
escalation adapter speaks the native SDK's types; (4) an `/alpha/` path can change under us.
OpenRouter's value is availability — if you are still on the TypeSafe waitlist, it is the
only door, and the port makes that a config switch. The response shapes are close enough
that one pydantic/zod model with optional `probabilities`/`confidence` covers both.

**Could not verify:** that either path is reachable with your credentials today. First task
of M0.

---

## 3. Python or TypeScript for the decision layer?

The ground truth pushes this one way: the typed-escalation adapter is Python-only, DSPy is
Python-only, the Python SDK has pydantic response models. **The simulation core and every
model call live in Python.** TypeScript is the frontend and the shared contract types. This
is recorded in ADR-008/ADR-009 rather than relitigated per module.

---

## 4. Escape-hatch model matrix

IDs, prices, context, and capabilities: `[V]` from `openrouter.ai/api/v1/models` and
`/endpoints` today. Latency: `[V]` read from OpenRouter's provider tables today (P50 and P99
selectors), but **these are OpenRouter-wide figures mixing all request sizes and all
reasoning-effort settings over a rolling window**, and the provider table and the
performance block use different windows (both quoted where they differ). They bound
expectations; they are not what jeve will observe. M0 measures our own.

**What OpenRouter's "Latency" means is unclear `[U]`.** The page legend reads "Latency is
total round-trip time… TTFT is time-to-first-token", yet the same page reports a separate,
much larger "E2E Latency" (Luna on Bedrock: 0.73s vs. 2.04s). A sub-second figure cannot be
a full multi-hundred-token response, so I read "Latency" as roughly time-to-first-token and
"E2E" as the full response — by inference, against the legend's wording. For jeve's short
generations E2E is the number that matters.

| | `z-ai/glm-5.3-flash` | `openai/gpt-5.6-luna` | `qwen/qwen3.8-flash` |
|---|---|---|---|
| Your name for it | GLM 5.3 Flash ✔ | GPT 5.6 Luna ✔ | "Qwen 3.8 Next Flash" ✘ (no such model) |
| List price in / out per M | $0.15 / $0.50 most providers; $0.09 / $0.30 cheapest list; $0.075 / $0.25 promo (DeepInfra, fp4) | $0.20 / $1.20 (OpenAI, Azure); $0.22 / $1.32 (Bedrock, Azure regional); $0.40 / $2.40 (OpenAI Fast) | $0.15 / $0.47 |
| Context | 1.05–1.31M | 1.05M | 1.0M |
| Providers | 30 | 7 endpoints, but **only 2 (OpenAI, Azure) are in OpenRouter's standard routing**. The other 5 — OpenAI Flex, OpenAI Fast, two regional Azure, and **Bedrock** — are listed under "Not used in Standard routing"; I did not read OpenRouter's explanation of why `[U]` | **1** (Alibaba) — no failover |
| `structured_outputs` | provider-dependent: 22 of 30 endpoints. All five fast providers named below support it. | OpenAI, Azure yes; **Bedrock no** | yes |
| `seed` | provider-dependent; of the fast providers only Friendli and CoreWeave accept it (Modal, Baseten, Together do not) | yes (not Bedrock) | yes |
| "Latency" P50 (best providers) | Modal 0.29s · Friendli 0.36s · CoreWeave 0.60s · Together 0.66s · Baseten 0.70s (89 tps) | **Standard routing: OpenAI 1.75s · Azure 3.90s.** Outside it: Bedrock 0.55s · OpenAI Fast 1.35s · regional Azure 2.0–2.6s | 1.72s (perf block) / 2.15s (table) |
| "Latency" P99 | Modal 1.85s · CoreWeave 5.35s · Baseten 6.66s · Friendli 7.0s · many providers 15–72s | **Standard: OpenAI 13.9s · Azure 34.2s.** Outside: Bedrock 3.07s · regional Azure 9.1–13.3s · OpenAI Fast 23.4s | 31.2s |
| E2E P50 | Modal 2.42s · CoreWeave 3.32s · Together 3.37s | Bedrock 2.04s · OpenAI Fast 4.47s · **OpenAI 5.23s** | 11.35s |
| E2E P99 | not shown per-provider in what I captured `[U]` | Azure EU 37.6s · OpenAI 55.0s · OpenAI Fast 55.5s | **222.5s** |
| Structured-output error rate (best) | 0.37–0.72% | 0.18–0.46% | not captured |
| Notes | Quantization varies (fp4/fp8/nvfp4) — pin providers or accept quality variance. Effective paid input price ≈ $0.046/M thanks to cache hits. | `openai/flex` at $0.10/$0.60 has P50 **41s** and is excluded from standard routing — the cheap price is not usable online. Web page lives only under the dated slug `openai/gpt-5.6-luna-20260709` (undated URL 404s; API id is fine). | Single provider + 222s P99 tail. |

Also seen, not evaluated: `z-ai/glm-5.3-flashx` (released 2026-09-18, Z.AI only, $0.37/$1.25);
aliases `~z-ai/glm-flash-latest`, `~openai/gpt-luna-latest`.

**Read-across for the design:**

1. **No LLM call may sit on the tick's critical path.** Even the best E2E P50 is 2–5s and
   P99 runs 40–220s. Generation and typed escalation are asynchronous jobs whose results
   land in a later tick (ADR-002).
2. Luna's only sub-second endpoint (Bedrock) lacks `structured_outputs` *and* sits outside
   standard routing. What you actually get from Luna by default is OpenAI at ≈ 1.75s to first
   token and ≈ 5.2s end to end. GLM 5.3 Flash on a pinned fast-provider allowlist (Modal,
   Friendli, CoreWeave, Baseten, Together — all support structured outputs) is both faster
   and cheaper.
3. **Recommendation:** primary `z-ai/glm-5.3-flash` with a provider allowlist; secondary
   `openai/gpt-5.6-luna` (different vendor, different failure domain, best structured-output
   reliability); **drop Qwen3.8 Flash** — one provider and a 222s tail buy nothing the other
   two don't. Routing config must use the API ids above, never display names.

---

## 5. Cost model inputs (full treatment in ADR-003)

Verified prices in; **my assumptions** for volumes (3,500 tokens per Jev call, 1.7 calls per
active agent-tick, 85% of business-hour ticks active, 15-sim-minute ticks, 8-hour sim
workday, 3 generated messages + 1 reflection per agent per sim-day, 3% typed escalation).
Sanity anchor: TypeSafe's Doom demo ("10 queries a second … ~$7/hour") implies ~4,600
tokens per rich call, so 3,500 is not optimistic by an order of magnitude.

| N = 24 agents | Jev $/sim-workday | Generation $/sim-workday (GLM list) |
|---|---|---|
| central | 0.163 | 0.035 |
| pessimistic (6k tok, 2.5 calls, 10% escalation) | 0.411 | 0.047 |

| Clock speed | Real seconds per tick | Central $/real-day | Pessimistic $/real-day | Central $/month |
|---|---|---|---|---|
| 1× | 900 | 0.14 | 0.33 | 4 |
| 12× | 75 | 1.70 | 3.93 | 51 |
| 24× | 37.5 | 3.39 | 7.86 | 102 |
| 60× | 15 | 8.48 | 19.65 | 254 |

Same typed workload on a flash LLM instead of Jev (answering ~30 questions with
distributions costs ~900 output tokens per call): GLM ≈ 6.6× Jev, Luna ≈ 12×.

Rate-limit headroom at native limits: N=24 → ~35 calls per tick, ~121k-token burst; the
request limit alone would allow ~500×. **Cost binds long before rate limits do.**

Three findings, stated plainly:

- Jev is ~80% of spend. Generation is the expensive exception *per call* (2–3×), but it is
  rationed; Jev runs on every decision.
- Spend is linear in clock speed. The speed multiplier is a budget decision, not a UX one.
- The biggest lever is not price, it is **not calling**: an agent mid-task needs no
  decision. This table is a tick-driven **ceiling**. workbench, which is event-driven,
  measured ≈7–12 model calls per person per sim-day (§6.4) against the ≈46 assumed here —
  so an event-driven jeve plausibly costs a quarter of these figures. ADR-003 carries both
  anchors; M0/M1 replace them with measurements.

---

## 6. workbench

Read-only. `.env` and `jobs/` were not opened. `[V]` = I opened the file myself; `[A]` =
reported by the read-only research agent with file references, **not re-checked by me**.

### 6.1 What it is

A factory for RL environments of professional work. An offstage simulation plays every
employee and client of a firm day by day and writes one validated append-only world log;
the log is projected into SQLite-backed MCP emulators (Gmail, Calendar, Slack, iManage,
Clio); Harbor-format tasks are graded against oracles computed from the same world. `[A]`

The part that matters here is `src/simulation` — ≈11.3k non-test lines `[V]` — a clean-room
**Concordia-pattern, LLM-driven multi-agent simulation of a firm**. It already has an
event-sourced durable store with kill-anywhere resume, a referee that makes zero LLM calls,
DSPy personas with memory/plan/reflect, and content-keyed record/replay of every LLM call.
No TypeSafe/Jev/System One code exists anywhere in it (0 hits in src, scripts, tests, docs,
lockfile `[A]`), and no confidence or escalation logic.

**You have already built most of jeve's skeleton once, in a batch setting.** The question
is what survives the move from "record 130 workdays, then stop" to "run forever, online".

### 6.2 workbench is already a typed-gate + generation system

`src/simulation/persona/programs.py` `[V]`:

```python
class ExtendedActionChoice(BaseModel):
    action: Literal["reply_email","send_email","post_chat","react_chat","create_ticket",
                    "comment_ticket","log_time","create_document","revise_document",
                    "schedule_meeting","update_ticket","respond_invite","idle"]
    target_ref: str | None
    intent: str
    reason: str
    emoji: str | None; minutes: int | None
    response: Literal["accept","decline","tentative"] | None
```

`DecideNextAction(identity, situation, current_plan, relevant_memories, pending,
recent_activity) → choice`. Separate `Draft*` signatures then turn `intent` into prose.
In System One terms the decide call is: one `choice` over 13 verbs, one `choice` over the
pending refs, one `choice` of 3, a duration bucket, and one short free-text `intent`.
`reason` is consumed by nothing `[A]`. **An LLM is currently being paid ~2.7k prompt tokens
to emit what is almost entirely an enum.**

Measured by the agent from the recordings `[A]`: decide is 38–66% of all LLM calls and
54–75% of prompt tokens; in the 130-workday Merrick recording ≈62% of sampled decides end in
an outcome routed with no drafter call at all (idle, react_chat, respond_invite). In Calder
75% of decides were `idle`.

### 6.3 The cassettes are a free offline benchmark for Jev — this should be M0

`src/workplaces/calder/cassettes/epoch-seed42/` holds 1,954 committed entries `[V]`. One
entry `[V]`:

```jsonc
{ "request":  { "model": "deepseek/deepseek-v4-flash-0731", "seed": 1199…, "max_tokens": 4096,
                "messages": [ {system: 6,386 chars}, {user: 4,312 chars} ], … },
  "response": { "text": "[[ ## choice ## ]]\n{\"action\": \"idle\", \"target_ref\": null, …",
                "usage": { "prompt_tokens": 2713, "completion_tokens": 132 } },
  "site": … }
```

Every decide entry carries the full rendered decision context and the enum a competent LLM
chose. The gitignored epoch recordings hold on the order of 11k more `[A]`. Replaying those
contexts through Jev as `choice` questions measures, **before any jeve code exists**:
agreement with the LLM's choice; whether Jev's `confidence` predicts disagreement (the
escalation threshold curve, ADR-005); whether different personas in the same situation get
different distributions (the §0 risk); real tokens per call; real latency. That is a better
first milestone than anything synthetic.

Caveat: agreement with DeepSeek-Flash/Haiku/Sonnet is not correctness, and those recordings
show a strong `idle` prior. Treat it as a reference, not ground truth.

### 6.4 Two measured anchors that correct my cost model

- **Tokens per decision:** ≈2.2k (Calder, flat over 140 days) to ≈3.7–3.9k (Merrick) prompt
  tokens per call `[A]`; the entry I opened was 2,713 `[V]`. My 3,500 assumption holds.
- **Decisions per person per day:** Merrick made 29,710 LLM calls over 130 workdays with 31
  people ≈ **7 calls per person per sim-day, all call types**; Calder ≈ 12 `[A]`. workbench
  is event-driven (interrupt engine, wake on cue/event), not tick-driven. My §5 estimate of
  ≈46 Jev calls per agent per sim-day is a **tick-driven upper bound**. An event-driven
  jeve at 10–15 decision points per agent-day costs ≈$0.04 per sim-workday at N=24, about a
  quarter of the §5 central figure. §5 stays as the ceiling; ADR-003 carries both.

### 6.5 Transfer table

| Pattern | Where | Verdict | Why |
|---|---|---|---|
| Path-derived seeds: `blake2b(domain ‖ root ‖ len-prefixed path parts)` → int / `random.Random` | `src/core/seed.py` `[V]` | **Lift near-verbatim** | Stateless and process-stable. `derive_rng(seed, agent_id, tick, purpose)` means there is no RNG state to persist, so `kill -9` cannot desynchronise randomness. Exactly what ADR-007 needs. |
| Canonical JSON + blake2b content hash | `src/core/hashing.py` `[V]` | **Lift near-verbatim** | Call-order-independent key for the model-call log and idempotent replay. |
| Decorator chain `Budgeted(Recording(Retry(backend)))` with retry *inside* the recorder | `src/simulation/lm/` `[V]` protocol, `[A]` chain | **Lift the pattern, not the protocol** | `LMResponse` is `text: str` `[V]`. Jev returns typed answers. jeve needs a sibling `DecisionModel` protocol with the same decorator stack. The agent's "Jev is one more `LanguageModel`" is wrong in detail. |
| OpenRouter backend: raw httpx, pinned `provider.order` with `allow_fallbacks: false`, `reasoning: {enabled: false}`, **`seed % 2**63`** | `src/simulation/lm/openrouter.py` `[A]` | **Lift** for the generation path | The seed mask exists because a seed ≥ 2⁶³ is rejected by the gateway and killed a 15-day run on day 6 `[A]`. Note the cassette I opened has a seed > 2⁶³ in the *request*; the mask is applied at send time. |
| `RetryLM`: 6 attempts, 2s·2ⁿ ≤ 30s, jitter | `lm/retry.py` `[A]` | Transfers with changes | Add `Retry-After`, and a circuit breaker that pauses the sim clock rather than burning attempts (ADR-002). |
| One transaction per engine step: event + queue removal + newly scheduled rows + meta | `engine/engine.py:241-257` `[A]` | **Lift the design** | This is the restart-safety core. A crashed step re-executes and its model calls replay from the record. Port SQLite→Postgres. |
| Run store: `events`, `scheduled`, `snapshots`, `run_meta` | `src/core/store.py` `[A]` | Transfers with changes | Maps onto Postgres with JSONB payloads. Contiguous `seq` assumes one in-process writer — add an advisory-lock lease so a second sim process cannot start. |
| Roll-forward resume | `simulation/run.py` `[A]` | Transfers with changes | Reads the whole log into memory and rewrites every persona's facts each step `[A]` — fine for 130 days, unbounded for forever. Needs windowed hydration + periodic snapshots. |
| **Refuse to resume on `engine_fingerprint`/`config_hash` mismatch** | `run.py:531-620` `[A]` | **Does not transfer** | Correct for a frozen recording; fatal for an always-on sim that must accept deploys. A `ruff format` alone broke a live resume `[A]`. Replace with a logged `sim.engine.changed` event so the seam is visible in the data. |
| **Raise-and-die on budget exhaustion; per-process call budget that resets on resume** | `lm/budget.py` `[A]` | **Does not transfer** | jeve needs a persisted rolling $ budget that *slows the clock* (ADR-001/003). Keep its rule: never fabricate a model response. |
| Zero-LLM referee, typed intents, reject-with-guidance returned as a high-importance memory | `gm/grounded.py`, `core/intents.py` `[A]` | **Lift the design** | All four orgs' ledgers must be grounded in code. Concordia's own maintainers say the same (see 01). |
| Two-audience rejections (`reason` for the persona, `detail`/`engine_fault` for the operator) | `gm/grounded.py:106-153` `[A]` | **Lift** | The reported incident is the best argument in either repo for keeping engine errors out of agent memory: a pydantic dump became an importance-8 memory and over thirty days the firm built a shared story of a platform outage that never happened, and staff billed time to it `[A]`. In jeve, where outages are a *real* mechanic, a phantom one would poison the headline result. |
| Dampeners: reply-chain depth 3, threads ≤ 12, chat streak ≤ 6, cues ≤ 8/day | `gm/grounded.py`, `director/schedule.py` `[A]` | **Lift as defaults** | An earlier run produced 200+ acknowledgment-only emails `[A]`. These are the loop failure mode in §5 of the brief, already met and already fixed once. |
| "Derive, don't ask" intent shapes | `core/intents.py:117-143` `[A]` | **Lift the principle** | Asking for raw seconds → 42.4% malformed calendar starts; asking replies to restate recipients → 38.2% refused `[A]`. Same lesson as Jev's jaggedness page: ask for the judgment, compute the rest. |
| `PermitPool` (asyncio semaphore) | `lm/permits.py` `[A]` | Lift | Add a token bucket for Jev's tok/s limit. |
| Interrupt engine + `EventDrivenTimeModel` | `engine/`, `time_model.py` `[A]` | Transfers with changes | Right scheduler shape. No wall-clock pacing and no tick budget exist (a sim-day took 8–15 real minutes) — jeve adds both. |
| Integer-only memory scoring `importance × recency × (1 + relevance)`, no embeddings | `persona/retrieval.py` `[A]` | Transfers with changes | Exists to make replay byte-identical. jeve keeps "no embeddings" for MVP for a different reason (ADR-006) and swaps rule-based importance for a Jev `score`. |
| Cassette = one JSON file per call | `lm/cassette.py` `[A]`, format `[V]` | Transfers with changes | 29,770 files in one directory does not scale to forever. Same idea as a Postgres table with retention; keep file cassettes for hermetic CI. |
| Kill-and-resume byte-compare test | `tests/simulation/test_resume_anywhere.py` `[A]` | **Lift** | The arbiter for the `kill -9` line in the MVP definition of done. |
| Determinism lint: ruff `banned-api` on `random.*`, `uuid4`, `time.time`, `datetime.now` | `pyproject.toml:86-102` `[A]` | **Lift** | Cheap and it holds the line ADR-007 draws. |
| Tooling: uv + committed lock, ruff `E,F,W,I,UP,B,TID`, pytest `asyncio_mode=auto`, paid-LLM tests opt-in via marker, test files named as invariant sentences, per-package `AGENTS.md`, mutation-tested gates in CI | repo root `[A]` | Lift | Note Python 3.14 + PEP 758 `except A, B:` syntax is in use `[A]`; jeve should match 3.14 or lifted code will not parse on older interpreters. |
| DSPy | `persona/programs.py` `[V]`, `optimize/` `[A]` | Transfers with changes | In workbench DSPy earns its keep as **typed signatures + parser + swappable instruction surface**. Its optimizers did not: the hand-rolled reflective loop's best candidate "quoted the evaluation day verbatim (reward hacking)" and nothing generic shipped `[A]`. That is direct evidence for ADR-008's position: DSPy for the generative minority's signatures; no optimizer in the MVP. |
| Harbor tasks, MCP emulators, oracles, gateway | `src/tools`, `src/adapters`, `datasets/` | Does not transfer | That is the eval product. Its *method* — fidelity bands reported PASS/FAIL/ABSENT, rank-correlation coherence checks — feeds `02-validation.md`. |

Latency lesson worth carrying `[A]` (`docs/METHOD.md`): "cast size is nearly free… tick
count and tail latency are the whole cost"; "a cohort's wall time is its slowest member."
That is the argument for keeping every LLM call off the tick's critical path (ADR-002), and
for staggering wake-ups — workbench's own stagger is reportedly broken (`slots == 1` pins
every persona to phase 0, so 21 personas shared all 323 wake timestamps `[A]`).

### 6.6 Heads-up, unrelated to jeve

The agent reports that `docs/RESUME.md:70` says `jobs/` "contains plaintext API keys in
logs", and that gateway tokens appear unmasked in `jobs/*.json` `[A]`. The directory is
gitignored and nothing opened those files, but if any of those keys are live they are
sitting in ~400 directories on disk.

## 7. Pointers

- Prior-art mechanism mapping and the typed-decidable table: `01-prior-art-mapping.md`.
- Validation survey and instrumentation plan: `02-validation.md`.

## 8. Could not verify — carry into M0

1. Live reachability of native `/v1/systemone` and OpenRouter `/api/alpha/decisions` with your keys.
2. Determinism of byte-identical requests.
3. Real latency from your machine for a ~3.5k-token, ~30-question request (P50/P95/P99 over ≥ 500 calls).
4. Current effective rate limits (docs say they float).
5. OpenRouter rate limits and added latency for the decisions endpoint.
6. **Persona sensitivity and behavioural diversity when sampling Jev distributions as policy** (the §0 risk).
7. Actual tokens per call for a realistic jeve decision surface.
8. Whether `extra_body` fields hinted in SDK docs (`beam_width`, per-question `weight`) are real features — they appear only as forward-compatibility illustrations. Assume not.
