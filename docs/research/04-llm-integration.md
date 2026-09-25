# 04 — Where a general-purpose LLM could make jeve more real

Researched 2026-09-24, for the question "add general-purpose LLMs where they
measurably help, without undoing the typed thesis". It extends
`01-prior-art-mapping.md` (Concordia, Smallville, workbench at source level) and
`02-validation.md`; it does not redo them. What was then built and measured is
`docs/ops/llm-integration.md`; the numbers are `ops/evals.md`.

**Evidence tags.** `[V]` I read it on the primary page myself today. `[A]`
reported by a research agent with a URL or `path:line`, not re-checked by me.
`[U]` my inference. Two agents did the reading — one over `~/projects/workbench`
(read-only), one over the 2025–26 literature — and I spot-checked the three
figures the plausibility bands rest on (§5), all of which held.

---

## 1. What jeve already has, checked in the code

| Seam | State | Where |
|---|---|---|
| Tier 1 — an uncertain medium/high-stakes Jev answer re-asked of a flash LLM in Jev's typed shape | Built. Off by default; `shadow` records both, `live` acts for named sets. Low-stakes sets never escalate; a propensity (P) only at high stakes; 5% of yesterday's decisions a day | `decide/escalation.py`, `jev_policy._second_opinions` `[V]` |
| Tier 2 — prose for a reader | Built: `GET /encounters/{seq}/dialogue`, rendered on click, never read back | `gen/dialogue.py` `[V]` |
| Tier 2 — ontology-gap proposals | Built: counting is SQL; `--propose` asks a model, writes `ops/ontology-gaps.md` for a person | `gen/ontology.py` `[V]` |
| Judge panel — three families answer cached contexts, agreement with Jev | Built, never run live | `sim/panel.py` `[V]` |
| Shadow arm for the episode docking gap | Built: the episodes-off arm records each encounter's shadow stake, and `ops/episodes.md` splits the gap into selection (+0.03) and resolution (+0.33) | `sim/episode_study.py` `[V]` |

So the first thing tonight did not need to build a way in: a flash LLM can
already answer any of jeve's typed questions, and its answer is cached, replayed
and priced like Jev's. What was missing was a way to tell whether it *helps*.

## 2. Workbench: what to port, as ideas `[A]`

