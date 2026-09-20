# 01 — Prior-art mapping: what is typed-decidable?

Sources read at source level on 2026-09-20:

- **Concordia** `google-deepmind/concordia` v2.4.0, HEAD `3e30a20` (2026-09-14). HEAD contains
  an unreleased interrupt-driven game master not in the changelog.
- **Smallville** `joonspk-research/generative_agents` + the paper (arXiv 2304.03442).
- **workbench** `~/projects/workbench` (see 00 §6).

**Evidence tags.** `[V]` I checked it in the source myself. `[A]` reported by a research agent
that read the source (file paths in its report), not re-checked by me. Neither codebase was
executed, so every call *count* is derived from reading code or from a shipped saved run.

**Classes.**

| | Meaning |
|---|---|
| **C** | Plain code. No model. |
| **T** | Typed-decidable: a Jev `noul`, `choice`, or `score` over supplied state is sufficient. |
| **T+G** | A typed gate decides *whether / which*; prose is needed only for content. |
| **G** | Generation required: free prose is inherent to the output. |

Typed questions come in two kinds, and jeve must treat them differently (ADR-004, ADR-007):

- **J — judgment** about the state ("is this ticket a billing issue?"). Act on the
  argmax/threshold. This is the use Jev was trained and calibrated for.
- **P — propensity** ("what does Priya do next?"). **Sample** from the returned distribution
  with our seeded PRNG. This use is *not* validated by anything in TypeSafe's docs (00 §0).

---

## 1. Headline evidence

| System | Finding | Tag |
|---|---|---|
| Smallville | 38 prompt sites (34 `run_gpt_*` functions `[V]` + 4 raw prompts in `revise_identity`); 27 live in the loop. Weighted by call frequency in the one saved 3-agent sim-day that ships with the repo: ≈1,257 LLM calls per agent-day, of which **48% T, 35% C, 12% T+G, 5% G**. | `[A]` — the agent's own computation from one saved run |
| Concordia v2 | Core call sites: **70 `open_question`, 14 `multiple_choice_question`, 16 `yes_no_question`** `[V]`. ≈20 of the open questions ask for structure disguised as prose (name lists, `name\|value`, JSON specs, integers) `[A]`. Per sequential step with N entities and the default prefabs: 2N+16 to 4N+16 LLM calls, 25–45% already typed, **2–6 inherently prose**. | counts `[V]`; per-step derivation `[A]` |
| workbench | The typed `decide` call is 38–66% of LLM calls and 54–75% of prompt tokens; ≈62% of decides end in an outcome needing no drafter call. | `[A]`; signature and cassette shape `[V]` |

Read together: **by call count, 80–90% of what these loops ask a language model is already a
typed question or should have been code.** By *tokens* the generative share is larger (AGA
measured ≈2,000 prompt tokens of retrieved events per dialogue turn `[A]`), and the
frequency mix comes from one small saved run. It is strong evidence the thesis is worth
testing; it is not a result.

One more finding that frames the project. Concordia's `sample_choice` interface returns
`(index, response, info)`. The OpenAI backend returns `info = {}`; the HuggingFace backend
returns **per-option log-probabilities** in it; and the only caller,
`InteractiveDocument.multiple_choice_question`, binds that value and discards it `[V]`. The
base docstring even warns sampling "may not reflect the underlying log_probabilities." So
Concordia has the plumbing slot for a decision distribution and throws it away; no component
can act on confidence. (The agent's report said probabilities are "never returned" — true
at the component level, not at the backend level.) jeve is, in one sentence, *what happens
if you keep that value and build the loop around it.*

---

## 2. The table

Frequencies are per agent per sim-day (Smallville, from the saved run `[A]`) or per
sequential step (Concordia `[A]`).

