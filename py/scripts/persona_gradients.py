"""Persona in routed conversations, measured on the decisions themselves.

For every routed `episode.round` decision in finished worlds: how much likelier
the most outspoken third of people are to press than the quietest third, and
the most sociable third to make small talk than the least, in three answers
kept on each decision: what the world applied (`decisions.distributions`),
what Jev said for this person (`escalations.jev`), and what the LLM said
(`escalations.llm`). Bar 4 of the brief compares the first with the second.

    uv run python scripts/persona_gradients.py rounds-plain,rounds-persona \\
        20261260,20261261 ../ops/evals/prompt-lab/transplant-world.json
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

from jeve.decide.questions import trait_level
from jeve.evals.runner import database, dsn_for

ANSWERS = ("applied", "jev", "llm")


def gradients(arm: str, seeds: list[int]) -> dict[str, object]:
    by: dict[str, dict[tuple[str, int], list[float]]] = {
        w: defaultdict(list) for w in ANSWERS
    }
    done: dict[str, list[float]] = defaultdict(list)
    n = 0
    for seed in seeds:
        with psycopg.connect(
            dsn_for(database(arm, seed)), row_factory=dict_row, autocommit=True
        ) as conn:
            rows = conn.execute(
                "SELECT d.distributions, x.jev, x.llm, p.traits FROM escalations x "
                "JOIN decisions d ON d.id = x.decision_id "
                "JOIN persons p ON p.id = d.person_id "
                "WHERE x.question_set = 'episode.round'"
            ).fetchall()
        for r in rows:
            n += 1
            traits = r["traits"] or {}
            loud = trait_level("vocality", traits.get("vocality"))
            social = trait_level("sociability", traits.get("sociability"))
            for w, dist in zip(
                ANSWERS, (r["distributions"], r["jev"], r["llm"]), strict=True
            ):
                act = dist.get("act", {})
                if "press" in act:  # offered only to someone held up by it
                    by[w][("press", loud)].append(float(act["press"]))
                by[w][("small_talk", social)].append(float(act.get("small_talk", 0)))
                done[w].append(float(dist.get("done", {}).get("yes", 0)))
    out: dict[str, object] = {"decisions": n}
    for w in ANSWERS:
        g = by[w]
        out[w] = {
            "press_by_vocality": statistics.fmean(g[("press", 2)])
            - statistics.fmean(g[("press", 0)]),
            "small_talk_by_sociability": statistics.fmean(g[("small_talk", 2)])
            - statistics.fmean(g[("small_talk", 0)]),
            "p_done": statistics.fmean(done[w]),
        }
    return out


def main() -> int:
    arms = sys.argv[1].split(",")
    seeds = [int(s) for s in sys.argv[2].split(",")]
    result = {"seeds": seeds, **{arm: gradients(arm, seeds) for arm in arms}}
    text = json.dumps(result, indent=1) + "\n"
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
