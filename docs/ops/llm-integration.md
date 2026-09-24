# LLM integration: what was tried, what it measured, what was kept

Session of 2026-09-24 (01:23–, overnight, autonomous). The question: where does
a general-purpose LLM measurably make jeve more realistic, deeper or better,
without a causal path through generated text? The research behind the
candidates is `docs/research/04-llm-integration.md`; every number below is in
`ops/evals.md`, rendered from `ops/evals/runs/*.json` and
`ops/evals/judge/*.json`; the rule a role had to pass is EVAL-0001.

## Method, in one paragraph

Each arm is the same world under one difference, run through `python -m
jeve.sim` for seven sim-days on a database of its own. Dev seeds 20260920–22
were used while building; held-out seeds 20261101–06 were not looked at until
a role was final. Every contrast is paired by seed, with a bootstrap 95%
interval and d_z. Plausibility is six stylized facts against cited bands;
depth is persona signal, identifiability, episode closure, diffusion and
memory; believability is GPT-5.6 Luna comparing matched episodes rendered from
typed records by one template, both orders, with any episode touched by its
own family excluded; non-regression is the soak's invariants, an event-log
digest, and cost per sim-day. `make evals ARMS=… SEEDS=…` reruns any of it.

## The instruments, checked before use

| check | result |
|---|---|
| judge on planted defects (wrong actor, loop, phantom effect, closed hours), 40 pairs, both orders | 0.98; 10/10 on closed hours, loops and phantom effects, 9.25/10 on a wrong actor |
| judge on identical pairs (position bias) | 0.50, all ties |
| judge test–retest under another sampling seed, 50 pairs | 50/50 the same two verdicts |
| same seed, same arm, twice (rules) | identical event-log digest |
| an LLM-routed world replayed from its cassette with no key | identical digest (`ed5f904e…`), 3,102 calls, $0 |
| eval tests (`tests/test_evals.py`): a band can FAIL and be ABSENT, each defect breaks the account as it says, a verdict counts both orders, the judge never opens a gateway unless told to | pass |

The defects are blatant; passing them shows the judge can see a broken
account, not that it can rank two plausible ones finely.

## What the baseline said before any LLM was added

Jev against the rules twin, held-out seeds: Jev is the deeper world by every
persona measure (first batch: persona signal +0.136, identifiability +7.4,
action entropy +0.167, all clear) and the worse conversationalist — over six
seeds **0% of its episodes end settled and 48% stall**, news reaches a quarter
as many people second-hand (0.055 against 0.219), and the judge preferred the
rules twin's episodes in 35.5 of 46 pairs.

Neither world is plausible where it counts most: bills are paid about on time
(mean 0.1–0.8 days late against a 4.5–20 band, because four fifths of clients
auto-pay on the due date) and the cafe peaks at noon (real cafes peak at 8–10).
Both are rules, not decisions; no model was asked to fix them.

## Roles

### 1. Tier 1 answers conversations outright — kept (DECIDE-0006)

- **Hypothesis.** Jev's `episode.round` answers are the cause of the stall; a
  general-purpose model answering the *same typed questions* ends
  conversations the way people do, without collapsing the distribution.
- **Change.** `JEVE_ESCALATION_ROUTE=episode.round`: tier 1's existing request,
  schema, cache and replay, for every question of the set; the world samples
  the LLM's distribution; Jev is still asked and both are kept.
- **Held-out (6 seeds).** Settled +0.59 [+0.54, +0.64]; stalled −0.40 [−0.53,
  −0.25]; rounds −0.54; action entropy +0.017 (clear, small); judge 36/48 over
  Jev and 23.5/49 (level) against the rules twin; no banded fact, invariant or
  world-level persona signal moved. Second-hand knowledge rose clearly on the
  first three held-out seeds (+0.058) and not over all six (+0.023 [−0.037,
  +0.068]): not claimed. Dev seeds agreed (settled +0.64, judge 22/28).
- **Cost.** $0.0039 → $0.0176 a sim-day (held-out mean); ~8 s per round call.
- **What it gives up.** Over 513 decisions answered by both models, the act
  distribution is flatter (entropy 0.51 → 0.81 — spread, not collapsed),
  P(done) 0.29 → 0.52, and the gap between outspoken and quiet people in
  pressing shrinks from +0.40 to +0.16 (small talk by sociability: +0.39 →
  +0.29).
- **Verdict.** Kept, on by default; `JEVE_ESCALATION_ROUTE=off` restores Jev.

### 2. Tier 1 answers only `done` — rejected on dev

- **Hypothesis.** The stall is the verdict, not the acts: route `done` alone
  and keep Jev's persona-bearing acts.
