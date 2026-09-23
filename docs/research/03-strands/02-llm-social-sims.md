<!-- Raw strand report on LLM-based multi-agent social simulation, 2023–2026, gathered by a research agent on
2026-09-22 for ../03-recursive-micro-simulation.md. The verification tags are the
agent's own: [V] confirmed from a search index, a GitHub mirror, or a fetched source
during that session; [M] from memory. Not re-checked line by line. The synthesis in
../03-recursive-micro-simulation.md is the document of record; this file is the
evidence base behind it. -->

# Bounded sub-episodes and fidelity allocation in LLM social simulation (2023–2026): a survey for jeve


## Summary table

| Work | ID | Sub-episode / fidelity mechanism | Bounded by | Write-back | Typed? | Nesting |
|---|---|---|---|---|---|---|
| Generative Agents (Park+ 2023) | arXiv 2304.03442 [V-src] | Dyadic chat spawned on perception; ≤8 rounds, per-utterance LLM calls | 8 rounds or model-declared end | Prose summary → schedule slot + memory node; 800-tick cooldown | No | 0 |
| Concordia v1.8 (2023–24) | arXiv 2312.03664 [V-src v1.8.10] | GM detects speech → spawns conversation GM with own memory, finer clock, NPCs | ≤20 steps or LLM "key question answered" | One-sentence summary to players + main GM memory | No | 1 (fixed) |
| Concordia v2.x (2025–26) | github main @2026-09-14 [V-src] | Pre-scheduled `SceneSpec`s switch GMs; typed *decision scenes*; interrupt-driven GM with masks/timers | `num_rounds` | Payoffs→numbers→observation text | Yes (decision scenes) | 0 |
| HiSim (Mou+ 2024) | arXiv 2402.16333 [V-src via DeepWiki] | 300 LLM "core" users + rule ABM crowd | 1 call/user/round | LLM stances mirrored into ABM state | Yes (enum actions) | 0 |
| AgentTorch archetypes (Chopra+ 2024) | arXiv 2409.10568 [V] | Identical-profile agents share one LLM query; `n_arch` copies averaged | – | Float broadcast to all group members | Yes (float) | 0 |
| Lyfe Agents (Kaiya+ 2023) | arXiv 2310.02172 [V] | Option–action hierarchy; talk as persistent option | option exit | memory summaries | No | 0 |
| Humanoid Agents (Wang+ 2023) | arXiv 2310.05418 [V-src] | Co-located dyad → `dialogue(max_turns=10)` | 10 turns or `reaction is None` | transcript to memory; closeness ±1; emotion enum | Partly | 0 |
| Sotopia (Zhou+ 2023) | arXiv 2310.11667 [V] | Standalone dyadic episode | 20 turns / `leave` / stale | 7 integer scores by LLM judge | Post-hoc | 0 |
| AgentSociety (Piao+ 2025) | arXiv 2502.08691 [V] | Message chains between agents | `propagation_count>5`; comm budget | free text | No | 0 |
| OASIS (Yang+ 2024) | arXiv 2411.11581 [V] | 1 % random activation/step; function-call actions | – | platform DB | Yes (enum) | 0 |
| TinyTroupe (Microsoft) | github microsoft/TinyTroupe [V] | `TinyWorld.run(steps)`; `ResultsExtractor` → JSON fields; exact-input LLM cache | steps | extracted JSON | Post-hoc | 0 |
| Affordable Generative Agents (Yu+ 2024, TMLR) | arXiv 2402.02053 [V] | Lifestyle-policy pool (reuse plans), Social Impression Memory | – | – | No | 0 |
| Agent Hospital (Li+ 2024) | arXiv 2405.02957 [V] | Pipeline of dyadic consultations | stage | medical records, experience base | Partly | 0 |
| EconAgent (Li+ 2024, ACL) | arXiv 2310.10436 [V] | LLM emits numeric work/consume propensities into rule-based macro loop | monthly | numbers | Yes | 0 |
| APS (2026) | arXiv 2605.27419 [V-id] | Budgeted core-prototype / singleton-tail / shadow-audit agents; prototype responses propagated within strata | budget | – | – | 0 |

