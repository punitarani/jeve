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
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, tracing
from jeve.core.clock import DAY, TICK, SimTime
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.policy import Policy
from jeve.decide.recorder import ReplayMissError, finalize_cassette, load_cassette
from jeve.errors import (
    BudgetExceededError,
    ModelVersionDriftError,
    ProviderBudgetError,
    ResponseShapeError,
    TransportError,
)
from jeve.sim.runner import CASSETTE, Totals, build_policy, policy_from_env
from jeve.world.engine import Engine, skip_to_next_open
from jeve.world.seed_world import ROOT_SEED, seed

DEFAULT_DAY_MINUTES = 24.0
"""One sim-day per 24 real minutes: a fifteen-minute tick every fifteen seconds."""

DEFAULT_NIGHT_SPEEDUP = 10.0
"""Closed hours pass this much faster than open ones. Nothing happens at night,
and a town that sits empty for fourteen real minutes in every twenty-four is a
poor thing to watch. The tick rate while anything is open is unaffected.

A constant for two sessions, which meant the only way to shorten the hole a
night leaves in the usage graph was to speed the whole world up — and that
costs money, because the open hours are where the spend is. `JEVE_NIGHT_SPEEDUP`
buys the same silence back for nothing (SIM-0004)."""

DEFAULT_DAILY_BUDGET_USD = 2.00

MODEL_WEATHER: tuple[type[BaseException], ...] = (
    TransportError,
    ResponseShapeError,
    TimeoutError,
)
"""SIM-0002: what the model path raises when the model, or the road to it, is
having a bad minute — after the gateway's own retries have run out. A tick is
one transaction, so one that raised has changed nothing and can simply be run
again. One HTTP 520 used to end the process here, with the page still saying
`running`. Budget exhaustion and a replay miss are not in this list: waiting
cannot fix either."""

DATABASE_WEATHER: tuple[type[BaseException], ...] = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
)
"""SIM-0004: what Postgres going away looks like from in here — a failover, a
restart, a pooler dropping the session, a laptop's network coming back on a
different address.

It is weather for the same reason a 520 is (SIM-0002): the tick is one
transaction, so one that lost its connection changed nothing, and the world is
exactly where the last commit left it. The difference is that the status cannot
be written — there is nowhere to write it — so this loop is the only record
until the database answers again. Ending the process instead was survivable
only where something restarts it; `make sim` on a laptop is not that."""

BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 120.0
HEARTBEAT_EVERY_S = 5.0
DEFAULT_BUDGET_WAIT_S = 900.0
"""SIM-0003: how long between retries when OpenRouter says the account is out
of credit (402). Minutes, not seconds — the cap resets on a billing window,
and a faster poll is a heartbeat pretending to be progress."""


@dataclass(slots=True)
class Pace:
    """How fast sim time is allowed to pass, and how much it may spend."""

    day_minutes: float
    daily_budget_usd: float
    night_speedup: float = DEFAULT_NIGHT_SPEEDUP

    def __post_init__(self) -> None:
        if self.night_speedup <= 0.0:
            raise ValueError(
                f"night speedup must be positive, not {self.night_speedup} "
                "(JEVE_NIGHT_SPEEDUP). Dead time is skipped fast, never backwards "
                "and never for ever."
            )

    @property
    def seconds_per_tick(self) -> float:
        return self.day_minutes * 60.0 * TICK / DAY

    @property
    def window_s(self) -> float:
        """Real seconds that correspond to one sim-day: the budget's period."""

        return self.day_minutes * 60.0

    @property
    def speed(self) -> float:
        """Sim-seconds per real second while anything is open.

        What `sim_meta.speed` has always claimed to hold and never did: the
        column defaulted to 1.0 and nothing ever wrote it, so the API served
        `1.0` to a page watching a world running sixty times faster than that.
        """

        if self.seconds_per_tick <= 0.0:
            return 0.0  # `--day-minutes 0`: flat out, and no honest number.
        return TICK / self.seconds_per_tick

    @property
    def night_speed(self) -> float:
        """Sim-seconds per real second while everything is shut."""

        return self.speed * self.night_speedup


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


