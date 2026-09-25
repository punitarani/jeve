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
| --- | --- |
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
| --- | ---: |
| golden cassette re-record before any change (`LIVE=1 make e2e`) | 0.033 |
| judge validation and retest | 0.089 |
| dev arms: jev 0.054, tier-1 0.030, rounds 0.332, done 0.139, personas 0.059 | 0.614 |
| held-out arms: jev 0.127, tier-1 0.019, rounds 0.801, personas 0.036 | 0.983 |
| judge comparisons, dev and held-out | 0.387 |
| golden cassette re-record with routing on | 0.134 |
| **total** | **2.24** |

The key meter read $2.32 at the end: the difference is other traffic on the
shared key. $7.68 of the $10 was left unspent.

## Second session: signal, calibration, a prompt laboratory, a 60-day trial

The brief changed overnight: quality over cost; fix the model errors; make
decisions, events and interactions carry more data and signal, calibrated to
data; run a two-month trial; account for every eval and metric
(`docs/ops/metrics.md` is that catalogue). Then: treat LLM use as an
experiment, DSPy-style, and keep only what the evidence supports.

### Model errors

GLM 5.3 Flash's tier-1 replies were unreadable 17% of the time: one provider
(Together) wrote its reasoning into the content, and 1,600 tokens cut it off
before any JSON. Routed around it per request (LLM-0003), given 4,000 tokens,
and read for the last JSON object in a reply, GLM answered 508 of 509 routed
decisions in a 60-day world, and 677 of 678 in the interim trial (78% before).
No run logged a model error, retry or wait.

### More signal (WORLD-0013, MEM-0004)

- Every decision keeps the facts it was asked on (`decisions.facts`, about
  eight fields).
- A bill left late keeps a typed reason, and how often it was chased and
  raised in person. Payment, chase, encounter, cancellation and resignation
  events carry amounts, lateness, pressure, the tie between the two people,
  and a reason.
- People who meet have a tie (met, warmth). Encounters, episodes and kept or
  broken promises move it. It shapes whom somebody approaches within a firm,
  how a room and a conversation read, and whether staff have friends at work.
  The first version warmed a tie on every pleasant chat and cooled one only in
  a bad mood, which was rare: over half the pairs who met became friends, and
  0–3 ties per world ever soured. Now a chat moves a tie a quarter of the time
  either way, and a falling-out is an event (`relationship.soured`), counted
  as friction.

### Calibration, and a monthly base rate is a hazard (WORLD-0014)

The interim trial (3 seeds × 60 days, on the signal work as first written)
showed calibration working. Jev's late share went from 0.14 to 0.35, days
late from 4.5 to 5.7, and the cafe's peak from noon to 8am, in band on every
seed. It also caught asking everyone monthly. Jev renewed a customer who fully
trusted the vendor at P = 0.56, and let a content, paid employee resign at
about P = 0.10: 41% of subscribers and 8.7% of staff were lost a month. A
small monthly base rate is now a rule hazard, keyed by subject and month:

- staff quit at their industry's JOLTS rate (4.0% cafe, 2.0% otherwise);
- subscriptions lapse at 1% (SaaS Capital);
- only people something pushes are asked.

Other fixes from the same trial:

- **Disputes.** "Larger than expected" is relative to the payer's last bill
  from the firm. A fixed $2,000 had put two thirds of bills over it, and Jev
  queried most of those.
- **Lapses.** A lapse is quiet. It is not news that the vendor is in trouble.

### The prompt laboratory (`py/scripts/prompt_lab.py`)

Every model call in jeve is a typed question about a state, so a wording can
be scored without a label, on real states from finished worlds (decisions keep
their facts):

- **fit:** the mass on "something else";
- **persona:** the same state with a trait set low, then high;
- **situation:** the same state with one fact moved;
- **stability:** an irrelevant field added;
- **validity:** replies that parse.

The search is DSPy's propose → evaluate → select. Candidates come by hand and
from a proposer model (Claude Opus 5.5) shown the scores so far. It runs on
jeve's own gateway, since DSPy's calls would bypass `jeve.llm`, and selects on
a dev split. The winner then faces a held-out split, a world-level A/B, and
the blind judges (EVAL-0001). Outputs are in `ops/evals/prompt-lab/`.

