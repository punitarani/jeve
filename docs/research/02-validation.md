# 02 — Validation: how do we know it isn't a screensaver?

The literature survey behind this document was gathered by a research agent on 2026-09-20.
**Provenance tags:** `[E]` established practice with a citation; `[P]` proposal (the agent's or
mine — nothing in the literature does this for a society of agents); `†` the agent cited the
identifier from memory without re-fetching it. I know most pre-2026 citations independently
and spot-checked three others: Larooij & Törnberg (confirmed: arXiv 2504.03274, published in
*Artificial Intelligence Review* 2025; 35 papers; "many studies relying solely on subjective
assessments of model 'believability'"), Vending-Bench (confirmed: arXiv 2502.15840), and the
Concordia Contest report arXiv 2512.03318 (**not confirmed by my search**). 2026-dated arXiv
ids other than those are unverified by me.

---

## 1. The blunt version

jeve has no real-world dataset to fit. That rules out the only kind of validation the
literature treats as strong. Concordia's own paper ranks evidence in a hierarchy borrowed
from medicine — real-world effectiveness at the top, "consistency with prior theory" at the
bottom — and says plainly that "no amount of sensitivity analysis can substitute for a test of
generalization" `[E]` (arXiv 2312.03664). jeve cannot run that test.

**What jeve can defensibly claim**

1. **Verified.** Ledger and world-state invariants always hold.
2. **Internally causal.** "In jeve, an outage of duration D at state S changes missed billing
   by Δ [CI] against the exact counterfactual." A simulator permits cleaner identification
   than any observational study — about the model, not the world.
3. **Non-degenerate** relative to explicit null models, across seeds, up to the tested horizon.
4. **Robust, claim by claim**, to seed, decision-model version, question wording, tick size.
5. **Plausible** against a handful of stylized facts — the lowest rung, and contaminated
   wherever a model has read the textbook.
6. **In agreement with** a judge panel on decision probabilities. Agreement, not accuracy.

**What it cannot claim:** predictive validity; that personas represent real lawyers or
accountants (they are stereotypes — LLM personas flatten and misportray groups, arXiv
2402.01908 `[E]`); effect *magnitudes* (LLM simulations predict signs well and overstate sizes,
Manning/Zhu/Horton arXiv 2404.11794 `[E]`); **"emergence", unless the effect beats a null
model**; stability beyond the horizon actually run.

That last pair matters most. Gode & Sunder (1993) showed zero-intelligence traders reach
near-100% allocative efficiency: market *structure* alone produces rational-looking
aggregates `[E]`. jeve's design deliberately moves emergence into interaction structure
(01 §4), so without null models every cascade we show is open to "the rules did that, not the
agents." The honest label is: *a verified, non-degenerate, causally responsive,
plausibility-checked toy economy.*

**What critics say is wrong with current practice** `[E]`: Larooij & Törnberg review 35
generative-ABM papers and find validation "poorly addressed", many relying solely on
believability, and "even the most rigorous validation failing to adequately evidence
operational validity" (the agent reports the split as 15 of 35 solely subjective, 22
primarily). LLM judges overrate quality (arXiv 2403.08715) and prefer their own outputs
(arXiv 2404.13076). Bisbee et al. show compressed variance, prompt sensitivity, and
*different results from the same prompt three months later*. Most macro matches are
direction-only and from single runs.

---

## 2. What the literature does, by level

