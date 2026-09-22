<!-- Raw strand report on social-science and organisational-simulation grounding, gathered by a research agent on
2026-09-22 for ../03-recursive-micro-simulation.md. The verification tags are the
agent's own: [V] confirmed from a search index, a GitHub mirror, or a fetched source
during that session; [M] from memory. Not re-checked line by line. The synthesis in
../03-recursive-micro-simulation.md is the document of record; this file is the
evidence base behind it. -->

# Small-group encounters as the unit of simulation: social-science and org-sim grounding for jeve's "recursive micro-simulation"

## Summary table

| # | Work | Venue / ID | Status | Core mechanism | Lesson for jeve |
|---|---|---|---|---|---|
| 1 | Coleman, *Foundations of Social Theory* (1990) | Harvard/Belknap | [V] | Macro→micro (situational), micro action, micro→macro (transformational): the "boat" | Encounters are the *transformational* arrow; macro state must enter as situational inputs |
| 2 | Hedström & Ylikoski (2010) | *Annu. Rev. Sociol.* 36:49–67, doi:10.1146/annurev.soc.012809.102632 | [V] | Mechanism-based explanation; ABM as the tool that links action theory to macro patterns | Sub-sim = explicit mechanism; log what it transforms |
| 3 | Simon (1962) "Architecture of Complexity" | *Proc. Am. Phil. Soc.* 106(6):467–482 | [V] | Near-decomposability: intra-subsystem interactions are fast and dense, inter-subsystem slow and weak | Justifies a finer clock inside a group and a coarse clock outside; fold back only aggregates |
| 4 | Squazzoni (2012) *Agent-Based Computational Sociology* | Wiley, doi:10.1002/9781119954200 | [V] | Macro emerges from heterogeneous agents interacting within given structures; nothing programmed at macro | Never write macro outcomes directly; only encounter outputs |
| 5 | Goffman, *Encounters* (1961) | Bobbs-Merrill | [V] | Focused gathering: participants sustain a single focus of attention; has membrane, entry/exit, ratified participants | Defines entry, participants, exit for the sub-sim |
| 6 | Goffman, "The Interaction Order" (1983) | *ASR* 48(1):1–17 | [V] | The interaction order is a domain in its own right, loosely coupled to macro structure | Sub-sim needs its own state, not just macro state re-read |
| 7 | Collins, *Interaction Ritual Chains* (2004) | Princeton; JSTOR j.ctt13x0rs3 | [V] | Ingredients (co-presence, barrier, mutual focus, shared mood) → outcomes (solidarity, emotional energy, symbols, morality); EE chains across encounters | Encounter returns EE deltas, solidarity, shared symbols; EE drives next-encounter choice |
| 8 | Bales, *Interaction Process Analysis* (1950) | Addison-Wesley | [V] | 12 act categories (task vs socio-emotional); groups cycle between task and maintenance | Round = one typed act per speaker; act categories are a natural enum |
| 9 | Harrington & Fine (2000) | *Soc. Psych. Q.* 63(4):312–323 | [V] | Small groups are the meso level; constitute and are constituted by social order | Group is a first-class level, not just a set of dyads |
| 10 | Fine, *Tiny Publics* (2012); Fine (2012) | Russell Sage; *Annu. Rev. Sociol.* doi:10.1146/annurev-soc-071811-145518 | [V] | Groups hold "idioculture": local shared references that persist and shape action | Persistent group memory (idioculture) beyond the encounter |
| 11 | Feld (1981) "Focused Organization of Social Ties" | *AJS* 86(5):1015–1035, doi:10.1086/227352 | [V] | Ties form around *foci* (workplaces, cafés) that organise joint activity | Locations are foci: co-location is the trigger for encounter formation |
| 12 | Tsebelis, *Nested Games* (1990) | UC Press | [V] | Apparently sub-optimal moves in one arena are optimal given a simultaneous game in another | Encounter payoffs must include the agent's outside arenas |
| 13 | Putnam (1988) "Two-Level Games" | *Int. Org.* 42(3):427–460 | [V] | Negotiator bargains at Level I subject to a Level II ratification win-set | Sub-sim outcomes must be ratifiable by macro constraints (budgets, bosses) |
| 14 | Ostrom, *Understanding Institutional Diversity* (2005); Ostrom (2011) | Princeton; *Policy Studies J.* 39(1) | [V] | Action situation = 7 working parts: participants, positions, actions, outcomes, action–outcome linkage/control, information, costs/benefits | The specification schema for a sub-sim |
| 15 | McGinnis (2011) | *Policy Studies J.* 39(1):51–78, doi:10.1111/j.1541-0072.2010.00396.x | [V] | Networks of *adjacent* action situations: one situation's outcome sets another's rules/participants | Formal "fold-back": outputs of one situation are inputs of adjacent ones |
| 16 | Montes, Osman & Sierra (2022) | *Artificial Intelligence* 311, doi:10.1016/j.artint.2022.103756 | [V] | Action Situation Language + engine grounds an IAD description as an extensive-form game | Action situations are machine-executable; rounds = game stages |
| 17 | Ghorbani, Bots, Dignum & Dijkema (2013) MAIA | *JASSS* 16(2)9 | [V] | IAD-based meta-model for building ABMs (action arena, roles, institutions) | Existing ABM schema that already uses Ostrom's parts |
| 18 | Carley (1991); Carley & Prietula (1994); Construct | *ASR* 56:331–354; Erlbaum; CASOS guide 2023 | [V] | Constructuralism: interaction ⇢ shared knowledge ⇢ interaction; knowledge and social network co-evolve | Return value = knowledge transferred; it alters future encounter probabilities |
| 19 | Carley & Svoboda (1996) ORGAHEAD | *Sociol. Methods Res.* 25(1):138–168, doi:10.1177/0049124196025001005 | [V] | Dual-level: individual learning inside, structural restructuring above | Two clocks, two levels, explicit coupling |
| 20 | Jin & Levitt (1996); Levitt et al. (1999) VDT/SimVision | *CMOT* 2(3) doi:10.1007/BF00127273; *Mgmt Sci* 45(11) doi:10.1287/mnsc.45.11.1479 | [V] | Actors as bounded information processors; exceptions, rework, coordination/meetings [M details] predict duration, cost, quality | Meetings are modelled explicitly and cost attention; sub-sim should consume actor time |
| 21 | Cohen, March & Olsen (1972); Fioretti & Lomi (2008) | *ASQ* 17(1):1–25; *JASSS* 11(1)1 | [V] | Decisions happen where streams of participants, problems, solutions and choice opportunities collide; resolution, oversight, flight | Encounter = choice opportunity; carry problems/solutions in; exit types are an enum |
| 22 | Feldman & Pentland (2003); Pentland & Feldman (2005) | *ASQ* 48(1) doi:10.2307/3556620; *ICC* 14(5):793–815 | [V] | Routines have ostensive (pattern) and performative (specific enactment) aspects; performances change the pattern | Standups etc. are routines: template + performance; drift is the fold-back |
| 23 | Burton & Obel (1995) | *CMOT* 1:57–71, doi:10.1007/BF01307828 | [V] | Validity = purpose × design × model; prefer the simplest model answering the question | Add resolution only where macro is sensitive to it |
| 24 | Rouse & Boff (eds.) *Organizational Simulation* (2005) | Wiley, doi:10.1002/0471739448 | [V] | Survey: individual, group/team, org behaviours as layered modelling targets | Group/team is a recognised modelling layer |
| 25 | Mathieu, Marks & Zaccaro (2001) MTS; Sullivan et al. (2015) [authors M] | Handbook I/O Psych [M]; *Network Science* | [V]/[M] | Multi-team systems: episodic, interdependent teams; ABM of leadership-network emergence over space/time | Cross-firm encounters (client meetings) are MTS episodes |
| 26 | Flache & Mäs (2008) | *CMOT* 14:23–51, doi:10.1007/s10588-008-9019-1 | [V] | Team-level ABM of homophily/influence/rejection; *timing* of cross-faultline contacts changes cohesion | Order of contacts inside a group changes the outcome: multi-round matters |
| 27 | Mäs, Flache, Takács & Jehn (2013) | *Org. Sci.* 24(3):716–736, doi:10.1287/orsc.1120.0767 | [V] | Same micro-rules: short-term polarisation, long-term unification | Horizon of the sub-sim changes the sign of the effect |
| 28 | Heise (2007); Schröder, Hoey & Rogers (2016) BayesACT | Springer; *ASR* 81(4), doi:10.1177/0003122416650963 | [V] | Affect control: actors pick behaviours minimising deflection from identity sentiments; emotions signal it; multi-round dyad simulation (INTERACT) | A numeric, typed within-encounter engine exists (EPA vectors) |
| 29 | Hemelrijk DomWorld (1999 [M]; 2020 PLOS ONE doi:10.1371/journal.pone.0243877) | *Proc. R. Soc. B* [M]; *PLOS ONE* | [V] | Dyadic contests with winner–loser effect + spatial structure → linear hierarchy; removing either destroys the macro pattern | Ablation evidence that the within-encounter resolution rule drives macro structure |
| 30 | Ferguson et al. (2005, 2006) | *Nature* 437:209; 442:448–452, doi:10.1038/nature04795 | [V] | Individuals mix in households, schools/workplaces, and a spatial community layer [M detail] | Layered mixing groups, fixed membership, no intra-group dynamics |
| 31 | Grefenstette et al. (2013) FRED | *BMC Public Health* 13:940, doi:10.1186/1471-2458-13-940 | [V] | Census-based agents in household/school/workplace mixing groups | Same |
| 32 | Kerr et al. (2021) Covasim; Hinch et al. (2021) OpenABM-Covid19 | *PLOS Comp Biol* doi:10.1371/journal.pcbi.1009149; 1009146 | [V] | Contact layers (household, school, work, LTCF, community); per-layer transmissibility | Layer weights, not encounter content, carry the fidelity |
| 33 | Stroud et al. (2007) EpiSimS | *JASSS* 10(4)9 | [V] | Activity-based: individuals' schedules put them in locations; co-location = contact | Activity schedules generate co-location episodes (same as jeve's ticks) |
| 34 | Horni, Nagel & Axhausen (2016) MATSim; Waddell (2002) UrbanSim | Ubiquity Press; *JAPA* | [V] | Agents execute daily activity plans at facilities; iterative re-planning by score | Activities at facilities are the co-location episodes; replanning = learning |
| 35 | Shehory & Kraus (1998) | *AI* 101:165–200, doi:10.1016/S0004-3702(98)00045-9 | [V] | Coalition formation for task allocation with bounded computation | Group formation can be a cheap heuristic, not optimisation |
| 36 | Stone, Kaminka, Kraus & Rosenschein (2010) | AAAI 24:1504–1509 | [V] | Ad hoc teamwork: cooperate with unknown teammates without pre-coordination | Encounters with strangers need a "type inference" step |
| 37 | Sichman, Conte, Demazeau & Castelfranchi (1994) | ECAI'94 pp.188–192 | [V] | Dependence networks: who needs whom for which goal drives partner choice | "Whom to talk to" = dependence relation |
| 38 | Ferber & Gutknecht (1998) AGR; Ferber, Gutknecht & Michel (2004); MadKit | ICMAS'98 pp.128–135; AOSE LNCS | [V] | Agent/Group/Role: groups are dynamic containers; agents hold roles in several groups | Runtime container for an ad hoc group |
| 39 | Servat, Perrier, Treuil & Drogoul (1998) | MABS, LNAI 1534:183–198, doi:10.1007/10692956_13 | [V] | Emergent local groups get "an existence of their own" with behaviours | Groups as first-class emergent agents |
| 40 | Morvan (2012) survey; Gaud et al. (2008); Navarro et al. (2011); Davis & Hillestad (1993); Hjorth et al. (2020) LevelSpace | arXiv:1205.0561; *SMPT* 16(10):1659–1676; AAMAS pp.701–708; WSC pp.1003–1012; *JASSS* 23(1)4 | [V] | Multi-level / multi-resolution ABM: dynamic level of detail, holonic groups, aggregation–disaggregation consistency | Engineering patterns for zoom-in/zoom-out and fold-back consistency |