From a read-only survey of `~/projects/workbench` (paths in the agent's report).

- **The referee.** Workbench's game master makes zero model calls: every
  proposed action is a typed intent, resolved against world state or rejected
  with an enum reason; 44 rejection sites, 28 tests. Its hardest-won lesson is
  that engine errors must never become world data — a pydantic error surfaced
  as an importance-10 memory once made the firm invent a platform outage
  (7.12% of events). *Ported*: `sim/personas.py` compiles an LLM reply through a
  referee that accepts only enum levels for known ids and counts every rejection.
- **Code owns what is graded; the LLM owns texture.** Load-bearing facts are
  code constants in workbench, by decision. This is jeve's thesis from the other
  side, and the admission test used for every role below.
- **The director is rules, not a model.** Client stirs are a seeded, capped
  schedule keyed by (day, entity); the model only writes what the client says.
  Nothing in workbench argues for an LLM authoring *when* the world happens.
- **GEPA-style prompt optimisation did not generalise.** Four runs; the
  train-best instruction produced a degenerate day, another quoted the scenario;
  "only measured text ships". Two seeds were too few to separate candidates.
- **Measurement laws.** L14 (a check that cannot fail is not a check — only
  mutation finds these), L15 (a gate that documents a check it does not perform
  is worse than none), L16 (a gate that fails everything is unread). Fidelity
  bands are PASS/FAIL/ABSENT, and ABSENT is a finding. Its only LLM judge
  (`scripts/adjudicate.py`) is blind to code, sees full passages, and drops any
  split verdict.

## 3. What 2025–26 adds

### 3.1 Validation `[A]`

- Larooij & Törnberg, *Validation is the central challenge for generative
  social simulation* (AI Review, 2025): studies lean on face validity. Barrie &
  Törnberg (2505.23796): "emergent" conventions can be memorisation.
- SILICA (2608.28182): a perturbation arm and an anti-memorisation arm;
  swapping two options' order cost one model 58 points of cooperation. Option
  order is a *behaviour* key, not only a cache key.
- Replication with variance: an EPJ Data Science 2026 study ran 30 sims against
  30 real windows; Wu et al. (2506.19806) find under half of papers report
  variance, and simulated variance is usually too low.
- Signs, not magnitudes: Ashokkumar et al. (*Nature*, 2026) — LLM predictions
  of 70 experiments track real effects but overestimate sizes; Li & Ji
  (2604.02458) — optimising realism can *worsen* treatment-effect accuracy.

### 3.2 Judges `[A]`

- Position bias is systematic and worst when candidates are close (Shi et al.,
  2406.07791); *Reliability without Validity* (2606.19544; 21 judges) proposes a
  minimum protocol: both orders, report position bias, κ not raw agreement,
  reruns with the cache off, two benchmarks.
- Self-preference is familiarity (Panickssery et al., 2404.13076; Wataoka et
  al., 2410.21819): a different family reduces it but does not remove it.
- Planted defects first: FBI (2406.13439) — common judges missed over half of
  22 defect categories.
- Juries of small models from disjoint families beat one large judge (PoLL,
  2404.18796).

### 3.3 Architecture and cost `[A]`

- Keep the draw outside the model: LLMs describe distributions better than they
  sample from them (Meister et al., 2411.05403; Xiao et al., 2506.09998;
  *Illusion of Stochasticity*, 2604.06543). This is jeve's J/P/H design.
- Archetypes (Chopra et al., AAMAS 2025) and small distilled models (Oh &
  Gobet, 2608.05224: 0.6–1B matches 70B in distribution) are the cost frontier.
- Typed output: structured response protocols cut role-echoing from up to 70%
  to about 9% (*Echoing*, 2511.09710); format restrictions hurt reasoning in
  general LLMs (Tam et al., 2408.02442) — not Jev's case, but tier 1's.
- LLM economic agents are hyper-rational and too punctual (Yee & Koh,
  2602.01022; the digital-twin mega-study's "hyper-rationality", 2509.19088).

### 3.4 Memory, reflection, planning `[A]`

No evidence found that free-text reflection improves anything jeve measures.
Park 2023's reflection gain is on *interview* believability (29.89 vs 26.88
TrueSkill); EconAgent's "reflection" is mostly injected macro state; intrinsic
self-correction does not help (Huang et al., ICLR 2024). The best long-horizon
evidence is for explicit typed latent state (MF-MDP, 2604.05516: stable for
40,000 interactions against ~300). The one cost of stateless agents that shows
up in data is relational — fewer repeat interactions (the Voat replication).

### 3.5 Persona `[A]`

Individual fidelity is weak (digital twins r ≈ 0.20); LLM personas stereotype;
persona traits had no consistent effect on simulated belief updates (Pohl et
al., 2607.28347). Expect an LLM asked to write people to compress them toward
the agreeable middle.

## 4. Candidate roles, ranked by expected realism per dollar

The admission test for each: its output must be typed and validated before it
touches the world (the referee), and there must be a number that could come out
against it. Ranked *before* measuring, from §1–3; `docs/ops/llm-integration.md`
has what happened.

| # | Role | Why it might help | Why it might not | Cost | Built tonight |
|---|---|---|---|---|---|
| 1 | **Tier 1 answers a whole set** (`episode.round`) | The baseline shows Jev's conversations stall: 2% end settled, 42% repeat themselves. Same typed questions, different answerer: the cleanest test of "is Jev the cap here?" | design/005's most consequential line: sending propensities to an LLM collapses them and flattens persona | ~$0.01/sim-day | yes, and a one-question variant |
| 2 | **Tier 1 live** on uncertain medium/high-stakes answers | Built, cheap, the design's own first tier | Capped at 5% of decisions; nothing it touches is judged in episodes | ~$0.0005/sim-day | yes (arm only) |
| 3 | **Seed-time personas compiled to typed traits** | Role-coherent people instead of independent uniform draws | Literature: stereotyping, compression, hyper-rationality | ~$0.004 once | yes |
| 4 | Outside-world director compiled to typed shocks | State-responsive events (a dispute after a late bill) | Workbench kept its director as rules; LLM judges prefer narrative, which is not realism; shocks are ~1.5 a week, so an A/B needs months | ~$0.001/sim-week | no |
| 5 | Dialogue projection for episodes (tier 2) | Viewer-facing quality | Changes nothing in the world; LLM judges prefer fluency | per click | no |
| 6 | Typed reflection (belief deltas) | Memory shaping behaviour | Jev can already revise a typed belief (MEM-0003); no evidence free-text reflection helps (§3.4) | per person-day | no |
| 7 | Morning plans | — | Would reword `agent.tick`, 97% of cost | high | no |

The biggest plausibility gap found (§5) is not an LLM role at all: jeve's bills
are paid almost exactly on time because four fifths of clients auto-pay on the
due date (`AUTOPAY_ABOVE = 0.2`). That is a rules calibration, named here so it
is not mistaken for something a model should fix.

## 5. Priors for the stylized facts

The bands in `py/src/jeve/evals/priors.py` come from these. Three were
re-checked on the primary page today; the rest are the agent's.

| Fact | Prior | Source | Tag |
|---|---|---|---|
| Share of B2B invoice value overdue (US) | 43% overdue, 52% on time, 5% bad debt | Atradius Payment Practices Barometer US 2025 | `[V]` |
| Mean days late, small-business invoices | 7.8 (US); 4.5–9.7 across five countries | Xero Small Business Insights, Dec quarter 2025 (published 2026-03-02) | `[V]` |
| Cafe's busiest hours | 8–10am (US) | Square POS data via Sprudge, 2018 | `[V]` |
| Cafe's busiest hour (UK) | 10–11am | Square UK Coffee Report 2018 | `[A]` |
| Days past due when overdue B2B invoices are collected | ~20 | Atradius US (edition unclear) | `[A]` |
| Ticket resolution, median account | 8h17m business hours; tiers 32 min–36h | Freshworks CS Benchmark 2024–25 | `[A]` |
| Tickets escalated to engineering | no primary source | — | — |
| SMB SaaS monthly logo churn | 2.2%–6.1% by ARPA | ChartMogul 2022 | `[A]` |
| Monthly quits | 1.2% (financial) – 3.5% (food service) | BLS JOLTS, July 2026 | `[A]` |
| Staff who look to leave after pay problems | 24% after one, 49% after two (stated intent) | Workforce Institute, 2017 | `[A]` |

Every one is a practitioner survey or platform statistic, and jeve is four
firms: the bands are a plausibility envelope (02 §3.6), the lowest rung.
