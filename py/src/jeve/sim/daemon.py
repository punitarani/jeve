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
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, obs
from jeve.core.clock import DAY, TICK, SimTime
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.recorder import ReplayMissError, finalize_cassette, load_cassette
from jeve.errors import (
    BudgetExceededError,
    ModelVersionDriftError,
    ProviderBudgetError,
    ResponseShapeError,
    TransportError,
)
from jeve.obs import meters
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

log = obs.logger("jeve.sim")
"""OBS-0001: the same line to stdout as before, plus a record to Axiom.

Built at import time, which is before `start()` runs — so it resolves the live
stack per call rather than caching an emitter that does not exist yet."""

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


def _status(conn: Connection[DictRow], status: str, error: str | None = None) -> None:
    """Say what the process is doing, and why if it is not simply running."""

    conn.execute(
        "UPDATE sim_meta SET status = %s, last_error = %s, "
        "heartbeat_at = now(), updated_at = now()",
        (status, error),
    )
    conn.commit()
    meters.STATUS.add(1, {"jeve.status": status})


def _heartbeat(conn: Connection[DictRow], lag_s: float | None = None) -> None:
    """Wall-clock proof of life. Never read by the simulation."""

    if lag_s is None:
        conn.execute("UPDATE sim_meta SET heartbeat_at = now()")
    else:
        conn.execute("UPDATE sim_meta SET heartbeat_at = now(), lag_s = %s", (lag_s,))
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
            log.info(
                f"seeded {summary.orgs} orgs, {summary.persons} persons "
                f"({summary.staff} staff + {summary.counterparties} counterparties)",
                {
                    "jeve.orgs": summary.orgs,
                    "jeve.persons": summary.persons,
                    "jeve.staff": summary.staff,
                    "jeve.counterparties": summary.counterparties,
                },
            )
        if args.policy == "jev" and args.cassette is not None:
            # In both modes: a recording run must not pay again for what it has.
            loaded = load_cassette(conn, args.cassette)
            conn.commit()
            log.info(
                f"cassette: {loaded} call(s) preloaded from {args.cassette.name}",
                {"jeve.calls": loaded, "jeve.cassette": args.cassette.name},
            )

        policy = build_policy(
            args.policy, args.calls, root_seed=args.seed, cassette=args.cassette
        )
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
    failures = 0
    waiting_since = 0.0
    budget_since = 0.0
    _status(conn, "running")

    while not stop.requested():
        row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
        assert row is not None
        now = SimTime(int(row["sim_time"]))

        if args.until is not None and now.seconds >= args.until:
            _status(conn, "paused")
            log.info(
                f"reached the horizon at {now}",
                {"jeve.sim_time": now.seconds, "jeve.sim_label": now.label()},
            )
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
            _sleep(skipped_ticks * pace.seconds_per_tick / NIGHT_SPEEDUP, stop, conn)
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
                pause_s = pace.window_s - elapsed
                log.info(
                    f"daily model budget of ${pace.daily_budget_usd:.2f} spent; "
                    f"pausing {pause_s:.0f}s until the window rolls",
                    {
                        "jeve.budget_usd": pace.daily_budget_usd,
                        "jeve.pause_s": pause_s,
                    },
                )
                meters.WAIT_DURATION.record(pause_s, {"jeve.reason": "daily_budget"})
                with obs.span("sim.wait", {"jeve.wait_reason": "daily_budget"}):
                    _sleep(pause_s, stop, conn)
                _status(conn, "running")
                continue

        started = time.monotonic()
        try:
            # CORE-0003: sim time is an attribute here, never a timestamp. The
            # SDK stamps the span off the wall clock; `jeve.sim_time` is the
            # integer the world runs on, and the two must not be confused.
            with obs.span(
                "sim.tick",
                {
                    "jeve.sim_time": now.seconds,
                    "jeve.sim_label": now.label(),
                    "jeve.sim_day": now.day,
                    "jeve.policy": args.policy,
                },
            ) as tick:
                report = engine.tick()
                tick.set(
                    {
                        "jeve.decisions": report.decisions,
                        "jeve.events": len(report.events),
                    }
                )
        except BudgetExceededError as error:
            _status(conn, "halted", _describe(error))
            meters.TICKS.add(1, {"jeve.outcome": "halt"})
            log.error(
                f"HALTED: {error}",
                {"jeve.error_type": type(error).__name__, "jeve.exit_code": 4},
            )
            return 4
        except ReplayMissError as error:
            _status(conn, "halted", _describe(error))
            meters.TICKS.add(1, {"jeve.outcome": "halt"})
            log.error(
                f"HALTED: {error}",
                {"jeve.error_type": type(error).__name__, "jeve.exit_code": 5},
            )
            return 5
        except ModelVersionDriftError as error:
            # DECIDE-0004: not weather. Waiting cannot fix it and carrying on
            # would mix two models' answers in one world.
            _status(conn, "halted", _describe(error))
            meters.TICKS.add(1, {"jeve.outcome": "halt"})
            log.error(
                f"HALTED: {error}",
                {"jeve.error_type": type(error).__name__, "jeve.exit_code": 7},
            )
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
                meters.TICKS.add(1, {"jeve.outcome": "halt"})
                log.error(
                    f"HALTED: upstream budget has been out for {waited:.0f}s: {error}",
                    {
                        "jeve.error_type": type(error).__name__,
                        "jeve.waited_s": waited,
                        "jeve.exit_code": 6,
                    },
                )
                return 6
            _status(conn, "waiting_on_budget", _describe(error))
            meters.TICKS.add(1, {"jeve.outcome": "provider_budget"})
            meters.WAIT_DURATION.record(delay, {"jeve.reason": "provider_budget"})
            log.warn(
                f"waiting on the upstream budget: {_describe(error)}; "
                f"trying this tick again in {delay:.0f}s",
                {
                    "jeve.error_type": type(error).__name__,
                    "jeve.delay_s": delay,
                    "jeve.waited_s": waited,
                },
            )
            with obs.span("sim.wait", {"jeve.wait_reason": "provider_budget"}):
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
                meters.TICKS.add(1, {"jeve.outcome": "halt"})
                log.error(
                    f"HALTED: the model has not answered for {waited:.0f}s: {error}",
                    {
                        "jeve.error_type": type(error).__name__,
                        "jeve.waited_s": waited,
                        "jeve.failures": failures,
                        "jeve.exit_code": 6,
                    },
                )
                return 6
            _status(conn, "waiting_on_model", _describe(error))
            meters.TICKS.add(1, {"jeve.outcome": "weather"})
            meters.WAIT_DURATION.record(delay, {"jeve.reason": "model"})
            log.warn(
                f"waiting on the model (failure {failures}): {_describe(error)}; "
                f"trying this tick again in {delay:.0f}s",
                {
                    "jeve.error_type": type(error).__name__,
                    "jeve.failures": failures,
                    "jeve.delay_s": delay,
                    "jeve.waited_s": waited,
                },
            )
            with obs.span(
                "sim.wait",
                {"jeve.wait_reason": "model", "jeve.failures": failures},
            ):
                _sleep(delay, stop, conn)
            continue
        if failures or budget_since:
            if failures:
                log.info(
                    f"the model is back after {failures} failed attempt(s)",
                    {"jeve.failures": failures},
                )
            failures = 0
            budget_since = 0.0
            _status(conn, "running")
        totals.ticks += 1
        totals.decisions += report.decisions
        totals.events.update(report.events)
        spent = time.monotonic() - started
        lag = max(0.0, spent - pace.seconds_per_tick)
        meters.TICKS.add(1, {"jeve.outcome": "ok"})
        meters.TICK_DURATION.record(spent, {"jeve.policy": args.policy})
        # The advance is always one quantum of sim time, so the gap between that
        # and the wall time it took is the whole question: is the world keeping up.
        meters.TICK_LAG.record(lag, {"jeve.policy": args.policy})
        meters.DECISIONS.add(report.decisions, {"jeve.policy": args.policy})
        for kind in report.events:
            meters.EVENTS.add(1, {"jeve.kind": kind})
        _heartbeat(conn, lag_s=lag)
        _sleep(pace.seconds_per_tick - spent, stop, conn)

    _status(conn, "paused")
    log.info(
        "stopped on request; the world is at the end of its last complete tick",
        {"jeve.ticks": totals.ticks, "jeve.decisions": totals.decisions},
    )
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
    # OBS-0001: the run summary stays `print`. It is a formatted terminal
    # block — a leading blank line, an indented table — not a sequence of
    # events, and routing it through the logger would put a few hundred
    # near-empty records into Axiom per run for numbers the metrics already
    # carry. `test_resume.py` greps its exact bytes, too.
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
    # OBS-0001. The `finally` covers every exit: the horizon, the four
    # deliberate halts (4-7), a busy writer (3), and SIGTERM — which needs
    # nothing special here, because the stop flag makes `_loop` return
    # normally, so the flush lands after the last tick has committed.
    obs.start("jeve-sim")
    try:
        return run(parse(argv))
    except db.WriterBusyError as error:
        log.error(
            f"refusing to start: {error}",
            {"jeve.error_type": type(error).__name__, "jeve.exit_code": 3},
        )
        return 3
    finally:
        obs.shutdown()