No surveyed system does typed-only sub-simulation, recursion beyond one level, or caching of identical *group* situations.

---

## 1. Generative Agents / Smallville — Park, O'Brien, Cai, Morris, Liang, Bernstein; UIST 2023; arXiv 2304.03442, DOI 10.1145/3586183.3606763 [V-src: `reverie/backend_server/persona/cognitive_modules/{plan,converse,perceive}.py`]

**Trigger.** Every tick, `plan()` retrieves the focal perceived event and calls `_should_react`. `lets_talk` is a rule gate first: both agents need an address/description, neither is sleeping, hour ≠ 23, target not `<waiting>`, neither is `chatting_with`, and `chatting_with_buffer[target] == 0`. Only then one LLM yes/no (`generate_decide_to_talk`). Otherwise `lets_react` may return "wait until X".

**Run.** `_chat_react` → `agent_chat_v2`: `for i in range(8)` alternating initiator/target; each utterance = memory retrieval (50 then 15 nodes) + a relationship-summary call + `run_gpt_generate_iterative_chat_utt`, whose template ends `{"<name>": "<utterance>", "Did the conversation end with <name>'s utterance?": <json Boolean>}`. Break on `end`. The whole exchange is produced inside one macro tick; while `chatting_with` is set the agent skips reaction ("default to no reaction").

**Bounding.** ≤16 utterances or self-declared end; cost ≈ 3 LLM calls per utterance.

**Write-back.** `generate_convo_summary` (one call) becomes the inserted activity; duration `ceil(len(text)/8/30)` minutes; both schedules re-decomposed (`generate_new_decomp_schedule`); `act_event=(name,"chat with",other)`; `chatting_with_buffer[other]=800`, decremented each step, to stop A/B re-chat loops. `perceive.py` stores the transcript via `a_mem.add_chat` with an LLM poignancy score. Everything folded back is prose.

**Plan recursion.** `generate_first_daily_plan` (5–8 chunks) → `generate_hourly_schedule` → `generate_task_decomp` into 5–15-minute chunks, decomposed just-in-time (`determine_decomp`) and regenerated from the reaction point onward.

**Evidence.** Human-rated believability of interview answers under ablation; information diffusion (candidacy 1→8, party 1→13 of 25 agents); network density 0.167→0.74; 1.3 % hallucinated awareness. Nothing isolates the contribution of the conversation sub-loop.

**Lesson for jeve.** The pieces jeve already has (rule gate, then one cheap decision) are the same shape as `lets_talk`; the two things worth copying are the hard rule pre-filter before any model call and the explicit *post-encounter cooldown* to prevent encounter loops.

## 2. Concordia — Vezhnevets et al. (DeepMind); arXiv 2312.03664, Dec 2023 [V]; source at tags v1.8.10 and main (commit 3e30a20, 2026-09-14) [V-src]

### 2a. v1.x: the dynamically spawned conversation scene (the closest structural precedent)

`concordia/components/game_master/conversation.py` (class `Conversation`) hooks `update_after_event` on the main GM. After every resolved event:

1. yes/no "Does the event suggest anyone spoke or communicated?"; per player yes/no "did X probably take part?"
2. Optional NPCs: yes/no "anyone else present?", open list capped at `cap_nonplayer_characters=3`, each a throw-away `BasicAgent` with a blank "burner" memory and a random conversational style.
3. Open question generates a **key question** (explicitly citing the Microscope tabletop RPG mechanic): the scene exists to answer it.
4. `make_conversation_game_master` (`environment/scenes/conversation.py`) builds a **separate GM** with its own memory and a `ConversationTracker` component; `run_episode(max_steps=max_conversation_length)` (default 20) executes inside `with self._clock.higher_gear()` — a `MultiIntervalClock` advances in finer steps during the scene.
5. Termination each step: `max_steps`, else two multiple-choice prompts ("has the key question been answered?", "is it now unlikely to be answered / would ending make narrative sense?").
6. Exit: one-sentence summary; `player.observe(summary)` for each real participant; `"Summary of a conversation between A, B. …"` added to the **main GM memory**; full transcript kept only in the log.

