"""Gate 6: the measured unit-economics report.

Read from the spend ledger and the database, never projected. A run that made
no model calls reports $0 and says so — the honest number, not a placeholder.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

TARGETS = {
    "usd_per_100_persons": 1.00,
    "usd_per_10_orgs": 1.00,
    "usd_per_1000_events": 1.00,
}
DAILY_TARGET_USD = 2.00
DAILY_CAP_USD = 10.00


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()

    with urllib.request.urlopen(f"{args.api}/economics", timeout=20) as response:
        data = json.load(response)

    counts = data["counts"]
    per = data["per_sim_day"]
    modelled = int(counts.get("modelled", 0))
    decisions = int(counts.get("decisions", 0))

    out: list[str] = []
    add = out.append
    add("# Measured unit economics")
    add("")
    add(f"Fixture: {args.days} sim-days, seed-fixed, pacing off.")
    add("")
    add("| | measured |")
    add("| --- | --- |")
    add(f"| persons | {counts.get('persons', 0)} |")
    add(f"| orgs | {counts.get('orgs', 0)} |")
    add(f"| events | {counts.get('events', 0)} |")
    add(f"| decisions | {decisions} |")
    add(f"| of those, decided by a model | {modelled} |")
    add(f"| model calls | {data['model_calls']} |")
    add(f"| total spend | ${data['spend_usd']:.6f} |")
    add("")
    add("## Against the targets")
    add("")
    add("| metric | target | measured | |")
    add("| --- | --- | --- | --- |")
    for key, target in TARGETS.items():
        value = float(per[key])
        verdict = "ok" if value <= target else "OVER"
        add(f"| {key.replace('_', ' ')} | ${target:.2f} | ${value:.6f} | {verdict} |")
    daily = float(data["spend_usd"]) / max(1, args.days)
    add(
        f"| spend per sim-day | ${DAILY_TARGET_USD:.2f} "
        f"(cap ${DAILY_CAP_USD:.2f}) | ${daily:.6f} | "
        f"{'ok' if daily <= DAILY_TARGET_USD else 'OVER'} |"
    )
    add("")

    if modelled == 0:
        add("## What this number does and does not mean")
        add("")
        add(
            "**Every decision in this run was made by rules, so the measured "
            "cost is $0.** That is the true cost of what ran; it is not "
            "evidence that the targets are met, because the expensive path — "
            "typed decisions through Jev — never executed."
        )
        add("")
        add(
            "Jev is unreachable: the OpenRouter account's allowed-providers "
            "list excludes `typesafe`, so the decisions endpoint 404s. See "
            "`BLOCKED.md` B1. Until that is lifted, the unit-economics gate is "
            "**reported as not met rather than passed**, and the figures above "
            "describe the rules-only baseline (null model N1)."
        )
        add("")
        add(
            f"For scale, the run made {decisions} decisions over {args.days} "
            f"sim-days. At Jev's published $0.042/M input and an estimated "
            f"3.5k tokens per call, those would have cost about "
            f"${decisions * 3500 * 0.042 / 1e6:.4f} — an estimate from list "
            f"price, not a measurement, and exactly the kind of projection the "
            f"brief asks not to be given instead of a number."
        )
    else:
        add(f"Model-decided share: {modelled / max(1, decisions):.1%} of decisions.")
    add("")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
