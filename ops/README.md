# ops/

Runtime state, written by the running system. Everything here except this file
and `.gitkeep` is gitignored.

| File | Written by | Meaning |
|---|---|---|
| `ledger.jsonl` | `jeve.llm.ledger` | Append-only spend record. The source of truth for the ceiling. |
| `spend.json` | same | Derived checkpoint of the above, for humans and dashboards. |
| `discrepancies.jsonl` | `jeve.llm.gateway` | Times the local ledger and OpenRouter's `/key` disagreed by more than 10%. |
| `provider-settings.before.json` | captured by hand | The account's provider allowlist as found, so any change to it is reversible. |
| `night.json` | the overnight session | Start time and ceilings, so a resumed session knows its own clock. |
| `gates.json` | the overnight session | Which milestone gates have passed. |
| `economics.md` | gate 6 | Measured cost per person / org / event. |