This is exactly "ad hoc group formation → bounded higher-resolution sub-simulation with local state and finer clock → fold back", but (i) fold-back is prose, (ii) termination is LLM-adjudicated, (iii) the conversation GM cannot itself spawn scenes (depth exactly 1), (iv) per-scene cost is up to 20 steps × participants plus ~6 GM calls.

### 2b. v2.x: pre-scheduled scenes, typed decision scenes, and the interrupt-driven GM

- `typing/scene.py`: `SceneTypeSpec(name, game_master_name, default_premise, action_spec, possible_participants)`; `SceneSpec(scene_type, participants, num_rounds, start_time, premise)`. `action_spec` may be `free_action_spec` or `choice_action_spec` and may differ per participant.
- `components/game_master/scene_tracker.py`: flattens all scenes into a round index, counts rounds with `[scene counter](n)` markers in GM memory, answers `NEXT_GAME_MASTER` with the scene's GM name, queues premises to participants at step 0, and fires `Terminate` when rounds run out. The engine loop (`engines/sequential.py: run_loop`) is: terminate? → next_game_master → observe all → next_acting → act → resolve. Scenes are therefore **scheduled GM switches**, not dynamic spawns; a shared `external_queue` carries pending observations across GM switches.
- Conversation vs decision: `dialogic_and_dramaturgic` GM (free speech) vs `game_theoretic_and_dramaturgic` GM (`choice_action_spec`, `action_to_scores`, `scores_to_observation`, `PayoffMatrix` component). The CHEATSHEET's "selling cookies" pattern is 4 rounds of conversation scene then a 1-round decision scene with `options=['Yes','No']`; numeric payoffs are converted to observation text. This is typed outcome + fold-back, but pre-scheduled.
- Conversations inside situated worlds were **collapsed** in v2: `event_resolution.Conversation` thought chain asks yes/no "does the event suggest a conversation?", lists participants, asks each participant agent `act()` **once** ("what would X say?"), then the GM ghost-writes the whole conversation in one ≤2200-token completion and every participant `observe()`s it. Cost: N+3 calls instead of ≤20×N. Not enabled by default in the situated prefabs. `higher_gear`/`MultiIntervalClock` no longer exist in v2.
- Interrupt-driven GM (2026; `prefabs/game_master/interrupt_driven.py`, `components/game_master/interrupt_{scheduling,next_acting,resolution,time_model}.py`, `examples/interrupt_driven/`): a shared event queue totally ordered by `(timestamp, tag, source, description)` ("this makes the event queue deterministic"); each entity holds a prefix-based **interrupt mask** and exactly one mandatory **timer**; each action ends with JSON `{"tags","mask","timer"}`; `InterruptNextActing` pops the earliest event/timer, **advances simulated time to it** (skipping dead air), polls only entities whose mask matches (clearing their mask and timer), and queues the event as a pending observation for everyone else. Time model is either `DatetimeTimeModel` (no LLM) or `GenerativeTimeModel` (LLM narrates time labels, cached; arithmetic deterministic). Runs on the Simultaneous engine. There is also a fully `Asynchronous` engine (per-entity threads).

**Evidence.** None quantitative for scenes; the tech report and examples are demonstrations.

