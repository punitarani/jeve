# ADR-007 — Determinism and seeding

Status: proposed · 2026-09-20

## How much reproducibility is achievable

| Level | Meaning | Achievable? |
|---|---|---|
| **L0** | Re-run from the seed against live models and get the same world | **No.** Jev exposes no seed or temperature and documents no determinism guarantee; TypeSafe's own repeat runs show ≈ 0.01 standard deviation in probabilities and occasional argmax flips (00 §1.5). Aliases move silently. LLMs are worse. |
| **L1** | **Replay a recorded run and get a byte-identical event log** | **Yes — the design target.** The sim is a pure function of (root seed, seed state, code version, recorded model responses). |
| **L2** | Fork a recorded state, intervene, compare | **Yes, statistically.** Past the fork, new contexts need new model calls, so branches are comparable across seeds, not identical. Variance is cut by common random numbers and the call cache (below). |
| **Resume** | `kill -9` at any instant, restart, continue as if uninterrupted | **Yes, exactly.** A response lost in flight was never recorded, so there is no recorded history to diverge from. |

## Decision

### 1. The model returns distributions; our PRNG makes the choice

P-type decisions are sampled by code, never by the model (ADR-004). Randomness that matters
is therefore ours and seedable, even though the model is not.

### 2. Path-derived randomness — no RNG state exists

Lifted from workbench's `core/seed.py` (00 §6.5):

```
derive_seed(root, *path) = blake2b(domain ‖ root ‖ length-prefixed path parts) → int
rng = Random(derive_seed(root, "agent", agent_id, "decision", decision_seq, question_id))
```

`decision_seq` is a per-agent counter persisted with the agent. Because every draw is a pure
function of its path, there is **nothing to checkpoint**, and a crash cannot desynchronise a
stream. Keying by decision sequence rather than tick means a scheduler change does not
reshuffle every agent's luck — which is also what makes common random numbers work across
fork branches: a decision the intervention did not touch gets the same draw in both arms.

Exogenous processes (foot traffic, incident hazard, the shock deck) use the same scheme with
their own path prefixes.

### 3. Every model call is recorded by content hash

`model_calls` (ADR-009): key = blake2b of canonical JSON of (provider, **resolved** model
version, request). Value = the full typed response, tokens, latency, cost. One record serves
four purposes:

- **Crash idempotency** — a re-executed tick finds its responses instead of paying again.
- **L1 replay** — a `ReplayDecisionModel` behind the same port raises on a miss.
- **L2 variance reduction** — identical contexts in control and treatment share an answer.
- **Offline analysis** — threshold tuning (ADR-005) reads it directly.

Canonicalisation is workbench's: sorted keys, compact separators, UTF-8 (00 §6.5). The
decorator order is workbench's too — retry *inside* the recorder, so retried calls are not
double-recorded.

### 4. What is logged per decision

Agent, decision seq, tick, sim time; question-set version; model-call hash; **every
distribution returned**; PRNG path and the draw; what was chosen and which rule chose it;
escalation state; the resolved model version. Enough to answer "why did she do that?" from
the row alone.

### 5. Code-version seams are recorded, not refused

workbench refuses to resume when its engine fingerprint changes, and a `ruff format` once
broke a live resume (00 §6.5). Right for a frozen recording, fatal for an always-on sim. jeve
writes a `sim.engine.changed` event carrying the git sha at every start. L1 replay across a
seam means checking out the sha for each segment. The seam is in the data.

### 6. Lint holds the line

Inside the sim core, ruff `banned-api` forbids module-level `random.*`, `uuid.uuid4`,
`time.time`, `datetime.now`/`utcnow`, and the builtin salted `hash()` for anything persisted.
(The Concordia source read reports — by inspection only, not executed — that its memory
dedup keys on salted `hash()`, so dedup of restored memories is lost in a new process.) Ids
come from a seeded minter.

### 7. Pin the model

`jev-1.13.0`, never `jev-latest` (00 §1.5). The response's `model` field is stored on every
call. A daily canary suite replays ~200 recorded contexts and alerts on mean |Δp| > 0.05
(02 §3.8).

## Retention

Full request bodies for 30 real days; hash, answers, versions, tokens, and cost forever. At
≈ 10k decisions per real day the permanent part is on the order of a few GB per year.

## Alternatives rejected

- **Chase L0** with caching proxies and pinned providers. Still fails on the first novel
  context, and buys a false sense of reproducibility.
- **Stateful RNG streams, checkpointed.** A class of resume bugs that the path scheme makes
  impossible. Concordia does not restore RNG state at all (01 §2).
- **Argmax everywhere to avoid randomness.** Deterministic given state, and therefore a
  machine for producing loops and absorbing idle states (01 §4).
- **Refuse resume on code change.** See §5.

## Reverse if

- M0 shows byte-identical Jev requests *do* return identical responses → nothing changes
  architecturally, but the replica cache hit rate rises and studies get cheaper (ADR-003).
- `model_calls` growth becomes a storage problem → shorten body retention; the hash and
  answers are the part that matters.
