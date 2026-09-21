---
id: CORE-0001
title: Record architecture decisions as immutable per-file records
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["decisions/**", "**/decisions/*.md", "scripts/gen-decisions.py"]
tags: ["process", "documentation", "agents"]
supersedes: []
superseded-by: null
relates-to: []
confirmation: "python3 scripts/gen-decisions.py --check"
---

# CORE-0001 — Record architecture decisions as immutable per-file records

## Context and Problem Statement

Most of this codebase will be written by agents, including overnight with
nobody watching. An agent that cannot find out *why* something is the way it
is will re-derive it, usually differently, and the reasoning is lost the moment
the session ends. Prose docs rot silently because nothing checks them.

## Considered Options

- **A single `DECISIONS.md`** — right for a ten-decision repo, and by that test
  right for this one *today*. Rejected because per-record front matter is what
  makes scoped agent rules and the glob-drift check possible, the repo becomes
  multi-area immediately, and migrating later costs more than starting here.
- **An off-the-shelf ADR CLI** — the maintained ones are unmaintained.
- **MADR 4.0, one file per decision, everything else generated.** Taken.

## Decision Outcome

Decisions are MADR 4.0 records, one per file, named `<PREFIX>-NNNN-kebab.md`,
with machine-readable front matter; `INDEX.md`, `index.jsonl`, `schema.json`
and the AGENTS.md decision section are generated from them and never hand-edited.

Records live by blast radius: cross-cutting ones in `decisions/core/`,
area-specific ones next to the code they govern, so a package can be read
without the whole history. IDs are prefixed per area, which makes them globally
unique and greppable — `grep -r CORE-0005` finds every mention.

### Consequences

- Good: an agent reads one index, then only the records whose `scope` matches
  the files it is about to touch. AGENTS.md loads the matching section by itself.
- Good: agent-agnostic format works across Cursor, Devin, Claude Code, and other tools.
- Good: `scope` globs are checked against real files, so a restructure that
  orphans a decision fails CI instead of rotting. This is the top silent
  failure mode of scoped docs.
- Bad: ceremony. Eleven records in a repo with no application code yet.
- Bad: front-matter values are JSON, not idiomatic YAML, because an unquoted
  `[**/x]` is a YAML alias and breaks every reader. The linter explains this.
- Reverse it if: after a month the records are not being read or cited, or the
  generator needs more maintenance than it saves.

## Process rules

1. **Records are immutable.** Never edit the substance of an accepted record.
   Write a new one, set `superseded-by` on the old and `supersedes` on the new
   — CI enforces that both sides agree. Fixing a typo or filling in `scope`
   once the code lands is metadata, not substance, and is fine.
2. **Write one only when it was contested**, the obvious answer was wrong for a
   non-obvious reason, or someone would plausibly undo it.
3. **Cite the ID at the enforcement point** in code (`# CORE-0005: seeds are
  path-derived`), so the graph runs both ways.
4. **Agent-written records** carry `deciders: ["claude"]` and the tag
  `agent-decided` until a human reviews them. That is the morning audit list.
