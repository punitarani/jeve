# jeve

**A small economy that never stops — four firms on one street, running on
typed decisions instead of generated text.**

Generative-agent sims (Smallville, Concordia) drive agents with LLM prose.
jeve asks how much of that loop can be replaced by three primitives —
`noul` (a boolean with a probability), `choice` (pick from a set), `score`
(a scale) — answered by TypeSafe's **Jev** over OpenRouter. Prose still
exists, but only as a view: dialogue is rendered on click for a human, and
nothing that computes the world may read it back.

## The street

Four firms, coupled tightly enough that a bad Tuesday at one is a bad Friday
at another:

| Firm | Business | Depends on |
| --- | --- | --- |
| **Tallybird Software** | Sells the suite the other three run on — TimeTrack, Invoicing, POS | Subscriptions; ships the outages |
| **Halloran & Pike LLP** | Law firm, bills by the hour | TimeTrack + Invoicing |
| **Ledgerline Accounting** | Payroll and the monthly close for the street | Invoicing; clients' data on deadline |
| **Third Rail Cafe** | Feeds everyone | POS + TimeTrack |

Invoices, tickets, incidents, payroll, credits, catering, lunch — ten typed
flows over a double-entry ledger. Emergence comes from the structure, not the
script: an Invoicing outage at month-end → late bills → late payments → a
cash trough → a payer who starts stalling *their* suppliers.

## Why typed

* **Cheap.** 5 sim-days: 2,082 events, 5,823 decisions — 89% made by the
  model — for **$0.04**. Identical situations share one cached call; only
  the draw is per person.
* **Replayable.** A run replays byte-identical from its recorded responses.
  `make e2e` runs the whole stack on cassettes: no key, $0.00.
* **Inspectable.** Every event carries the ids that caused it; every decision
  shows the distribution it was sampled from. The frontend is a causal
  timeline, not a chat log.

## Run it

```bash
mise install        # tool versions: node, python, uv, pnpm
make db-up          # Postgres + migrations (docker compose)
make check          # lint, mypy --strict, tests — all offline
make e2e            # whole stack on recorded calls: free, no key, ~5 min
make sim            # the live world — spends real money, slowly
make api            # FastAPI on :8000
```

`make sim` is governed: a per-day budget slows the clock before it stops it,
per-process and global ceilings back that up, and OpenRouter's account cap is
the hard stop. Defaults are gentle ($2/day); set the account cap anyway.

## Map

| Path | What |
| --- | --- |
| `py/src/jeve/` | The simulation: `core → llm → decide → world → sim`, with `gen` and `api` outside |
| `apps/web/` | Next.js static export — voxel town hero, `/world` explorer, causal timeline |
| `packages/world/` | GL-free voxel scene model; three.js is a view over it |
| `packages/contracts/` | zod schemas generated from the pydantic API contract |
| `decisions/` | Immutable architecture records — `INDEX.md` first |
| `docs/` | `research/` ground truth · `design/` analysis · `deployment.md` |
| `ops/` | Measured economics, soak reports, spend ledger checkpoint |

## Contributing

* `AGENTS.md` is the house rules; nested `AGENTS.md` files cover `py/`,
  `apps/web/`, `packages/`.
* Before changing anything structural, read `decisions/INDEX.md` and open the
  records whose scope covers your files. Records are immutable — new choices
  get new records (`python3 scripts/gen-decisions.py --new PREFIX "title"`).
* The layering is enforced by a test, not a convention: nothing that computes
  the world imports `gen`, and `world` reaches a model only through the
  `Policy` seam.
* Every model call goes through `jeve.llm` and the Postgres spend ledger.
  `make check` must pass with no network and no key.