| Experiment | Result | Kept? |
| --- | --- | --- |
| **Audit of Jev on all 29 sets** (`audit`) | Stable: an irrelevant field moved answers by 0.005–0.05 (TV). Persona directions right (diligence → answer now +0.50, patience → dispute −0.22). Payment and career reasons fit after rewording (other 0.03, 0.003). Firm-level judgements showed order bias: reversing options moved them by 0.09–0.14 TV. | finding |
| **Judgements over every rotation** (`orders`, DECIDE-0007) | Reversal flipped 11–22% of firm-level verdicts. With every cyclic rotation averaged in one request, a verdict under an order never seen disagreed in 3.7% of 350 states, against 6.9% for a single order: supplier 18% → 2%, engineering allocation 12% → 2%, dispute resolution 7% → 0%. Founder review and credit did not improve (near-ties). | kept |
| **Typed reason lists** | Why a bill is left: other 0.60 → 0.02 with "not due" and "routine" (17 → 0 of 24 states reaching for it). Why someone resigns: 0.24 → 0.07 with Pew's reasons, asked as a supposition. | kept |
| **Tier-1 system prompt search** (`tier1`) | Best of 12 candidates, on held-out states: press by outspokenness +0.10 → +0.15, small talk by sociability +0.12 → +0.32, done by length −0.04 → +0.08. In the world (6 seeds × 14 days): persona gradients rose (press +0.18 → +0.25, small talk +0.19 → +0.39), but episodes settled less (0.88 → 0.71), stalled more (0.015 → 0.077) and cost 22% more. Judges preferred it 0.40 (Luna) and 0.44 (Haiku). | **rejected**: the prompt named the regularities the objective measured (Goodhart), and the independent measures disagreed |
| **Prompt ablation** | The contrastive device alone ("picture this person's opposite") gave half the gain without naming targets (objective 0.22 → 0.38). Untargeted effects (upset → less small talk, a friend → more) did not move beyond run-to-run noise (±0.04). | finding |
| **Role words over a bill** | The creditor was told "their work is held up": the outage's words. Now it is owed the money and the payer's firm owes it. Stake acts rose: a creditor pressing 0.18 → 0.23 (tier 1), a payer promising 0.20 → 0.24 (Jev). Neither model presses harder for a bill weeks late than days late. | kept (correctness); lateness is a blind spot |
| **Tier-1 model choice** (`models`, held-out states) | Objective: GLM 0.26, Gemini 3.8 Flash 0.59, DeepSeek V4 Flash 0.55 (P(done) 0.37, 21 s/call), GPT-5.6 Luna 0.53 (4.9 s/call), Qwen 3.8 Flash −0.16 (24 failures, 53 s/call). | finding |
| **Model A/B in the world** (6 seeds × 14 days vs GLM) | **Luna:** press +0.16 → +0.28, small talk +0.16 → +0.29 in the world's own routed decisions. Settled unchanged (0.81), stalls not clearly different, +0.17 rounds, cost +30%. Judge (Haiku) 0.46. **Gemini:** small talk +0.45, stalls → 0, cost ×9. Judges 0.40 (Haiku) and 0.44 (Luna). | not adopted: no judge preference (EVAL-0001); Luna is the leading candidate |

What the laboratory learned:

1. **A proxy objective is Goodharted even when it holds out-of-sample.** The
   tuned prompt beat the incumbent on held-out states and in the world on
   exactly what it was tuned for, and lost on what it was not: closure, cost,
   and the judges. Only the independent instruments caught it.
2. **Persona flattening is a property of the model more than of the prompt.**
   Luna and Gemini keep persona under the incumbent prompt, and GLM does not.
   A model changes behaviour without telling the model what to do.
3. **The pairwise judge cannot see persona, and seems to reward brevity.**
   Every challenger that lengthened conversations (by 0.17–0.43 rounds) was
   mildly dispreferred. The one that shortened them overnight was preferred
   36/48. Persona is a between-person property: a judge comparing two single
   episodes never sees a quiet person beside a loud one in the same moment.
   The instrument that would decide Luna is a persona-aware judge: two
   episodes with the same situation and contrasting people, asked which cast
   is more distinct and believable.
4. **Judgements have position bias; propensities absorb it.** Rotations
   remove most of it at one call per decision.
5. **Lateness does not reach conversation acts.** For Jev and tier 1 alike,
   a bill weeks overdue is pressed no harder than one days overdue. Lateness
   works through `payment.timing` and chasing instead.

