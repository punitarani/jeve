"""The simulation process (SIM-0001).

    python -m jeve.sim --seed-world --until-day 5 --day-minutes 0   # the fixture
    python -m jeve.sim                                              # ever-running

One code path for both. The fixture is this daemon with pacing off and a
horizon; the daemon is the fixture with a clock and no end.

Restart-safe by construction rather than by care: a tick is one transaction, so
a process killed at any instant leaves the world at the end of the last complete
tick, and starting again simply continues. There is no shutdown procedure to get
wrong. `--until` is what makes a wall-clock process replayable: a live run and
its replay both stop at the same sim time, whatever the wall clock was doing.

This module reads the wall clock, which the rest of the simulation is forbidden
to do. None of it reaches simulation state: it decides *when* the next tick
runs, never what the tick does.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, TICK, SimTime
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.recorder import ReplayMissError, finalize_cassette, load_cassette
from jeve.errors import BudgetExceededError
from jeve.sim.runner import CASSETTE, Totals, build_policy, policy_from_env
from jeve.world.engine import Engine, skip_to_next_open
from jeve.world.seed_world import ROOT_SEED, seed

DEFAULT_DAY_MINUTES = 24.0
"""One sim-day per 24 real minutes: a fifteen-minute tick every fifteen seconds."""

NIGHT_SPEEDUP = 10.0
"""Closed hours pass this much faster than open ones. Nothing happens at night,
and a town that sits empty for fourteen real minutes in every twenty-four is a
poor thing to watch. The tick rate while anything is open is unaffected."""

DEFAULT_DAILY_BUDGET_USD = 2.00


@dataclass(slots=True)
class Pace:
    """How fast sim time is allowed to pass, and how much it may spend."""

    day_minutes: float
    daily_budget_usd: float

    @property
    def seconds_per_tick(self) -> float:
        return self.day_minutes * 60.0 * TICK / DAY

    @property
    def window_s(self) -> float:
        """Real seconds that correspond to one sim-day: the budget's period."""

        return self.day_minutes * 60.0


class _Stop:
    """Set by a signal handler, so it can change between any two statements."""

    def __init__(self) -> None:
        self._requested = False

    def __call__(self, signum: int, frame: FrameType | None) -> None:
        self._requested = True

    def requested(self) -> bool:
        # A method, not an attribute: a type checker narrows `stop.requested()`
        # to False inside `while not stop.requested()` and then calls every later
        # check unreachable, which is exactly wrong for a flag a signal sets.
        return self._requested


def _status(conn: Connection[DictRow], status: str) -> None:
    conn.execute("UPDATE sim_meta SET status = %s, updated_at = now()", (status,))
    conn.commit()


def _sleep(seconds: float, stop: _Stop) -> None:
    deadline = time.monotonic() + seconds
    while not stop.requested() and (left := deadline - time.monotonic()) > 0:
        time.sleep(min(0.25, left))


def run(args: argparse.Namespace) -> int:
    stop = _Stop()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    pace = Pace(args.day_minutes, args.daily_budget)

    with db.connect() as conn:
        db.migrate(conn)
        # Ten seconds: long enough to outlive a killed predecessor's backend,
        # short enough that a genuine second writer is told promptly.
        db.take_writer_lock(conn, wait_s=10.0)

        seeded = conn.execute("SELECT 1 FROM sim_meta").fetchone() is not None
        if args.seed_world or not seeded:
            summary = seed(conn, root_seed=args.seed)
            print(
                f"seeded {summary.orgs} orgs, {summary.persons} persons "
                f"({summary.staff} staff + {summary.counterparties} counterparties)"
            )
        if args.policy == "jev":
            # In both modes: a recording run must not pay again for what it has.
            loaded = load_cassette(conn, CASSETTE)
            conn.commit()
            print(f"cassette: {loaded} call(s) preloaded from {CASSETTE.name}")

        policy = build_policy(args.policy, args.calls, root_seed=args.seed)
        engine = Engine(conn, policy, root_seed=args.seed)
        totals = Totals()
        code = 0
        try:
            code = _loop(conn, engine, policy, pace, args, stop, totals)
        finally:
            _report(conn, policy, args, totals)
        return code


