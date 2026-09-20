# ADR-004 — Jev question batching and the question-set abstraction

Status: proposed · 2026-09-20

## Your hypothesis, and the verdict

> "One Jev call per agent per tick carrying its whole decision surface."

**Confirm the unit. Reject the cadence.**

- *One request carrying the whole decision surface*: **yes.** State is billed once per
  request; questions are evaluated in parallel; TypeSafe measured 13 questions in one call
  as 12× cheaper and 10× faster than 13 calls, and 62 questions in 0.51s (00 §1). More
  fundamentally, questions in a request are **independent** — one answer is never context for
  another — so there is nothing to gain from sequencing and no way to chain. The documented
  pattern is speculative fan-out: ask every branch, read the ones that turn out to matter.
- *Per tick*: **no — per decision point.** An agent halfway through a two-hour task has no
  decision to make. workbench's LLM chose `idle` in 75% of Calder decides (00 §6.2): that is
  what paying for decisions nobody needed looks like. Per-tick evaluation is also
  behaviourally *wrong*, not only wasteful (hazard-rate distortion, below).

## Decision points (wake policy) — plain code

An agent is evaluated when: its current task completes; an inbox item arrives whose
rule-assigned importance clears a floor; a schedule boundary passes (day start, lunch, day
end); a synchronous interaction involves it; or a **mandatory timer** fires — at most 8 ticks
(2 sim-hours) at work without a decision. Each agent has a fixed phase offset within the tick
so wake-ups do not synchronise; a test asserts the offsets are actually distinct (workbench's
were not, 00 §6.5).

Target: ≤ 20 requests per agent per sim-workday (ADR-003).

## Two kinds of question

Carried from 01. The kind is a required field; it determines what code does with the answer.

| Kind | Example | Consumer | On low confidence |
|---|---|---|---|
| **J — judgment** about the state | "Which category is this ticket?" | argmax / threshold | Escalate, scaled by stakes (ADR-005) |
| **P — propensity** of the agent | "What does she do next?" | **sample** from the distribution with the path-derived PRNG (ADR-007) | A flat distribution is legitimate indecision. Sample. Escalate only if high-stakes. |

P-type use of Jev is unvalidated by TypeSafe's docs (00 §0). M0 tests it.

**Hazard-rate rule.** Sampling a propensity repeatedly makes an event's frequency a function
of how often you ask: p = 0.02 for "resign", asked at every wake, fires within a week. So
P-type questions about **irreversible or rare actions** (resign, churn, dispute, terminate an
engagement) are asked *only* at decision points triggered by a relevant event, and pass
through hysteresis in code — e.g. churn requires the `considering_alternatives` belief to sit
at or above a level across N separate triggers. Reversible everyday choices need none of this.

## The abstraction

```
Question      id · kind (J|P) · primitive (noul|choice|score) · instructions template ·
              criteria · state paths read · consumer · stakes (low|med|high) ·
              threshold-policy ref · version
QuestionSet   compose( base(agent) , role(role) , org(org policy) , situational(inbox kinds present) )
```

- **Composable:** yes. Four layers, merged by code from registries. The situational layer is
  what keeps requests small: parameter questions for `reply_to_message` are included only if
  there is a message to reply to.
- **Per-role:** yes — the role layer holds the verb enum.
- **Per-org:** yes — and this is how "swap a single org's rules without touching the rest"
  is met. Org policy is *data*: criteria text, thresholds, and which optional questions are
  on. Hard rules (payment terms, SLA clocks, approval limits) are code reading the same
  policy object.
- **Versioned:** each layer carries a version; the set's version is the content hash of the
  rendered request minus state. Every decision row stores it (ADR-009). Thresholds are keyed
  by (question id, question version, model version) and are void when any of the three moves.
- **Ids are for code.** Jev never sees them (00 §1.1), so they are structured paths
  (`verb`, `reply.tone`, `inbox[3].importance`) and the instruction text stands alone.

**Every verb `choice` includes `other`.** Mass on `other` is an ontology-gap event (01 §3,
ADR-005) — the project's primary research measurement.

## Budgets and lint

Per request: ≤ 40 questions, state ≤ 2.5k tokens, total ≤ 6k tokens. Jev degrades on large
irrelevant state (00 §1.6), so the state budget is an accuracy rule before it is a cost rule.

CI lints every question against Jev's documented failure modes: no arithmetic, counting, or
date comparison in instructions — pass named buckets computed in code; nouls phrased so high
means yes; criteria consistent with instructions; score levels are described situations,
never numerals, ≤ 10; choices ≤ 255 options; every choice has `other` or a justification;
**no question may depend on another question's answer**; no two questions whose answers the
consumer combines arithmetically (Jev guarantees no such identities, 00 §1.3).

Golden tests: each question has recorded contexts with an expected argmax or band, run
against the pinned model under a paid-test marker. workbench's cassettes seed the first few
hundred (00 §6.3).

## Legitimate second requests

Only when the second request cannot be *built* without the first answer (TypeSafe's own
rule): memory rerank when the relational filter returns more candidates than fit (ADR-006);
a `choice` over more than 255 options (hierarchical); the ontology-gap follow-up.

## Alternatives rejected

- **One question per call**, the habit coding agents fall into (TypeSafe says so in its
  docs): 10× the latency, 12× the cost.
- **One giant fixed question set per role**: wastes tokens on parameters for verbs that are
  impossible right now, and pushes irrelevant material at a model that is documented to
  degrade on it.
- **LLM-style chained reasoning** (situation → options → best option, as Concordia's
  perception chain does): impossible within a request, and three round trips otherwise. The
  chain collapses into parallel questions plus code.

## Reverse if

- M0 shows latency rising materially past ~30 questions, or answers shifting when unrelated
  questions are added (contradicting documented independence) → split sets by consumer.
- The wake policy yields visibly sluggish agents (idle-with-backlog alerts, 02 §3.2) →
  shorten the mandatory timer before anything else.
