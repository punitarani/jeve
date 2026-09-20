# jeve

A continuously-running simulation of a small interconnected economy: four firms
on one street — Tallybird Software (whose product the others use), Halloran &
Pike LLP, Ledgerline Accounting, Third Rail Cafe.

The research question: how much of a Smallville/Concordia-style agent loop can
be replaced by *typed decisions* — boolean-with-probability, choice-from-enum,
numeric scale — instead of generated text. Typed decisions come from TypeSafe's
Jev; prose generation is the rare exception, and no causal path in the
simulation ever reads generated text.

## Layout

| Path | What |
|---|---|
| `py/src/jeve/` | The simulation. `core → llm → decide → world → sim`, with `gen` and `api` on the outside. `tests/test_layering.py` enforces it |
| `py/src/jeve/decide/` | The `Policy` seam: `JevPolicy`, its rules twin, question sets, J/P/H sampling, the call cache |
| `py/src/jeve/world/` | Engine, the ten flows, the town map, encounters |
| `py/src/jeve/sim/` | `python -m jeve.sim`: the one run loop, for fixture and daemon alike |
| `py/src/jeve/gen/` | Prose rendered from typed state. **Nothing that computes the world may import it** |
| `py/fixtures/cassettes/` | Recorded Jev responses, keyed by content hash. What makes `make e2e` free |
| `packages/world/` | The voxel town: a GL-free scene model with three.js as a view over it |
| `packages/contracts/` | zod schemas for everything the API serves |
| `apps/web/` | The hero on `/`, the explorer at `/world`, and the causal timeline |
| `decisions/` | Decision records and their generated index |
| `docs/research/` | Ground truth on Jev, prior-art mapping, validation survey |
| `docs/design/` | Long-form analysis behind the decision records |
| `ops/` | Runtime state (spend ledger) and tracked measurements (`economics.md`, `persona-probe.md`, `providers.md`) |

## Decisions

Architecture decisions are recorded, not remembered. Before changing anything
structural:

1. Read `decisions/INDEX.md` — one row per decision, with the globs it governs.
2. Open **only** the records whose `scope` covers the files you are about to
   change. Do not read them all.
3. If you are making a consequential architectural choice that no record
   covers, write one: `python3 scripts/gen-decisions.py --new PREFIX "title"`,
   fill it in, then run `python3 scripts/gen-decisions.py`.

Records are **immutable**. Never edit the substance of an accepted decision —
write a new record and set `superseded-by` on the old one. Filling in `scope`
once the code exists is metadata, not substance, and is fine.

Write a record only when the choice was contested, the obvious answer was wrong
for a non-obvious reason, or a future engineer would plausibly undo it. Cite
the ID at the enforcement point in code (`# CORE-0005: seeds are path-derived`).

Records written autonomously carry `deciders: ["claude"]` and the tag
`agent-decided` until a human has reviewed them.

## Standards

- **Python**: full type hints, `uv`, pydantic at boundaries, `ruff` +
  `mypy --strict`, stdlib-first. Python 3.14.
- **TypeScript**: strict, no `any`, discriminated unions over optional-field
  soup, zod at every I/O boundary.
- One way to do each thing. No parallel abstractions "in case".
- Every module testable without network. Real model calls live in `jeve.llm`
  and in tests marked `live`.
- Prefer deleting code to adding configuration.
- Comments explain *why*, and carry the incident that justified the code.

## Money

**Every model call goes through `jeve.llm`.** Nothing else may import `httpx`;
ruff enforces it. The gateway reserves worst-case cost before issuing, settles
at the real cost, and refuses past the ceiling. Thresholds: $12 stops
exploratory work, $16 halts everything and triggers the handoff, $20 is the
backstop. State is in `ops/ledger.jsonl` and survives restarts — do not add a
second path to a model, and do not reset the ledger.

## Verify

```
make check            # lint, types (mypy + tsc), tests, decision records
make e2e              # the whole stack, strict replay: free, no key, ~5 min
LIVE=1 make e2e       # hit-or-call; the only thing that rewrites ops/economics.md
make smoke            # one real call, under a cent
make sim              # the ever-running world. Spends money, slowly
```

Three things that will otherwise cost you an evening:

- **Wording is a cache key.** A question set's text is hashed into the key of
  every call that used it. Edit a sentence and those calls are re-recorded, and
  the run changes. Re-record with `LIVE=1 make e2e` and commit the cassette.
- **A tick must own its transaction.** In psycopg 3, `conn.transaction()` inside
  an already-open transaction is a savepoint. `Engine.tick()` commits first for
  that reason (WORLD-0002); do not "simplify" it.
- **A connection that only reads must be autocommit** if another process will
  `TRUNCATE`. An open read transaction holds a lock the daemon waits on for ever.
