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

from jeve.evals.arms import ARMS, DEV_SEEDS, HELD_OUT_SEEDS, TRIAL_SEEDS, slug
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
    "late_reason_routine",
    "late_reason_approval",
    "late_reason_query",
    "late_reason_forgot",
    "late_reason_other_bills",
    "days_to_collect_mean",
    "receivables_open_share",
)
HEALTH = (
    "insolvency_warnings",
    "firms_failed",
    "payroll_held_or_missed",
    "staff_left",
    "subscriptions_cancelled",
    "detectors_firing",
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
    "repeat_meeting_share",
    "meetings_top10_pair_share",
    "distinct_pairs_met",
    "drift_first_last_week",
)
SIGNAL = (
    "event_payload_fields_mean",
    "event_caused_share",
    "causal_depth_mean",
    "causal_depth_max",
    "decision_facts_share",
    "decision_facts_fields_mean",
    "late_bill_reason_share",
    "late_bill_reminded_share",
    "late_bill_chases_mean",
)
BETTER: dict[str, int] = {
    "episode_settled_share": 1,
    "episode_stalled_share": -1,
    "ontology_gaps": -1,
    "persona_signal": 1,
    "identifiability_ratio": 1,
    "late_bill_reason_share": 1,
    "decision_facts_share": 1,
    "decision_facts_fields_mean": 1,
    "event_payload_fields_mean": 1,
    "event_caused_share": 1,
    "invariants_failed": -1,
    "detectors_firing": -1,
}
"""Which way is better, written down before the final trial was run
(2026-09-25): +1 higher, -1 lower. A measure with a cited band is scored by
its distance from the band instead. Everything else is reported and not
scored, because more of it is not plainly better: more entropy is not a more
real town, and nor is more drift or a longer causal chain."""


def band_distance(measure: str, value: float | None) -> float | None:
    """How far outside its band a measure is, in band widths: 0 inside."""

    prior = BY_MEASURE.get(measure)
    if prior is None or value is None:
        return None
    width = prior.high - prior.low
    outside = max(prior.low - value, value - prior.high, 0.0)
    return outside / width if width else outside


def verdict(
    measure: str, before: Sequence[float | None], after: Sequence[float | None]
) -> str:
    """`better`, `worse` or `` for a paired contrast, by the scorecard."""

    if measure in BY_MEASURE:
        p = paired(
            [band_distance(measure, v) for v in before],
            [band_distance(measure, v) for v in after],
        )
        sign = -1
    elif measure in BETTER:
        p = paired(before, after)
        sign = BETTER[measure]
    else:
        return ""
    if not p.clear or p.delta is None:
        return ""
    return "better" if p.delta * sign > 0 else "worse"


TRIAL_CONTRASTS: tuple[tuple[str, str, str], ...] = (
    ("before-rules", "rules", "The rules twin, before the signal work and after."),
    (
        "before",
        "jev-llm-rounds",
        "Production's world (Jev, conversations routed to tier 1), before the "
        "signal work and after.",
    ),
    ("jev", "jev-llm-rounds", "In the world after: conversations routed or not."),
)
"""The trial's contrasts cross a code change, which no arm's `against` can say:
`before` and `before-rules` ran at e9a8c2b and survive as their JSON."""
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
    against: str | None = None
    note: str = ""


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
                list(raw.get("checks_failed", [])), raw.get("against"),
                str(raw.get("note", "")),
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
        # A measure no world here can answer (added after these ran) is left
        # out rather than shown as a row of dashes.
        known = [_value(worlds.get((a, s)), measure) for a in arms for s in seeds]
        if all(v is None for v in known):
            continue
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
        # An arm whose code was retired still has its runs: what it was
        # compared against, and why, travel in its own JSON.
        kept = [w for (a, _), w in sorted(worlds.items()) if a == arm]
        known = ARMS.get(arm)
        against = known.against if known else (kept[0].against if kept else None)
        note = known.note if known else (kept[0].note if kept else "")
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
            f"{note} Paired by seed: Δ = {arm} - {against}, "
            f"bootstrap 95% interval, d_z. {clear} of {len(rows)} measures have an "
            "interval that excludes zero.",
            "",
            "| measure | Δ [95% CI], d_z | seeds |",
            "|---|---|---:|",
            *rows,
            "",
        ]
    return lines