def _status(
    conn: Connection[DictRow],
    status: str,
    error: str | None = None,
    *,
    speed: float = 0.0,
) -> None:
    """Say what the process is doing, and why if it is not simply running.

    `speed` is how fast sim time is moving right now, which for every status
    but `running` is nought: a paused world is not a slow one.
    """

    conn.execute(
        "UPDATE sim_meta SET status = %s, last_error = %s, speed = %s, "
        "heartbeat_at = now(), updated_at = now()",
        (status, error, speed),
    )
    conn.commit()


def _heartbeat(
    conn: Connection[DictRow],
    lag_s: float | None = None,
    *,
    speed: float | None = None,
) -> None:
    """Wall-clock proof of life. Never read by the simulation."""

    sets = ["heartbeat_at = now()"]
    values: list[float] = []
    if lag_s is not None:
        sets.append("lag_s = %s")
        values.append(lag_s)
    if speed is not None:
        sets.append("speed = %s")
        values.append(speed)
    conn.execute(f"UPDATE sim_meta SET {', '.join(sets)}", tuple(values))
    conn.commit()


def _sleep(
    seconds: float, stop: _Stop, conn: Connection[DictRow] | None = None
) -> None:
    """Sleep, but stay visibly alive.

    The beat comes from in here as well as from the tick, because most of a
    daemon's life is this loop: without it every night, every budget pause and
    every wait for the model would read as a dead process.
    """

    deadline = time.monotonic() + seconds
    next_beat = time.monotonic() + HEARTBEAT_EVERY_S
    while not stop.requested() and (left := deadline - time.monotonic()) > 0:
        time.sleep(min(0.25, left))
        if conn is not None and time.monotonic() >= next_beat:
            _heartbeat(conn)
            next_beat = time.monotonic() + HEARTBEAT_EVERY_S


def _backoff(failures: int) -> float:
    """Doubling from the base to the cap, jittered by up to a quarter either way.

    The jitter comes off the wall clock, which this module is allowed to read
    and the simulation is not; none of it reaches sim state.
    """

    delay = float(min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (failures - 1)))
    return delay * (0.75 + 0.5 * (time.monotonic() % 1.0))


def _describe(error: BaseException) -> str:
    first_line = (str(error).splitlines() or [""])[0]
    return f"{type(error).__name__}: {first_line}"[:500]


def _prepare(
    conn: Connection[DictRow], args: argparse.Namespace, *, first: bool
) -> None:
    """Make a fresh connection fit to run the world from."""

    db.migrate(conn)
    # Ten seconds: long enough to outlive a killed predecessor's backend,
    # short enough that a genuine second writer is told promptly.
    db.take_writer_lock(conn, wait_s=10.0)

    seeded = conn.execute("SELECT 1 FROM sim_meta").fetchone() is not None
    # `--seed-world` only on the way in. Honouring it again after an outage
    # would answer a dropped connection by deleting the world it interrupted.
    if (args.seed_world and first) or not seeded:
        summary = seed(conn, root_seed=args.seed)
        print(
            f"seeded {summary.orgs} orgs, {summary.persons} persons "
            f"({summary.staff} staff + {summary.counterparties} counterparties)"
        )
    if first:
        _stamp_engine(conn)
    if first and args.policy == "jev" and args.cassette is not None:
        # In both modes: a recording run must not pay again for what it has.
        loaded = load_cassette(conn, args.cassette)
        conn.commit()
        print(f"cassette: {loaded} call(s) preloaded from {args.cassette.name}")


