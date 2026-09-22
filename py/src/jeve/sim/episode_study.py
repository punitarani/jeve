"""`make episodes`: does giving a meeting rounds change anything?

    make episodes                      # 21 sim-days each arm, on rules: free
    make episodes DAYS=35
    make episodes POLICY=jev CALLS=record   # live; spends money

Two runs of the same world from the same seed, differing in one thing: whether
a meeting with a real stake gets rounds (WORLD-0006). It writes
`ops/episodes.md` and answers the two questions the prior-art survey said
nobody has answered (`docs/research/03-recursive-micro-simulation.md`):

**E2 — is the cheap proxy docked?**  For the meetings that had an outage
between the people in them, how often did the one-shot encounter escalate, and
how often did an episode? If those rates are far apart, the resolution dial is
also moving the world's base rates, and every comparison downstream is
confounded. This is Davis and Bigelow's consistency test, in the only form a
social simulation can run it: aggregate outcome distributions, not matched
pairs, because the two arms diverge the moment they differ.

**E1 — does the extra resolution reach the economy?**  The billing timeline the
one-shot encounter already moves: when the first services invoice goes out, how
long outages ran, how many invoice runs were blocked. Reported with its sign,
never asserted — `test_episodes.py` checks invariants, and which way this moves
is a finding.

Run on rules, both arms cost nothing, which is what makes a long horizon and a
re-run per change affordable. The honest limitation is stated in the report:
one seed is an anecdote. `--seeds` runs several and reports the spread.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row

from jeve import db
from jeve.config import find_repo_root
from jeve.core.clock import DAY, SimTime
from jeve.decide.policy import RulesPolicy
from jeve.sim.runner import advance
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed

REPORT = find_repo_root() / "ops" / "episodes.md"
DATABASE = "jeve_episodes"


@dataclass(slots=True)
class Arm:
    """What one arm of the experiment produced."""

    episodes_on: bool
    seed: int
    days: int
    counts: dict[str, int] = field(default_factory=dict)
    first_services_invoice: int | None = None
    outage_minutes: int = 0
    longest_outage: int = 0
    blocked_runs: int = 0
    decisions: int = 0
    episode_decisions: int = 0
    escalation_chances: int = 0
    escalations: int = 0
    paid_late_days: float = 0.0
    facts_reach: int = 0

    @property
    def escalation_rate(self) -> float:
        if not self.escalation_chances:
            return 0.0
        return self.escalations / self.escalation_chances


def _one(conn: Connection[DictRow], query: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type, unused-ignore]
    assert row is not None
    return int(next(iter(row.values())) or 0)


def _maybe(
    conn: Connection[DictRow], query: str, params: tuple[object, ...] = ()
) -> int | None:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type, unused-ignore]
    if row is None:
        return None
    value = next(iter(row.values()))
    return int(value) if value is not None else None


def measure(
    conn: Connection[DictRow], *, episodes_on: bool, seed_value: int, days: int
) -> Arm:
    arm = Arm(episodes_on=episodes_on, seed=seed_value, days=days)

    arm.counts = {
        str(row["kind"]): int(row["n"])
        for row in conn.execute(
            "SELECT kind, count(*) AS n FROM events GROUP BY kind ORDER BY kind"
        ).fetchall()
    }
    arm.decisions = _one(conn, "SELECT count(*) AS n FROM decisions")
    arm.episode_decisions = _one(
        conn, "SELECT count(*) AS n FROM decisions WHERE question_set = 'episode.round'"
    )

    # E1: the billing timeline, exactly as `test_space.py` reads it for the
    # question "does space matter?".
    arm.first_services_invoice = _maybe(
        conn,
        "SELECT min(sim_time) AS t FROM events WHERE kind = 'invoice.issued' "
        "AND payload->>'invoice_kind' = 'services' "
        "AND payload->>'to' LIKE '%%.client.%%'",
    )
    arm.outage_minutes = _one(
        conn,
        "SELECT COALESCE(sum((payload->>'minutes')::int), 0) AS m FROM events "
        "WHERE kind = 'incident.ended'",
    )
    arm.longest_outage = _one(
        conn,
        "SELECT COALESCE(max((payload->>'minutes')::int), 0) AS m FROM events "
        "WHERE kind = 'incident.ended'",
    )
    arm.blocked_runs = arm.counts.get("invoice.blocked", 0)
    late = conn.execute(
        "SELECT COALESCE(avg(days_late), 0) AS d FROM payments"
    ).fetchone()
    arm.paid_late_days = float(late["d"]) if late else 0.0

    # E2: the docking comparison. A "chance to escalate" is a meeting at which
    # somebody stuck with a broken module was standing next to the vendor —
    # counted the same way in both arms, from whichever record that arm keeps.
    if episodes_on:
        arm.escalation_chances = _one(
            conn, "SELECT count(*) AS n FROM episodes WHERE stake = 'outage'"
        )
        arm.escalations = _one(
            conn,
            "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated' "
            "AND payload->>'decided_by' = 'episode'",
        )
    else:
        arm.escalation_chances = _one(
            conn,
            "SELECT count(*) AS n FROM events WHERE kind = 'encounter' "
            "AND payload->>'topic' = 'the_outage'",
        )
        arm.escalations = _one(
            conn,
            "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated' "
            "AND payload->>'decided_by' <> 'episode'",
        )

    arm.facts_reach = _one(conn, "SELECT count(*) AS n FROM knowledge WHERE hops > 0")
    return arm


def run_arm(
    conn: Connection[DictRow], *, episodes_on: bool, seed_value: int, days: int
) -> Arm:
    seed(conn, root_seed=seed_value)
    engine = Engine(
        conn, RulesPolicy(seed_value), root_seed=seed_value, episodes=episodes_on
    )
    advance(conn, engine, until=days * DAY)
    conn.commit()
    return measure(conn, episodes_on=episodes_on, seed_value=seed_value, days=days)


# -- the report ------------------------------------------------------------------


def _clock(seconds: int | None) -> str:
    return SimTime(seconds).label() if seconds is not None else "never"


def _delta(on: float, off: float, unit: str = "") -> str:
    difference = on - off
    if abs(difference) < 1e-9:
        return "no change"
    return f"{difference:+,.0f}{unit}" if abs(difference) >= 1 else f"{difference:+.3f}"


def render(pairs: list[tuple[Arm, Arm]]) -> str:
    days = pairs[0][0].days
    lines = [
        "# Episodes: what the extra rounds bought",
        "",
        f"{len(pairs)} seed(s), {days} sim-days per arm, on the rules twin "
        "(null model N1), so both arms are free and this can be re-run on every "
        "change. Generated by `make episodes`; do not hand-edit.",
        "",
        "Two runs of one world differing in one thing: whether a meeting with a "
        "real stake gets rounds instead of one shot (WORLD-0006). Everything "
        "below is **measured, not asserted** — `py/tests/test_episodes.py` holds "
        "the invariants, and which way these move is the finding.",
        "",
        "## E2 — is the one-shot encounter docked to the episode?",
        "",
        "The question that has to be answered first: if the cheap proxy and the "
        "expensive arm disagree about how often a conversation gets an outage "
        "escalated, then turning episodes on moves the world's base rates and "
        "every other comparison is confounded. A *chance* is a meeting at which "
        "somebody stuck with a broken module stood next to the vendor.",
        "",
        "**Read the gap as an upper bound, not an effect.** The two denominators "
        "are not the same construct and cannot be: with episodes off the world "
        "keeps no record of a stake, so the count is every conversation whose "
        "topic was the outage, while with them on it is the meetings that were "
        "*selected* into an episode — which requires a live stake, a free "
        "cooldown and room in the day's budget. Selection is therefore inside "
        "the gap along with resolution, and the honest reading is that the two "
        "arms disagree by at most this much. Separating them needs the shadow "
        "arm this harness does not yet run: episodes computed at every eligible "
        "meeting and applied at none.",
        "",
        "| seed | chances (off) | escalated (off) | rate (off) | chances (on) | "
        "escalated (on) | rate (on) | gap |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for on, off in pairs:
        gap = on.escalation_rate - off.escalation_rate
        lines.append(
            f"| {on.seed} | {off.escalation_chances} | {off.escalations} | "
            f"{off.escalation_rate:.2f} | {on.escalation_chances} | "
            f"{on.escalations} | {on.escalation_rate:.2f} | {gap:+.2f} |"
        )

    mean_gap = sum(on.escalation_rate - off.escalation_rate for on, off in pairs) / len(
        pairs
    )
    lines += [
        "",
        f"**Mean gap: {mean_gap:+.2f}.** A gap near zero means the two "
        "resolutions agree about what a meeting is worth, and the dial is safe "
        "to turn. A large gap is not a bug in either arm — it is the finding "
        "that resolution and base rate are entangled, and the one-shot "
        "question's wording is what would have to be recalibrated.",
        "",
        "## E1 — does it reach the economy?",
        "",
        "The billing timeline the one-shot encounter already moves.",
        "",
        "| measure | episodes off | episodes on | change |",
        "|---|---:|---:|---:|",
    ]

    def row(label: str, get: str, unit: str = "") -> str:
        ons = [getattr(on, get) for on, _ in pairs]
        offs = [getattr(off, get) for _, off in pairs]
        on_mean = sum(ons) / len(ons)
        off_mean = sum(offs) / len(offs)
        return (
            f"| {label} | {off_mean:,.1f} | {on_mean:,.1f} | "
            f"{_delta(on_mean, off_mean, unit)} |"
        )

    first_on = [on.first_services_invoice or 0 for on, _ in pairs]
    first_off = [off.first_services_invoice or 0 for _, off in pairs]
    mean_on_first = sum(first_on) / len(first_on)
    mean_off_first = sum(first_off) / len(first_off)
    lines.append(
        f"| first services invoice | {_clock(int(mean_off_first))} | "
        f"{_clock(int(mean_on_first))} | "
        f"{_delta(mean_on_first, mean_off_first, 's')} |"
    )
    lines += [
        row("outage minutes, total", "outage_minutes", " min"),
        row("longest outage", "longest_outage", " min"),
        row("blocked invoice runs", "blocked_runs"),
        row("average days late, paid bills", "paid_late_days"),
        row("second-hand knowledge rows", "facts_reach"),
        "",
        "## What the extra resolution cost",
        "",
        "| measure | episodes off | episodes on |",
        "|---|---:|---:|",
    ]
    on_decisions = sum(on.decisions for on, _ in pairs) / len(pairs)
    off_decisions = sum(off.decisions for _, off in pairs) / len(pairs)
    on_rounds = sum(on.episode_decisions for on, _ in pairs) / len(pairs)
    lines += [
        f"| decisions | {off_decisions:,.0f} | {on_decisions:,.0f} |",
        f"| of those, episode rounds | 0 | {on_rounds:,.0f} |",
        f"| extra decisions | — | {on_decisions - off_decisions:+,.0f} "
        f"({(on_decisions / off_decisions - 1) * 100:+.1f}%) |",
        "",
        "On the rules twin a decision is free. The figure that matters is the "
        "*share*: against the measured $0.0000384 per distinct model call in "
        "`ops/economics.md`, and before any cache sharing between rooms in the "
        "same state, the extra rounds above would add roughly "
        f"${(on_rounds - 0) * 0.0000384 / days:,.4f} per sim-day.",
        "",
        "## What happened, by event",
        "",
        "| event | off | on |",
        "|---|---:|---:|",
    ]
    kinds = sorted(
        {k for on, off in pairs for k in (*on.counts, *off.counts)} - {"agent.moved"}
    )
    for kind in kinds:
        on_total = sum(on.counts.get(kind, 0) for on, _ in pairs)
        off_total = sum(off.counts.get(kind, 0) for _, off in pairs)
        if on_total == off_total == 0:
            continue
        lines.append(f"| `{kind}` | {off_total} | {on_total} |")

    lines += [
        "",
        "## How to read this",
        "",
        "One seed is an anecdote; `--seeds` runs more. Both arms are the rules "
        "twin, so this measures what the *mechanism* does, not what Jev does "
        "with it — the same report under `POLICY=jev CALLS=record` is the "
        "measurement that bears on the research question, and it costs money.",
        "",
        "The comparison is between two worlds that diverge: once an episode "
        "runs, the people in it have spent decisions the other arm did not, so "
        "their later draws differ. That is a counterfactual, not noise, but it "
        "does mean a single-seed difference cannot be read as an effect size.",
        "",
    ]
    return "\n".join(lines)


# -- entry point -----------------------------------------------------------------


def _own_database() -> str:
    """A database of this experiment's own, beside the one a daemon may hold."""

    parts = urlsplit(db.dsn())
    admin = urlunsplit(parts._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True, row_factory=dict_row) as conn:
        found = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if found is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
    return urlunsplit(parts._replace(path=f"/{DATABASE}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument(
        "--seeds",
        type=int,
        default=1,
        help="how many seeds to run per arm; one is an anecdote",
    )
    parser.add_argument("--out", default=str(REPORT))
    args = parser.parse_args(argv)

    try:
        dsn = _own_database()
    except psycopg.OperationalError as error:
        print(f"no database at {db.dsn()}: {error}", file=sys.stderr)
        return 2

    pairs: list[tuple[Arm, Arm]] = []
    for index in range(args.seeds):
        seed_value = ROOT_SEED + index
        with psycopg.connect(dsn, row_factory=dict_row, autocommit=False) as conn:
            db.migrate(conn)
            conn.commit()
            print(f"seed {seed_value}: episodes off …", file=sys.stderr)
            off = run_arm(
                conn, episodes_on=False, seed_value=seed_value, days=args.days
            )
            print(f"seed {seed_value}: episodes on  …", file=sys.stderr)
            on = run_arm(conn, episodes_on=True, seed_value=seed_value, days=args.days)
        pairs.append((on, off))

    report = render(pairs)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