---

## 1. Micro–macro link

**Coleman (1990)** [V]. Macro conditions shape actors' situations; actors act; actions aggregate. The "boat" makes explicit that the *transformational* arrow is where most sociological difficulty lives. **Implication:** an encounter sub-sim is a transformational mechanism; its inputs must be situational (who is here, with what macro-derived state), its outputs must be the only route by which macro changes.

**Hedström & Ylikoski (2010)** [V] argue that mechanism-based explanation is what ABMs are for: middle-range mechanisms linking an action theory to macro explananda. **Implication:** every sub-sim should be a nameable mechanism ("escalation", "information leak", "commitment"), which fits jeve's causal ids.

**Simon (1962)** [V]. Near-decomposable systems: within-subsystem interactions are frequent and strong, between-subsystem ones rare and weak, so short-run dynamics of each subsystem can be analysed roughly independently and only aggregates matter at the higher level. **Implication:** this is the theoretical licence for a bounded, finer-clocked sub-sim that returns aggregates. Its condition is also the design constraint: the sub-sim is valid only if cross-boundary coupling during the episode is weak (nobody outside the café table changes the table's state mid-encounter).

**Squazzoni (2012)** [V]; **Harrington & Fine (2000)**, **Fine (2012)** [V]. Groups are the meso level; they "constitute social order just as they are constituted by it." Fine's idioculture: groups carry persistent local references. **Implication:** groups need memory across encounters, not just per-encounter state.

**Lesson:** jeve's macro should never be written directly; encounters are the transformational arrow, groups persist as meso entities, and Simon's condition tells you when a sub-sim may be closed.

## 2. Micro-sociology of encounters

**Goffman, *Encounters* (1961)** [V]. A focused gathering exists when participants "effectively agree to sustain for a time a single focus of cognitive and visual attention"; it has ratified participants, a membrane against outsiders, openings and closings, and rules of irrelevance (what is bracketed out). **Implication:** entry = ratification + focus; participants = ratified set (bystanders are not participants); exit = closing move; local rules can exclude macro variables that are "irrelevant" here.

**Goffman (1983)** [V]. The interaction order is "a substantive domain in its own right," only loosely coupled to macro structure. **Implication:** the sub-sim needs its own state variables (footing, face, turn), not a re-read of macro state.

**Collins (2004)** [V]. Ingredients: bodily co-presence, barrier to outsiders, mutual focus, shared mood. Outcomes: group solidarity, individual emotional energy (EE: "confidence, enthusiasm, initiative"), symbols of membership, standards of morality. Rituals succeed or fail; EE gained or drained is carried into the next encounter, and people choose encounters where their cultural capital yields the best EE payoff (the "market for interaction rituals"). **Implication:** structure the sub-sim as ingredient check → rounds that raise or fail to raise mutual focus/mood → success/failure exit → return EE deltas per person, solidarity delta per pair/group, and any new shared symbol.

**Bales (1950)** [V]. Twelve act categories split task/socio-emotional; groups oscillate between task progress and relational repair. **Implication:** one round = one typed act per speaker from a small enum; jeve's non-generative decision model can answer this directly.

**Feld (1981)** [V]. Ties form around foci; the workplace or café organises who meets. **Implication:** locations are foci; co-location at a focus is the correct trigger for candidate encounters (jeve already does this).

**Affect Control Theory: Heise (2007), Schröder, Hoey & Rogers (2016)** [V]. Actors select behaviours that minimise deflection between fundamental sentiments (identity EPA vectors) and transient impressions; emotions are the signal; INTERACT and BayesACT simulate multi-round dyads; a 2021 JASSS paper extends affect control to collaborative groups within social structure [V title; authors not retrieved]. **Implication:** a proven, fully numeric within-encounter engine exists: each round is "actor–behaviour–object" with impression update; it needs only enum/scale answers.

**Lesson:** Goffman gives the membrane and the entry/exit moves; Collins gives what accumulates and what returns; Bales/ACT give a typed per-round act model that a cheap decision model can drive.

## 3. Nested games and action situations

**Tsebelis (1990)** [V]. Behaviour that looks irrational in one arena is rational given a concurrent game in another. **Putnam (1988)** [V]. Level I bargains are constrained by the Level II win-set. **Implication:** a sub-sim payoff must include the participant's outside arenas (the vendor's promise costs them at their firm), and its outcome must be ratifiable at macro (Putnam) or it is a failed ritual. Both are cheap to add: pass a "win-set" summary in, check the outcome against it on exit.