def _trial_contrasts(
    worlds: dict[tuple[str, int], World], seeds: Sequence[int]
) -> list[str]:
    lines: list[str] = []
    measures = PLAUSIBILITY + HEALTH + DEPTH + SIGNAL + COST
    for before, after, note in TRIAL_CONTRASTS:
        if not any((before, s) in worlds for s in seeds):
            continue
        if not any((after, s) in worlds for s in seeds):
            continue
        rows: list[str] = []
        clear = 0
        score: dict[str, list[str]] = {"better": [], "worse": []}
        for measure in measures:
            a = [_value(worlds.get((before, s)), measure) for s in seeds]
            b = [_value(worlds.get((after, s)), measure) for s in seeds]
            p = paired(a, b)
            if p.delta is None:
                continue
            clear += p.clear
            mark = " **clear**" if p.clear else ""
            said = verdict(measure, a, b)
            if said:
                score[said].append(f"`{measure}`")
            rows.append(
                f"| `{measure}` | {p.text(_digits(measure))}{mark} | {said} | {p.n} |"
            )
        lines += [
            f"#### `{after}` against `{before}`",
            "",
            f"{note} Paired by seed: Δ = {after} - {before}, bootstrap 95% "
            f"interval, d_z. {clear} of {len(rows)} measures have an interval "
            "that excludes zero. Scored by the scorecard fixed before the "
            "trial (`report.BETTER`; a banded measure by its distance from the "
            f"band): clearly better on {len(score['better'])} "
            f"({', '.join(score['better']) or 'none'}), clearly worse on "
            f"{len(score['worse'])} ({', '.join(score['worse']) or 'none'}).",
            "",
            "| measure | Δ [95% CI], d_z | scored | seeds |",
            "|---|---|---|---:|",
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
    worlds = load(arms, [*DEV_SEEDS, *HELD_OUT_SEEDS, *TRIAL_SEEDS])
    held = [s for s in HELD_OUT_SEEDS if any((a, s) in worlds for a in arms)]
    dev = [s for s in DEV_SEEDS if any((a, s) in worlds for a in arms)]
    trial = [s for s in TRIAL_SEEDS if any((a, s) in worlds for a in arms)]
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
        f"{', '.join(map(str, held)) or 'none yet'}. Trial seeds: "
        f"{', '.join(map(str, trial)) or 'none yet'}. Horizon: "
        f"{', '.join(f'{d} sim-days' for d in days)}. Cells are mean ± sd over seeds.",
        "",
    ]
    for label, seeds in (
        ("60-day trial seeds", trial),
        ("held-out seeds", held),
        ("dev seeds", dev),
    ):
        if not seeds:
            continue
        # Only the arms that ran on these seeds get a column.
        here = [a for a in arms if any((a, s) in worlds for s in seeds)]
        everything = PLAUSIBILITY + HEALTH + DEPTH + SIGNAL + COST
        lines += [
            f"## On the {label}",
            "",
            "### Plausibility: stylized facts against real-world bands",
            "",
            *_arm_table(worlds, here, seeds, PLAUSIBILITY, bands=True),
            "",
            "### Health: does the economy hold up?",
            "",
            *_arm_table(worlds, here, seeds, HEALTH, bands=False),
            "",
            "### Depth: does who someone is, what they remember and whom they "
            "meet change what they do?",
            "",
            *_arm_table(worlds, here, seeds, DEPTH, bands=False),
            "",
            "### Signal: what each record says, and how far a consequence travels",
            "",
            *_arm_table(worlds, here, seeds, SIGNAL, bands=False),
            "",
            "### Cost and integrity",
            "",
            *_arm_table(worlds, here, seeds, COST, bands=False),
            "",
            "### Contrasts",
            "",
            *(
                _trial_contrasts(worlds, seeds)
                if seeds is trial
                else _contrasts(worlds, here, seeds, everything)
            ),
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