**Lesson for jeve.** Take v1's shape (spawn-on-detection, own state, finer clock, hard step cap, explicit exit write-back) and v2's typed decision-scene contract (`choice_action_spec` + `action_to_scores`); reject v1's LLM-adjudicated termination and prose summaries. The interrupt GM's mask+timer scheduling is a direct model for "who is polled during an encounter and when the encounter ends".

## 3. HiSim — Mou, Wei, Huang; ACL 2024 Findings; arXiv 2402.16333; github xymou/HiSim [V; DeepWiki-read]

Core users are `TwitterAgent`s (AgentVerse) making **one LLM call per round**, parsed by `TwitterParser` into `post / retweet / reply / like / do_nothing`; ordinary users run mesa opinion models (`BCModel`, `BCMultiModel`, `RAModel`, `SJModel`). Coupling: the ABM carries attitude state for *all* agents; LLM agents' stances are mirrored into it via `update_mirror`, so rule agents respond to LLM agents' posts; trigger events enter as background text. Li & Tao (arXiv 2603.00113) describe it as 1,000 users per movement with 300 core LLM users. Evaluation (SoMoSiMu-Bench) compares stance-distribution bias/diversity and cascades with empirical data; secondary sources report the hybrid beating full-LLM and pure-ABM baselines [V via search summary, not the paper].

**Lesson.** Fidelity by *role*, enumerated actions, and a mechanistic substrate that holds shared state; the LLM layer never returns prose to the crowd.

## 4. AgentTorch archetypes — Chopra et al.; "On the limits of agency in agent-based models", arXiv 2409.10568 [V]; github AgentTorch/AgentTorch [V; DeepWiki-read]

`Archetype.broadcast(population, group_on=...)`: agents with identical `group_on` attributes share one rendered prompt; `n_arch` LLM copies answer and are **averaged**; the float (e.g. isolation probability) is broadcast as a tensor to every member; `last_k` bounds conversation history. Population 8.4 M (NYC); sensitivity over GPT-3.5/4o and M = 1, 3, 6 queries per archetype. Abstract claims archetypes beat both full LLM-agents (infeasible at scale) and heuristic agents on population statistics.

**Lesson.** This *is* cache-sharing of identical situations with typed output — but at population, not group, granularity. jeve's "identical (state, questions) share one call" is the same principle applied per encounter; the averaging-over-`n_arch` trick is how they regain probabilities from samples, which Jev returns natively.

## 5. Lyfe Agents — Kaiya et al. 2023; arXiv 2310.02172 [V]

Option–action hierarchy: agent picks a high-level option (e.g. talk, search) and then low-level actions until the option exits, so most ticks make no high-level call; summarize-and-forget memory; feedforward memory; claimed 30–100× cheaper than Park et al.; evaluated in LyfeGame 3D scenarios (murder mystery, etc.). Per-agent-hour cost figure and exit rules [M].

**Lesson.** Persistent "option" state across ticks is a cheap way to make an encounter multi-tick without re-asking the entry question.

## 6. Humanoid Agents — Wang, Chiu, Chiu; EMNLP 2023 demo; arXiv 2310.05418 [V-src: `humanoidagents/humanoid_agent.py`]

`dialogue(other, curr_time, max_turns=10)`: each turn is a reaction call (may return `None` → conversation ends) plus a speech call conditioned on basic needs, emotion and closeness. Exit: transcript to both memories (`memory_type="dialogue"`); then one yes/no per side, `"Did {name} enjoy the conversation?"` → `closeness += 1 / −1`; emotion re-classified into a 7-word enum; basic needs clipped to 0–10. Evaluation: human agreement with the model's judgments of need/emotion changes.

**Lesson.** The only ad hoc dyadic sub-episode surveyed that folds back a **typed** result (±1, enum); the interior is still generative. Shows how thin the typed fold-back can be and still drive behaviour.

## 7. Sotopia — Zhou et al.; ICLR 2024; arXiv 2310.11667; github sotopia-lab/sotopia [V; DeepWiki-read]