| Level | Practice `[E]` | Weakness | Use in jeve |
|---|---|---|---|
| **Micro** — is an agent believable and consistent? | Smallville: each agent interviewed (25 questions, 5 categories), full architecture vs. 3 ablations vs. human-authored, 100 raters, ranks → TrueSkill (29.89 vs 21.21, d = 8.16). Argyle: four algorithmic-fidelity criteria. Park et al. 2024: accuracy normalised by each human's own 2-week retest. Persona-drift measures (arXiv 2402.10962: drift within 8 turns). | Subjective; judge bias; needs a human reference population jeve lacks. | Interviews apply only to rendered prose. Run them **in a fork** so probes never enter agent memory. |
| **Meso** — interactions | Smallville: information diffusion (4% → 32%, 4% → 52%), every knowledge claim checked against the memory stream (1.3% hallucinated), network density 0.167 → 0.74. OASIS: cascade scale/depth/breadth vs. 198 real propagations. Taubenfeld: debating agents converge to the model's bias regardless of persona. | Descriptive; null models rare; diffusion is nearly guaranteed by design. | Fully applicable — **computed on the transaction graph, not on chat.** |
| **Macro** — stylized facts | EconAgent: Phillips/Okun *signs* vs. rule-based and RL baselines. TwinMarket: four financial stylized facts vs. real data with ablations. LLM beer game reproduces bullwhip. | Underdetermination (Windrum/Fagiolo/Moneta 2007: many models reproduce the same facts); contamination; "stopped clock" — right endpoint, implausible path. | A plausibility envelope only. Prefer facts that are not scripted into exogenous inputs. |
| **Causal** | Manning/Zhu/Horton: structural causal model specifies hypotheses, agents, experiment, analysis. Concordia: an intervention shows "A causes B *in the model*". | In-model only; magnitudes inflated; framing can move outcomes by tens of points (TRAILS, arXiv 2605.18890†). | **jeve's strongest asset** — exact counterfactual forks. |
| **Robustness** | Sargent's internal validity; Secchi & Seri: most ABM studies are underpowered, with run-count formulas; ten Broeke: OFAT, regression, and Sobol each reveal different things. | Rarely done. | Per claim, not per model. |
| **Operational, long-horizon** | Vending-Bench: every model had runs that derailed — misread state → tangential "meltdown" loops; failure timing uncorrelated with context fill; *"without the pressure of a recurring cost, the model appears to get stuck in loops, waiting for the next day."* Project Vend: identity crisis, hallucinated accounts, talked into discounts. Smallville §7.2: memory growth degrades retrieval; norm misclassification; over-cooperation. | **No society-level degeneracy metric exists in this literature.** | §3 is therefore mostly construction, and is marked as such. |

Classical canon, and what transfers `[E]`: Sargent 2013 (conceptual validity, verification,
operational validity, data validity; techniques: traces, **extreme-condition and degenerate
tests**, internal validity, sensitivity, Turing tests; validity is always relative to a
pre-stated purpose and accuracy range) — transfers almost whole. Pattern-oriented modelling
(Grimm 2005: several patterns at several scales at once) — transfers as the envelope.
Docking (Axtell 1996) — transfers: dock against a rule-based twin. Werker–Brenner,
history-friendly modelling, simulated moments — **do not transfer**; there is nothing to fit.

---

## 3. Instrumentation and test plan `[P]`

Thresholds are starting defaults. They are recalibrated against the null-model runs (§3.6)
and the first healthy sim-week.

### 3.0 Prerequisites — these constrain the architecture

- Event-sourced log: tick, agent, role, persona, decision kind, context hash, distribution,
  PRNG key, draw, outcome, world-state delta (ADR-007, ADR-009).
- **Forkable snapshots.**
- **Counter-based PRNG keyed by (seed, agent, decision index)**, so decisions untouched by an
  intervention draw identical random numbers in both branches — common random numbers, a
  standard variance-reduction technique `[E]`. workbench's `derive_rng(seed, *path)` is
  exactly this (00 §6.5).
- **The live run is n = 1.** Every statistical claim comes from headless, time-compressed
  replicas forked from snapshots — which cost real money (ADR-003 budgets for it).
- A fixed **canary suite** of ~200 recorded decision contexts replayed daily against the
  pinned Jev version to catch silent model drift. TypeSafe's aliases move without notice
  (00 §1.5); Bisbee et al. is the evidence this happens.

### 3.1 Hard invariants — halt on violation

Double entry (debits = credits per transaction); stock-flow consistency (total cash = initial
+ exogenous sources − sinks); no negative inventory; no negative cash without an explicit
credit line; referential integrity (payment → invoice → engagement/order; ticket → licensed
customer); temporal order (work → invoice → payment); capacity (billed ≤ worked ≤ available
hours); work-item conservation (opened = closed + open); crash-recovery idempotence; **an A/A
fork with the same seed yields Δ exactly 0.**

