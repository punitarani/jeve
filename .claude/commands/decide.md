---
description: Scaffold a new architecture decision record with the next free ID
argument-hint: <PREFIX> <title>
allowed-tools: Bash(python3 scripts/gen-decisions.py:*), Read, Edit, Write
---

Create a decision record for: $ARGUMENTS

1. Pick the prefix from the argument, or infer it from the area the decision
   governs: `CORE` cross-cutting, `LLM` the model gateway, `WORLD` ledger and
   rules, `DECIDE` question sets and sampling, `MEM` memory and beliefs, `GEN`
   prose rendering, `SIM`/`API` process entrypoints, `WEB` the dashboard.
2. Run `python3 scripts/gen-decisions.py --new <PREFIX> "<title>"`.
3. Fill in the four MADR sections in the scaffolded file. Keep it under one
   screen. Specifically:
   - **Considered Options** must name at least one option that was rejected,
     and say why it loses. A record with one option is not a decision.
   - The first paragraph of **Decision Outcome** becomes the index summary, so
     it has to stand alone.
   - **Consequences** must include a cost. If there is no cost, the choice was
     not contested and does not need a record.
   - Include what evidence would reverse it — concretely, not "if it doesn't
     work out".
4. Set `scope` to globs that match files that exist **now**; leave it `[]` if
   the code is not written yet, and fill it in with the commit that creates it.
5. If this supersedes an existing record, set `supersedes` here and
   `superseded-by` plus `status: superseded` on the old one.
6. If you decided this autonomously, set `deciders: ["claude"]` and add the tag
   `agent-decided`.
7. Run `python3 scripts/gen-decisions.py` and show me the diff.