`ParallelSotopiaEnv`: action types `none/speak/non-verbal/action/leave`; round-robin or simultaneous; `RuleBasedTerminatedEvaluator` ends at `max_turn_number=20`, on `leave`, or on stale turns; `EpisodeLLMEvaluator` then emits seven integer scores (believability 0–10, relationship −5..5, knowledge, secret −10..0, social rules, financial, goal). Sotopia-π (ACL 2024) and Lifelong Sotopia (arXiv 2506.12666) extend it; no embedding in a larger world.

**Lesson.** Typed *post-hoc* scoring of a prose episode is a viable middle path if jeve ever needs a generative interior; the 20-turn/leave/stale triad is the standard bound.

## 8. Large-scale platforms (no sub-episodes)

- **AgentSociety** (Piao+ 2025, arXiv 2502.08691; v2 arXiv 2607.11895) [V; DeepWiki]: `send_message_to_agent`; chats bounded by `propagation_count > 5` and a per-agent `_communication_left` budget; `chat_probability`; free text; 10k agents, ~500 interactions/agent/day; reproduced polarization, inflammatory spread, UBI, hurricane shock.
- **OASIS** (Yang+ 2024, arXiv 2411.11581) [V; DeepWiki]: 1 % of agents randomly activated per step; enumerated `ActionType` exposed as function tools; `asyncio.gather` under a semaphore; groups via `CREATE_GROUP/SEND_TO_GROUP`; up to 1 M agents; finding that scale changes group phenomena.
- **GenSim** (Tang+, NAACL 2025 demo; arXiv 2410.04360) [V]: AgentScope-based, 100k agents, error-correction; roughly linear time in agents.
- **YuLan-OneSim** (Wang+ 2025, arXiv 2505.07581) [V; DeepWiki]: asyncio `EventBus`; `ROUND` vs `TIMED` modes; ODD text compiled by `WorkflowAgent` into an action/event graph; "scene" only as scenario metadata.
- **SocioVerse** (arXiv 2504.10157) [V]: 10 M-user pool with alignment modules; survey-style typed outputs.
- **Project Sid / PIANO** (Altera 2024, arXiv 2411.00114) [V]: concurrent modules with a coherence bottleneck; 10–1000 agents; notes hallucinations compounding across LLM calls and agents.
- **Park et al. 2024** (arXiv 2411.10109) [V]: interview-grounded individual agents answering typed survey items — the strongest validation of *typed* LLM outputs at the individual level.

**Lesson.** Hop-count and per-agent communication budgets (AgentSociety), enumerated actions as function calls (OASIS), and event-bus timing (YuLan) are the field's standard cost governors; none allocates fidelity per *interaction*.

## 9. Typed-decision economies and organisations

- **EconAgent** (Li, Gao, Li, Li, Liao; ACL 2024; arXiv 2310.10436) [V]: LLM returns numeric work/consumption propensities monthly into a rule-based market/central bank; 100 agents; macro stylized facts. **TwinMarket** (arXiv 2502.01506, NeurIPS 2025) [V; DeepWiki]: structured `stock_decisions {action, target_position, target_price}`, belief updates, forum like/repost; 1,000 agents; fat tails, volatility clustering. **CompeteAI** (Zhao+, ICML 2024 oral; arXiv 2310.17512) [V]: restaurant vs customer agents, daily choice loop. **Shachi** (Sakana, arXiv 2509.21862, ALIFE 2026) [V; DeepWiki]: Pydantic `response_type` per observation; structured output or function calling; environment `step(responses)` is the only group-level abstraction.
- **MetaGPT** (arXiv 2308.00352) / **ChatDev** (arXiv 2307.07924) [V]: organisation as a fixed SOP / chat chain of role-pair phases with document artefacts; ChatDev's "communicative dehallucination". **Agent Hospital** (Li+ 2024, arXiv 2405.02957) [V]: patients traverse triage→consultation→examination→diagnosis→treatment→follow-up as dyadic dialogues; doctors accumulate a record library and an experience base (MedAgent-Zero) over tens of thousands of patients and improve on MedQA. **RecAgent** (arXiv 2306.02552) and **S3** (arXiv 2307.14984) [V]: round-based activation (Pareto), one-on-one chats and broadcasts; S3 tracks numeric emotion/attitude.