Sargent-style degenerate tests, run in CI against a headless world: arrivals > service ⇒
backlog diverges; zero cafe customers ⇒ zero revenue; permanent outage ⇒ tickets explode.

### 3.2 Liveness and degeneracy — the §5 failure modes, one detector each

| Failure mode (brief §5) | Detector | How computed |
|---|---|---|
| **Everyone idles** | Idle fraction, and **idle-with-backlog** — idle while the agent's own queue is non-empty. The second is the real bug signature. | Share of scheduled working ticks. |
| | Normalised action entropy per agent per day | H = −Σ p̂ log₂ p̂ with Miller–Madow correction, ÷ log₂\|role action set\|. Also the entropy *rate* H(aₜ \| aₜ₋₁). |
| **Loops** | Distinct-n (n = 3–6); compression ratio | zlib ratio over 512-action windows ÷ median ratio of shuffles with the same marginals. |
| | No-progress periodicity | Period p ≤ 20 repeated ≥ 4× **with zero world-state delta** — daily routine is legitimately periodic and must not alarm. |
| | Dyadic ping-pong | Repeated exchange within one pair with zero state change. workbench hit this (200+ acknowledgment-only emails) and fixed it with depth caps. |
| **Convergence on one action / persona flattening** | Role information I(role; action) / H(action) | From the action log. |
| | Within-role pairwise Jensen–Shannon divergence vs. the shuffled-persona null | §3.6 N2. |
| | Persona-identity classifier | Multinomial logit on daily action-feature vectors, time-blocked CV, permutation p-value. Accuracy near chance = agents are interchangeable. |
| **Runaway agreement** | Acceptance rate of inter-org requests; **negative-event rate** (disputes, rejections, late payments, churn, escalations) | **A conflict-free economy is degenerate.** Smallville names over-cooperation; sycophancy is documented (arXiv 2310.13548). |
| **Economy freezes or explodes** | Per queue: L(t), λ, μ, ρ = λ/(cμ), Little's-law residual; stationarity tests on deseasonalised backlog†; money velocity; cash Gini/HHI; runway days; bankruptcies | **Cascades need finite slack**: if backlog is always 0 or ρ < 0.3, an outage cannot propagate — the scenario must be tuned so the orgs run warm. |
| **Drift over weeks** | JSD against the same-weekday reference window, per agent/role/population, with a permutation null; Mann–Kendall trend | — |
| **Hallucinated world state** (rendered prose only) | Grounding rate: every id, amount, or date in generated text must resolve against the ledger, as Smallville checked claims against memory | Must be ≥ 99%. Because prose never feeds back into state (01 §3), a failure here embarrasses the viewer but cannot corrupt the sim. |

**Every detector is mutation-tested.** Lifted from workbench's CI: "a gate that has stopped
refusing looks exactly like a gate with nothing to refuse." For each detector there is a
headless run with the failure injected (force all agents idle; splice a ping-pong; strip
personas) and the detector must fire. A detector that has never been seen to fire is not
instrumentation.

### 3.3 Interventional tests — the proof that named behaviours are real

For each named emergent behaviour in `docs/plan/scenario.md`:

