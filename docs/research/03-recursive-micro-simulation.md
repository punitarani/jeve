# 03 — Recursive micro-simulation: what exists, what is new, what to build

Researched 2026-09-22 against the tree at `78cb007`. Six literature strands were gathered by
research agents in parallel — classic multi-level simulation; LLM social simulation; games
and interactive narrative; social and organisational theory; recursive and multi-fidelity
methods; the 2025–2026 frontier. Their raw reports are in `03-strands/`. This document is
the synthesis, and the only part that carries a recommendation.

**Evidence tags.** `[V]` I read it first-hand this session: jeve's own tree, a GitHub source
file, or the DeepWiki index over one. `[A]` a research agent confirmed the identifier from a
search index or a GitHub-hosted mirror; the mechanism is as the agent reported it and I did
not re-check. `[M]` recalled from memory, unconfirmed. **Access caveat:** this session's
egress proxy blocked arxiv.org, Semantic Scholar, dblp, RAND, Springer, ACM and the ACL
Anthology, and the web-search budget ran out mid-survey. No 2026 arXiv paper was opened at
its source; every 2026 identifier is `[A]` at best. Re-verify before citing any of them
outside this repo.

---

## 0. The blunt version

**Does the concept exist?** In pieces, under at least six names, none of them ours:

| Piece of the idea | Closest existing thing | Tag |
|---|---|---|
| A running world spawns a bounded, finer-clocked sub-simulation of a few co-located agents and folds the result back | Concordia v1.8's `Conversation` component: after any event an LLM decides whether people spoke; a *separate* game master with its own memory and a clock that "will advance in higher gear during the conversation scene" runs it for ≤ 20 rounds; a one-sentence summary returns to the participants and the main game master. Removed in v2 (2025) and replaced by one ghost-written exchange, on cost. | `[V]` |
| Models within models, typed values only across the boundary | NetLogo LevelSpace (2015; JASSS 2020): a parent opens child models; "parents must ask their children to report"; only strings, numbers and lists cross. Its *Wolf Chases Sheep* example is structurally jeve's proposal: a co-location event spawns a finer child model, the parent pauses, a typed outcome returns. | README `[V]`; example `[A]` |
| Simulate at high resolution only where it matters, and stay consistent with the coarse model | Sunshine-Hill & Badler 2010, "alibi generation": a cheap "perceptual simulation" runs detail only where observed and is "statistically guaranteed … perceptually indistinguishable" from the full one. Equation-free multiscale computation (Kevrekidis 2003): *lift* → short micro burst → *restrict*. | `[A]` |
| Social interaction as a bounded, typed multi-party sub-game | Comme il Faut / Prom Week (2010–11): intent → accept/reject → effects → trigger rules that ripple to third parties. Versu (2014): "social practices" as reactive joint plans that frame, but never control, the agents. | `[A]` |
| A specification language for such an episode | Ostrom's action situation (2005): participants, positions, actions, information, control, costs/benefits, outcomes; McGinnis 2011 adds *adjacency* — one situation's outcome sets another's rules. Goffman's *focused gathering* (1961) gives entry, membrane and closing. | `[A]` |
| When to refine, on a budget | Nested Monte Carlo (Gordy & Juneja 2010; Broadie et al. 2011): spend inner effort on scenarios near a decision threshold; many situations × few rounds beats few × many. Multi-fidelity Monte Carlo (Peherstorfer et al. 2018): a cheap proxy helps only if it is highly correlated with the fine model *and* much cheaper. | `[A]` |

**What nobody has done.** Five agents searched independently and each reported the same
absences: a typed-only, non-generative multi-round group interior; nesting deeper than one
level; cache-sharing of canonicalised *group* situations; byte-identical replay with causal
provenance across levels; a per-encounter rule for escalating from a one-shot decision to a
richer episode; and — the one that matters — any measurement of whether intra-encounter
resolution changes macro outcomes. The nearest evidence is **negative**: Jang et al.
(September 2026) found sealed-monologue agents reach nearly the same final stance balance as
full multi-round debates `[A]`.

**Verdict.** The parts are old (Swarm's nested swarms with their own schedules are from 1996
`[A]`). The *combination* is new, and the defensible novelty is narrower than "recursive
micro-simulation": (a) typed, cacheable, replayable group episodes with causal ids across
levels; (b) resolution as a budget-governed dial with a *docked* cheap proxy, so the world's
base rates do not move when the dial does; (c) the interventional test of whether resolution
matters at all. The fidelity hypothesis is unproven and the best 2026 evidence leans against
it, so this is built as an experiment with a null model, not as a feature.

**Do first, in this order.** (1) A knowledge/belief store — MEM-0001 is accepted and
`py/src/jeve/memory/` holds only the record `[V]`; without it an episode has nowhere to
write except the one escalation rule. (2) The episode-versus-encounter A/B on the outage →
escalation → invoice timeline that `test_space.py` already measures. (3) The proxy docking
test: the one-shot encounter's marginal must match the episode's, or every study confounds
resolution with base rate.

---

## 1. The idea, stated so it can be tested

### 1.1 Three things get called recursive simulation

| | What runs | What the result is | Who does it |
|---|---|---|---|
| **Execution-time nesting** — *this proposal* | The live world spawns a bounded sub-simulation of a subset of its own entities at finer resolution | Committed: the sub-simulation *is* what happened | Concordia v1 scenes `[V]`, LevelSpace, GAMA `capture`/`release`, Total War battles `[A]` |
| Decision-time rollout | An agent runs copies of the world, or models of other minds, to choose an action | Advice, discarded after the choice | Gilmer & Sullivan's "recursive simulation" (WSC 1998–2005), MCTS, LLM world models (RAP, GDP-Zero), Hypothetical Minds `[A]` |
| Structural hierarchy | Agents composed of agents; a group is itself an agent | A level of description | Holonic MAS, Swarm, Repast's "recursive" (a philosophy of porous actors, no nested clock) `[A]` |

Jeve's idea is the first row. The second is worth a note: Jev is cheap enough that
decision-time rollouts of a typed world are affordable, and that is a separate research idea
(§8, R6). Do not conflate them; the literature does, and a search for "recursive simulation"
returns mostly the second.

### 1.2 What an episode is

Borrowing Goffman's *focused gathering* for the boundary and Ostrom's *action situation* for
the parts, an **episode** is:

| Part | In jeve |
|---|---|
| Participants | 2–6 people who are co-located now, or co-involved (an invoice between their firms, a ticket, a catering order), *ratified* — a bystander in the same zone is not a participant |
| Positions | Their roles, rendered as today under neutral slots (`person_a`, `person_b`) so identical rooms share a call |
| Local state | Typed, small, and *not* a re-read of the macro state: who has spoken, what has been raised, mood, tension, whether the matter is settled |
| Rounds | One typed question set per participant per round. Jev cannot chain inside a request, so a round is one request per participant, and rounds are sequential |
| Information | What each participant knows, from the relational memory MEM-0001 describes |
| Exit | A typed question ("is this settled? do they leave?") plus a hard cap; never a prose judgement |
| Outcome | Typed events that cite the episode, and the *only* way macro state changes: knowledge transferred, a commitment, a belief shift, an escalation, a mood |
| Adjacency | An outcome may open or schedule another episode (a meeting agreed at lunch); an episode may spawn a child with a subset (a side conversation). Depth is capped |

An episode is *not* a transcript. Prose stays a projection (GEN-0001). That is the one design
constraint no prior system shares, and it is the reason the cost, cache and replay claims are
plausible at all.

### 1.3 What jeve has today, measured

From the tree at `78cb007` and `ops/economics.md` `[V]`:

- An encounter is dyadic, zone-level, one tick long and one question set (`agent.tick`),
  decided from where everyone stands now, resolved, then everyone moves (WORLD-0003). Only
  the initiator's `interact`/`with_whom` is read; the other party is not asked. One
  consequence rule exists (`raise_outage` → `ticket.escalated`, once per incident). `topic`
  is recorded and, when it is `the_outage`, cites the incident; nothing else reads it. `mood`
  is written to `positions`.
