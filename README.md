# jeve

**A small economy that never stops — twelve firms in one district, running on
typed decisions instead of generated text.**

Generative-agent sims (Smallville, Concordia) drive agents with LLM prose.
jeve asks how much of that loop can be replaced by three primitives —
`noul` (a boolean with a probability), `choice` (pick from a set), `score`
(a scale) — answered by TypeSafe's **Jev** over OpenRouter. Prose still
exists, but only as a view: dialogue is rendered on click for a human, and
nothing that computes the world may read it back.

## The district

Twelve firms in three rows of buildings, 225 staff on 27 floors, coupled
tightly enough that a bad Tuesday at one is a bad Friday at another. The
roster is one spec, `py/src/jeve/core/orgs.py` (CORE-0012); a team is a floor
of its building (WORLD-0006).

| Firm | Business | Floors | Runs on |
| --- | --- | --- | --- |
| **Tallybird Software** | Sells TimeTrack, Invoicing and POS to the street | 3 | Its own suite; ships the outages |
| **Halloran & Pike LLP** | Law firm, bills by the hour | 3 | Tallybird TimeTrack + Invoicing |
| **Ledgerline Accounting** | Payroll and the monthly close for everyone else | 2 | Tallybird Invoicing |
| **Keystone Property** | Every lot's landlord | 2 | Tallybird Invoicing |
| **Third Rail Cafe** | Feeds everyone; caters the offices | 1 | Tallybird POS + TimeTrack |
| **Brightwater Dental** | A clinic with a till and an appointment book | 2 | Tallybird Invoicing |
| **Meridian Studio Architects** | Bills by milestone | 3 | Quill Hours + Billing |
| **Commonwealth Credit Union** | The bank; keeps its own books | 2 | Nothing of anyone's |
| **Pemberton Hardware** | A shop floor and a stock room | 2 | Tallybird POS + Invoicing |
| **Quill Systems** | The other software vendor | 3 | Its own suite |
| **Ironworks Gym** | Where the street goes after work | 2 | Quill Register + Hours |
| **Northfield Provisions** | Supplies the cafe and the shop | 2 | Quill Billing |

Invoices, tickets, incidents, payroll, credits, catering, four tills, outside
income — the typed flows run over a double-entry ledger. Emergence comes from
the structure, not the script: an Invoicing outage at month-end → late bills
→ late payments → a cash trough → a payer who starts stalling *their*
suppliers.

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