1. **Pre-register** the hypothesis (e.g. "a month-end Invoicing outage hurts accounting-firm
   billing more than a mid-month one").
2. Fork the world at M states; run treatment (inject the outage) and control for H sim-days,
   K ≥ 30 seeds.
3. Per seed Δₖ = Y_treatment − Y_control for on-time invoices, DSO, missed billings.
4. Report mean Δ, bootstrap 95% CI, d_z = mean/sd, sign test.
5. **Noise floor:** A/A forks (different seeds, no treatment). The effect must exceed the
   95th percentile of that distribution.
6. **Dose-response:** 1h / 4h / 1d / 3d outages should be monotone.
7. **Path-blocking:** give the accounting firm an offline billing fallback — the effect should
   vanish. *If it persists, the causal story is wrong.*
8. **Negative controls:** an outage of a module nobody uses; a causally unconnected outcome.
9. Multiple-comparison correction across outcomes†.

An event study around outages that occur naturally in the live run is suggestive only.

### 3.4 Null models

| | Variant | Purpose |
|---|---|---|
| N0 | Random policy (uniform, and marginal-frequency) | Floor. |
| N1 | **Rule-based twin** (FIFO work, pay at due date) | The docking partner, and the Gode–Sunder test: what do the rules alone produce? |
| N2 | Shuffled / stripped personas | Does persona matter at all? |
| N3 | Context-blind: each decision kind uses its time-average probability | Does the *state* matter? |
| N4 | No-messaging ablation | Smallville-style. |

A phenomenon is "due to agent cognition" only if it differs from N0–N3 by more than seed
noise. Reported as a phenomenon × variant table. **N1 and N3 cost nothing to run** — no model
calls — which makes them the natural first check and a permanent CI fixture.

### 3.5 Calibration — what sampling does and does not validate

Sampling outcomes from Jev's stated *p* makes a reliability diagram of outcomes against *p* a
**plumbing test only**. It catches PRNG, clamping, and double-sampling bugs. It does not
show: that *p* is right; **resolution** (a constant base-rate forecaster is perfectly
calibrated — use the Murphy decomposition†); subgroup calibration by role or counterpart;
**joint dependence** (independent draws miss common shocks, and cascades live in the joint
distribution); **temporal coherence** (independent resampling every wake produces
flip-flopping — check run lengths); on-policy shift (label contexts the sim actually visits).

Reference labels, in order of trust: (1) human labels stratified by predicted-*p* decile,
two raters, Cohen's κ; (2) an LLM panel of ≥ 3 model families via TypeSafe's typed adapter
(00 §1.7), each judge answering M times, mean = reference *p* — TypeSafe's own docs recommend
exactly this for label-free threshold tuning; (3) empirical base rates as marginal anchors;
(4) **metamorphic checks**: monotonicity, paraphrase invariance, invariance to irrelevant
detail. (Not P(A) + P(¬A) = 1 — Jev's docs say outright that identity does not hold, 00 §1.3.)

Metrics: Brier and log scores (strictly proper); reliability diagrams; equal-mass debiased
ECE; classwise ECE for choices. **Reported as panel agreement, never as accuracy.**

Unknown that bears on this: TypeSafe does not document Jev's training labels. Its published
workflow evals use frontier LLMs as the reference. If RLCD labels derive from LLM judgments,
Jev inherits their flattening and agreeableness even though no LLM runs at sim time.

### 3.6 Stylized-fact panel (envelope only)

Cafe day-of-week and intraday seasonality — *but if scripted into the foot-traffic generator,
reproducing it is verification, not validation*. Bursty activity: burstiness
B = (σ − μ)/(σ + μ) on inter-event times (priority queues produce heavy-tailed waits,
Barabási `[E]`); with ~24 agents, report B and CV, **do not claim power laws**. Payment
delays: right-skewed, with a meaningful late share (the agent cites Xero 2026: US small
businesses paid on average 9.0 days late — practitioner source, unverified by me). Ticket
arrivals overdispersed relative to Poisson, with post-outage bursts. Variance amplification
along the dependency chain (bullwhip). Revenue concentration needs an exogenous client
population to mean anything.

### 3.7 Judge and human spot-checks

Sample random, metric-flagged, and intervention-window episodes. **Mix in null-model traces,
judges blind to condition** — if judges cannot tell the full model from random-policy traces,
either the judges or the model are uninformative. Rubrics: role consistency, grounding,
proportionality, excess politeness. Measure judge–human agreement before trusting judges.

### 3.8 Alert defaults

| Metric | Degenerate signature | Alert |
|---|---|---|
| Normalised action entropy | stuck near 0, or random near 1 | < 0.15 or > 0.95 for 3 sim-days |
| I(role; action)/H | homogenisation | < 0.1 |
| Idle-with-backlog | idle beside a non-empty queue | > 20% over a sim-day |
| No-progress cycle / compression vs. shuffled | looping | any cycle, or ratio > 2 |
| Same-weekday JSD | monotone drift | > 99th pct of null on 3 consecutive comparisons |
| Persona classifier | flattening | < 1.3× chance |
| Acceptance rate / negative events | runaway agreement | > 95% over 100 requests, or zero negative events in 5 sim-days |
| Any invariant | violation | **halt** |
| ρ / backlog slope | exploding or frozen | ρ > 1 for 3 days; ρ < 0.1 for 5 days |
| Money velocity | freeze or runaway | < 20% of reference, or > 5%/week growth for 3 weeks |
| Canary suite mean \|Δp\| | silent model drift | > 0.05 |
| Ontology-gap rate (01 §3) | typed vocabulary too small | tracked, not alarmed — it is the research result |

---

## 4. What lands in the MVP, and what waits

| MVP | After MVP |
|---|---|
| All hard invariants, halting | Stylized-fact panel |
| Entropy, idle-with-backlog, loop detection, role information, negative-event rate, queue ρ — on the dashboard | Persona classifier; drift tests |
| Mutation tests for each of those detectors | Judge / human spot-checks; interviews in forks |
| N1 rule-based twin and N3 context-blind, headless (free) | N0, N2, N4 with full seed counts |
| **One pre-registered interventional test end-to-end** (outage → accounting billing), K ≥ 30, with A/A noise floor and dose-response | Path-blocking, negative controls, robustness audit per claim |
| Canary suite against pinned `jev-1.13.0` | Calibration study against an LLM panel |
| M0: persona-sensitivity probe on workbench cassettes (00 §6.3) | — |

The interventional test is in the MVP on purpose. It is the difference between "we saw a
cascade once" and "the cascade is a property of the system", and it is the brief's own bar.

---

## 5. Bibliography

Known to me independently unless marked. `†` = identifier not re-fetched by the agent.
`(A)` = I have not verified this entry exists; 2026-dated ids postdate what I can check from
memory.

1. Park et al. 2023, *Generative Agents* — arXiv 2304.03442
2. Vezhnevets et al. 2023, *Concordia* — arXiv 2312.03664
3. Concordia Contest report — arXiv 2512.03318 (A; my search did not find it)
4. Argyle et al. 2023, *Out of One, Many* — arXiv 2209.06899
5. Aher et al. 2023, *Turing Experiments* — arXiv 2208.10264
6. Horton, Filippas, Manning, *Homo Silicus* — arXiv 2301.07543
7. Park et al. 2024, *Generative Agent Simulations of 1,000 People* — arXiv 2411.10109
8. Manning, Zhu, Horton 2024, *Automated Social Science* — arXiv 2404.11794
9. Li et al., *EconAgent* — arXiv 2310.10436
10. *OASIS* — arXiv 2411.11581
11. *AgentSociety* — arXiv 2502.08691
12. *TwinMarket* — arXiv 2502.01506
13. *CompeteAI* — arXiv 2310.17512
14. *Sotopia* — arXiv 2310.11667
15. Sargent 2013, *Verification and validation of simulation models*, J. Simulation
16. Windrum, Fagiolo, Moneta 2007, JASSS 10(2) 8
17. Fagiolo et al. 2019, *Validation of agent-based models in economics and finance*
18. Grimm et al. 2005, *Pattern-oriented modeling*, Science
19. Axtell et al. 1996, *Aligning simulation models* (docking)
20. Gode & Sunder 1993, *Allocative efficiency of markets with zero-intelligence traders*, JPE 101(1)
21. Larooij & Törnberg 2025 — arXiv 2504.03274; *Artificial Intelligence Review* 10.1007/s10462-025-11412-6 (verified today)
22. Anthis et al. 2025, *LLM social simulations are a promising research method* — arXiv 2504.02234
23. Wang, Morgenstern, Dickerson — arXiv 2402.01908
24. Bisbee et al. 2024, *Synthetic replacements for human survey data?*, Political Analysis
25. Taubenfeld et al. 2024, *Systematic biases in LLM simulations of debates* — arXiv 2402.04049
26. Backlund & Petersson 2025, *Vending-Bench* — arXiv 2502.15840 (verified today)
27. Anthropic, *Project Vend* 1 and 2
28. Secchi & Seri 2017, on statistical power in ABM studies
29. ten Broeke et al. 2016, on sensitivity analysis for ABMs, JASSS
30. TRAILS — arXiv 2605.18890 (A); SLALOM — arXiv 2604.11466 (A); LLM beer game — arXiv 2604.17220 (A)