**Ostrom (2005; 2011)** [V]. An action situation has seven working parts: participants, positions, allowable actions, potential outcomes, action–outcome linkage and control, information, and costs/benefits. Seven rule types (boundary, position, choice, scope, aggregation, information, payoff) configure them. **McGinnis (2011)** [V]: real governance is a network of *adjacent* action situations, where outcomes of one set rules or participants of another. **Montes, Osman & Sierra (2022)** [V] make this executable (ASL → extensive-form game); **MAIA (2013)** [V] uses it as an ABM meta-model. **Implication:** the action situation is a complete, already-computational specification of a bounded episode, including an explicit outcome function and the adjacency relation that defines fold-back.

**Lesson:** specify each encounter type as an action situation; specify fold-back as adjacency edges.

## 4. Computational organisation theory

**Carley (1991), Construct** [V]. Interaction probability is proportional to relative shared knowledge; interaction transfers knowledge; the social and knowledge networks co-evolve. **Implication:** the minimal return value of any encounter is "which facts moved," and that return changes tomorrow's encounter probabilities.

**ORGAHEAD (1996)** [V]. Dual-level model: learning inside, restructuring above, on different clocks. **VDT / SimVision (1996, 1999)** [V]. Actors are boundedly rational information processors with in-trays; tasks generate exceptions that require communication and rework; meetings are explicit activities that consume attention [M detail]; the model predicts schedule, cost, and quality. **Implication:** the sub-sim must *cost time*: the 15-minute tick of a meeting is attention withdrawn from work; escalation is an exception-handling path.