### Reproducibility

The local Docker Postgres (OrbStack) slept with the lid closed. A native
Postgres 18 cluster in C collation, as CI's alpine image, ran everything
after that:

- The rules twin at e9a8c2b gave **identical** event-log digests on both
  clusters, on all three seeds.
- Worlds with model calls diverged only where a call was not in a cassette
  and was re-asked live (2–3k of ~23k per 60-day world).
- The ties table's pair check compared under the database's collation. On an
  `en_US` macOS cluster it rejected a pair Python ordered the other way. It is
  `COLLATE "C"` now, which production (glibc `en_US`) needs as much as CI
  (musl).

## Third session: instruments that can see, the person from Jev, and the bar

The brief set a bar and asked for research towards it:

1. Every banded prior is in band on every seed, for the rules twin and for
   production, and no soak invariant fails on any seed.
2. Production beats the world before this PR (e9a8c2b) on the paired contrasts
   that matter, with intervals excluding zero, and loses clearly on nothing.
3. Both validated judges prefer after over before, Wilson interval clear of 0.5.
4. Persona survives: world-level gradients at least as strong as Jev's own.
5. Every figure comes from committed JSON that can be regenerated.

Each idea went hypothesis → dev A/B → held-out → keep or revert. Negative
results are kept here beside the kept ones.

### The judge prefers short accounts (EVAL-0003)

Every challenger that lengthened conversations had been mildly dispreferred.
`judge-validate` now plants a length-only variant: an episode against itself
with one unremarkable exchange added before its last round. Neither judge was
indifferent. On 20 pairs from the rules-twin trial worlds, Luna chose the
shorter copy 0.88 of the time and Haiku 0.93. That is as strong as their
preference for a clean record over a broken one
(`ops/evals/judge/0-validation*.json`).

Arms are now compared only on episodes of the same shape: stake, rounds and
people. Re-judged that way, the earlier rejections stand. Haiku gave Luna
0.43 [0.35, 0.51] over GLM, and gave Gemini 0.50 while Luna gave it 0.46.
The tuned tier-1 prompt got 0.43 and 0.50. So length did not explain those
results.

### A judge that can see persona (EVAL-0004)

Persona is a difference between people, and a judge reading one encounter at
a time cannot see it. The persona judge shows one real moment twice: the
person deciding is described once as outspoken and sociable and once as
quiet and reserved, and each version shows what that person did. On planted
defects, where both versions do the same thing (*flattened*) or each does
the other's act (*swapped*), Luna caught 0.975 and Sonnet 5 caught 0.95.
Haiku caught 0.61, mostly following position, so it is not a persona judge
(`ops/evals/judge/0-validation-casts*.json`).

### The person from Jev, the conversation from the LLM (DECIDE-0008)

On the same routed decisions, Jev's persona gradients were about twice
GLM's. Luna kept more persona but cost 30% more, and the ordinary judge did
not prefer it.

The transplant asks the LLM about the average person in the situation, and
asks Jev about this person and the average person. The LLM's answer is then
moved by Jev's ratio between the two. The laboratory
(`transplant.json`, held-out states) showed GLM's gradients rising to Jev's
level while P(done) stayed GLM's. The persona judge (`casts.json`, 60
held-out moments × 2 draws) preferred transplanted acts over GLM's: Sonnet
0.62 [0.53, 0.70], Luna 0.57 [0.48, 0.66]. It preferred them over Luna's too,
at 0.56 [0.48, 0.65] (Sonnet).

The first world A/B moved every routed answer by Jev's ratio, and was
**rejected** (six 14-day dev worlds). Persona rose (press 0.16 → 0.31, small
talk 0.19 → 0.29), but moving the judgement "has this person had their say?"
lowered P(done). Conversations settled less, 0.84 → 0.72, and ran a third of
a round longer. The kept version moves only propensities. It kept the persona
gain (press 0.16 → 0.32, small talk 0.19 → 0.27, where Jev's own on the same
decisions were 0.39 and 0.38) and closure improved: stalls 0.042 → 0.006 and
rounds 1.38 → 1.21, both clear. Cost did not change, and the ordinary judge
at equal length gave 0.55 with both judges.

It cost one thing on the scorecard. The identifiability ratio fell from 38 to
31, clearly. Distinctness between people did not change (0.238 → 0.232). What
rose was each person's variety of topics over time (retest JSD 0.147 → 0.183),
as more news travelled.