def engine_sha() -> str:
    """The commit this engine was built from, or `unknown`.

    `JEVE_ENGINE_SHA` in an image (the build passes the commit in, because an
    image holds no `.git`), else `git rev-parse` in a checkout. The column
    existed from the first migration and nothing ever wrote it, so a
    production world that had run 232 sim-days across several deploys could not
    say which code had produced which of them (field report, defect 6).
    """

    explicit = os.environ.get("JEVE_ENGINE_SHA", "").strip()
    if explicit and explicit != "unknown":
        return explicit[:40]
    try:
        found = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return "unknown"
    sha = found.stdout.strip()
    return sha if found.returncode == 0 and len(sha) >= 7 else "unknown"


def _stamp_engine(conn: Connection[DictRow]) -> None:
    """Write down which engine is running this world, and when it changed.

    A change between two known builds is an event, at the sim time it happened:
    the report can then split a long run at its deploys, the way the research
    notes ask of any long-running simulation (00 §6.5). A world stamped for the
    first time says nothing: there is no "before" to have changed from.
    """

    row = conn.execute("SELECT engine_sha, sim_time, tick_seq FROM sim_meta").fetchone()
    sha = engine_sha()
    if row is None or sha == "unknown" or str(row["engine_sha"]) == sha:
        return
    previous = str(row["engine_sha"])
    if previous != "unknown":
        conn.execute(
            "INSERT INTO events (sim_time, tick_seq, kind, payload) "
            "VALUES (%s, %s, 'engine.changed', %s)",
            (
                int(row["sim_time"]),
                int(row["tick_seq"]),
                json.dumps({"from": previous, "to": sha}),
            ),
        )
    conn.execute("UPDATE sim_meta SET engine_sha = %s", (sha,))
    conn.commit()


def run(args: argparse.Namespace) -> int:
    stop = _Stop()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    pace = Pace(args.day_minutes, args.daily_budget, args.night_speedup)
    # Built before the first connection and kept across every reconnection: the
    # recorder's cache, its statistics and the governor's window all belong to
    # the run, not to whichever database session happens to be carrying it.
    policy = build_policy(
        args.policy, args.calls, root_seed=args.seed, cassette=args.cassette
    )
    totals = Totals()
    summarise = True
    try:
        return _supervise(policy, pace, args, stop, totals)
    except db.WriterBusyError:
        # `main` turns this into "refusing to start". It is the one exit with
        # no summary: nothing of this run ran, so a report would describe a
        # world this process never touched — and finalise a cassette it never
        # opened, rewriting a file that is somebody else's.
        summarise = False
        raise
    finally:
        try:
            if summarise:
                _report(policy, args, totals)
            elif isinstance(policy, JevPolicy):
                policy.close()
        finally:
            # Every tick is a trace (LLM-0009), including a rules run's and one
            # that never opened a gateway, whose own flush would not happen —
            # and the last of them explain a run whose summary failed.
            tracing.flush()


def _supervise(
    policy: Policy,
    pace: Pace,
    args: argparse.Namespace,
    stop: _Stop,
    totals: Totals,
) -> int:
    """Hold a connection to the world, and get another when one is lost."""

    first = True
    outages = 0
    waiting_since = 0.0
    while not stop.requested():
        try:
            with db.connect() as conn:
                _prepare(conn, args, first=first)
                first = False
                if outages:
                    print(f"the database is back after {outages} attempt(s)")
                    outages = 0
                engine = Engine(conn, policy, root_seed=args.seed)
                return _loop(conn, engine, policy, pace, args, stop, totals)
        except DATABASE_WEATHER as error:
            outages += 1
            if outages == 1:
                waiting_since = time.monotonic()
            delay = _backoff(outages)
            waited = time.monotonic() - waiting_since
            if args.max_wait is not None and waited + delay > args.max_wait:
                print(
                    f"HALTED: the database has not answered for {waited:.0f}s: {error}",
                    file=sys.stderr,
                )
                return 6
            # No connection, so nothing to beat into and no status to set: this
            # line is the only sign of life until Postgres answers.
            print(
                f"waiting on the database (outage {outages}): {_describe(error)}; "
                f"reconnecting in {delay:.0f}s",
                file=sys.stderr,
            )
            _sleep(delay, stop)
    return 0


