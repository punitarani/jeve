# ops/

Two kinds of thing live here, and git treats them differently.

**Measurements are tracked.** They are evidence: written only by a run that
actually spent money, and committed so a reader sees what was measured against
which commit.

| File | Written by | Meaning |
|---|---|---|
| `economics.md` | `LIVE=1 make e2e`, and nothing else | Measured cost per sim-day, per person, per org, per event; decisions by model. A replay writes `economics.replay.md` beside it and says so if the two have drifted. |
| `soak.md` | `make soak` | 35 sim-days on rules: the invariants a world must keep (WORLD-0005), the counterfactual, and what happened. Free. |
| `soak.live.md` | `make soak POLICY=jev CALLS=record DAYS=10 COUNTERFACTUAL=1` | The same, decided by Jev, with what it cost. Run at gates. |
| `episodes.md` | `make episodes` | Does giving a meeting rounds change anything (WORLD-0006)? The same sim-days played twice, with and without: the docking comparison first, then the billing timeline. Both arms on rules, so it is free. |
| `soak.episodes.md` | `make soak --episodes` | The long-horizon invariants in the episodes arm. They have to hold there too, and on rules it is still free. |
| `persona-probe.md` | `make persona-probe` | Does sampling Jev's distributions preserve persona? With a control. |
| `providers.md` | `make providers` | One real call per model: reachable, not merely resolvable. |

**Runtime state is ignored.** Written by the running system; yours is not mine.

| File | Written by | Meaning |
|---|---|---|
| `spend.json` | `jeve.llm.ledger` | Read-only checkpoint of the Postgres `spend_entries` table (LLM-0007), for humans and dashboards. The table is the source of truth for the ceiling. Do not reset it. |
| `discrepancies.jsonl` | `jeve.llm.gateway` | Times the local ledger and OpenRouter's `/key` disagreed by more than 10%. `/key` lags by minutes; the local figure is a floor. |
| `provider-settings.before.json` | captured by hand | The account's provider allowlist as found in session 1, so any change is reversible. |
| `economics.replay.md` | `make e2e` | The same report from a replay run. |
| `provider-settings.before.json` | captured by hand | The account's provider allowlist as found in session 1, so any change is reversible. |
