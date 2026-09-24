"""`make escalation-report`: what tier 1 said when it was asked (DECIDE-0005).

Reads the `escalations` rows a run kept and writes `ops/escalation.md`: per
question set, how often the two tiers agreed inside the bands and in the
uniform sample, and what the second opinions cost and how long they took.

design/005 sets the bar a set must clear before a person names it in
`JEVE_ESCALATION_LIVE`: at least 200 shadow rows, and disagreement that is
concentrated in the band. Agreement above 95% inside the band means tier 1
buys nothing there; agreement in the band no lower than in the uniform sample
means confidence is not a usable gate, and stakes alone should decide.

Wall-clock latency is reported because it decides design/005's open question:
a tier-1 call is synchronous inside the tick (DECIDE-0005), and if its P95 is
long enough to matter, the answer is a `deliberating` state, not a faster tick.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.config import find_repo_root
from jeve.decide import escalation

REPORT = find_repo_root() / "ops" / "escalation.md"
MIN_SHADOW = 200
NOTHING_TO_BUY = 0.95
BAND_MUST_BEAT_SAMPLE_BY = 0.10


@dataclass(frozen=True, slots=True)
class SetRow:
    question_set: str
    shadow: int
    live: int
    banded: int
    banded_agree: float | None
    sampled: int
    sampled_agree: float | None

    @property
    def verdict(self) -> str:
        if self.live:
            return "live"
        if self.shadow < MIN_SHADOW:
            return f"collecting ({self.shadow}/{MIN_SHADOW})"
        if self.banded_agree is not None and self.banded_agree > NOTHING_TO_BUY:
            return "tier 1 buys nothing here: keep Jev"
        if (
            self.banded_agree is not None
            and self.sampled_agree is not None
            and self.sampled_agree - self.banded_agree >= BAND_MUST_BEAT_SAMPLE_BY
        ):
            return "the band finds the disagreement: a candidate for live"
        return "disagreement is not where the band looks: gate on stakes alone"


def by_set(conn: Connection[DictRow]) -> list[SetRow]:
    rows = conn.execute(
        """
        SELECT question_set,
               count(*) FILTER (WHERE NOT applied) AS shadow,
               count(*) FILTER (WHERE applied) AS live,
               count(*) FILTER (WHERE NOT sampled) AS banded,
               avg(agrees::int) FILTER (WHERE NOT sampled) AS banded_agree,
               count(*) FILTER (WHERE sampled) AS sampled,
               avg(agrees::int) FILTER (WHERE sampled) AS sampled_agree
        FROM escalations GROUP BY question_set ORDER BY question_set
        """
    ).fetchall()
    return [
        SetRow(
            question_set=str(row["question_set"]),
            shadow=int(row["shadow"]),
            live=int(row["live"]),
            banded=int(row["banded"]),
            banded_agree=_float(row["banded_agree"]),
            sampled=int(row["sampled"]),
            sampled_agree=_float(row["sampled_agree"]),
        )
        for row in rows
    ]


def _float(value: object) -> float | None:
    return None if value is None else float(str(value))


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def render(conn: Connection[DictRow]) -> str:
    sets = by_set(conn)
    lines = [
        "# Tier-1 escalation",
        "",
        "Written by `make escalation-report` from the `escalations` table "
        "(DECIDE-0005). Agreement is agreement with a flash LLM, not "
        "correctness: it is the only reference there is (design/005).",
        "",
    ]
    if not sets:
        lines += [
            "No second opinions yet. Run the daemon with `JEVE_ESCALATION=shadow` "
            "and `JEVE_CALLS=record`; a replay only reads back what was recorded.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## By question set",
        "",
        "| set | stakes | shadow | live | in band | agree in band "
        "| sampled | agree in sample | verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sets:
        lines.append(
            f"| {row.question_set} | {escalation.stakes(row.question_set)} "
            f"| {row.shadow} | {row.live} | {row.banded} "
            f"| {_pct(row.banded_agree)} | {row.sampled} "
            f"| {_pct(row.sampled_agree)} | {row.verdict} |"
        )

    rules = conn.execute(
        """
        SELECT t->>'rule' AS rule, count(*) AS n, avg(e.agrees::int) AS agree
        FROM escalations e, jsonb_array_elements(e.triggers) t
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    lines += ["", "## By rule", "", "| rule | fired | agree |", "|---|---:|---:|"]
    lines += [
        f"| {row['rule']} | {row['n']} | {_pct(_float(row['agree']))} |"
        for row in rules
    ]

    calls = conn.execute(
        """
        SELECT model, count(*) AS n, coalesce(sum(cost_usd), 0) AS cost,
               avg(latency_s) AS mean_s,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_s) AS p95_s
        FROM model_calls WHERE kind = %s AND NOT response ? 'unanswered'
        GROUP BY model ORDER BY model
        """,
        (escalation.KIND,),
    ).fetchall()
    lines += [
        "",
        "## What it cost",
        "",
        "Every tier-1 call recorded, cached or not, by the model that answered.",
        "",
        "| model | calls | cost | mean latency | p95 latency |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {row['model']} | {row['n']} | ${float(row['cost']):.4f} "
        f"| {float(row['mean_s'] or 0):.1f}s | {float(row['p95_s'] or 0):.1f}s |"
        for row in calls
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make escalation-report", description=__doc__)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    # Autocommit: a reader that holds a transaction open blocks the daemon's
    # TRUNCATE on a reseed.
    with db.connect(autocommit=True) as conn:
        text = render(conn)
    args.out.write_text(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
