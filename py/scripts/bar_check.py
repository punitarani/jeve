"""The PR's bar, checked from committed JSON alone.

Each condition of the brief is read from files under `ops/evals/`, and nothing
is recomputed from a database, so anyone with the repository can regenerate
the verdict:

1. Every banded prior in band on every seed, for the rules twin and for
   production, with no soak invariant failing (`runs/*.json`).
2. Production beats the world before (e9a8c2b) on the scored contrasts and
   loses clearly on none (`report.verdict`, the scorecard fixed before the
   trial).
3. Both validated judges prefer after over before, with the Wilson interval
   clear of 0.5 (`judge/before-vs-jev-llm-rounds-*.json`).
4. Persona in routed conversations at least as strong as Jev's own on the same
   decisions (`prompt-lab/persona-final.json`, from
   `scripts/persona_gradients.py`).

    uv run python scripts/bar_check.py     # writes ops/evals/bar.json
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from jeve.config import find_repo_root
from jeve.evals import report
from jeve.evals.arms import CONFIRM_SEEDS, TRIAL_SEEDS
from jeve.evals.priors import PRIORS
from jeve.evals.stats import proportion_interval

OPS = find_repo_root() / "ops" / "evals"
PRODUCTION, BEFORE = "jev-llm-rounds", "before"
ROUNDS = {"trial": list(TRIAL_SEEDS), "confirm": list(CONFIRM_SEEDS)}
JUDGES = ("", ".claude-haiku-4.5")


def bands(worlds: dict[tuple[str, int], report.World]) -> dict[str, Any]:
    misses: list[str] = []
    checked = 0
    for arm in ("rules", PRODUCTION):
        for name, seeds in ROUNDS.items():
            for seed in seeds:
                world = worlds.get((arm, seed))
                if world is None:
                    misses.append(f"{arm} {seed}: not run")
                    continue
                for prior in PRIORS:
                    checked += 1
                    value = world.values.get(prior.measure)
                    if prior.verdict(value, world.days) != "PASS":
                        misses.append(f"{arm} {name} {seed}: {prior.measure} = {value}")
                misses += [f"{arm} {name} {seed}: {c}" for c in world.checks_failed]
    return {"holds": not misses, "checked": checked, "misses": misses}


def contrasts(worlds: dict[tuple[str, int], report.World]) -> dict[str, Any]:
    measures = (
        report.PLAUSIBILITY + report.HEALTH + report.DEPTH + report.SIGNAL + report.COST
    )
    out: dict[str, Any] = {}
    for name, seeds in ROUNDS.items():
        score: dict[str, list[str]] = {"better": [], "worse": []}
        for m in measures:
            a = [report._value(worlds.get((BEFORE, s)), m) for s in seeds]
            b = [report._value(worlds.get((PRODUCTION, s)), m) for s in seeds]
            said = report.verdict(m, a, b)
            if said:
                score[said].append(m)
        out[name] = {**score, "holds": bool(score["better"]) and not score["worse"]}
    out["holds"] = all(v["holds"] for v in out.values() if isinstance(v, dict))
    return out


def judges() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, seeds in ROUNDS.items():
        for suffix in JUDGES:
            # `evals.py judge` names its file after `--seeds` as given: the
            # seeds themselves, or the round's name.
            found = [
                OPS / "judge" / f"{BEFORE}-vs-{PRODUCTION}-{label}{suffix}.json"
                for label in (",".join(map(str, seeds)), name)
            ]
            key = f"{name}{suffix or '.gpt-5.6-luna'}"
            path = next((p for p in found if p.exists()), None)
            if path is None:
                out[key] = {"holds": False, "why": f"no {found[0].name}"}
                continue
            rows = json.loads(path.read_text())["tallies"]
            (total,) = [r for r in rows if str(r["label"]).endswith("(all)")]
            ci = proportion_interval(float(total["points"]), int(total["n"]))
            out[key] = {
                "n": total["n"],
                "after_preferred": float(total["points"]) / int(total["n"]),
                "wilson": ci,
                "holds": ci is not None and ci[0] > 0.5,
            }
    out["holds"] = all(v["holds"] for v in out.values() if isinstance(v, dict))
    return out


def persona() -> dict[str, Any]:
    path = OPS / "prompt-lab" / "persona-final.json"
    if not path.exists():
        return {"holds": False, "why": f"no {path.name}"}
    raw = json.loads(path.read_text())
    out: dict[str, Any] = {}
    for arm, got in raw.items():
        if not isinstance(got, dict) or "applied" not in got:
            continue
        rows = {
            g: {"applied": got["applied"][g], "jev": got["jev"][g]}
            for g in ("press_by_vocality", "small_talk_by_sociability")
        }
        out[arm] = {
            "decisions": got["decisions"],
            **rows,
            "holds": all(r["applied"] >= r["jev"] for r in rows.values()),
        }
    out["holds"] = bool(out) and all(v["holds"] for v in out.values())
    return out


def main(argv: Sequence[str] | None = None) -> int:
    seeds = [s for group in ROUNDS.values() for s in group]
    worlds = report.load([BEFORE, "before-rules", "rules", PRODUCTION], seeds)
    result = {
        "1_bands_and_invariants": bands(worlds),
        "2_beats_before": contrasts(worlds),
        "3_judges_prefer_after": judges(),
        "4_persona_at_least_jevs": persona(),
    }
    (OPS / "bar.json").write_text(json.dumps(result, indent=1) + "\n")
    for name, part in result.items():
        print(f"{name}: {'HOLDS' if part['holds'] else 'DOES NOT HOLD'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
