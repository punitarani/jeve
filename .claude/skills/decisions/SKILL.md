---
name: decisions
description: Find why this codebase is the way it is, and record new architectural choices. Use when someone asks "why did we", "what did we decide", "why is this like this", "who decided", "can I change this", "are we allowed to", "is there a reason", or mentions an architecture decision, decision record, ADR, MADR, rationale, trade-off, supersede, or a record ID like CORE-0005, LLM-0004, DECIDE-0001, MEM-0001, WEB-0001. Also use before making a consequential structural choice — a new dependency, a schema change, a swapped library, a changed boundary — so it gets recorded instead of forgotten.
---

# Decision records

Architecture decisions live in this repo as MADR 4.0 records, one per file.
Markdown is canonical; the index and the Cursor rules are generated.

## Answering "why is it like this?"

1. Read `decisions/INDEX.md`. One row per decision: ID, status, the globs it
   governs, title, and a one-line summary.
2. Open only the records whose `scope` covers the files in question. Do not
   read them all — the index exists so you do not have to.
3. `decisions/index.jsonl` is the same data, one JSON object per line, for when
   you want to filter by tag or status rather than read.

Grep works too: IDs are globally unique, so `grep -rn CORE-0005 .` finds the
record, every mention in prose, and every enforcement point in code.

If no record covers it, say so plainly rather than inventing a rationale. The
absence of a record is itself information: the choice was not contested.

## Where records live

- Cross-cutting → `decisions/core/` with the `CORE` prefix.
- Area-specific → next to the code, e.g. `py/src/jeve/llm/decisions/`, with
  that area's prefix (`LLM`, `WORLD`, `DECIDE`, `MEM`, `GEN`, `SIM`, `API`,
  `WEB`).

## Writing one

Only when the choice was contested, the obvious answer was wrong for a
non-obvious reason, or someone would plausibly undo it. Otherwise it is a
comment in the code.

```bash
python3 scripts/gen-decisions.py --new DECIDE "Sample propensities, never argmax"
# fill in the four sections, set scope to globs that match real files
python3 scripts/gen-decisions.py        # regenerate index + rules
```

Then cite the ID at the point in code that enforces it.

## Changing one

You do not. Records are immutable. Write a new record, set `supersedes` on it
and `superseded-by` on the old one, and set the old one's status to
`superseded`. CI checks that both sides agree.

Two things are metadata rather than substance and may be edited in place:
filling in `scope` once the code it governs exists, and fixing a typo.

## Checks

`python3 scripts/gen-decisions.py --check` validates front matter, the
supersede graph, and that **every glob matches a real file** — which is how a
restructure that orphans a decision gets caught instead of rotting. It also
fails if the generated artifacts are stale.
