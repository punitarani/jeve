# ADR-005 — Confidence-gated escalation

Status: proposed · 2026-09-20 · Depends on ADR-002, ADR-004.

## Decision

**Two tiers, and tier 1 is not generation.**

| Tier | Trigger | What runs | Output |
|---|---|---|---|
| **1 — typed second opinion** | A high- or medium-stakes answer falls inside its uncertainty band | The *same question(s)* — only the uncertain ones, not the whole set — sent to an LLM through TypeSafe's `system-one-adapter`, which returns the same response type (00 §1.7). Primary `z-ai/glm-5.3-flash` on a pinned fast-provider allowlist; secondary `openai/gpt-5.6-luna` (00 §4). | Typed answer. The downstream pipeline is unchanged. |
| **2 — generative** | `other` mass on a verb choice ≥ 0.35 (an ontology gap), or a viewer opens something that needs prose | An LLM proposes a mapping onto existing verbs or a new enum member *as structured data for review*; or renders text from a typed act | Structured proposal, or view-only prose |

Neither tier is on the tick barrier. A tier 1 escalation makes the agent hesitate for up to
3 ticks (ADR-002).

### The rule, per primitive

Noul has no `confidence` field, and TypeSafe warns never to carry a threshold across
primitives (00 §1.3). So there are three rules, not one.

| Primitive | Uncertain when | Note |
|---|---|---|
| `choice` | `confidence < 0.50` **or** top-two margin `< 0.15` — **unless** the top two options are in the same consequence class | Consequence classes are declared in code per question. Dithering between two ways of continuing to work is not worth a dollar. |
| `score` | `confidence < 0.40` **and** ≥ 0.25 of the mass lies on each side of the code boundary the consumer uses | A wide distribution entirely on one side of the boundary changes nothing. |
| `noul` | `\|noul − θ\| < 0.12`, where θ is that question's action threshold | A band around the **threshold**, not around 0.5. A noul of 0.5 on a question gated at 0.9 is a confident "no". |

Modifiers:

- **Stakes.** `low` never escalates — sample and move on. `high` (irreversible or large:
  pay a big invoice, dispute, churn, terminate, resign) widens every band × 1.5.
- **P-type questions escalate only when high-stakes.** A flat distribution over plausible
  next actions is what indecision looks like, and sampling is the correct response to it.
  Sending every flat propensity to an LLM would route the most human decisions through the
  model most prone to collapsing them to one mode (02 §1), and destroy the diversity the
  sampling exists to produce. This is the single most consequential line in this ADR.
- **Budget.** Tier 1 is capped at 5% of decisions per sim-day. If the cap binds, the
  governor narrows the bands, highest-stakes last.

### What the second opinion does

- **J-type:** adapter in `discrete` mode; the LLM's answer replaces Jev's. LLM-stated
  probabilities are not calibrated, so none are requested.
- **P-type (high-stakes only):** adapter in `probabilities` mode; the sampled distribution is
  a 50/50 mixture of Jev's and the LLM's, so a persona signal present in Jev's answer is not
  overwritten.
- Both answers, the rule that fired, and the final outcome are logged on the decision row.

## How the thresholds get tuned rather than guessed

The numbers above are placeholders with a documented replacement procedure. TypeSafe's own
guidance is to "test thresholds by plotting confidence against accuracy on your data" and,
lacking labels, to "use an ensemble of expensive reasoning models to generate them."

1. **M0, offline, before any sim exists.** Replay workbench's recorded decide contexts
   through Jev (00 §6.3). For each question plot P(Jev disagrees with the recorded LLM
   choice) against confidence and against margin. Set each band at the knee where
   disagreement exceeds 2× its base rate. If there is no knee — disagreement is flat in
   confidence — **confidence is not a usable gate** and escalation falls back to stakes only.
2. **Online, shadow mode, from the first day the sim runs.** Tier 1 runs asynchronously on
   every decision inside the placeholder bands *plus a uniform 2% sample of all decisions*,
   and **changes nothing**. The uniform sample is what makes the estimate unbiased: without
   it you only ever learn about decisions you already suspected.
3. **Weekly tuning job.** Per (question id, question version, model version): choose the band
   that captures ≥ 60% of observed disagreements within the 5% budget. Tier 1 is switched
   from shadow to live per question, only once that question has ≥ 200 shadow samples.
4. **Invalidation.** A Jev version bump or a question edit voids that question's bands and
   returns it to shadow. `jev-1.13.0` is pinned precisely so this happens on our schedule
   (00 §1.5). The daily canary suite (02 §3.0) detects an unannounced change.

What this measures is **agreement with an LLM panel, not correctness** (02 §3.5). That is
the only reference available and the docs say so.

## Alternatives rejected

- **One global confidence threshold.** Contradicts the vendor's documentation, ignores that
  noul has no confidence, and ignores stakes.
- **Escalate to prose generation** ("ask the smart model what to do"). Returns free text that
  must be parsed back into the ontology — reintroducing the failure class the project exists
  to remove — when a typed channel to the same model is available.
- **Synchronous escalation with a deadline.** Puts a 40–220s P99 on the tick barrier.
- **Self-consistency voting on Jev** (ask N times). Jev's repeat variance is ≈ 0.01 in
  probability (00 §1.5); N calls return the same answer N times.
- **Escalate on any low confidence, P-type included.** See above.

## Reverse if

- Shadow data shows the LLM agrees with Jev > 95% of the time *inside* the bands → tier 1
  buys nothing; delete it and keep the logging.
- Disagreement is uncorrelated with confidence or margin → gate on stakes alone.
- The ontology-gap rate exceeds ~5% of decisions → the verb enums are too small; that is a
  modelling problem to fix in the role definitions, not a routing problem.
