---
id: PREFIX-0000
title: A short imperative sentence
status: proposed
date: 2026-01-01
deciders: ["punitarani"]
scope: []
tags: []
supersedes: []
superseded-by: null
relates-to: []
confirmation: null
---

# PREFIX-0000 — A short imperative sentence

## Context and Problem Statement

What forced a choice. One paragraph. Say what breaks if nobody decides.

Write a record only when the choice was contested, the obvious answer was
wrong for a non-obvious reason, or a future engineer or agent would plausibly
undo it. Everything else is a comment in the code.

## Considered Options

- **The one we took** — one line.
- **The one we rejected** — one line, and why it loses.

## Decision Outcome

The decision, stated in one line. This line becomes the index summary, so it
must stand alone.

Then a short paragraph of the reasoning that is not obvious from the line.

### Consequences

- Good: what this buys.
- Bad: what it costs. If nothing, the decision was not contested.
- What would reverse it: the concrete evidence, not "if it doesn't work out".

<!--
Field notes:

  scope         globs this decision governs, quoted: ["py/src/jeve/llm/**"].
                Leave [] until the code exists — every glob must match a real
                file or CI fails, which is how a restructure gets caught.
  confirmation  a command that verifies compliance, or null. Not aspirational:
                if it is there, CI can run it.
  deciders      ["claude"] plus the tag "agent-decided" for records written
                autonomously, until a human has reviewed it.
-->
