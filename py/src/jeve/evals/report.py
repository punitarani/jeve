"""`ops/evals.md`: every arm's numbers, and every contrast with its variance.

Rendered from the committed per-world JSON under `ops/evals/runs/` and the
judge's JSON under `ops/evals/judge/`, never from a live database, so the
report regenerates for nothing and a reviewer can check a figure against the
file it came from.

Held-out seeds are reported apart from dev seeds and first: a role is kept or
reverted on the held-out contrast, which nobody looked at while building it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jeve.evals.arms import ARMS, DEV_SEEDS, HELD_OUT_SEEDS, slug
from jeve.evals.priors import BY_MEASURE, PRIORS
from jeve.evals.runner import RUNS
from jeve.evals.stats import paired, proportion_interval, summary

JUDGE_DIR = RUNS.parent / "judge"

PLAUSIBILITY = (
    *(p.measure for p in PRIORS),
    "ticket_escalation_share",
    "cafe_morning_share",
    "cafe_lunch_share",
    "cafe_walkout_share",
    "dispute_share",
)
DEPTH = (
    "persona_signal",
    "identifiability_ratio",
    "persona_retest_jsd",
    "action_entropy",
    "role_information",
    "episodes_per_day",
    "episode_settled_share",
    "episode_stalled_share",
    "episode_rounds_mean",
    "episode_moved_share",
    "knowledge_secondhand_share",
    "knowledge_max_hops",
    "promises_per_week",
    "promise_kept_share",
    "trust_spread",
    "negative_events",
    "ontology_gaps",
)
COST = (
    "cost_per_day_usd",
    "decisions_per_day",
    "model_share",
    "llm_share",
    "money_velocity",
    "invariants_failed",
)


@dataclass(frozen=True, slots=True)
class World:
    arm: str
    seed: int
    days: int
    values: dict[str, float | None]
    digest: str
    checks_failed: list[str]


def load(arms: Sequence[str], seeds: Sequence[int]) -> dict[tuple[str, int], World]:
    found: dict[tuple[str, int], World] = {}
    for arm in arms:
        for seed in seeds:
            path = RUNS / f"{slug(arm)}-{seed}.json"
            if not path.exists():
                continue
            raw: dict[str, Any] = json.loads(path.read_text())
            found[(arm, seed)] = World(
                arm, seed, int(raw["days"]), dict(raw["values"]), str(raw["digest"]),
                list(raw.get("checks_failed", [])),
            )  # fmt: skip
    return found


def _value(world: World | None, measure: str) -> float | None:
    if world is None:
        return None
    return world.values.get(measure)


def _digits(measure: str) -> int:
    return 5 if measure == "cost_per_day_usd" else 3


def _arm_table(
    worlds: dict[tuple[str, int], World],
    arms: Sequence[str],
    seeds: Sequence[int],
    measures: Sequence[str],
    *,
    bands: bool,
) -> list[str]:
    tail = " | band | source |" if bands else " |"
    header = "| measure | " + " | ".join(arms) + tail
    lines = [header, "|---|" + "---:|" * len(arms) + ("---|---|" if bands else "")]
    for measure in measures:
        cells = []
        for arm in arms:
            present = [worlds.get((arm, s)) for s in seeds]
            s = summary([_value(w, measure) for w in present])
            cell = s.text(_digits(measure))
            prior = BY_MEASURE.get(measure)
            if bands and prior is not None:
                verdicts = [
                    prior.verdict(_value(w, measure), w.days) for w in present if w
                ]
                passed = sum(1 for v in verdicts if v == "PASS")
                absent = sum(1 for v in verdicts if v == "ABSENT")
                cell += (
                    " (absent)"
                    if absent == len(verdicts)
                    else f" ({passed}/{len(verdicts) - absent} in band)"
                )
            cells.append(cell)
        row = f"| `{measure}` | " + " | ".join(cells) + " |"
        if bands:
            prior = BY_MEASURE.get(measure)
            row += (
                f" {prior.low:g}-{prior.high:g} | {prior.source} |"
                if prior
                else " — | no primary source |"
            )
        lines.append(row)
    return lines


def _contrasts(
    worlds: dict[tuple[str, int], World],
    arms: Sequence[str],
    seeds: Sequence[int],
    measures: Sequence[str],
) -> list[str]:
    lines: list[str] = []
    for arm in arms:
        against = ARMS[arm].against
        if against is None or against not in arms:
            continue
        rows: list[str] = []
        clear = 0
        for measure in measures:
            a = [_value(worlds.get((against, s)), measure) for s in seeds]
            b = [_value(worlds.get((arm, s)), measure) for s in seeds]
            p = paired(a, b)
            if p.delta is None:
                continue
            clear += p.clear
            mark = " **clear**" if p.clear else ""
            rows.append(f"| `{measure}` | {p.text(_digits(measure))}{mark} | {p.n} |")
        lines += [
            f"#### `{arm}` against `{against}`",
            "",
            f"{ARMS[arm].note} Paired by seed: Δ = {arm} - {against}, "
            f"bootstrap 95% interval, d_z. {clear} of {len(rows)} measures have an "
            "interval that excludes zero.",
            "",
            "| measure | Δ [95% CI], d_z | seeds |",
            "|---|---|---:|",
            *rows,
            "",
        ]
    return lines


def _judge_section() -> list[str]:
    if not JUDGE_DIR.exists():
        return ["No judge results yet."]
    lines: list[str] = []
    for path in sorted(JUDGE_DIR.glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text())
        lines += [f"#### {raw.get('title', path.stem)}", ""]
        lines += [str(raw.get("note", "")), ""]
        lines += [
            "| pair | n | right preferred | 95% CI | consistent both ways | ties |",
            "|---|---:|---:|---|---:|---:|",
        ]
        for row in raw.get("tallies", []):
            n = int(row["n"])
            ci = proportion_interval(float(row["points"]), n)
            ci_text = f"{ci[0]:.2f}-{ci[1]:.2f}" if ci else "—"
            rate = float(row["points"]) / n if n else 0.0
            lines.append(
                f"| {row['label']} | {n} | {rate:.2f} | {ci_text} | "
                f"{row['consistent']}/{n} | {row['ties']} |"
            )
        lines += ["", str(raw.get("footer", "")), ""]
    return lines


def render(arms: Sequence[str]) -> str:
    worlds = load(arms, [*DEV_SEEDS, *HELD_OUT_SEEDS])
    held = [s for s in HELD_OUT_SEEDS if any((a, s) in worlds for a in arms)]
    dev = [s for s in DEV_SEEDS if any((a, s) in worlds for a in arms)]
    days = sorted({w.days for w in worlds.values()})
    lines = [
        "# Evals: realism, depth and quality as numbers",
        "",
        "Generated by `make evals` from `ops/evals/runs/*.json` and "
        "`ops/evals/judge/*.json`; do not hand-edit. The harness and every "
        "definition are in `py/src/jeve/evals/` (EVAL-0001); the priors and "
        "their sources in `docs/research/04-llm-integration.md` §F.",
        "",
        f"Arms: {', '.join(f'`{a}`' for a in arms)}. Dev seeds: "
        f"{', '.join(map(str, dev)) or 'none'}. Held-out seeds: "
        f"{', '.join(map(str, held)) or 'none yet'}. Horizon: "
        f"{', '.join(f'{d} sim-days' for d in days)}. Cells are mean ± sd over seeds.",
        "",
    ]
    for label, seeds in (("held-out seeds", held), ("dev seeds", dev)):
        if not seeds:
            continue
        lines += [
            f"## On the {label}",
            "",
            "### Plausibility: stylized facts against real-world bands",
            "",
            *_arm_table(worlds, arms, seeds, PLAUSIBILITY, bands=True),
            "",
            "### Depth: does who someone is, what they remember and whom they "
            "meet change what they do?",
            "",
            *_arm_table(worlds, arms, seeds, DEPTH, bands=False),
            "",
            "### Cost and integrity",
            "",
            *_arm_table(worlds, arms, seeds, COST, bands=False),
            "",
            "### Contrasts",
            "",
            *_contrasts(worlds, arms, seeds, PLAUSIBILITY + DEPTH + COST),
        ]
    lines += ["## Believability: the judge", "", *_judge_section()]
    failing = sorted({c for w in worlds.values() for c in w.checks_failed})
    lines += [
        "## Invariants",
        "",
        (
            "Every world passed every soak invariant at its horizon."
            if not failing
            else "Failed somewhere: " + "; ".join(failing)
        ),
        "",
    ]
    return "\n".join(lines)


def write(arms: Sequence[str], out: Path) -> str:
    text = render(arms)
    out.write_text(text)
    return text
