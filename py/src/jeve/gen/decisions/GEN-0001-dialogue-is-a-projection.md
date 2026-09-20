---
id: GEN-0001
title: Dialogue is a projection — rendered on click, cached by content hash, never read back
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/gen/**", "py/tests/test_layering.py", "py/tests/test_dialogue.py"]
tags: ["prose", "escape-hatch", "layering", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0002", "DECIDE-0003", "LLM-0005", "CORE-0006", "WORLD-0003", "WEB-0002"]
confirmation: "cd py && uv run pytest tests/test_layering.py tests/test_dialogue.py"
---

# GEN-0001 — Dialogue is a projection — rendered on click, cached by content hash, never read back

## Context and Problem Statement

People in the town meet and talk, and a visitor who clicks on a conversation
reasonably wants to read it. But the research question is how much of a
generative agent can be typed decisions instead of generated text, and the
design principle for this session is that simulation state never depends on
generated text. An encounter is five typed fields — who, whom, where, about
what, in what mood — and everything downstream follows from those.

So prose has to exist for the reader without existing for the simulation.

## Considered Options

- **Generate dialogue for every encounter as it happens**, Smallville-style.
  About 540 generative calls per five sim-days for text almost nobody reads,
  and it puts a slow model on the tick path. Loses.
- **Generate it and store it on the event.** The moment prose is in the event
  log it is state: it gets hashed, replayed, and eventually read by something.
  Loses.
- **No prose at all; show the typed fields.** Honest and free, and it is the
  default. But the brief asks for dialogue on demand, and the typed record reads
  as a form, not as something that happened. Kept as the fallback.
- **Render on click, cache by content hash, keep it out of the import graph.** Taken.

## Decision Outcome

`GET /encounters/{seq}/dialogue` always returns the typed record, and renders
two to four lines of dialogue only when asked: from the first reachable
escape-hatch model (LLM-0005), cached in `model_calls` under the content hash of
the request, and imported by nothing that computes the world.

The prompt is built from typed fields and two names and is told to invent no
facts. Nothing relies on its obeying: the text is shown to a person and goes
nowhere else. The cache key is built from the typed fields rather than the
event's `seq`, so two encounters alike in every typed respect share their prose.

`tests/test_layering.py` walks the AST of every module — catching lazy imports
inside functions too — and fails if `core`, `world`, `decide`, `memory`, `sim`
or `llm` imports `jeve.gen`. That is the test CORE-0006 promised when it folded
seven packages into one, written now.

Without an API key, or once spend passes the $12 exploratory rung, the endpoint
returns the typed record with `prose: null` and the reason. The page shows the
typed fields and says why there is no prose. Speech bubbles on the map always
show the typed topic, never generated text.

### Consequences

- Good: the principle is a failing test away from being violated, not a comment.
- Good: prose costs nothing until somebody asks, and once per distinct encounter.
- Bad: a clean clone shows no dialogue at all. The cassette holds decisions, not
  prose, because no test clicks "imagine".
- Bad: the rendered lines can contradict the typed record — a model may write a
  friendly exchange for a `stressed` mood. The typed fields are printed beside
  the prose so the reader can see which is the record.
- Bad: DSPy was considered for this prompt and not used. There is no dialogue
  eval anyone would run tonight, and an optimiser without a metric is a random
  walk.
- Reverse it if: generated text is ever wanted as an *input* — memory summaries,
  say. That needs its own decision, a typed extraction step between the prose
  and the state, and this test loosened on purpose rather than by accident.
