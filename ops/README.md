# ops/

Two kinds of thing live here, and git treats them differently.

**Measurements are tracked.** They are evidence: written only by a run that
actually spent money, and committed so a reader sees what was measured against
which commit.

| File | Written by | Meaning |
|---|---|---|
| `economics.md` | `LIVE=1 make e2e`, and nothing else | Measured cost per sim-day, per person, per org, per event; decisions by model. A replay writes `economics.replay.md` beside it and says so if the two have drifted. |
| `persona-probe.md` | `make persona-probe` | Does sampling Jev's distributions preserve persona? With a control. |
| `providers.md` | `make providers` | One real call per model: reachable, not merely resolvable. |

**Runtime state is ignored.** Written by the running system; yours is not mine.

| File | Written by | Meaning |
|---|---|---|
| `ledger.jsonl` | `jeve.llm.ledger` | Append-only spend record. The source of truth for the ceiling. Do not reset it. |
| `spend.json` | same | Derived checkpoint of the above, for humans and dashboards. |
| `discrepancies.jsonl` | `jeve.llm.gateway` | Times the local ledger and OpenRouter's `/key` disagreed by more than 10%. `/key` lags by minutes; the local figure is a floor. |
| `provider-settings.before.json` | captured by hand | The account's provider allowlist as found in session 1, so any change is reversible. |
| `economics.replay.md` | `make e2e` | The same report from a replay run. |
| `night.json`, `gates.json` | session 1 | Historical. |