### What the instruments found wrong with the world

- **A filled desk was hired for again.** The vacancy query compared person ids
  as text. `account_manager.24` sorts before `account_manager.7`, so one firm
  hired four account managers in four weeks for one departure.
- **Colleagues were told it was none of their business.** Only one vendor
  person holds an outage, so a support lead in the room was told their own
  firm's outage was "not their problem either way". The persona judge's
  renders showed it.
- **Twenty days of cash read as plenty.** Cash had two bands, and Jev gave
  0.000 to cash flow as the reason for every late payer above 14 days. The
  middle band ("enough, but not much to spare") sits below JPMorgan Chase
  Institute's median buffer of 27 days.
- **The firm owed money was told it had cash "to pay it".**
- **Two invariants miscounted.** "Every week has friction" ignored creditors
  chasing late bills: one quiet week held sixteen chases. "Support is still
  hearing from people" counted tickets only, so an outage raised in person
  with an engineer read as silence.
- **Monthly rates were drawn every 28 days**, thirteen times a year, which
  put quits and lapses about 9% high.

### Calibrating the rules twin

The rules twin paid most bills on the due date. Its pressure was set on six
dev seeds (20261240–45), with the trial and confirmation seeds untouched:

| measure | result | cited target |
| --- | --- | --- |
| late share | 0.40–0.51 | Atradius: 0.43 |
| days late | 5.3–6.6 | Xero: 7.8 |
| cash flow share of late bills | 0.30–0.43 | Atradius: 0.35 of mentions |

### Turnover cannot pass on every seed

Over 60 days, one departure among 24 staff reads 0.021 a month and two read
0.042, on either side of the band's 0.035 ceiling. `scripts/band_power.py`
computes the chance exactly, using the world's own quit rates and the heads
who never quit. A world with nothing pushing anyone passes on one seed with
probability 0.77, on three seeds with 0.45, and on six with 0.20
(`ops/evals/band-power.json`). Even at 180 days six seeds pass only 0.69 of
the time. The bar's turnover condition is a lottery at this scale, and the
band is not widened to hide that.

The final seeds drew badly. The hazard predicts 0.92 departures a world. Six
final worlds drew 10 between them, a draw of probability 0.053. Eleven dev
worlds drew 13, which is unremarkable (P(≥13) = 0.22). The world is calibrated
in expectation, and the misses are the draw. The draw is keyed by person and
month (CORE-0009), so a person reads the same uniform in every arm. A pushed
person's threshold moves only by the relative risk they are judged to carry.
Jev's worlds lost exactly as many people as the rules twin's on all six seeds.
Production should therefore miss turnover on 20261203, 20261301 and 20261303
as they did. The seeds were fixed
before the trial, and choosing others would be choosing the result.

### Lateness reaches the chase, not the conversation

The second session's lab found that neither model pressed harder in
conversation for a bill weeks overdue. Before spending on that, I measured
where lateness reaches a decision in finished worlds, using six seeds per arm
(`scripts/lateness_world.py`, `ops/evals/prompt-lab/lateness-world.json`):

| days late | Jev P(chase) | rules P(chase) | invoice conversations (Jev / rules) |
| --- | --- | --- | --- |
| not yet | — | — | 260 / 876 |
| 1–3 | 0.30 | 0.38 | 96 / 276 |
| 4–6 | 0.26 | 0.44 | 0 / 22 |
| 7–9 | 0.41 | 0.47 | 0 / 0 |
| 10–20 | 0.36 | 0.61 | 0 / 0 |
| 21+ | 0.39 | 0.94 | 0 / 0 |

- **The conversation blind spot has almost no support in the world.** Of 1,730
  decisions in conversations about a bill, 22 concerned one more than three
  days late. Street firms owe each other few bills, and those that go late
  are paid within days. Outside clients owe most late bills, and they are
  never in the room. Closing the gap in conversation would change nothing a
  world can measure, so it was not pursued.