**Lesson.** Typed numeric outputs from LLMs inside mechanistic loops are well established (EconAgent, TwinMarket, AgentTorch, Park 2024); what is not established is a *multi-round group* interior that is typed.

## 10. Cost/fidelity work, 2024–2026

- **Affordable Generative Agents** (Yu, Zhang, Li, Fu, Ye; TMLR 2024; arXiv 2402.02053) [V; README read]: "Lifestyle policy" pool reuses previously generated plans for recurring situations, and "Social Impression Memory" compresses what an agent knows of others before dialogue; both on by default, ablatable (`--disable_policy`); token statistics per function shipped. Reported cost reduction [M].
- **TinyTroupe** [V; DeepWiki]: no nested worlds; `ResultsExtractor.extract_results_from_world(extraction_objective, fields, fields_hints)` turns transcripts into JSON; `CACHE_API_CALLS` keys on the exact input; `control.begin/checkpoint/end` cache simulation state for reruns.
- **APS** (arXiv 2605.27419) [V-id]: budgeted "core-prototype", "singleton-tail" and "shadow-audit" agents; prototype responses propagated within strata — the most explicit 2026 statement of adaptive fidelity by population stratum.
- **Open-Theatre** (arXiv 2509.16713) [V]: director–global-actor scene control at 2.0 LLM calls/turn vs 3.4 for director–actor.
- Related, id-verified only: LLM+diffusion hybrid (arXiv 2510.16366), topology-aware grouping (arXiv 2604.18011), AI Metropolis out-of-order execution on agent dependencies (arXiv 2411.03519; speedups [M]), EcoLANG induced compact communication language (arXiv 2505.06904), classic-AI scaffolding (arXiv 2609.01167), AgentGroupChat multi-party debates (arXiv 2403.13433), Simulating Teams in 2D (arXiv 2510.08242), NegotiationGym (arXiv 2510.04368), Multi² hierarchical decision-making (arXiv 2606.03698).

## 11. Surveys and critiques

Gao et al., "LLM-empowered ABM and simulation: a survey and perspectives" (arXiv 2312.11970; HSSC 2024) [V]. Mou et al., "From individual to society" (arXiv 2412.03563; ACM CSUR 58(11), DOI 10.1145/3800683) [V] — its middle category, *scenario simulation* (a few agents pursuing a goal in a bounded context), is the closest taxonomic slot for jeve's sub-episode. Larooij & Törnberg (arXiv 2504.03274) [V]: validation "poorly addressed", most studies rest on believability. Taillandier et al. (arXiv 2507.19364) [V]: proposes "Hybrid Constitutional Architectures" stratifying ABM / small LMs / LLMs inside GAMA/NetLogo. Li & Tao (arXiv 2603.00113) [V]: role-play plausibility ≠ behavioural validity; outcomes are often driven by agent–environment co-dynamics and by the interaction *protocol*. Flint, Aiello, Pastor-Satorras, Baronchelli (PNAS 2026, DOI 10.1073/pnas.2531697123; arXiv 2510.22422) [V]: group size shifts LLM collective dynamics nonlinearly with a critical size. Ghaffarzadegan et al. (arXiv 2309.11456; SDR) [V]: couple an LLM to a mechanistic system-dynamics model — the earliest "typed LLM decision inside a mechanistic loop" statement.

---

## (a) Closest precedent