**Garbage can (1972); Fioretti & Lomi (2008)** [V]. Decisions are collisions of participants, problems, solutions and choice opportunities; exit by resolution, oversight, or flight. **Implication:** an encounter is a choice opportunity; import the participants' open problems/solutions; exit type is an enum with distinct macro effects (flight leaves the problem attached to someone else).

**Feldman & Pentland (2003; 2005)** [V]. Routines = ostensive pattern + performative enactments; performances modify the pattern. **Implication:** recurring encounters (standup, client meeting) should be a template plus a performance; the fold-back includes template drift.

**Burton & Obel (1995)** [V]: the simplest model that answers the question. **Rouse & Boff (2005)** [V]: group/team behaviour is a recognised modelling layer. **Mathieu, Marks & Zaccaro (2001)** [V]; Sullivan et al. (2015) [V/M]: MTS are episodic, interdependent teams; ABMs of shared-leadership emergence over space/time exist. **Implication:** inter-firm encounters are MTS episodes with cross-team interdependence.

**Flache & Mäs (2008); Mäs et al. (2013)** [V]. Within-team ABMs with homophily, influence, rejection: the *timing/order* of contacts across a demographic faultline changes cohesion, and the same rules give polarisation short-term but unification long-term. This is the closest thing to evidence that multi-round within-group dynamics change macro outcomes. **Hemelrijk's DomWorld** [V]: self-reinforcing dyadic contests plus spatial structure produce hierarchy; ablating either destroys the macro pattern.