- **Chasing is where lateness matters, and Jev does not read a bill's age at
  all.** The world asks daily from a week late, and again a week after each
  chase, so a bill still being asked about at three weeks has mostly been
  chased already. `times_chased` is in the decision's facts, but the question
  never says so. `prompt_lab.py lateness` asked 30 held-out bills at 7, 14,
  21 and 35 days late (`ops/evals/prompt-lab/lateness.json`). The keep rule
  was set before the run: the age gradient must beat the incumbent's with a
  paired interval clear of zero, and the first ask must move by less than
  0.05.

  | wording | P(chase) at 7 / 14 / 21 / 35 days | gradient | first ask vs incumbent | kept |
  | --- | --- | --- | --- | --- |
  | incumbent ("more than a week" … "more than a month overdue") | 0.68 / 0.67 / 0.67 / 0.67 | −0.01 | | |
  | + chase history ("they have chased it twice, …") | 0.52 / 0.67 / 0.67 / 0.65 | +0.13 | −0.16 | no |
  | + history, never chased | 0.53 / 0.51 / 0.51 / 0.52 | −0.01 | | |
  | the age as a count ("35 days overdue") | 0.70 / 0.69 / 0.68 / 0.68 | −0.02 | +0.01 | no |

  Both hypotheses are rejected. The history wording's "gradient" is a drop at
  the first ask, where "they have not chased it yet" reads as a reason to
  wait. It is not escalation. A count of days moves nothing. Jev judges this
  question on the person and the cash, and age plays no part. If age is to
  matter, it has to be structural. The pattern would be WORLD-0014's: a
  dunning cadence set by rule from credit-control practice, with Jev judging
  how the situation moves it. That is a design change for its own record and
  PR, not a wording.
- **Thin cash: the words answered the question** (`prompt_lab.py cash`,
  `ops/evals/prompt-lab/cash.json`). Over 2,682 asked decisions in six
  worlds, Jev gave cash flow as the reason for leaving an overdue bill 0.54
  of the time when cash was tight, 0.036 when thin (14–30 days, where the
  median small business sits: JPMorgan Chase Institute, 27 days) and 0.000
  when comfortable. The thin band's words begin "there is enough cash to pay
  it". I asked 30 held-out overdue bills at each band, under three wordings:

  | wording | P(cash flow) tight / thin / comfortable | thin, change | P(pay today), thin |
  | --- | --- | --- | --- |
  | incumbent | 0.69 / 0.057 / 0.000 | | 0.32 |
  | `thin`: "cash is thinner than they would like; paying this would take a fair bite out of it" | 0.69 / 0.63 / 0.000 | +0.58 [+0.50, +0.66] | 0.26 |
  | `weeks`: the runway itself ("two to four weeks of cash in hand") in every band | 0.59 / 0.12 / 0.003 | +0.06 [+0.02, +0.11] | 0.24 |

  Both pass the pre-registered lab rule. They disagree about what a thin
  buffer means. Told the plain fact, Jev mostly still says "routine". Told
  it feels thin, Jev treats it almost like tight. The world decides between
  them. The measure is the cash-flow share of late bills, which sits at the
  floor today (0.17–0.28 against 0.20–0.50, Atradius 0.35), together with
  late share and days late. A share pushed past 0.50, or late share out of
  band, would reject `thin`. That A/B changes the world, so it belongs in the
  follow-up PR.
- **A bill not yet due is described in conversation as "falls due today".**
  `Stake.days_late` is floored at zero (it has been since #14), so a bill due
  in two days reads as due today. This is left for the same follow-up PR,
  because it changes wording and so the recorded calls.

### Where the bar stands

- **Rules twin (final, six seeds):** every band holds on every seed except
  turnover, which missed on three. No invariant failed.
- **Jev alone:** the same, except that cash flow fell under the band on one
  seed. Jev gives cash flow for a payer whose cash is thin 0.02–0.03 of the
  time and "routine" 0.88–0.94. The middle band corrected the wording but did
  not move Jev. The lab has since found a wording that does (+0.58 on
  held-out states, above). It waits on a world A/B in the follow-up PR.
- **Persona (bar 4):** met in log-odds and not in probability. It reached 84%
  and 70% of Jev's own gradients on the same decisions, because GLM's
  average-person baseline for pressing and chatting is lower than Jev's.
- **The production world, the before/after contrasts and the judges:** not
  finished. The OpenRouter account behind the key ran out of credits during
  the final trial, and every routed world halted with a 402 between day 18
  and day 32. Production shares the account and will wait at its next live
  call (SIM-0003). `scripts/evals.py run --resume` carries a halted world on
  from its last committed tick.