- **Change.** `episode.round:done` (`set:ask` routing).
- **Dev (3 seeds).** Settled 0.32, stalled 0.34 (full routing: 0.66, 0.04);
  judge 16.5/35 against Jev; cost ×2.1. Not carried to held-out.

### 3. Tier 1 live wherever DECIDE-0005 allows — not adopted

- **Hypothesis.** Re-asking uncertain medium- and high-stakes answers changes
  outcomes a judge or a fact can see.
- **Change.** `JEVE_ESCALATION=live` for every medium/high set; no code.
- **Result.** 20–26 escalations a world, ~70% acted on, disagreement with Jev
  concentrated in `founder.review`, `dispute.resolution`, `eng.allocation`.
  Held-out: nothing clear except cost (+$0.0009 a sim-day); judge 9.5/22.
- **Verdict.** Production stays in shadow, as it was. The judge reads
  episodes, and tier 1 never touches one: a judge of firm-level decisions
  would be needed to measure it properly (open question 3).

### 4. Staff written by an LLM, compiled to typed traits — reverted (EVAL-0002)

- **Hypothesis (two-sided, pre-registered from the literature).** Role-coherent
  people read as more believable — or LLM personas compress toward the middle
  and flatten persona.
- **Change.** One GLM request per firm; a zero-LLM referee typed each trait
  level (144 of 144 accepted) into its tertile; $0.004 once.
- **Held-out.** Persona signal −0.050 [−0.067, −0.038], d_z −3.2; action
  entropy −0.019; stalls +0.17; judge 14/22 (dev 12/23) — indifferent within
  its interval. The cast leaned diligent (14/24 high vs 6 seeded).
- **Verdict.** Reverted; code removed, runs kept.

### Not built, and why (docs/research/04 §4)

An LLM director of outside events (workbench kept its director as rules;
shocks are ~1.5 a week, so an A/B needs months of sim), dialogue projection
for episodes (viewer quality only, and judges prefer fluency), typed
reflection (Jev can already revise a typed belief; no evidence free-text
reflection helps), morning plans (would reword `agent.tick`, 97% of cost).

## Models

Jev stays at its pin (`typesafe/jev-1.13-20260917`); nothing moved it. Routed
questions go through tier 1, so they walk LLM-0006's generative order — GLM 5.3
Flash, Gemini 3.8 Flash, GPT-5.6 Luna, DeepSeek V4 Pro, DeepSeek V4.1 Flash —
rather than the brief's GLM → DeepSeek V4.1 Flash → Luna. One order for every
tier-1 path, and LLM-0006 measured V4.1 Flash failing 8 of 12 billed dialogue
attempts. The cost of keeping it: when GLM returns reasoning instead of JSON
(17% of its replies), the next model is Gemini, at five times GLM's input price
— 110 of 513 held-out routed decisions (21%). Whether V4.1 Flash does better at a strict
schema than at prose is unmeasured (open question 2). The judge is GPT-5.6
Luna; three held-out routed decisions were answered by Luna, and their
episodes were excluded from judging.

## The typed thesis

Nothing measured tonight says typed decisions cap realism. The one real
deficit found — conversations that never end — was fixed by a different
answerer of the *same typed questions*, with the draw still outside the model
and nothing generated read back. What the evidence does overturn is
design/005's blanket rule against sending a low-stakes propensity to an LLM,
for this one set, with the cost in persona stated (DECIDE-0006). The
ontology-gap rate — the thesis's own measure: the share of modelled choices
offering `other` that put at least 0.35 on it — sat at 4.6–5.0% on held-out
seeds, at the 5% line design/005 set for "the options are too small". That is
the number to watch, and no role tonight moved it.

## Spend

Budget: $10 for the session on the shared OpenRouter key, $2 held back for
the held-out runs. Each run's own ledger refused anything past what was left
(ceilings from the key's usage at the start, $2.2410); the key meter also
counts other users of the key and so over-counts.

| phase | $ (own ledgers) |
|---|---:|
| golden cassette re-record before any change (`LIVE=1 make e2e`) | 0.033 |
| judge validation and retest | 0.089 |
| dev arms: jev 0.054, tier-1 0.030, rounds 0.332, done 0.139, personas 0.059 | 0.614 |
| held-out arms: jev 0.127, tier-1 0.019, rounds 0.801, personas 0.036 | 0.983 |
| judge comparisons, dev and held-out | 0.387 |
| golden cassette re-record with routing on | 0.134 |
| **total** | **2.24** |

The key meter read $2.32 at the end: the difference is other traffic on the
shared key. $7.68 of the $10 was left unspent.