### Perception

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| What an agent notices | `perceive.py`: square window `vision_r`, same-arena filter, nearest `att_bandwidth` events, dedupe against last `retention` | Observation queue drained in code | C | Typed events delivered by org/role subscription into an inbox. Attention bandwidth becomes a **hard cap on items rendered into `state`** — Jev's context rot makes this mandatory, not cosmetic. | **C** | `world.perception` |
| Observation when nothing is queued | — | `make_observation` fallback: "What does {X} observe now?… Keep the story moving forward" + format-check YN + reformat | G + T + G | Never. No queued event → no observation. This fallback is a hallucination source by design. | **C** | — |

### Memory write

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Importance / poignancy | 1–10 integer prompt per new non-idle event (185–247/day) + per thought + per chat. Idle events short-circuit to 1 in code. `int()` parse, no range check. | none (no importance column at all `[V]`) | T | Jev `score` with **described** levels (Jev's docs show numeric level labels fail). Batched: every new inbox item is scored in the same request as the decision surface — they are in `state` already. J-type. Rule-based floor in code for event kinds with obvious importance (workbench does this). | **T (J)** | `memory.importance` |
| Event triple (s, p, o) | LLM call per action and per thought (≈275/day) | — | C | Events are born typed `{actor, verb, object, refs}`. | **C** | `world.events` |
| Emoji, object-state phrase | 2 + 1 calls per action (≈240/day) | — | C / T+G | Lookup by verb. | **C** | `web` |

### Retrieval

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Scoring | `new_retrieve`: min-max-normalised recency, relevance, importance; weights **`gw = [0.5, 3, 2]`** `[V]` (paper says all 1). Recency is `decay ** rank`, **over rank not time** `[V]` (paper: 0.995 per sandbox hour). Top-30. | Top-k dot product over a 2-column DataFrame `[V]`; `retrieve_recent`; `scan` | C | Recency (true sim-time decay) and importance in SQL. **Relevance is relational first**: jeve events carry typed entity ids, so "memories about this client / ticket / person" is a join, not a similarity search. No embeddings in MVP. | **C** | `memory.retrieval` |
| Relevance rerank | embedding cosine | embedding dot | C | Only when the relational filter returns more than *k*: one Jev `choice` whose options are the candidate memory ids yields a relevance distribution in a single question (TypeSafe's line-search cookbook does this over 218 ids), or one `noul` per candidate. A real second request, because the decision state depends on it. | **T (J)**, optional | `memory.retrieval` |
| Query formation | — | `AllSimilarMemories`: LLM summarises the context to form the embedding query, once per act *and* once per GM act | G used as C | Query = the entity ids in the current situation. | **C** | `memory.retrieval` |

Side note `[V]`: as written, Smallville sorts candidates by `last_accessed` ascending and
assigns `decay ** 1` to index 0, so the *oldest*-accessed memory gets the highest recency
score. Nothing was executed and I found no upstream issue; treat as "reads inverted".

### Reflection

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Trigger | Sum of event poignancy counts down from `importance_trigger_max` (150 default; **250 in all 25 shipped personas**) | — | C | Same: accumulated importance per (agent, entity) crosses a threshold, plus a sim-daily floor. | **C** | `memory.reflection` |
| Focal points | LLM generates 3 questions over recent memories | — | G | The entities with the most new high-importance memories. | **C** | `memory.reflection` |
| Insights | 5 insights × 3 focal points with evidence pointers; each then gets a triple + poignancy call → **34 LLM calls per reflection**; measured 6–9 reflections per agent-day (paper says 2–3) | none | G | **Typed belief revision over a fixed schema**: for each (belief dimension, entity) slot — reliability, trust, fairness of price, workload strain — one Jev `score` over the evidence memories. The slot set is per-role config. | **T (J)** | `memory.beliefs` |
| *New* concepts | implicit in free-text insights | — | G | **Ontology extension**: a rare LLM call (weekly per agent, or when triggered by ontology-gap events) proposes new belief slots or goals *as structured data*, validated against a schema. | **G**, rare | `gen.ontology` |
| Post-conversation memo + planning thought | 2 calls + 2 triples + 2 poignancy per participant | — | T+G | Typed commitments extracted by `noul` per candidate commitment kind ("did B agree to pay by Friday?"). | **T (J)** | `memory.beliefs` |

### Planning

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Wake hour | LLM → int | — | T | Role schedule + a persona parameter. | **C** | `agents.schedule` |
| Daily plan | Broad-strokes prose (first day only; later days run `revise_identity`, 4 raw calls) | `Plan`: "should {name} change their current plan?" (YN) + "write a step-by-step plan" (OQ) | G | **The plan is a ranking of work items that already exist**, not invented prose. One `score` per open work item ("how pressing does she consider this today?") in one request; code sorts. P-type. | **T (P)** | `agents.planning` |
| Hourly schedule, 5-minute decomposition | ≈17 calls/day × ≤3 passes; ≈8–11 decomposition calls/day | — | T+G | Work items carry typed effort. Code schedules. Office work does not need 5-minute decomposition. | **C** | `agents.planning` |
| Identity revision | 4 prose calls per new day; `daily_req` never actually regenerated (literal TODO) | `SelfPerception` over all memories every act | G | Static persona card + typed belief/mood slots. | **C** + T | `agents.persona` |

### Action selection — the core

| Mechanism | Smallville | Concordia v2 | workbench | Class today | jeve | jeve class |
|---|---|---|---|---|---|---|
| What to do next | `_determine_action` reads the schedule | `Act FREE`: "What would {name} do next?" 2,200-token open question, after a **3-call sequential perception chain** (`SituationPerception`, `SelfPerception`, `PersonBySituation`) | `DecideNextAction` → `Literal[13 verbs]` + `target_ref` + free-text `intent` | G / T+G / LLM-typed | **One request per decision point carrying the role's whole decision surface**: `choice` over the role's verb enum + `other` (P); `choice` over pending refs for the target (P); per-verb parameter questions asked speculatively (tone `choice`, urgency `score`, accept/decline `choice`); situation classification (J). The perception chain collapses into the question set. | **T** |
| Constrained choices | — | `Act CHOICE` (MCQ, capped at 26 options by an a–z `zip`) | `ChoiceActionSpec` declared, never used `[V]` | T | native | **T** |
| Numeric actions | — | `Act FLOAT` = open question + `float()`; **never requested anywhere** in library, contrib, or examples `[V]` path, `[A]` "never" | `FloatActionSpec` declared, never used `[V]` | T | `score` over named buckets; the number is computed in code from the bucket. Jev cannot do magnitudes. | **T** + C |

### Action grounding

| Mechanism | Smallville | Class today | jeve | jeve class |
|---|---|---|---|---|
| Where | Three **chained** choice-from-list calls: sector → arena → object (≈240/day). Chained because each depends on the last. `arena` has no membership check (KeyError upstream). | T | Location follows from verb + target. No spatial world in the MVP (ADR-010). If one is ever added: a single `choice` over ≤255 flattened leaf locations, not a chain — Jev questions cannot depend on each other within a request. | **C** |

### Reaction and interrupts

| Mechanism | Smallville | Others | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Talk? Wait? | `decide_to_talk` (yes/no), `decide_to_react` (1/2/3), behind code gates (asleep, hour 23, cool-down). The agent reads both as chain-of-thought prompts run at `max_tokens=20`, so they likely always hit their fail-safes — unverified. | — | T | `noul` / `choice` inside the fan-out. P-type. Code gates first. | **T (P)** | `agents.decide` |
| Re-plan after an interruption | LLM rewrites the hourly blocks; its fail-safe is already the deterministic answer | — | C | Code. | **C** | `agents.planning` |
| When to re-decide at all | every step (8,640/day) checks | Lyfe Agents: hold an option until a **non-LLM** termination check fires; removing this tripled LLM calls with no quality gain `[A]`. Concordia HEAD: interrupt masks + mandatory timers. | C | Wake policy: task finished, new inbox item above an importance floor, schedule boundary, mandatory timer. | **C** | `sim.scheduler` |

### Dialogue

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class | Module |
|---|---|---|---|---|---|---|
| Whether / with whom | code gates + yes/no | `Conversation` chain: "does the event suggest a conversation?" (YN), participants (open question → name list) | T | `noul` per co-present candidate. | **T (P)** | `agents.decide` |
| What is exchanged | Per utterance: retrieve 50 → **relationship summary recomputed every turn** → retrieve 15 → JSON `{utterance, ended}`. ≤16 utterances; 5 of 8 saved conversations hit the cap. | "Generate a conversation" | T+G | **Typed speech acts.** `choice` of act type (inform, request, remind, dispute, offer, accept, decline); `noul` per salient topic for "does A mention T to B?" — *this is the whole information-diffusion mechanic, and it needs no prose*; the receiver's response is its own decision. Completion is a property of the act type, in code. | **T (P)** | `agents.comms` |
| The words | the utterance | the transcript | G | **Rendered lazily for the viewer, cached, and never read back into decision state.** Prose is a view, not state. | **G**, on demand | `gen.render` |
| Relationship summary | LLM prose, every turn | — | G | Typed relationship slots (see Reflection). AGA's "Social Memory" made the same move and cut tokens to 58.6% on its own `[A]`. | **C** | `memory.beliefs` |

### Turn-taking and scheduling

| Mechanism | Smallville | Concordia v2 | Class today | jeve | jeve class |
|---|---|---|---|---|---|
| Who acts next | sequential `for persona` loop, no parallelism | Default generic GM: **LLM MCQ "Whose turn is next?"**; code variants exist; HEAD adds a discrete-event scheduler (sorted event queue, per-entity timers, interrupt masks, zero GM LLM calls) | T or C | Discrete-event scheduler. A model is never asked who goes next. | **C** |
| What form the action takes | — | `next_action_spec`: LLM emits a JSON spec, `json.loads`, unparseable → `RuntimeError` | T | The role determines the spec. | **C** |
| Simultaneity | — | `Simultaneous` engine joins all actions into one string for one resolve; no built-in conflict handling | — | Footprint-disjoint batching as in workbench: decisions in parallel, effects committed in canonical order. | **C** |

### Event resolution

| Mechanism | Concordia v2 | Class today | jeve | jeve class |
|---|---|---|---|---|
| Does it succeed? | "Does the attempted action succeed?" (YN) + "Why did it fail?" (open question) | T+G | Rules wherever a rule exists: ledger, permissions, capacity, SLA clocks, system availability. | **C** |
| Who knows about it? | Open question → comma-separated name list | T | Subscription rules. | **C** |
| Consent of affected parties | `AccountForAgencyOfOthers`: `q.act(CHOICE Yes/No)` — runs the bystander's **entire 4-call pipeline, with side effects, mid-resolve** to get one bit | T | It is simply the other agent's own decision at its next wake. | **T (P)** |
| Narration | "What happens as a result…", "…take a stance… **and invent when necessary**" | G | Nothing is narrated into state. | — |
| Putative event → event | yes | — | Keep: intent → validated → event, with reject-with-guidance back to the agent (workbench). | **C** |
| Fuzzy outcomes with no rule | — | — | Exogenous counterparties (walk-in customers, the cafe's supplier, the landlord) are seeded stochastic processes in code. | **C** |

### World state, time, persistence, forgetting

| Mechanism | Smallville | Concordia v2 | jeve | jeve class |
|---|---|---|---|---|
| World state | Tile map + JSON files | `WorldState`: **the LLM authors a `name\|value` dict; nothing is ever deleted**. `Inventory`: balance enforced only by a prompt sentence; parse failure falls back to "+1 or lose all units" `[A]`. Every in-tree economic example does money in code instead `[A]`. | Double-entry ledger and typed tables. Non-negotiable. | **C** |
| Clock | 10 sim-seconds per step; **an open browser tab drives the clock through files**; timestamp equality checks are only correct when the step divides 60s `[A]` | v2 removed clocks; `GenerativeClock` asks the LLM what time it is | ADR-001. | **C** |
| Survive a kill | Save only on explicit command; every sim is a full `copytree` fork (210k files in the repo); `last_accessed` not persisted | Full-snapshot JSON per step (O(steps²) disk), non-atomic writes, engine cursor and RNG **not restored**, open issue #331 | workbench's one-transaction-per-step, ported to Postgres. ADR-009. | **C** |
| Forgetting | Thoughts get `expiration = +30 days`; **nothing enforces it** | "memories cannot be deleted" `[V]`; the basic prefab sets history length to 1,000,000, so prompts grow linearly per act | ADR-006. Neither system was built to run longer than days. | **C** + T |

---

## 3. Scorecard for jeve's design

Counting the 41 mechanism rows above by their jeve class (three rows are mixed — identity
revision and forgetting are C with a T component, numeric actions are T with a C component —
and are counted under their primary class):

| Class | Rows | What they are |
|---|---|---|
| **C** — code | 26 | perception (2), event triples, cosmetics, retrieval scoring, query formation, reflection trigger, focal points, wake hour, schedule decomposition, identity, grounding, re-planning, wake policy, relationship storage, turn-taking (3), success, awareness, intent validation, exogenous outcomes, world state, clock, persistence, forgetting |
| **T** — Jev | 12 | importance, relevance rerank (optional), belief revision, commitments, plan ranking, action choice, constrained choices, numeric actions via buckets, talk/react, whether to converse, speech acts, consent |
| **G** — LLM | 2 | lazy prose rendering; ontology extension |
| removed | 1 | LLM narration of outcomes |

Rows are mechanisms, not call volume, so this is a statement about *where* models appear in
the design, not how often they run. §1 has the frequency-weighted evidence.

Two design principles fall out, and both are stronger than "use Jev as a classifier":

1. **Prose is a view, not state.** No causal path in the simulation reads generated text. An
   email is `{act: payment_reminder, tone: firm, refs: [inv_17], deadline: …}`; the receiver
   decides on those fields; the words are rendered when a human opens it. This removes
   generation from the tick entirely, removes agent-to-agent prompt injection (Jev is
   documented as steerable by adversarial state), and makes the sim's behaviour independent
   of which LLM renders it.
2. **Jev decides inside the ontology; the LLM extends the ontology.** Verbs, speech-act
   types, belief slots, and work-item kinds are enums. A typed system cannot invent a new
   one. So every verb `choice` carries an `other` option, and mass on `other` is logged as an
   **ontology-gap event**. The **ontology-gap rate — the share of decision points where no
   typed option fit — is the direct measurement of the research question**, and the trigger
   for the rare generative call that proposes a new enum member for review.

## 4. Where I expect typed decisions to fail

Stated now so the MVP instruments for them rather than discovering them.

| Risk | Why | What would show it |
|---|---|---|
| **Persona flattening** | P-type questions are one hop of indirection ("would *a person like this* do X") — a documented Jev weakness. LLM sims already homogenise (02). | Pairwise JS divergence between personas' action distributions in matched situations ≈ 0. **M0 tests this on workbench cassettes before anything is built.** |
| Hazard-rate distortion | Sampling a propensity every tick makes event frequency a function of tick rate: p = 0.02 for "quit" asked 32×/day fires within days. | Rare-event rates scale with clock resolution. Fix is structural: irreversible actions are evaluated only at event-triggered decision points, with hysteresis in code (ADR-004). |
| Absorbing `idle` | The safest option has the highest probability; argmax picks it forever. workbench's LLM chose `idle` in 75% of Calder decides `[A]`. | Idle fraction, action entropy. Sampling instead of argmax is the first mitigation. |
| No novelty | Closed enums cannot produce the unplanned Valentine's party. jeve's emergence must come from **interaction structure** (cash constraints, queues, dependencies), not from invented actions. | If the named cascades in the scenario doc do not appear, the thesis fails at the macro level even if every micro decision looks fine. |
| Believability of rendered prose | Text generated from typed acts after the fact may read as hollow, or contradict state. | LLM-judge consistency check of rendered prose against the typed act (02). |
| Reflection without abstraction | Fixed belief slots cannot form "Klaus is dedicated to his research"-style insights. | Agents fail to adapt to regime changes not anticipated by the slot schema. |

## 5. What the cost-cutting literature replaced, and with what `[A]`

| Work | Replaced | With | Reported saving |
|---|---|---|---|
| Affordable Generative Agents (arXiv 2402.02053) | Plan decomposition; retrieved-event context in dialogue | Embedding-matched cache of prior decompositions (cosine > 0.97 + condition match); typed relationship keywords + ≈100-token running summaries | Tokens to 31.1% (3 agents), 42.7% (25 agents). Also reports distinct activities **saturate** — sampling changes wording, not behaviour, which supports an enum action space. |
| Lyfe Agents (arXiv 2310.02172) | Per-step action selection | Option held until a non-LLM termination check; async self-monitoring summary; summarize-and-forget memory | Claims 10–100× cheaper than Smallville; no-option ablation: ≈3× more calls, no quality gain. Dollar figures from a page summary. |
| OASIS (arXiv 2411.11581) | Free-form action | LLM picks among **21 fixed actions** via function calling; recommender, clock, DB in code | scale, not $ |
| AgentSociety (arXiv 2502.08691) | Free-text mind | Numeric emotions/needs/attitudes; mobility, traffic, and account-book economics in code | none found |
| Project Sid / PIANO (arXiv 2411.00114) | One serial LLM loop | Concurrent modules at different speeds; small non-LLM reflex nets; slow LLM goal generation behind a bottleneck | none given. Names "speech contradicting action" as a failure — the argument for principle 1 above. |
| 1,000 People (arXiv 2411.10109) | The town loop entirely | LLM conditioned on interview transcripts answering **typed** survey/game items | 85–86% of participants' own 2-week retest accuracy |

The agent's search found **no paper that replaces a Smallville-style loop with a
non-autoregressive typed-question evaluator**. That is absence of evidence from one search,
not proof of novelty.

## 6. What jeve must not copy

- Concordia: prose perception chain re-run every act over unbounded history; LLM-authored
  world state, clock, and locations; numbers and name lists parsed out of prose; hard-sampled
  yes/no with the distribution discarded; a global GM lock; per-step full-snapshot
  checkpoints; hard crashes on format errors (`RuntimeError` on a bad action spec,
  `InvalidResponseError` after 20 MCQ retries).
- Smallville: a per-10-second step loop; a clock driven by a browser tab; a relationship
  summary regenerated every utterance; ChatGPT wrappers that return `False` on failure so
  declared fail-safes are dead code and callers crash on `[0]` (upstream #91); hyperparameters
  that differ between paper, code defaults, and shipped personas.
- Both: no forgetting, no compaction, no restart story.

## 7. What is worth borrowing

- Concordia: the `ActionSpec` contract; **GM-as-dispatcher over typed sub-questions with
  pass-through components**, which lets an LLM decision be swapped for code without touching
  the engine; the observation queue with LLM fallback disabled; putative-event → event;
  the interrupt scheduler's masks and mandatory timers; per-component `get_state`/`set_state`.
  Its maintainers' own guidance (issue #26 `[A]`) is that grounding belongs in components
  that "ask a series of yes/no and multiple choice questions in order to set the values of
  grounded variables" — the same conclusion from the other direction.
- Smallville: the retrieval triad; the importance-sum reflection trigger; the evaluation
  design (interviews with ablations — see 02); information diffusion and network density as
  end-to-end measures.
- workbench: see 00 §6.5.
