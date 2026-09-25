"""How often a perfectly calibrated world passes the turnover band on one seed.

Staff turnover over a 60-day run is a count of one or two departures among 24
staff, and the band's ceiling (0.035 a month, BLS JOLTS quits) sits between
them: one departure reads 0.021, two read 0.042. Whether a seed passes is then
mostly luck. This computes that luck exactly, from the seeded staff, the heads
who never quit, the world's own quit rates converted to its 28-day months, and
the month-ends whose notice ends inside the run. Only the hazard for staff
nothing is pushing is counted, so this is the best case: a world whose people
have reasons to go does worse.

It then counts what the rules twin's 60-day worlds actually drew: departures
by the unpushed hazard whose notice ended inside the run, per world, and how
likely that many or more is from a calibrated world. The final trial's seeds
and the dev seeds are read separately.

    uv run python scripts/band_power.py            # writes ops/evals/band-power.json
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

from jeve.config import find_repo_root
from jeve.core.clock import DAY
from jeve.evals.arms import CONFIRM_SEEDS, TRIAL_SEEDS
from jeve.evals.priors import BY_MEASURE
from jeve.evals.runner import database, dsn_for
from jeve.world.economy import (
    HEADS,
    MONTH,
    NOTICE,
    QUITS_MONTHLY,
    QUITS_MONTHLY_DEFAULT,
    UNPUSHED_REASONS,
    per_month,
)
from jeve.world.seed_world import STAFF

FIRST_MONTH_END = 3 * DAY + 9 * 3600 + 30 * 60
"""`seed_world`: month-end lands on day 3 at 09:30, and careers are weighed
then (WORLD-0014)."""


def departures(chances: list[float]) -> list[float]:
    """The exact distribution of how many of these independent draws come up."""

    dist = [1.0]
    for p in chances:
        nxt = [0.0] * (len(dist) + 1)
        for k, q in enumerate(dist):
            nxt[k] += q * (1 - p)
            nxt[k + 1] += q * p
        dist = nxt
    return dist


DEV_SEEDS = (*range(20261211, 20261216), *range(20261240, 20261246))
"""The rules twin's complete 60-day dev worlds (20261210 stopped at day 26)."""


def drawn(seeds: Sequence[int], chances: list[float]) -> dict[str, object]:
    """Unpushed departures the rules twin drew in these worlds, and the chance
    of that many or more from a calibrated world run as many times."""

    unpushed = [name for name, _ in UNPUSHED_REASONS]
    per_world = {}
    for seed in seeds:
        with psycopg.connect(
            dsn_for(database("rules", seed)), row_factory=dict_row, autocommit=True
        ) as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM events WHERE kind = 'staff.notice' "
                "AND payload->>'reason' = ANY(%s) "
                "AND sim_time + %s < (SELECT sim_time FROM sim_meta)",
                (unpushed, NOTICE),
            ).fetchone()
        per_world[str(seed)] = int(row["n"]) if row else 0
    total = sum(per_world.values())
    dist = departures(chances * len(seeds))
    return {
        "per_world": per_world,
        "total": total,
        "expected": round(sum(chances) * len(seeds), 3),
        "p_at_least_total": round(sum(dist[total:]), 4),
    }


def main() -> int:
    prior = BY_MEASURE["staff_turnover_monthly"]
    staff = len(STAFF)
    eligible = [org for org, role, _ in STAFF if HEADS.get(org) != role]
    out: dict[str, object] = {"band": [prior.low, prior.high], "staff": staff}
    rows = []
    for days in (60, 180, 365):
        reviews = [
            t
            for t in range(FIRST_MONTH_END, days * DAY, MONTH)
            if t + NOTICE < days * DAY
        ]
        chances = [
            per_month(QUITS_MONTHLY.get(org, QUITS_MONTHLY_DEFAULT))
            for _ in reviews
            for org in eligible
        ]
        dist = departures(chances)
        # The harness's measure: departures over staff, per 30 days.
        passing = sum(
            q
            for k, q in enumerate(dist)
            if prior.low <= k / staff * 30 / days <= prior.high
        )
        mean = sum(chances)
        rows.append(
            {
                "days": days,
                "reviews": len(reviews),
                "expected_departures": round(mean, 3),
                "expected_monthly": round(mean / staff * 30 / days, 4),
                "pass_one_seed": round(passing, 4),
                "pass_three_seeds": round(passing**3, 4),
                "pass_six_seeds": round(passing**6, 4),
                "most_departures_in_band": max(
                    k for k in range(len(dist)) if k / staff * 30 / days <= prior.high
                ),
            }
        )
    out["horizons"] = rows
    sixty = [
        per_month(QUITS_MONTHLY.get(org, QUITS_MONTHLY_DEFAULT))
        for t in range(FIRST_MONTH_END, 60 * DAY, MONTH)
        if t + NOTICE < 60 * DAY
        for org in eligible
    ]
    out["drawn"] = {
        "final": drawn([*TRIAL_SEEDS, *CONFIRM_SEEDS], sixty),
        "dev": drawn(DEV_SEEDS, sixty),
    }
    out["note"] = (
        "Unpushed hazard only (the best case). A seed passes when departures / "
        "staff per 30 days is inside the band; the chance is exact "
        "(Poisson-binomial over each eligible person's draw at each month-end "
        "whose notice ends inside the run)."
    )
    path = find_repo_root() / "ops" / "evals" / "band-power.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    for row in rows:
        print(row)
    print(out["drawn"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
