"""Where lateness reaches a decision, measured on finished worlds.

Two readings per arm, pooled over seeds, from the decisions' own facts and
stored distributions (WORLD-0013):

* **chase** — the issuer's chance of chasing a bill (`chase.invoice`, P(yes)
  where a model answered, the drawn choice for the rules twin), by how late the
  bill is. Credit control escalates with a debt's age, and the rules twin does.
* **conversation** — how late the bills are that people talk about
  (`episode.round` with an invoice at stake), and a creditor's chance of
  pressing by that lateness. The prompt lab found that neither Jev nor tier 1
  presses harder for a bill weeks overdue. This asks whether the world ever
  puts such a bill in front of them.

    uv run python scripts/lateness_world.py jev,rules 20261201,20261202 \\
        ../ops/evals/prompt-lab/lateness-world.json
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

from jeve.evals.runner import database, dsn_for

AGES = ((0, 0, "not late"), (1, 3, "1-3"), (4, 6, "4-6"), (7, 9, "7-9"))
AGES += ((10, 20, "10-20"), (21, 10**6, "21+"))


def _age(days: int) -> str:
    return next(name for low, high, name in AGES if low <= days <= high)


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 4) if xs else None


def readings(arm: str, seeds: list[int]) -> dict[str, object]:
    chase: dict[str, list[float]] = defaultdict(list)
    talked: dict[str, int] = defaultdict(int)
    press: dict[str, list[float]] = defaultdict(list)
    for seed in seeds:
        with psycopg.connect(
            dsn_for(database(arm, seed)), row_factory=dict_row, autocommit=True
        ) as conn:
            for r in conn.execute(
                "SELECT (facts->>'days_late')::int AS late, "
                "(distributions->'chase'->>'yes')::float AS p, "
                "(chosen->>'chase')::bool AS drawn "
                "FROM decisions WHERE question_set = 'chase.invoice' "
                "AND facts ? 'days_late'"
            ):
                p = r["p"] if r["p"] is not None else float(bool(r["drawn"]))
                chase[_age(int(r["late"]))].append(p)
            for r in conn.execute(
                "SELECT (facts->>'days_late')::int AS late, "
                "facts->>'role_in_stake' AS role, distributions, chosen "
                "FROM decisions WHERE question_set = 'episode.round' "
                "AND facts->>'stake' = 'invoice' AND facts ? 'days_late'"
            ):
                age = _age(int(r["late"]))
                talked[age] += 1
                if r["role"] != "asker":
                    continue
                act = (r["distributions"] or {}).get("act")
                press[age].append(
                    float(act.get("press", 0.0))
                    if act
                    else float(r["chosen"].get("act") == "press")
                )
    names = [name for _, _, name in AGES]
    return {
        "p_chase": {a: _mean(chase[a]) for a in names if chase[a]},
        "chase_decisions": {a: len(chase[a]) for a in names if chase[a]},
        "invoice_round_decisions": {a: talked[a] for a in names if talked[a]},
        "creditor_p_press": {a: _mean(press[a]) for a in names if press[a]},
    }


def main(argv: list[str]) -> int:
    arms, seeds, path = (
        argv[0].split(","),
        [int(s) for s in argv[1].split(",")],
        argv[2],
    )
    out = {"seeds": seeds, **{arm: readings(arm, seeds) for arm in arms}}
    with open(path, "w") as f:
        f.write(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
