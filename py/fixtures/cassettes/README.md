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

**It is absent now.** The field-report review (WORLD-0009 to WORLD-0012,
DECIDE-0005) rewords `agent.tick` and `episode.round`, asks fewer of them, and
adds question sets, so every recorded run diverged within its first day. The
last cassette is in git history at `1ed0084`. Recording a new one needs an
OpenRouter key: `LIVE=1 make e2e`, then commit this file.