def _loop(
    conn: Connection[DictRow],
    engine: Engine,
    policy: Policy,
    pace: Pace,
    args: argparse.Namespace,
    stop: _Stop,
    totals: Totals,
) -> int:
    window_started = time.monotonic()
    window_spent_from = _live_spend(policy)
    failures = 0
    waiting_since = 0.0
    budget_since = 0.0
    _status(conn, "running", speed=pace.speed)

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
                _sleep(1.0, stop, conn)
            return 0

        if not now.anything_open:
            before = now.seconds
            after = skip_to_next_open(conn)
            if args.until is not None and after > args.until:
                conn.execute("UPDATE sim_meta SET sim_time = %s", (args.until,))
                conn.commit()
                after = args.until
            skipped_ticks = (after - before) / TICK
            _heartbeat(conn, speed=pace.night_speed)
            _sleep(
                skipped_ticks * pace.seconds_per_tick / pace.night_speedup, stop, conn
            )
            _heartbeat(conn, speed=pace.speed)
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
                _sleep(pace.window_s - elapsed, stop, conn)
                _status(conn, "running", speed=pace.speed)
                continue

        started = time.monotonic()
        try:
            report = engine.tick()
        except BudgetExceededError as error:
            _status(conn, "halted", _describe(error))
            print(f"HALTED: {error}", file=sys.stderr)
            return 4
        except ReplayMissError as error:
            _status(conn, "halted", _describe(error))
            print(f"HALTED: {error}", file=sys.stderr)
            return 5
        except ModelVersionDriftError as error:
            # DECIDE-0004: not weather. Waiting cannot fix it and carrying on
            # would mix two models' answers in one world.
            _status(conn, "halted", _describe(error))
            print(f"HALTED: {error}", file=sys.stderr)
            return 7
        except ProviderBudgetError as error:
            # SIM-0003: the upstream cap is spent. Not weather — a two-minute
            # backoff refills nothing — and not a halt, because the window
            # rolls over and the world resumes by itself. Slow retry, still
            # beating, same tick.
            conn.rollback()
            if budget_since == 0.0:
                budget_since = time.monotonic()
            waited = time.monotonic() - budget_since
            delay = args.budget_wait
            if args.max_wait is not None and waited + delay > args.max_wait:
                _status(conn, "halted", _describe(error))
                print(
                    f"HALTED: upstream budget has been out for {waited:.0f}s: {error}",
                    file=sys.stderr,
                )
                return 6
            _status(conn, "waiting_on_budget", _describe(error))
            print(
                f"waiting on the upstream budget: {_describe(error)}; "
                f"trying this tick again in {delay:.0f}s",
                file=sys.stderr,
            )
            _sleep(delay, stop, conn)
            continue
        except MODEL_WEATHER as error:
            # SIM-0002 / CORE-0004: a dead model is a paused world, not a dead
            # one and not a world that guessed. The tick rolled back whole, and
            # the engine has put the sequences back, so the retry is the same
            # tick; whatever the model did answer is already in the call cache.
            conn.rollback()
            failures += 1
            if failures == 1:
                waiting_since = time.monotonic()
            delay = _backoff(failures)
            waited = time.monotonic() - waiting_since
            if args.max_wait is not None and waited + delay > args.max_wait:
                _status(conn, "halted", _describe(error))
                print(
                    f"HALTED: the model has not answered for {waited:.0f}s: {error}",
                    file=sys.stderr,
                )
                return 6
            _status(conn, "waiting_on_model", _describe(error))
            print(
                f"waiting on the model (failure {failures}): {_describe(error)}; "
                f"trying this tick again in {delay:.0f}s",
                file=sys.stderr,
            )
            _sleep(delay, stop, conn)
            continue
        if failures or budget_since:
            if failures:
                print(f"the model is back after {failures} failed attempt(s)")
            failures = 0
            budget_since = 0.0
            _status(conn, "running", speed=pace.speed)
        totals.ticks += 1
        totals.decisions += report.decisions
        totals.events.update(report.events)
        spent = time.monotonic() - started
        _heartbeat(
            conn, lag_s=max(0.0, spent - pace.seconds_per_tick), speed=pace.speed
        )
        _sleep(pace.seconds_per_tick - spent, stop, conn)

    _status(conn, "paused")
    print("stopped on request; the world is at the end of its last complete tick")
    return 0


