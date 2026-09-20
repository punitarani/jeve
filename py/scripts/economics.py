"""Gate 6: the measured unit-economics report.

Every dollar figure here was billed by OpenRouter and recorded against the call
that incurred it. Nothing is projected from list price. A run in which no
decision used a model reports $0 and says the gate is not met, because $0 is
what it cost and proves nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

TARGETS = {
    "usd_per_100_persons": ("per 100 persons, per sim-day", 1.00),
    "usd_per_10_orgs": ("per 10 orgs, per sim-day", 1.00),
    "usd_per_1000_events": ("per 1000 events", 1.00),
}
DAILY_TARGET_USD = 2.00
DAILY_CAP_USD = 10.00


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--stats",
        type=Path,
        action="append",
        default=[],
        help="call statistics from a sim process; repeat for a run made of several",
    )
    args = parser.parse_args()
    parts = [json.loads(p.read_text()) for p in args.stats if p.exists()]
    stats = (
        {
            "mode": parts[0]["mode"],
            **{
                key: sum(part[key] for part in parts)
                for key in ("asked", "from_cache", "live_calls", "live_usd")
            },
        }
        if parts
        else None
    )

    with urllib.request.urlopen(f"{args.api}/economics", timeout=20) as response:
        data = json.load(response)

    counts = data["counts"]
    per = data["per_sim_day"]
    raw = data["without_dedup"]
    modelled = int(counts.get("modelled", 0))
    decisions = int(counts.get("decisions", 0))
    days = data["sim_days"]

    out: list[str] = []
    add = out.append
    add("# Measured unit economics")
    add("")
    add(
        f"Golden fixture, {days} sim-days, seed-fixed, pacing off. Every figure "
        "is what OpenRouter billed (`usage.cost`), recorded against the call "
        "that incurred it. Nothing is projected from list price."
    )
    add("")
    add("| | measured |")
    add("| --- | --- |")
    add(f"| persons | {counts.get('persons', 0)} |")
    add(f"| orgs | {counts.get('orgs', 0)} |")
    add(f"| events | {counts.get('events', 0)} |")
    add(f"| decisions | {decisions} |")
    add(f"| of those, decided by a model | {modelled} |")
    add(f"| distinct model calls those decisions needed | {data['model_calls']} |")
    add(f"| input tokens billed | {data['input_tokens']:,} |")
    add(
        f"| calls whose cost was estimated, not billed | "
        f"{data['spend_is_estimated_calls']} |"
    )
    add(
        f"| **total cost of this run, from a cold cache** | "
        f"**${data['spend_usd']:.6f}** |"
    )
    add("")

    add("## Decisions by model")
    add("")
    if data["decisions_by_model"]:
        add("| model | decisions | distinct calls |")
        add("| --- | --- | --- |")
        for row in data["decisions_by_model"]:
            add(f"| `{row['model']}` | {row['decisions']} | {row['calls']} |")
    else:
        add("None. Every decision in this run was made by rules.")
    add("")

    add("## By question set")
    add("")
    add("| question set | decided by | decisions | distinct calls | cost |")
    add("| --- | --- | --- | --- | --- |")
    for row in data["by_kind"]:
        add(
            f"| `{row['kind']}` | {row['source']} | {row['decisions']} | "
            f"{row['calls']} | ${row['usd']:.6f} |"
        )
    add("")

    add("## Against the targets")
    add("")
    add("| metric | target | measured | if nothing were shared | |")
    add("| --- | --- | --- | --- | --- |")
    met = modelled > 0
    for key, (label, target) in TARGETS.items():
        value, worst = float(per[key]), float(raw["per_sim_day"][key])
        ok = worst <= target
        met = met and ok
        add(
            f"| {label} | ${target:.2f} | ${value:.6f} | ${worst:.6f} | "
            f"{'ok' if ok else 'OVER'} |"
        )
    daily, daily_worst = float(per["usd"]), float(raw["per_sim_day"]["usd"])
    ok = daily_worst <= DAILY_TARGET_USD
    met = met and ok
    add(
        f"| spend per sim-day | ${DAILY_TARGET_USD:.2f} (cap ${DAILY_CAP_USD:.2f}) | "
        f"${daily:.6f} | ${daily_worst:.6f} | {'ok' if ok else 'OVER'} |"
    )
    add("")
    add(
        f"**Sharing.** {data['dedup_rate']:.1%} of model-made decisions reused a "
        "call another decision had already paid for: the situation, rendered in "
        "words, was identical, so the distribution is too — only the draw "
        "differs, and the draw is per person. *Measured* is what this run costs "
        "from a cold cache. *If nothing were shared* prices every decision as "
        "its own call; it is an upper bound computed from measured per-call "
        "costs, not something that was run, and the verdict column is judged "
        "against it so the targets are not met on the strength of the cache."
    )
    add("")

    if stats is not None:
        add(
            f"**This invocation** ran in `{stats['mode']}` mode: "
            f"{stats['asked']} decisions asked of the model, "
            f"{stats['from_cache']} answered from the cache, "
            f"{stats['live_calls']} live call(s) costing ${stats['live_usd']:.6f}."
        )
        add("")
    if data["unpriced_decisions"]:
        add(
            f"**Warning:** {data['unpriced_decisions']} decision(s) name a call "
            "that is not in `model_calls`, so their cost is missing above."
        )
        add("")

    add("## Verdict")
    add("")
    if modelled == 0:
        add(
            "**NOT MET.** Every decision in this run was made by rules, so the "
            "measured cost is $0. That is the true cost of what ran and is not "
            "evidence about the typed-decision path, which never executed."
        )
    elif met:
        add(
            f"**MET.** {modelled / max(1, decisions):.1%} of decisions were made "
            "by a model, and every target holds even with sharing ignored."
        )
    else:
        add("**NOT MET.** At least one target is exceeded; see the table.")
    add("")
    print("\n".join(out))
    return 0 if met else 3


if __name__ == "__main__":
    sys.exit(main())
