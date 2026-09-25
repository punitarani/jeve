# Cassettes

`golden.jsonl` is every response Jev gave during the golden run, one JSON object
per line, sorted by key. It is what makes `make e2e` free and keyless: strict
replay reads answers from here and fails loudly on anything it does not find.

A row's key is `H("v2" | model build | the exact bytes sent)` (DECIDE-0004), and
the row keeps those bytes as `wire`. So rewording a question, reordering its
options, or a new build of the model behind the same slug are all misses.

Re-record with `LIVE=1 make e2e` and commit the file. Never edit it by hand, and
never point a long live run at it: `make soak` keeps its own cassette under
`ops/` for exactly that reason.

If the file is absent — between a change to the key and the recording that
follows — the tests that replay it skip, and `LIVE=1 make e2e` recreates it.

Recorded 2026-09-24 by `LIVE=1 make e2e` with conversations routed to tier 1
(DECIDE-0006): 985 Jev calls and 106 tier-1 rows (87 GLM 5.3 Flash replies,
19 Gemini 3.8 Flash), $0.134 from a cold cache (`ops/economics.md`).