- The five-day fixture: 5,823 decisions, 5,182 by model, 1,137 distinct calls, $0.0436.
  `agent.tick` is 4,200 of those decisions and 1,064 of the calls — 81% of decisions, 97% of
  cost — and shares least, because "who is here" varies. A distinct call averages ≈ 913 input
  tokens and ≈ $0.000038.
- The tick is a barrier and one transaction (CORE-0004, WORLD-0002). Code-only processes may
  sub-step inside a tick (ADR-001: the cafe queue); nothing with a model call does yet.
- Randomness is path-keyed by what it is about (CORE-0009); nothing is keyed by tick.
  Decisions are numbered per person by the engine.
- No knowledge, belief or commitment store exists. MEM-0001 is accepted; the package holds
  only the record.
- The control arm exists: `Engine(encounters=False)`, and `test_space.py` asserts that
  encounters change the invoice timeline and the event-log hash, and that an encounter
  reaches an invoice through `causes`.
- Scenario behaviours #5 (workaround divergence), #6 (diffusion through the cafe) and #7
  (churn bargaining) are all group-interaction shaped and unimplemented.

**So the encounter is already the cheap proxy.** The question is whether a multi-round typed
episode, in the situations where it is spawned, produces outcomes the proxy cannot — and
whether those outcomes reach money.

### 1.4 Where fidelity could come from, and where it cannot

Multi-round typed rounds add information only through three channels, and a design with
none of them is a screensaver by jeve's own standard (02 §1):

1. **Sequential dependence.** Round 2 sees round 1's typed outcome. Inside one Jev request
   that is impossible (questions are independent, 00 §0); across requests it is what an
   episode is. Whether it *changes* anything is the empirical question — Jang et al. say
   often not `[A]`.
2. **Group state.** Who has raised what, whether the vendor has already promised, how tense
   the table is. Think-Before-Speak (2026) runs exactly this as typed internal-state updates
   plus one arbitration per interval `[A]`.