**Concordia v1.8's `Conversation` component + conversation scene** is the only surveyed system that *dynamically* forms a group from an event, gives it its own game master, memory, participants (including transient NPCs), finer clock and step cap, then folds a result back into the main loop and participants' memories. Its deficits relative to jeve's idea are exactly the interesting ones: prose in and out, LLM-judged termination, depth 1, and cost. The typed half of the idea exists separately in **Concordia v2's decision scenes** (`choice_action_spec` → `action_to_scores` → observation), in **Humanoid Agents'** ±1 closeness / emotion-enum fold-back after an ad hoc dyadic scene, and in **AgentTorch's** shared-query archetypes. Nobody has joined the three.

## (b) Known failure modes

1. **Prose drift / endless scenes** — Concordia v1 needed a key-question mechanic and a 20-step cap; GA needed an 800-tick cooldown; AgentSociety a 5-hop limit. Concordia v2 abandoned nested conversations for a one-shot ghost-written exchange, largely on cost.
2. **Homogenisation and hallucinated consensus** — negotiation agents show "diversity without fidelity" (arXiv 2604.11840); smaller models conform more (arXiv 2507.22467); Project Sid documents hallucinations compounding across calls and agents; PNAS 2026 shows group-size-dependent collective bias.
3. **Protocol dominance** — Li & Tao: results are often artefacts of the interaction protocol, which is a warning that sub-episode *design* (rounds, order, who is polled) will itself shape macro outcomes.
4. **Cost blow-up** — Smallville-style per-utterance calls (≈3 per line); Lyfe's 30–100× and AGA's policy pools exist because of it.
5. **Believability-only evaluation** — Larooij & Törnberg; "Stop drawing scientific claims… without robustness audits" (arXiv 2605.18890); "LLM-based social simulations require a boundary" (arXiv 2506.19806); "Too human to model" (arXiv 2507.06310). No paper isolates the causal contribution of a sub-episode mechanism to downstream outcomes.

## (c) Genuinely absent

- **Typed-only (non-generative) sub-simulations.** Every multi-round group interior found is generative; typed outputs appear only at the *decision* boundary (Concordia decision scenes, EconAgent, TwinMarket, AgentTorch, Park 2024) or as post-hoc extraction (Sotopia-Eval, TinyTroupe `ResultsExtractor`, Humanoid ±1).
- **Recursion deeper than one level.** Concordia v1 is depth-1 by construction (the conversation GM has no `Conversation` component); MetaGPT/ChatDev have fixed two-level SOPs, not spawnable scenes; nothing else nests at all.
- **Cache-sharing of identical group situations.** Only population-level sharing exists (AgentTorch `group_on`, APS prototype propagation) plus TinyTroupe's exact-input call cache. No system canonicalises a small-group state and reuses the episode result.
- **Deterministic replay of group episodes.** Concordia's 2026 interrupt GM orders events deterministically and TinyTroupe checkpoints state, but with stochastic LLM interiors; a replayable typed interior with causal ids is not in the literature.
- **Ad hoc formation with variable clock resolution + typed fold-back**, evaluated on downstream causal outcomes rather than believability.

## Design lessons distilled for jeve

- Gate encounters with rules first, then one probability question (GA `lets_talk`); add a cooldown per pair (GA 800 ticks) and a hop/round cap (AgentSociety 5, Sotopia 20, Concordia 20).
- Give the sub-episode Concordia-v1 structure — own participants, local state, finer clock, hard cap, explicit exit write-back — but Concordia-v2 typed action specs and a payoff-style `action_to_scores` fold-back.
- Terminate by typed question ("did this resolve? / continue?") with a cap, never by prose judgment.
- Use masks and timers (interrupt GM) to decide who inside a group is polled each sub-tick; let disengagement be a typed choice.
- Treat AgentTorch's `group_on` as the model for canonicalising group states for cache sharing; average or sample from returned probabilities rather than from repeated calls.
- Validate against downstream event timings (jeve's "earlier fix → earlier invoices"), which no prior work does; the field's believability metrics will not discriminate.