def _live_spend(policy: Policy) -> float:
    return policy.recorder.stats.live_cost_usd if isinstance(policy, JevPolicy) else 0.0


def _report(policy: Policy, args: argparse.Namespace, totals: Totals) -> None:
    """The run summary, printed once however many connections it took.

    It opens its own connection for the parts that need one, because the run's
    may be exactly what went wrong (SIM-0004) — and a summary that disappears
    when the database does is a summary you cannot trust to be there.
    """

    if isinstance(policy, JevPolicy):
        stats = policy.recorder.stats
        policy.close()
        if args.calls == "record" and args.cassette is not None:
            finalize_cassette(args.cassette)
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
    if not args.verbose:
        return
    print("\nevents:")
    for kind, count in sorted(totals.events.items()):
        print(f"  {count:6d}  {kind}")
    try:
        with db.connect() as conn:
            for row in conn.execute(
                "SELECT source, count(*) AS n FROM decisions "
                "GROUP BY source ORDER BY source"
            ).fetchall():
                print(f"  decided by {row['source']}: {int(row['n'])}")
            balance = conn.execute(
                "SELECT COALESCE(sum(amount_cents),0) AS total FROM ledger_entries"
            ).fetchone()
            assert balance is not None
            print(
                f"\nledger balances: {balance['total'] == 0} (sum={balance['total']})"
            )
    except DATABASE_WEATHER as error:
        print(f"\nno database to summarise from: {_describe(error)}", file=sys.stderr)


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
        "--night-speedup",
        type=float,
        default=float(os.environ.get("JEVE_NIGHT_SPEEDUP") or DEFAULT_NIGHT_SPEEDUP),
        help="how much faster than the open hours dead time passes; the higher "
        "it is, the smaller the hole a night leaves (JEVE_NIGHT_SPEEDUP)",
    )
    parser.add_argument(
        "--daily-budget",
        type=float,
        default=float(
            os.environ.get("JEVE_DAILY_BUDGET_USD") or DEFAULT_DAILY_BUDGET_USD
        ),
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=None,
        help="give up (exit 6) after this many seconds waiting on the model or "
        "the upstream budget; the default is to wait for ever, which is what "
        "a daemon should do",
    )
    parser.add_argument(
        "--budget-wait",
        type=float,
        default=float(os.environ.get("JEVE_BUDGET_WAIT_S") or DEFAULT_BUDGET_WAIT_S),
        help="seconds between retries while the upstream budget (402) is out",
    )

    def _cassette(value: str | None) -> Path | None:
        # `off`/`none` means no write-through: production's cache is the
        # model_calls table, and a cassette would grow without bound on disk.
        if value is not None and value.lower() in ("off", "none"):
            return None
        return Path(value) if value is not None else None

    parser.add_argument(
        "--cassette",
        type=_cassette,
        default=_cassette(os.environ.get("JEVE_CASSETTE") or str(CASSETTE)),
        help="recorded calls to preload and, when recording, to append to; "
        "'off' disables the file entirely (JEVE_CASSETTE). The default is the "
        "golden cassette `make e2e` replays; a soak keeps its own, so that a "
        "long live run never rewrites the file a replay depends on",
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
