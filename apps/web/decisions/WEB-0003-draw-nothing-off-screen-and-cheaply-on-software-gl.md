---
id: WEB-0003
title: Draw nothing off-screen, and draw cheaply on a software renderer
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["packages/world/src/render.ts", "packages/world/src/index.ts"]
tags: ["three.js", "performance", "testing", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0002"]
confirmation: "pnpm --filter @jeve/web exec tsc --noEmit"
---

# WEB-0003 — Draw nothing off-screen, and draw cheaply on a software renderer

## Context and Problem Statement

Three times tonight a page holding the hero stopped dead in headless Chromium:
twice it never hydrated, and once a test with a thirty-second timeout sat for
fifteen minutes, which means the page's main thread was frozen so hard that the
test runner could not even enforce its own timeout. Each time the laptop was
also running macOS Photos analysis at 350% CPU, with load averages of 30 to 80.
On a quiet machine the same build loaded seven times in a row in 800 ms at 40
frames a second.

Headless Chromium here renders WebGL through SwiftShader, a CPU rasteriser.
Every GL call is a synchronous wait on a GPU process shared by all tabs. An
antialiased scene at 2x pixel ratio and sixty frames a second is nothing to a
GPU and a great deal to a core that is busy with something else.

This is a hypothesis with circumstantial evidence, not a diagnosis: I did not
capture a stack from the frozen process.

## Considered Options

- **Retry flaky specs.** Hides a freeze that a real visitor on a VM or a remote
  desktop would hit too. Loses.
- **Skip the WebGL specs in CI.** Then nothing tests the page people land on.
  Loses.
- **Cap everyone at 30 fps.** Penalises the common case to protect the rare one,
  and the brief asks for sixty. Loses.
- **Do less work when it cannot matter or cannot be afforded.** Taken.

## Decision Outcome

The scene is not drawn while its canvas is off-screen or the tab is hidden, and
when WebGL turns out to be a CPU rasteriser it is drawn without antialiasing, at
1x pixel ratio, fifteen times a second. The model advances regardless: positions
are what tests and clicks read, and they must not depend on whether anyone is
watching.

The renderer is identified from a throwaway context before the real one is
created, because antialiasing cannot be changed afterwards. Visibility comes
from an `IntersectionObserver` and `document.hidden`. `status()` reports
`software` and `drawing`, and a spec scrolls the hero away and asserts both that
drawing stops and that people keep walking.

### Consequences

- Good: a reader scrolled down to the timeline is no longer paying for a town
  they cannot see. That holds on a real GPU too.
- Good: a visitor on a VM, a remote desktop or a blocklisted driver gets a town
  that moves, rather than a tab that hangs.
- Bad: fifteen frames a second looks like fifteen frames a second.
- Bad: the root cause is unproven. If the freeze was something else, this makes
  it rarer without making it impossible, and the `reloaded` annotation in the
  specs is how it would show.
- Reverse it if: a stack from a frozen tab points somewhere other than the GPU
  process, or software renderers turn out to cope with the full picture.