**Lesson:** organisational sim already treats meetings, exceptions and routines as bounded episodes that cost time; the few ablation-style results (Flache & Mäs; Hemelrijk) say sequence and self-reinforcement inside encounters change macro structure.

## 5. Epidemiological and activity-based microsimulation

**Ferguson (2005, 2006), FRED (2013), Covasim (2021), OpenABM-Covid19 (2021), EpiSimS (2007)** [V]. Individuals belong to household, school/workplace and community layers (Covasim adds LTCF); contact within a layer is homogeneous with a per-layer weight; EpiSimS and **MATSim (2016)** derive co-location from activity schedules; **UrbanSim (2002)** microsimulates location choices. **Implication:** this tradition validates layered mixing groups and activity-driven co-location but deliberately has *no* intra-encounter dynamics. It is the baseline jeve is trying to beat: content-free co-location.

**Lesson:** jeve's tick-based co-location is exactly EpiSimS/MATSim; the added value of a sub-sim is entirely in what happens *inside* the mixing group.

## 6. Group formation in MAS and multi-level ABM

**Shehory & Kraus (1998)** [V]: bounded-rationality coalition formation. **Stone et al. (2010)** [V]: ad hoc teams without pre-coordination. **Sichman et al. (1994)** [V]: dependence networks drive partner choice. **Ferber & Gutknecht (1998) AGR / MadKit** [V]: a group is a dynamic container; agents hold roles in several groups simultaneously; no theory of what happens inside. **Servat et al. (1998)** [V]: emergent local groups are granted their own existence and behaviours. **Multi-level ABM** [V]: Morvan's survey; Gaud et al.'s holonic groups that change level of description at runtime; Navarro et al.'s dynamic level of detail triggered by user focus or events; Davis & Hillestad's aggregation/disaggregation consistency problem; LevelSpace's "models within models."

**Lesson:** the mechanics of creating a group instance, raising its resolution, running it, and re-aggregating are solved engineering patterns; the unsolved part is the social content and the consistency of what returns.

---

## (a) Which formalism fits jeve's ad hoc group sub-simulations

Argue for a layered answer, because the three candidates answer different questions:

- **Ostrom's action situation** answers *what is being specified*. It is the only one of the three with an explicit finite action set, positions, information partition, and outcome function, and with an adjacency relation (McGinnis) that defines fold-back. Its parts map directly onto jeve's typed decisions: positions = roles at the table; allowable actions = enums; information = what each participant knows (from Construct-style knowledge state); costs/benefits = numeric scales; outcomes = a typed record with a causal id. It has already been made executable (Montes et al. 2022; MAIA), and it is agnostic about the content of rounds, so it can host a Bales/ACT act model or a Collins ritual model inside.
- **Ferber's AGR** answers *how to instantiate it at runtime*: a group is created from co-location at a focus (Feld), roles are assigned, an agent may be in several groups, the group dissolves on closing. It says nothing about dynamics; use it as the container, not the theory.
- **Collins's interaction ritual** answers *what state evolves and what returns*: mutual focus and shared mood as local variables, EE, solidarity and symbols as outputs, success/failure as exit. It has no formal action set and its variables are ordinal, which is fine for a scale-valued decision model but not a specification language.

**Recommendation:** specify each encounter type as an action situation (with entry rules from Goffman: ratification, membrane, focus), run it in an AGR-style group container, and use Collins/ACT variables as the local state and the returned deltas. Putnam's win-set is the ratification check on exit; McGinnis adjacency is the fold-back graph.

## (b) Which encounter variables the theory says matter for macro outcomes

1. **Emotional energy** per person (Collins): chains across encounters, decays, and biases the next choice of whom to approach. Model as a scalar per agent updated on exit.
2. **Solidarity / tie strength** per pair or group (Collins; Feld; Flache & Mäs): changes future co-location and interaction probability; sequence-sensitive.
3. **Information / shared knowledge** (Carley): the return value that changes tomorrow's encounter probabilities; also the driver of Construct's homophily loop.
4. **Obligations and expectations** (Coleman's social capital chapter [M]; Putnam ratification): commitments made inside must be enforceable outside, or become failed rituals.
5. **Shared symbols / idioculture** (Collins; Fine): persistent group memory; in jeve, a topic or causal id the group now "owns."
6. **Identity confirmation / deflection** (ACT): predicts who escalates versus de-escalates in a given round; emotions are the observable.
7. **Attention consumed** (VDT): every round is time not spent on work; the macro effect of a long encounter can be negative even if the ritual succeeds.
8. **Exit type** (garbage can): resolution, oversight, or flight determines where the problem now sits.
9. **Timing and horizon** (Flache & Mäs; Mäs et al.): the order of contacts and the number of rounds can flip the sign of the effect, so round count is a variable, not a constant.

## (c) What is absent

- **No direct ablation of one-shot versus multi-round encounters on macro outcomes in organisational ABM.** The closest are Flache & Mäs (timing) and Hemelrijk (winner–loser removal); epidemiology deliberately removes intra-encounter dynamics. jeve would be producing new evidence here and should build the A/B as a first-class experiment.
- **No social-theoretic trigger for when to zoom in.** Dynamic-LOD work (Navarro; Gaud) triggers on user focus or events; Simon's near-decomposability gives a criterion (weak external coupling during the episode) but no operational test.
- **No formalism for recursion.** Nested action situations (McGinnis) are adjacency, not containment; LevelSpace and holonic MAS handle containment mechanically but say nothing about when an encounter within an encounter is meaningful.
- **Fold-back consistency is under-specified.** Davis & Hillestad frame aggregation/disaggregation, but conservation of time, money, and information across levels in social sims is rarely audited.
- **Emotional energy is rarely quantified.** ACT provides numbers, but for dyads; group-level extensions are recent and thin.
- **Groups as decision units.** AGR and Servat make groups first-class, but no reviewed model gives a *group* a typed decision output distinct from its members'.
- **Calibration data at encounter granularity.** Bales IPA is a coding scheme; no organisational ABM found here is calibrated to act-rate data.

---

**Verification note.** All [V] items had title, venue and year confirmed in search-result metadata; DOIs and page numbers are those returned by search. [M] marks mechanism details (e.g. VDT exception handling, Ferguson's spatial kernel, Coleman's obligations chapter) and the author list of the 2015 *Network Science* MTS paper, which I could not fetch. No references were invented; where a candidate could not be verified (e.g. a Warwick thesis on "energy from social interactions," the 2021 JASSS affect-control-in-groups paper's authors), I have cited only what was confirmed.