3. **Richer outcomes that reach macro state.** Today only escalation and mood do. Knowledge
   transfer (scenario #6), commitments ("pay by Friday"), belief slots (trust, reliability)
   and referrals are the outcomes the theory says matter (§2.4), and none has a store yet.

Channel 3 is the load-bearing one. Channels 1–2 without 3 change nothing the economy can see.

---

## 2. What exists, by strand

Each table keeps the rows that bear on the design. The strand reports in `03-strands/` hold
the rest.

### 2.1 Simulations inside simulations: multi-level and multi-resolution modelling

| Work | Mechanism | Lesson for jeve | Tag |
|---|---|---|---|
| Swarm (Minar, Burkhart, Langton, Askenazi 1996, SFI WP 96-06-042) | A swarm is agents plus a schedule; swarms nest, are created and destroyed at run time, and are "used by agents as models of their own world" | Nesting with its own clock is thirty years old; the novelty is *ad hoc* formation | `[A]` |
| LevelSpace (Hjorth, Head, Brady, Wilensky; JASSS 23(1)4, 2020) | A parent opens child models; only strings, numbers, lists return; synchronous (fixed tick ratio) or asynchronous (parent pauses); *Wolf Chases Sheep* spawns a chase model per meeting | The direct structural precedent; a typed boundary was already their design | README `[V]`; paper `[A]` |
| PADAWAN (Picault & Mathieu, IJCAI 2011) | Any agent may encapsulate an environment with its own interaction matrix and period; agents sit in several at once; "no limiting principle to the creation or dissolution of any level" | The formalism that permits recursion: a meeting is an environment hosted by the meeting | `[A]` |
| GAMA multi-level (Vo, Drogoul, Zucker 2012) | A host agent `capture`s co-located agents, runs their behaviour itself, `release`s them | "The cafe table captures its diners" | `[A]` |
| IRM4MLS (Morvan, Veremme, Dupont 2011); Morvan & Kubera 2017 | Levels emit *influences*; each level's *reaction* commits them; reading another level mid-update yields arbitrary values | Separate what an episode wants from what the world commits; read a frozen tick snapshot | `[A]` |
| Camus, Bourjot, Chevrier 2015 (JASSS 18(3)7) | Micro and macro as separate DEVS models with explicit up/down coupling artifacts; at a 4:1 tick ratio the macro sees only the last micro output | Decide which round's state the macro sees | `[A]` |
| Davis & Hillestad 1993; Davis & Bigelow 1998 (RAND MR-1004) | Families of models at different resolution; *weak consistency* = "simulate then aggregate" agrees with "aggregate then simulate"; calibrating the coarse model to the fine one is the hard part | The docking test for proxy vs episode | `[A]` |
| Reynolds, Natrajan, Srinivasan 1997 (TOMACS 7(3)) | Multiple Representation Entities: keep all resolutions live and reconcile; names *chain disaggregation* and *level flip-flop* | Do not swap representations; cap depth; add hysteresis to formation | `[A]` |
| Navarro, Flacher, Corruble 2011 (AAMAS) | Dynamic level of detail by "level of interest"; reports CPU saved *and* dissimilarity from a full-resolution reference run | The evaluation template: always run the full-resolution reference | `[A]` |
| Holonic MAS (Gaud et al. 2008) | Pedestrians with the same goal merge into a super-holon; an energy-like deviation indicator triggers a split | Everyone else zooms *out* for cost; jeve zooms *in* for fidelity, and needs the inverse indicator | `[A]` |
| Heterogeneous multiscale method (E & Engquist 2003); equation-free (Kevrekidis 2003) | Run the micro solver only where the macro rule has no closure; *lifting* (macro → consistent micro state) is the hard operator | Spawn only where the one-shot rule is missing; building an episode's local state from macro state is under-determined | `[A]` |
| Simon 1962 | Near-decomposability: intra-subsystem interaction is fast and dense, inter-subsystem slow and weak | The licence for a bounded episode, and its validity condition: nothing outside may change the table's state mid-episode | `[A]` |

Closest here: LevelSpace for the mechanism, PADAWAN for recursion, Davis & Bigelow for the
test.

### 2.2 LLM social simulation, 2023–2026

| Work | Sub-episode mechanism | Bound | What returns | Typed? | Tag |
|---|---|---|---|---|---|
| Generative Agents (Park et al. 2023, arXiv 2304.03442) | Rule gate (`lets_talk`: awake, not already chatting, cooldown) → one yes/no → `agent_chat_v2`, `for i in range(8)` alternating turns | 8 rounds or self-declared end; `chatting_with_buffer = 800` ticks per pair afterwards | Prose summary → schedule slot and memory; no lookahead | No | `[V]` loop, cap, cooldown |
| Concordia v1.8 `Conversation` (2023–24) | After every event: "did anyone speak?"; participants; up to 3 burner NPCs; an LLM-chosen *key question* (citing the Microscope RPG); a separate game master with its own memory; a `MultiIntervalClock` that "will advance in higher gear during the conversation scene" | `max_conversation_length = 20` rounds, or the key question judged answered | "Summary of a conversation between …" to participants and the main GM memory | No | `[V]` source |
| Concordia v2.x (2025–26) | Scenes are *pre-scheduled* `SceneSpec(scene_type, participants, num_rounds, start_time, premise)`; round-robin turn-taking with no LLM; decision scenes use `choice_action_spec` → `action_to_scores` → `scores_to_observation`; in situated worlds a conversation is now **one** ghost-written completion after each participant acts once | `num_rounds` | Numeric payoffs rendered as observation text | Decision scenes: yes | `[V]` source, CHANGELOG |
| Concordia interrupt-driven GM (2026, in tree, not in the changelog) | Shared event queue; per-entity interrupt masks and one mandatory timer; events can target a sub-group; deterministic ordering; no LLM in scheduling; `DatetimeTimeModel` needs no model | — | — | — | `[V]` source |
| Humanoid Agents (Wang, Chiu, Chiu 2023, arXiv 2310.05418) | Co-located dyad → `dialogue(max_turns=10)`; ends when a reaction is `None` | 10 turns | One yes/no "did X enjoy the conversation?" → `closeness ± 1`; emotion re-classified into an enum | Fold-back: yes | `[V]` source |
| Sotopia (Zhou et al., ICLR 2024, arXiv 2310.11667) | Standalone dyadic episode with private goals | 20 turns, `leave`, or stale | Seven integer scores from an LLM judge | Post hoc | `[V]` README |
| HiSim (Mou, Wei, Huang; ACL 2024 Findings, arXiv 2402.16333) | ~300 LLM "core" users; the crowd as deductive opinion models; LLM stances mirrored into the ABM state | one call per user per round | enum actions | Yes | `[V]` README |
| AgentTorch archetypes (Chopra et al. 2024, arXiv 2409.10568) | Agents with identical `group_on` attributes share one LLM query; `n_arch` copies averaged; the float is broadcast | — | a probability | Yes | `[A]` |
| Lyfe Agents (Kaiya et al. 2023, arXiv 2310.02172) | An option (e.g. *talk*) persists across ticks until a non-LLM exit check | option exit | summaries | No | `[A]` |
| OASIS (arXiv 2411.11581); AgentSociety (2502.08691, v2 2607.11895); TinyTroupe | Enumerated actions, activation sampling, hop caps (`propagation_count > 5`), `TinyWorld.run(n)` + `ResultsExtractor` | — | — | Partly | `[V]` READMEs |
| Affordable Generative Agents (arXiv 2402.02053) | Reuse of prior plans for recurring situations; typed relationship keywords | — | — | — | `[A]` |
| Mou et al. 2024 survey (arXiv 2412.03563) | "Scenario simulation" — a few agents pursuing a goal in a bounded context — is the taxonomic slot | — | — | — | `[A]` |

Closest here, and closest overall: **Concordia v1.8's conversation scene**. It is spawned
dynamically from an event; it has its own game master, memory, participants and a finer
clock, a hard cap, and an explicit fold-back. Its deficits are exactly what jeve would
change: prose in and out, LLM-judged termination, depth one (the conversation game master
has no `Conversation` component of its own `[V]`), and a cost that led DeepMind to collapse
it into one call in v2. The typed half exists separately — v2 decision scenes, Humanoid
Agents' ±1 — and nobody has joined them.

### 2.3 Games and interactive narrative

| Work | Mechanism | Lesson | Tag |
|---|---|---|---|
| Sunshine-Hill & Badler 2010 (AIIDE), alibi generation | A "perceptual simulation" runs detail only for observed pedestrians, sampled from the full simulation's distribution; "statistically guaranteed … perceptually indistinguishable" | The macro sim is the prior; an episode is a conditional sample; correctness is distributional, not per event | `[A]` |
| Brom, Šerý, Poch 2007 (IVA), simulation LOD for virtual humans | A membrane separates full-detail space; outside it agents run higher nodes of their behaviour tree; state is disaggregated on crossing | LOD applies to behaviour and place; disaggregation on entry is the expensive step | `[A]` |
| Navarro et al. 2011; O'Sullivan et al. 2002; Osborne & Dickinson 2010 | Level of interest per region; groups as collapsible trees | The group is the unit of expand/collapse | `[A]` |
| Total War, Bannerlord (campaign → battle → results; auto-resolve as the proxy) | Bannerlord's proxy is a round-based loop of random troop-pair typed contests; Total War compares "combat potential"; documented divergences (whole units destroyed, defender bias) are what players exploit | A proxy that matches win probability but not the *shape* of outcomes biases the world; when the proxy resolves every unobserved battle, its biases are the world's laws | `[A]` |
| Comme il Faut / Prom Week (McCoy et al. 2010–11) | Social exchange: initiator intent → responder accept/reject → effects; trigger rules ripple to third parties; > 40 exchanges | The closest *data model*: a typed exchange with typed ripple | `[A]` |
| Versu (Evans & Short 2014, IEEE TCIAIG) | Social practices are "reactive joint plans, providing affordances"; they "never control the agents directly" | The episode frames roles and legal moves; the agent's decision function is unchanged — one `Policy` serves both levels | `[A]` |
| Façade (Mateas & Stern 2005); storylets (Kreminski & Wardrip-Fruin 2018) | Beats with preconditions, internal joint behaviours, exit by beat goals, selected by a drama manager; storylets as chunks with preconditions and effects | The selection layer is the budget; an episode invocation is a storylet | `[A]` |
| Dwarf Fortress, S.T.A.L.K.E.R. A-Life, Sims 3, CK3, Kenshi | Off-screen abstract simulation; seam artefacts (fights erupting at the switch distance); CK3 replaced mean-time-to-happen triggers because they "made it difficult to govern how frequently events spawn"; Kenshi refused a dynamic economy for stability | Trigger on actions, not timers; micro → macro feedback destabilises economies; layer seams are the canonical bug | `[A]` |
| Aura/nimbus (Benford & Fahlén 1993); locales (Barrus et al. 1996); HLA DDM | Awareness = focus × nimbus, per medium; a locale is a bounded region with its own event stream | Asymmetric membership: in earshot is not in the conversation | `[A]` |

Nothing here nests below one level, none uses a learned inner loop, and no game publishes a
proxy-calibration procedure; the modding communities fix the proxies by hand.

### 2.4 Social and organisational theory

| Work | Claim | What it implies for an episode | Tag |
|---|---|---|---|
| Coleman 1990, *Foundations of Social Theory* | Macro → situation → action → macro (the boat); the micro-to-macro arrow is where the difficulty lives | Episodes are the transformational arrow; macro state changes only through their outcomes | `[A]` |
| Goffman 1961 *Encounters*; 1983 "The Interaction Order" | A focused gathering has ratified participants, a membrane, openings and closings, and rules of irrelevance; the interaction order is a domain of its own | Entry = ratification; bystanders excluded; local state that is not a re-read of macro state | `[A]` |
| Collins 2004, *Interaction Ritual Chains* | Co-presence + barrier + mutual focus + shared mood → solidarity, emotional energy, symbols; EE carries into the next encounter and biases whom one approaches | What returns: EE per person, solidarity per pair, a shared symbol; success/failure as exit | `[A]` |
| Bales 1950; affect control theory (Heise 2007; Schröder, Hoey, Rogers 2016) | Twelve act categories, task vs socio-emotional; actors choose acts minimising deflection from identity sentiments — a numeric multi-round dyadic engine exists (INTERACT, BayesACT) | One typed act per speaker per round from a small enum; a proven typed within-encounter engine | `[A]` |
| Ostrom 2005; McGinnis 2011; Montes, Osman, Sierra 2022 (*AI* 311) | Action situation = seven working parts; adjacency networks; made executable as extensive-form games | The specification schema, already computational | `[A]` |
| Tsebelis 1990; Putnam 1988 | Nested and two-level games: a move that looks irrational in one arena is rational given another; a bargain must be ratifiable by the principal's win-set | An outcome must be ratifiable by macro constraints (cash, the boss) or it is a failed ritual | `[A]` |
| Carley 1991, Construct | Interaction transfers knowledge; the knowledge and social networks co-evolve | The minimal return value of any episode is *which facts moved*; it changes tomorrow's encounter probabilities | `[A]` |
| Levitt et al., Virtual Design Team (1996, 1999); Cohen, March, Olsen 1972 | Meetings cost attention and predict schedule; a decision is a collision of participants, problems, solutions; exit by resolution, oversight or flight | An episode consumes work time; exit type is an enum with distinct macro effects | `[A]` |
| Flache & Mäs 2008; Mäs et al. 2013; Hemelrijk (DomWorld) | The *order* of contacts inside a group changes cohesion; the same rules polarise short-term and unify long-term; removing the within-contest winner–loser rule destroys the macro hierarchy | The only ablation-style evidence that within-encounter sequence drives macro structure | `[A]` |
| Ferguson 2006; FRED; Covasim; EpiSimS; MATSim | Mixing groups from activity schedules; per-layer weights; deliberately *no* intra-encounter dynamics | Jeve's tick co-location is exactly this baseline; the episode's value is entirely what happens inside | `[A]` |
| Ferber & Gutknecht 1998 (AGR); Servat et al. 1998; Feld 1981 | A group is a dynamic container; emergent groups get "an existence of their own"; ties form around *foci* (workplaces, cafes) | The runtime container; groups as first-class; co-location at a focus is the trigger | `[A]` |

Recommendation from this strand: specify each episode kind as an action situation,
instantiate it in an AGR-style container from co-location at a focus, keep Collins's
variables as local state and returned deltas, and check outcomes against Putnam's win-set on
exit.

### 2.5 Recursive simulation proper, multi-fidelity, seeding, time

| Work | Mechanism | Lesson | Tag |
|---|---|---|---|
| Gilmer & Sullivan, WSC 1998–2005 | A simulated commander spawns a copy of the running simulation per option; child events must be tagged apart from parent events | Decision-time only; but tag hypothetical events distinctly if jeve ever adds rollouts | `[A]` |
| Hybinette & Fujimoto 2001 (TOMACS 11(4)) | Clone a running simulation at a decision point; share the common prefix across clones | Memoise the shared prefix of sibling episodes | `[A]` |
| Cazenave 2009, nested Monte-Carlo search; I-POMDPs (Gmytrasiewicz & Doshi 2005) | Level-*n* evaluates by level-(*n*−1); useful depth is 2–4; nesting depth is a hard parameter | Cap depth explicitly; the benefit comes from adapting the cheap policy between levels | `[A]` |
| Gordy & Juneja 2010; Broadie, Du, Moallemi 2011; Giles & Haji-Ali 2019 | Inner samples contribute bias ∝ 1/N_inner, outer ∝ 1/N_outer; allocate inner effort to scenarios near the threshold | Few rounds, many situations; refine near-threshold encounters | `[A]` |
| Peherstorfer, Willcox, Gunzburger 2018 (MFMC); Giles 2008 (MLMC) | A cheap model helps only if highly correlated *and* much cheaper; couple coarse and fine samples on the *same* random inputs | A computable go/no-go per encounter class; jeve's path seeds already permit the coupling | `[A]`; formula `[M]` |
| Bobashev et al. 2007 (WSC) | Switch ABM ↔ ODE at a threshold; ABM aggregates seed the ODE | The shape of a per-instance switch | `[A]` |
| Random123 (Salmon et al. 2011); JAX splittable keys; L'Ecuyer streams | value = f(key, counter); child key = fold_in(parent key, id) | Jeve's `derive_seed` is this idiom; an episode's key is fold_in(encounter, round, question) | `[A]` |
| Zeigler (DEVS closure under coupling); Ferber & Müller 1996 (influence/reaction); Fujimoto 1990 | A coupled model is atomic from outside; agents emit influences, the environment reacts once; snapshot reads + one-tick lookahead = conservative, no rollback | An episode is atomic to the tick; outcomes are influences committed once in a reaction phase | `[A]` |
| Grimm et al. 2005 (pattern-oriented modelling); Bigelow & Davis 2003 | Multiple patterns at multiple scales decide sufficient resolution; higher resolution is not automatically more valid | The acceptance test: macro patterns the proxy cannot reproduce and the episode can | `[A]` |
| LLM rollouts: RAP (2305.14992), LLM-MCTS (2305.14078), GDP-Zero (2305.13660), Hypothetical Minds (2407.07086) | All decision-time; GDP-Zero simulates ~20 dialogues per real turn; Hypothetical Minds scores hypotheses, no rollouts | Execution-time nesting has different requirements: determinism, caching, causal tags | `[A]` |

### 2.6 The 2025–2026 frontier

| Work | What it shows | Bearing on the hypothesis | Tag |
|---|---|---|---|
| Jang et al., Sept 2026 (arXiv 2609.07573) | Census-grounded personas debating policy against national surveys: sealed-monologue agents change stance at similar rates and reach nearly the same final balance as full debates | **The null jeve must beat.** Richer interaction did not move the outcome distribution | `[A]` |
| López, Pastor-Galindo, Ruipérez-Valiente, June 2026 (2606.12369) | A finite-state policy vs LLM policies in a 1,000-agent network: LLMs deviate (mean JSD 0.21) and are 135–1,337× slower | The template for a Jev-vs-prose benchmark; explicit engines win on cost and control | `[A]` |
| EpisodeSim (Gershman, Sept 2026, 2609.01167) | A *bounded social episode* (participants, setting, frame, business, closure) with a classical "World Master" holding authoritative state and obligations; the LLM only role-plays | Independent arrival at the episode contract; single level; author-judged | `[A]` |
| Think-Before-Speak (Yang et al., June 2026, 2606.03137) | A group episode as typed internal-state updates per interval plus one arbitration | Directly expressible as Jev questions; the utterance is optional | `[A]` |
| Belief Engine (Yang et al., May 2026, 2605.15343) | Scalar stance with an explicit log-odds update; validated on human debate data | Keep group state as typed scalars with explicit update rules | `[A]` |
| Tak … Gratch, Sept 2026 (2609.13261); Loop-Back Authority (2609.14767); Yuan et al. (2609.19759) | LLM groups converge earlier and follow majorities; an extra supervisory round costs +51.5% tokens for worse output; recursion depth should follow dependency structure | Each round must earn its cost; depth is conditional, not fixed | `[A]` |
| TRAILS (Ye … Ferrara, May 2026, 2605.18890); Li & Tao (2603.00113) | Meso-level protocol perturbations shift outcomes by up to 76 points; collective outcomes are mediated by scheduling and visibility | The episode *protocol* (rounds, order, who is polled) will itself shape macro outcomes; audit it per claim | `[A]` |
| APS (2605.27419); GASim (ACL 2026, 2605.07692); MicroWorld (2604.18011) | Prototype agents with tail escalation to direct LLM calls; core/ordinary splits with a learned propagator; call the model only for influenced agents | The population-side twin of the idea; escalation exists at population level, not per encounter | `[A]` |
| Jev ecosystem (Sept 2026): hermes-agent `DecisionProvider` RFC with a shadow mode; the Jevtown demo; an audit in which Jev picked "unknown" for 95% of ambiguous items | No academic benchmark of typed-decision agents yet; shadow evaluation is the community's own pattern | Run episodes in shadow against the encounter engine first; always give Jev an abstain option and handle it in code | `[A]` |
| Concordia 2.3–2.4 (Feb–Mar 2026); AgentSociety 2 (July 2026) | `SceneBasedTerminator`, scene-aware event delivery, `CHOICE`/`FLOAT` action specs; no primitive for a scene to spawn an inner simulation and return a result | Reuse the SceneSpec vocabulary; nesting and fold-back are ours to build | `[V]` CHANGELOG |

---

## 3. What is new, honestly

| Candidate contribution | Nearest thing | Confidence it is absent |
|---|---|---|
| **N1** A typed-only multi-round group interior — no prose anywhere in the loop | Concordia v2 decision scenes (typed, one round, pre-scheduled); Humanoid Agents' ±1 (typed fold-back, generative interior); Think-Before-Speak (typed state, generative utterances) | High: six agents, none found one |
| **N2** Cache-sharing of canonicalised *group* situations | AgentTorch `group_on` and APS prototypes (population level); TinyTroupe's exact-input cache; transposition tables in game search | High |
| **N3** Budget-governed *per-encounter* resolution with a docked proxy | APS tail escalation and GASim core/ordinary splits (per agent, static); Bobashev's threshold switch (per model); Broadie's allocation (per scenario, in finance) | Medium-high: the rule exists in finance, not in social simulation |
| **N4** Recursion below one level with typed outcomes and causal ids across levels | PADAWAN and Swarm permit it; no published run; Concordia v1 is depth one by construction | High for the demonstration; the mechanism is not new |
| **N5** Byte-identical replay of nested episodes with common random numbers across arms | The Random123/JAX idiom; Concordia's interrupt GM orders events deterministically but with stochastic LLM interiors | High |
| **N6** An interventional measurement of whether intra-encounter resolution changes macro outcomes, against a one-shot null and an A/A floor | Navarro's dissimilarity (CPU vs fidelity, entity LOD); Flache & Mäs (timing inside teams); Jang 2026 (negative, opinion dynamics) | High — and it is the one that matters |
| **N7** Groups as decision units with a typed output distinct from their members' | AGR and Servat make groups first-class; none gives a group a typed decision | High; speculative value |

Absent is not the same as valuable. N1, N2 and N5 fall out of jeve's existing architecture
almost for free; N3 and N6 are the research; N4 and N7 are second-order and should wait for
N6's answer.

---

## 4. What the literature says is hard, and where jeve stands

| Problem | Who names it | Jeve's position |
|---|---|---|
| **Consistency and double counting.** Attributes at two levels lose correlation; concurrent effects at both levels must be combined once (Reynolds 1997); "simulate-then-aggregate" must agree with "aggregate-then-simulate" (Davis & Bigelow) | MRM | While an episode runs, the one-shot `agent.tick` for its participants is suppressed, and macro writes are a pure function of the episode's typed outcome. The docking test (§7, E2) is the measurement |
| **Time.** Reading another level mid-update yields arbitrary values (Morvan & Kubera); pausing the parent is legitimate only if nothing outside changes meanwhile (Simon; LevelSpace's asynchronous mode) | ML-ABM | The tick barrier is already a frozen snapshot; an episode that sub-steps inside one tick is safe by construction; one that spans ticks marks its participants busy and reads nothing new |
| **Lifting.** Constructing a group's local state from macro state is under-determined (equation-free) | Multiscale | Episode state is built from typed facts only (who, roles, open issues, traits) — which is also what Jev's context-rot limit demands |
| **Thrashing and chain reactions.** Flip-flop and chain disaggregation (Reynolds); mean-time-to-happen triggers cause "statistical anomalies" (CK3); reminder ping-pong (workbench, 00 §6.5) | MRM, games, jeve's own history | Hysteresis on formation; a per-pair cooldown (Smallville's 800 ticks); a hard depth cap; rounds continue only on state change |
| **The proxy's shape.** Auto-resolve that matches win rate but not casualty distribution gets exploited (Total War) | Games | The one-shot encounter is docked to the episode on the full outcome distribution, not the mean |
| **Protocol dominance.** Rounds, order and visibility can move outcomes more than the agents do (TRAILS; Li & Tao) | 2026 validation | The episode protocol is a treatment variable in every study, and every claim is audited against it |
| **Runaway agreement.** LLM groups converge early and follow majorities (Tak et al.); Sotopia-style episodes reward agreement | LLM sims | Typed acts include decline, dispute and leave; the negative-event detector (02 §3.2) applies inside episodes |
| **Hazard-rate distortion inside episodes.** A propensity asked every round fires within a few rounds | jeve (ADR-004) | Irreversible acts (`press`, `dispute`) are asked once per episode, at the first round where they are possible; everything else is reversible |
| **Cost.** Per-utterance calls killed Concordia v1 scenes and motivated Lyfe and AGA | LLM sims | See §6.8: at four firms, episodes roughly double a $0.009 sim-day; the dial matters at a hundred firms |
| **Validation.** Dynamic-LOD models are hard to validate (Morvan; Gil-Quijano); believability is not validity (Larooij & Törnberg) | All | Jeve's existing plan transfers whole: null models, interventional forks, A/A floors, mutation-tested detectors (02 §3) |

---

## 5. Lessons to integrate, mapped to the tree

| Lesson | From | Where it lands | Cost |
|---|---|---|---|
| Rule gate first, then one cheap probability; a cooldown per pair after an episode | Smallville `lets_talk`, `chatting_with_buffer` `[V]` | `world/space.py` before `decide_many`; a last-episode column on `positions` or a pair table | small |
| An episode has its own participants, local state, cap and explicit exit write-back; termination by typed question plus cap, never prose | Concordia v1 `[V]`; v2 `SceneSpec` `[V]`; EpisodeSim `[A]` | a new `world/episodes.py` (§6) | the feature |
| Typed action spec → typed scores → observation | Concordia v2 `game_theoretic_and_dramaturgic` `[V]` | `decide/questions.py`: `episode.<kind>` sets whose `interpret` returns typed acts | medium |
| Who is polled each sub-step is a mask plus a mandatory timer; disengagement is a typed choice | Concordia interrupt GM `[V]` | a per-participant `leave` act per round; someone who leaves is not polled again | small |
| Canonicalise the group as role slots so identical rooms share a call; sample from returned probabilities, never repeat calls | jeve `slot()` `[V]`; AgentTorch `group_on` `[A]` | already the pattern; extend it to the episode's local state | free |
| Influence then reaction: outcomes are collected and committed once, in a fixed order | Ferber & Müller; IRM4MLS `[A]` | `episodes.close()` applies every write-back in one place, ordered by episode id | small |
| The one-shot encounter is the proxy; dock it to the episode on the outcome distribution; recalibrate wording, not code | Davis & Bigelow; Total War auto-resolve `[A]` | E2 in §7; an `ops/docking.md` report in the style of `ops/persona-probe.md` | study time |
| Spawn where the one-shot answer is near its threshold *and* a macro consequence is reachable; few rounds, many situations | Broadie et al.; Gordy & Juneja; HMM `[A]` | the entry rule in §6.2 | none |
| Cap depth; make it conditional on dependency, not fixed | I-POMDP, NMCS `[A]`; Yuan et al. 2026 `[A]` | `MAX_DEPTH = 2`; a child only when the parent's outcome creates a new stake | none |
| Minimal return value: which facts moved; then commitments, belief deltas, mood or EE | Carley's Construct; Collins; Coleman `[A]` | MEM-0001's knowledge and belief slots — the prerequisite | medium |
| Ratify outcomes against macro constraints on exit | Putnam; Tsebelis `[A]` | gates in `decide/gates.py` applied to episode outcomes (nobody promises cash they lack) | small |
| An episode costs attention: participants do no desk work while in one | VDT `[A]` | `_support`, `_payments` skip people marked in-episode this tick | small |
| Run new machinery in shadow first | hermes `DecisionProvider` RFC `[A]`; DECIDE-0002's shadow mode | `episodes="shadow"`: run, record, apply nothing | small |
| Always give Jev an abstain option and handle it in code | the Jev audit `[A]`; jeve's `other` convention `[V]` | every episode `choice` carries `other`; `other` on an act means say nothing this round | none |
| Evaluate on downstream event timings, not believability | Larooij & Törnberg `[A]`; `test_space.py` `[V]` | E1 in §7 reuses `first_services_invoice` | none |

---

## 6. A design sketch — not a decision record

Written so a WORLD-000x record can be cut from it after E1 and E2 report. Nothing here is
decided.

### 6.1 The object

```text
Episode
  id            serial; the seed path is ("episode", kind, sorted participants, zone, day, slot)
  kind          "cafe_table" | "hallway" | "client_meeting" | "standup" | ...
  participants  2–6 person ids, ratified at open
  zone          where it happens
  opened_seq    the event that opened it (a cause)
  parent_id     for a child episode, else null; depth <= 2
  round         0..MAX_ROUNDS
  local         typed: raised[], promised[], settled: bool, tension: 0-3, spoke_last, left[]
  outcome       typed dict, written once at close
```

Events: `episode.opened` (causes: the encounter or the scheduled job), `episode.round`
(causes: opened, previous round), `episode.closed` (payload: the outcome; causes: opened, last
round). Every write-back cites `episode.closed`, so the recursive `causes` query in
`test_space.py` walks through episodes unchanged.

### 6.2 Entry

Three conditions, all in code, none a model call:

1. **Co-location or co-involvement now**, as `space.run` computes it, with the same "someone
   had to move" rule (WORLD-0003).
2. **A stake**: an open issue an outcome could change — an outage one party can act on, an
   unpaid invoice between the firms, a fact one participant knows and another does not
   (scenario #6), a pending catering order, a ticket. No stake → the one-shot encounter
   stands. This is HMM's rule: refine only where the macro rule is missing.
3. **Near-threshold, or budget**: the one-shot `interact`/`raise_outage` answer lies inside
   its uncertainty band (DECIDE-0002's bands, reused), *or* the day's episode budget has
   room. Broadie's allocation as a dial: `JEVE_EPISODE_BUDGET` as a share of the day's
   decisions, governed like clock speed (CORE-0002).

Plus hysteresis: a pair that closed an episode cannot open another for `N` ticks
(Smallville's 800 ten-second ticks is about two hours; start at 8 of ours).

### 6.3 Rounds

Jev's independence rule (00 §0) means a round is one request per participant, with the
group's local state rendered in words and the others under role slots. Per participant per
round, borrowing Bales and Think-Before-Speak:

| Ask | Mode | Primitive |
|---|---|---|
| `act` | P | choice: raise_issue / press / promise / decline / inform / ask / small_talk / leave / other |
| `about` | P | choice over the open stakes present, plus other |
| `mention_<fact>` | P | one noul per salient fact this person knows and someone here does not — the whole diffusion mechanic (scenario #6) |
| `mood` | J | score, as today |
| `settled` | J | noul: "is the matter they came about now settled?" — the exit question |

Code arbitrates: one speaker's act is applied per round in a fixed order seeded by the
episode path, `local` is updated, and the state is re-rendered. A `leave` removes the
participant from later rounds. `MAX_ROUNDS` starts at 3 — Smallville uses 8 turns, Concordia
20 rounds, Sotopia 20, and Loop-Back Authority's result says every extra round must earn its
place. Irreversible acts (`press` about an outage, `dispute`) are asked only in the first
round in which they are possible.

An alternative to measure: one request per round carrying the whole group state with
per-participant questions (Jev's structured instructions can carry per-question data,
00 §1.1). Cheaper per episode; shares less across episodes.

### 6.4 Exit and fold-back

Close when all remaining participants say `settled`, or all have left, or `MAX_ROUNDS` is
reached. Then, in one reaction phase:

- **Knowledge.** Every `mention_<fact>` sampled true writes a knowledge row for the hearer
  (MEM-0001), cause `episode.closed`.
- **Commitments.** A `promise` writes a typed commitment (who, what, by when); the payer's
  next `payment.timing` sees `reminded_in_person` as today, and a broken promise later moves
  a trust slot.
- **Escalation.** `press` about an outage with a vendor present is today's `_escalate`,
  unchanged, once per incident.
- **Mood**, and — if Collins is worth testing — an emotional-energy scalar per participant
  (R5).
- **Ratification.** An outcome that promises cash the ledger lacks is written as a `promise`
  with `credible=false`; money is never moved by an episode. The referee stays code.

Nothing is applied per round. Nothing outside the episode changes during it. The macro
tick's own `agent.tick` for the participants is skipped that tick.

### 6.5 Time

Default: rounds are sub-steps inside the spawning tick, like the cafe queue (ADR-001), each
round a real Jev request on the barrier (≈ 0.3–0.5 s each by vendor figures, 00 §0). Three
rounds add ≈ 1–1.5 s to a tick that already waits on `agent.tick`. For episode kinds that
should last longer than fifteen minutes (a client meeting), one round per tick with
participants marked busy, Lyfe-style; a `busy_until` on `positions` keeps `_support` and
`_payments` from asking them anything.

### 6.6 Determinism, cache, causes

- **Seeds.** Every group-level draw in an episode is `derive_rng(root, "episode", kind,
  *sorted_participants, zone, day, slot, round, ask)`. No tick anywhere in the path
  (CORE-0009). Per-person decisions keep their `decision_seq` path.
- **Cache.** The rendered state uses slots, bucketed traits and worded local state, so two
  lunch tables with the same roles, the same open stake and the same round history share
  every call. E4 measures how often that happens.
- **Replay.** Episodes are decisions and events; the cassette already covers them. Strict
  replay raises on a miss, as today.
- **Common random numbers across forks.** An intervention that does not touch an episode's
  participants leaves its draws identical in both arms.

### 6.7 Recursion

A child episode opens when a round's outcome creates a *new* stake for a *subset* (two
people at the table now have a private matter), or a `promise` schedules a follow-up
(`episode.open` as a scheduler job in WORLD-0005's registry). Depth ≤ 2. Yuan et al.'s
finding stands as the rule: nest only where the dependency structure demands it; a flat
episode is the default.

### 6.8 Cost envelope

From the measured run `[V]`: a distinct call ≈ 913 tokens ≈ $0.000038. An episode of 3
rounds × 4 participants is 12 calls ≈ $0.0005 from a cold cache. Twenty episodes per sim-day
≈ $0.01, roughly doubling today's $0.0087 per sim-day. Rate limits are nowhere near. What
binds at four firms is not cost but whether outcomes reach money; what binds at a hundred
firms is episodes × rounds × participants, and that is what the budget dial in §6.2 is for.

### 6.9 Null models and flags

- `Engine(episodes=False)`: the proxy only — today's world. The docking partner.
- `episodes="shadow"`: run and record, apply nothing.
- A `RulesPolicy` twin for every episode question set (WORLD-0001), so `make soak` runs
  episodes for free.
- Shuffled-participant and shuffled-round-order variants, for the protocol audit (TRAILS).

---

## 7. Experiments, pre-registered

Every one follows 02 §3.3: forks at M states, K ≥ 30 seeds, an A/A noise floor, bootstrap
CIs, and a path-blocking control.

| # | Question | Design | Observable | Falsified if |
|---|---|---|---|---|
| **E1** Does the second round matter? | 1-round (proxy) vs 3-round episodes at the same spawn points, same seeds | `first_services_invoice`, outage minutes, `invoice.blocked` count, DSO — the `test_space.py` quantities | Δ inside the A/A floor. This is Jang's null, on money |
| **E2** Is the proxy docked? | For each episode kind, run N spawn points both ways with identical keys; compare the outcome distributions (escalated? fact moved? promise?) | JSD between proxy and episode marginals; MFMC correlation ρ and cost ratio w | ρ low → the dial changes base rates, and every other study is confounded until the proxy's wording is recalibrated |
| **E3** Does diffusion through the cafe reach money? | Seed one fact (a planned price rise) in one Tallybird engineer; episodes on and off | Share of agents who know it over time (Smallville's measure, typed); whether knowing it changes a churn or credit decision downstream | Knowledge spreads but nothing downstream moves — a screensaver |
| **E4** Does canonicalisation buy sharing? | Cache-hit rate with slots only, slots + mood, slots + local state | Hit rate; $ per sim-day | Hit rate < 30%: episodes cost like unique calls |
| **E5** Dose–response in rounds | `MAX_ROUNDS` ∈ {1, 2, 3, 5} | E1's observables | Non-monotone, or flat past 2: cap at 2 |
| **E6** Protocol sensitivity | Shuffle speaking order; poll all vs poll on state change only; vary the entry band | E1's observables | Effects larger than E1's treatment effect: the protocol is the model (TRAILS) |
| **E7** Persona inside episodes | Low- vs high-tertile `vocality` and `sociability` at identical tables | Within-role JSD of episode acts vs the shuffled-persona null (02 §3.4, N2) | Flat: episodes homogenise, as LLM groups do |

Run E2 before E1. Run E1 before building anything in §6.7.

---

## 8. Research ideas beyond the build

| # | Idea | Why it is open | What jeve uniquely has |
|---|---|---|---|
| **R1** A typed-vs-prose episode benchmark | López et al. 2026 compared explicit policies to LLM policies for *individual* actions; no one has for group episodes | The same `Policy` seam takes Jev, a rules twin, and — through TypeSafe's adapter — a flash LLM answering the same typed questions (DECIDE-0002): three arms, one harness |
| **R2** Resolution as a treatment: the first interventional dose–response of intra-encounter resolution on macro outcomes | Absent in six strands; Navarro measured CPU, Flache & Mäs measured timing, Jang measured opinion | Exact counterfactual forks with common random numbers |
| **R3** The docked proxy as a learned summary | MRM calibrates Lanchester coefficients from high-resolution runs; nobody calibrates a *question's wording* to a sub-simulation's outcome distribution | The cache makes every episode a labelled example; the one-shot question can be re-worded until its marginal matches |
| **R4** Situation canonicalisation for cache sharing | Transposition tables exist in game search, not in ABM | Content-hash caching is already the cost story; episodes are a harder test of it |
| **R5** Interaction ritual chains, typed | Collins's emotional energy is rarely quantified; ACT gives numbers for dyads only | A `score` per participant at close; test whether EE predicts whom they approach next, against a null without it |
| **R6** Decision-time recursion with Jev | Gilmer's recursive simulation was too expensive to use; LLM rollouts cost ~20 dialogues per real turn | Typed rollouts of a typed world are cheap and cacheable; high-stakes decisions (churn, dispute) could run three rollouts and vote — off the tick barrier |
| **R7** Groups as decision units | AGR makes groups first-class; none gives a group a typed decision distinct from its members' | A `close.signoff`-style question asked *of the table* ("does this group leave agreeing?") with the members' answers as state, and a test of whether it beats the members' argmax |
| **R8** Fidelity allocation as a control problem | APS and GASim allocate by agent stratum, statically | The budget governor (CORE-0002) already turns dollars into clock speed; turning dollars into resolution per encounter is one more dial with a measurable response |

---

## 9. Bibliography

Grouped by strand. The tag is the strongest verification achieved this session. Identifiers
marked `[A]` were confirmed by an agent from a search index or a GitHub-hosted mirror and
not opened at source.

**Read first-hand `[V]`**

1. jeve at `78cb007`: `world/space.py`, `world/engine.py`, `decide/questions.py`,
   `decide/policy.py`, `decide/jev_policy.py`, `decide/sampling.py`, `core/seed.py`,
   `tests/test_space.py`, `ops/economics.md`, `ops/persona-probe.md`; the WORLD-0003,
   DECIDE-0001, DECIDE-0003, DECIDE-0004 and MEM-0001 records.
2. google-deepmind/concordia at `3e30a20` (2026-09-14): `typing/scene.py`,
   `components/game_master/scene_tracker.py`, `next_acting.py`, `event_resolution.py` (the
   `Conversation` chain), `interrupt_scheduling.py`, `interrupt_time_model.py`,
   `interrupt_next_acting.py`, `prefabs/game_master/game_theoretic_and_dramaturgic.py`,
   `dialogic_and_dramaturgic.py`, `CHANGELOG.md`; and v1.8's
   `components/game_master/conversation.py` and `environment/scenes/conversation.py` from
   an agent's saved copies.
3. joonspk-research/generative_agents: `persona/cognitive_modules/converse.py`, `plan.py`,
   `perceive.py`.
4. READMEs of NetLogo/LevelSpace, xymou/HiSim, camel-ai/oasis, tsinghua-fib-lab/AgentSociety,
   sotopia-lab/sotopia, microsoft/TinyTroupe; Humanoid Agents' `humanoid_agent.py` (saved
   copy).

**Multi-level and multi-resolution simulation `[A]`**

5. Morvan 2012, *Multi-level agent-based modeling: a literature survey*, arXiv 1205.0561.
6. Morvan, Veremme, Dupont 2011, IRM4MLS, MABS XI, LNCS 6532; arXiv 1310.7951.
7. Morvan & Kubera 2017, *On time and consistency in multi-level agent-based simulations*,
   arXiv 1703.02399.
8. Mathieu, Morvan, Picault 2018, *Four design patterns for multi-level ABM*, SIMPAT 83,
   doi:10.1016/j.simpat.2017.12.015.
9. Picault & Mathieu 2011, PADAWAN, IJCAI-11 pp. 332–337.
10. Vo, Drogoul, Zucker 2012, the GAMA multi-scale meta-model, IEEE RIVF,
    doi:10.1109/rivf.2012.6169849.
11. Gil-Quijano, Louail, Hutzler 2012, *From biological to urban cells*, PRIMA 2010, LNCS
    7057, doi:10.1007/978-3-642-25920-3_45.
12. Camus, Bourjot, Chevrier 2015, JASSS 18(3)7, doi:10.18564/jasss.2645.
13. Uhrmacher et al. 2007, ML-DEVS, WSC 2007.
14. Hjorth, Head, Brady, Wilensky 2020, LevelSpace, JASSS 23(1)4, doi:10.18564/jasss.4130;
    Head et al. 2015, WSC.
15. Minar, Burkhart, Langton, Askenazi 1996, *The Swarm simulation system*, SFI WP
    96-06-042.
16. Gaud, Galland, Gechter, Hilaire, Koukam 2008, SIMPAT 16(10),
    doi:10.1016/j.simpat.2008.08.015; Rodriguez, Hilaire, Gaud, Galland, Koukam 2011,
    doi:10.1007/978-3-642-17348-6_11.
17. Davis & Hillestad 1993, WSC pp. 1003–1012; Davis & Bigelow 1998, RAND MR-1004-DARPA;
    Bigelow & Davis 2003, MR-1750; Davis & Bigelow 2003, MR-1570.
18. Reynolds, Natrajan, Srinivasan 1997, *Consistency maintenance in multiresolution
    simulations*, ACM TOMACS 7(3), doi:10.1145/259207.259235; Rabelo et al. 2025,
    *Information* 16(8):635.
19. Navarro, Flacher, Corruble 2011, *Dynamic level of detail for large scale agent-based
    urban simulations*, AAMAS pp. 701–708.
20. Brailsford, Eldabi, Kunc, Mustafee, Osorio 2019, EJOR 278(3),
    doi:10.1016/j.ejor.2018.10.025; Burghout, Koutsopoulos, Andréasson 2005, TRR 1934.
21. E & Engquist 2003, HMM, CMS 1(1); Kevrekidis et al. 2003, equation-free, CMS 1(4); Liu,
    Samaey, Gear, Kevrekidis 2015, arXiv 1404.7199.
22. Simon 1962, *The architecture of complexity*, Proc. Am. Phil. Soc. 106(6).

**LLM social simulation `[A]`, except where listed under 1–4**

23. Park et al. 2023, arXiv 2304.03442.
24. Vezhnevets et al. 2023, Concordia, arXiv 2312.03664.
25. Mou, Wei, Huang 2024, HiSim, ACL Findings, arXiv 2402.16333.
26. Chopra et al. 2024, AgentTorch, arXiv 2409.10568.
27. Kaiya et al. 2023, Lyfe Agents, arXiv 2310.02172.
28. Wang, Chiu, Chiu 2023, Humanoid Agents, arXiv 2310.05418.
29. Zhou et al. 2024, Sotopia, ICLR, arXiv 2310.11667.
30. Piao et al. 2025, AgentSociety, arXiv 2502.08691; v2, arXiv 2607.11895.
31. Yang et al. 2024, OASIS, arXiv 2411.11581.
32. Tang et al. 2024, GenSim, arXiv 2410.04360; YuLan-OneSim 2025, arXiv 2505.07581;
    SocioVerse 2025, arXiv 2504.10157; Altera 2024, Project Sid, arXiv 2411.00114.
33. Park et al. 2024, *Generative agent simulations of 1,000 people*, arXiv 2411.10109.
34. Yu et al. 2024, Affordable Generative Agents, TMLR, arXiv 2402.02053.
35. Li et al. 2024, EconAgent, ACL, arXiv 2310.10436; TwinMarket, arXiv 2502.01506;
    CompeteAI, arXiv 2310.17512; Agent Hospital, arXiv 2405.02957.
36. Gao et al. 2023 survey, arXiv 2312.11970; Mou et al. 2024, *From individual to
    society*, arXiv 2412.03563, ACM CSUR, doi:10.1145/3800683.
37. Larooij & Törnberg 2025, arXiv 2504.03274, doi:10.1007/s10462-025-11412-6.

**Games and interactive narrative `[A]`**

38. Sunshine-Hill & Badler 2010, *Perceptually realistic behavior through alibi generation*,
    AIIDE 6(1).
39. Brom, Šerý, Poch 2007, *Simulation level of detail for virtual humans*, IVA, LNAI 4722,
    doi:10.1007/978-3-540-74997-4_1; Brom, Poch, Šerý 2010, MIG.
40. O'Sullivan et al. 2002, CGF 21(4); Osborne & Dickinson 2010, AISB.
41. Mateas & Stern 2005, Façade, AIIDE.
42. McCoy, Treanor, Samuel, Reed, Mateas, Wardrip-Fruin 2010, Comme il Faut, AIIDE; 2011,
    Prom Week, FDG, doi:10.1145/2159365.2159425.
43. Evans & Short 2014, Versu, IEEE TCIAIG.
44. Ryan 2018, *Curating simulated storyworlds*, UCSC; Samuel et al. 2016, Bad News,
    ICIDS.
45. Kreminski & Wardrip-Fruin 2018, storylets, ICIDS, doi:10.1007/978-3-030-04028-4_14.
46. Greenhalgh & Benford 1995, MASSIVE, ACM TOCHI 2(3); Barrus, Waters, Anderson 1996,
    locales, IEEE CG&A 16(6); Liu & Theodoropoulos 2014, ACM CSUR 46(4).
47. Total War, Bannerlord, X-COM, Battle Brothers, Dwarf Fortress, S.T.A.L.K.E.R., Sims 3,
    CK3, RimWorld, Kenshi: community documentation and developer interviews as listed in
    `03-strands/03-games-narrative.md`.

**Social and organisational theory `[A]`**

48. Coleman 1990, *Foundations of Social Theory*; Hedström & Ylikoski 2010, Annu. Rev.
    Sociol. 36.
49. Goffman 1961, *Encounters*; 1983, *The Interaction Order*, ASR 48(1).
50. Collins 2004, *Interaction Ritual Chains*.
51. Bales 1950, *Interaction Process Analysis*; Harrington & Fine 2000, Soc. Psych. Q.
    63(4); Fine 2012, *Tiny Publics*; Feld 1981, AJS 86(5).
52. Tsebelis 1990, *Nested Games*; Putnam 1988, Int. Org. 42(3).
53. Ostrom 2005, *Understanding Institutional Diversity*; McGinnis 2011, Policy Studies J.
    39(1); Montes, Osman, Sierra 2022, *Artificial Intelligence* 311; Ghorbani et al.
    2013, MAIA, JASSS 16(2)9.
54. Carley 1991, ASR 56; Carley & Prietula 1994; Carley & Svoboda 1996, ORGAHEAD.
55. Jin & Levitt 1996, CMOT 2(3); Levitt et al. 1999, Mgmt Sci 45(11).
56. Cohen, March, Olsen 1972, ASQ 17(1); Fioretti & Lomi 2008, JASSS 11(1)1; Feldman &
    Pentland 2003, ASQ 48(1).
57. Flache & Mäs 2008, CMOT 14; Mäs, Flache, Takács, Jehn 2013, Org. Sci. 24(3); Hemelrijk
    2020, PLOS ONE, doi:10.1371/journal.pone.0243877.
58. Heise 2007; Schröder, Hoey, Rogers 2016, ASR 81(4).
59. Ferguson et al. 2006, Nature 442; Grefenstette et al. 2013, FRED; Kerr et al. 2021,
    Covasim; Stroud et al. 2007, EpiSimS, JASSS 10(4)9; Horni, Nagel, Axhausen 2016,
    MATSim.
60. Shehory & Kraus 1998, AI 101; Stone, Kaminka, Kraus, Rosenschein 2010, AAAI; Ferber &
    Gutknecht 1998, AGR, ICMAS; Servat, Perrier, Treuil, Drogoul 1998, MABS.

**Recursive simulation, multi-fidelity, seeding `[A]`**

61. Gilmer & Sullivan 1998, 2000, 2004, 2005, WSC (multitrajectory and recursive
    simulation).
62. Hybinette & Fujimoto 2001, TOMACS 11(4), doi:10.1145/508366.508370.
63. Rosen 1985/2012, *Anticipatory Systems*; Davidsson 1996, doi:10.1007/3-540-61314-5_30;
    Gmytrasiewicz & Doshi 2005, I-POMDP, JAIR.
64. Cazenave 2009, IJCAI; Rosin 2011, IJCAI.
65. Gordy & Juneja 2010, Mgmt Sci 56(10); Broadie, Du, Moallemi 2011, Mgmt Sci 57(6);
    Giles & Haji-Ali 2019, SIAM/ASA JUQ.
66. Peherstorfer, Willcox, Gunzburger 2018, SIAM Rev 60(3); Giles 2008, Oper Res 56(3).
67. Bobashev, Goedecke, Yu, Epstein 2007, WSC.
68. Kennedy & O'Hagan 2001, JRSS-B 63(3); Lamperti, Roventini, Sani 2018, JEDC 90.
69. Salmon, Moraes, Dror, Shaw 2011, Random123, SC'11; Claessen & Pałka 2013; L'Ecuyer et
    al. 2002, Oper Res 50(6).
70. Zeigler, Muzy, Kofman 2018, *Theory of Modeling and Simulation* 3e; Fujimoto 1990, CACM
    33(10); Ferber & Müller 1996, ICMAS.
71. Grimm et al. 2005, Science 310.
72. Cross et al. 2024, Hypothetical Minds, arXiv 2407.07086; Hao et al. 2023, RAP, arXiv
    2305.14992; Zhao, Lee, Hsu 2023, LLM-MCTS, arXiv 2305.14078; Yu, Chen, Yu 2023,
    GDP-Zero, arXiv 2305.13660.

**2025–2026 `[A]`, none opened at source**

73. Jang et al. 2026, arXiv 2609.07573.
74. López, Pastor-Galindo, Ruipérez-Valiente 2026, arXiv 2606.12369.
75. Gershman 2026, EpisodeSim, arXiv 2609.01167.
76. Yang, Peng, Lee, Liu 2026, Think-Before-Speak, arXiv 2606.03137.
77. Yang, Flechtner, Dailisan, Bakker 2026, Belief Engine, arXiv 2605.15343.
78. Tak et al. 2026, arXiv 2609.13261; Agachan, van Duijn, Zohrehvand 2026, arXiv
    2609.14767; Yuan et al. 2026, arXiv 2609.19759.
79. Ye, Cao, Chen, Ferrara 2026, TRAILS, arXiv 2605.18890; Li & Tao 2026, arXiv
    2603.00113.
80. APS 2026, arXiv 2605.27419; GASim, ACL 2026, arXiv 2605.07692; Xu et al. 2026,
    MicroWorld, arXiv 2604.18011.
81. Blando et al. 2026, arXiv 2607.17948; Qin, Li, Cheng 2026, arXiv 2604.06663; Zhu et
    al. 2026, TaskWeave, arXiv 2606.01199; Hashimoto et al. 2026, EconSimulacra, arXiv
    2606.26883.
82. Zhao, Pham, Vincent 2026, arXiv 2605.12824; Hullman et al. 2026, arXiv 2602.15785;
    Ziems et al. 2026, arXiv 2607.02464; Andric 2026, arXiv 2604.11840; Taillandier et al.
    2025, arXiv 2507.19364.
83. Flint, Aiello, Pastor-Satorras, Baronchelli 2026, PNAS, doi:10.1073/pnas.2531697123.
84. hermes-agent RFC #113008 and issue #118599 (Sept 2026); the AbdelStark/awesome-typesafe-jev
    audit note; Jiang, Li, Li 2026, Jev-Mem, arXiv 2609.23986.
