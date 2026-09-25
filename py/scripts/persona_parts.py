"""Where a world's `persona_signal` comes from, detector part by detector part.

`persona_signal` (API-0004) is the mean gap between a trait's top and bottom
tertiles over five trait→act pairs. It counts every decision with a boolean
act, gated or asked. This splits it apart: each pair's gap, and for paying a
bill, the gap among decisions a model answered beside the rows a gate settled.
A gate settles the same way whoever the person is, so its rows can only
narrow the gap.

    uv run python scripts/persona_parts.py before,jev-llm-rounds \\
        20261201,20261202,20261203 ../ops/evals/prompt-lab/persona-parts.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

from jeve.api import detectors
from jeve.decide.questions import trait_level
from jeve.evals.runner import database, dsn_for


def _rate(yes: int, n: int) -> float | None:
    return round(yes / n, 4) if n else None


def parts(arm: str, seeds: list[int]) -> dict[str, object]:
    per_seed: dict[str, object] = {}
    # (asked or the gate's reason, tertile) -> [paid, decisions]
    pay: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for seed in seeds:
        with psycopg.connect(
            dsn_for(database(arm, seed)), row_factory=dict_row, autocommit=True
        ) as conn:
            reading = detectors.persona_signal(conn, 0)
            per_seed[str(seed)] = {"value": reading.value, "parts": reading.detail}
            for r in conn.execute(
                "SELECT p.traits->>'promptness' AS trait, "
                "(d.chosen->>'pay')::boolean AS paid, d.model_call IS NOT NULL "
                "AS asked, d.chosen->>'reason' AS reason FROM decisions d "
                "JOIN persons p ON p.id = d.person_id "
                "WHERE d.question_set = 'payment.timing' "
                "AND jsonb_typeof(d.chosen->'pay') = 'boolean'"
            ):
                trait = r["trait"]
                level = trait_level("promptness", float(trait) if trait else None)
                if level not in (0, 2):
                    continue
                how = "asked" if r["asked"] else f"gated: {r['reason']}"
                pay[(how, level)][0] += bool(r["paid"])
                pay[(how, level)][1] += 1
    split = {
        how: {
            "low": _rate(*pay[(how, 0)]),
            "high": _rate(*pay[(how, 2)]),
            "n_low": pay[(how, 0)][1],
            "n_high": pay[(how, 2)][1],
        }
        for how in sorted({how for how, _ in pay})
    }
    return {"per_seed": per_seed, "pay_by_promptness": split}


def main(argv: list[str]) -> int:
    arms, seeds, path = (
        argv[0].split(","),
        [int(s) for s in argv[1].split(",")],
        argv[2],
    )
    out = {"seeds": seeds, **{arm: parts(arm, seeds) for arm in arms}}
    with open(path, "w") as f:
        f.write(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