def _loop(
    conn: Connection[DictRow],
    engine: Engine,
    policy: object,
    pace: Pace,
    args: argparse.Namespace,
    stop: _Stop,
    totals: Totals,
) -> int:
    window_started = time.monotonic()
    window_spent_from = _live_spend(policy)
    _status(conn, "running")

    while not stop.requested():
        row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
        assert row is not None
        now = SimTime(int(row["sim_time"]))

        if args.until is not None and now.seconds >= args.until:
            _status(conn, "paused")
            print(f"reached the horizon at {now}")
            if not args.idle:
                return 0
            # Stay up so the API and the page have a live process to look at;
            # the world itself is finished and nothing more is written.
            while not stop.requested():
                _sleep(1.0, stop)
            return 0

        if not now.in_office_hours and not now.cafe_open:
            before = now.seconds
            after = skip_to_next_open(conn)
            if args.until is not None and after > args.until:
                conn.execute("UPDATE sim_meta SET sim_time = %s", (args.until,))
                conn.commit()
                after = args.until
            skipped_ticks = (after - before) / TICK
            _sleep(skipped_ticks * pace.seconds_per_tick / NIGHT_SPEEDUP, stop)
            continue

        # The governor (CORE-0002). A sim-day's worth of real time has a model
        # budget; spend it and the clock stops until the window rolls over.
        # Sim time stretches; the world never sees a rule change.
        if pace.window_s > 0:
            elapsed = time.monotonic() - window_started
            if elapsed >= pace.window_s:
                window_started, window_spent_from = (
                    time.monotonic(),
                    _live_spend(policy),
                )
            elif _live_spend(policy) - window_spent_from >= pace.daily_budget_usd:
                _status(conn, "paused_budget")
                print(
                    f"daily model budget of ${pace.daily_budget_usd:.2f} spent; "
                    f"pausing {pace.window_s - elapsed:.0f}s until the window rolls"
                )
                _sleep(pace.window_s - elapsed, stop)
                _status(conn, "running")
                continue

        started = time.monotonic()
        try:
            report = engine.tick()
        except BudgetExceededError as error:
            _status(conn, "halted")
            print(f"HALTED: {error}", file=sys.stderr)
            return 4
        except ReplayMissError as error:
            _status(conn, "halted")
            print(f"HALTED: {error}", file=sys.stderr)
            return 5
        totals.ticks += 1
        totals.decisions += report.decisions
        totals.events.update(report.events)
        _sleep(pace.seconds_per_tick - (time.monotonic() - started), stop)

    _status(conn, "paused")
    print("stopped on request; the world is at the end of its last complete tick")
    return 0


def _live_spend(policy: object) -> float:
    return policy.recorder.stats.live_cost_usd if isinstance(policy, JevPolicy) else 0.0


def _report(
    conn: Connection[DictRow],
    policy: object,
    args: argparse.Namespace,
    totals: Totals,
) -> None:
    if isinstance(policy, JevPolicy):
        stats = policy.recorder.stats
        policy.close()
        if args.calls == "record":
            finalize_cassette(CASSETTE)
        if args.stats is not None:
            args.stats.write_text(
                json.dumps(
                    {
                        "mode": args.calls,
                        "asked": stats.lookups,
                        "from_cache": stats.hits,
                        "live_calls": stats.live_calls,
                        "live_usd": round(stats.live_cost_usd, 8),
                    }
                )
            )
        print(
            f"\nmodel calls: {stats.lookups} asked, {stats.hits} from cache, "
            f"{stats.live_calls} live, ${stats.live_cost_usd:.6f} spent this run "
            f"({args.calls})"
        )
    print(f"\nran {totals.ticks} ticks, {totals.decisions} decisions ({args.policy})")
    if args.verbose:
        print("\nevents:")
        for kind, count in sorted(totals.events.items()):
            print(f"  {count:6d}  {kind}")
        if conn.closed:
            return
        for row in conn.execute(
            "SELECT source, count(*) AS n FROM decisions "
            "GROUP BY source ORDER BY source"
        ).fetchall():
            print(f"  decided by {row['source']}: {int(row['n'])}")
        balance = conn.execute(
            "SELECT COALESCE(sum(amount_cents),0) AS total FROM ledger_entries"
        ).fetchone()
        assert balance is not None
        print(f"\nledger balances: {balance['total'] == 0} (sum={balance['total']})")


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    import os

    policy, calls = policy_from_env()
    parser = argparse.ArgumentParser(prog="python -m jeve.sim", description=__doc__)
    parser.add_argument("--seed", type=int, default=ROOT_SEED)
    parser.add_argument(
        "--seed-world", action="store_true", help="reset the world first"
    )
    parser.add_argument("--policy", choices=("rules", "jev"), default=policy)
    parser.add_argument("--calls", choices=("record", "replay"), default=calls)
    horizon = parser.add_mutually_exclusive_group()
    horizon.add_argument("--until", type=int, help="stop at this sim time, in seconds")
    horizon.add_argument(
        "--until-day", type=float, help="stop at the start of this day"
    )
    parser.add_argument("--idle", action="store_true", help="stay up at the horizon")
    parser.add_argument(
        "--day-minutes",
        type=float,
        default=float(os.environ.get("JEVE_SIM_DAY_MINUTES") or DEFAULT_DAY_MINUTES),
        help="real minutes per sim-day; 0 runs flat out",
    )
    parser.add_argument(
        "--daily-budget",
        type=float,
        default=float(
            os.environ.get("JEVE_DAILY_BUDGET_USD") or DEFAULT_DAILY_BUDGET_USD
        ),
    )
    parser.add_argument("--stats", type=Path, help="write call statistics here")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.until_day is not None:
        args.until = int(args.until_day * DAY)
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse(argv))
    except db.WriterBusyError as error:
        print(f"refusing to start: {error}", file=sys.stderr)
        return 3
