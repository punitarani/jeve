"""The simulation process: one writer, a horizon, a governor (SIM-0001)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, DISTRICT_CLOSE, DISTRICT_OPEN, TICK, at
from jeve.decide.policy import RulesPolicy
from jeve.sim import daemon
from jeve.sim.daemon import Pace
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.test_world import event_log_hash

pytestmark = pytest.mark.timeout(300)

FLAT_OUT = ["--policy", "rules", "--day-minutes", "0"]


@pytest.fixture
def conn() -> Iterator[Connection[DictRow]]:
    try:
        # Autocommit: this connection only *watches* a world another process
        # writes. A plain SELECT would otherwise leave a transaction open, and
        # that holds a lock the daemon's TRUNCATE then waits on for ever.
        with db.connect(autocommit=True) as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def sim_time(conn: Connection[DictRow]) -> int:
    conn.commit()
    row = conn.execute("SELECT sim_time, status FROM sim_meta").fetchone()
    assert row is not None
    return int(row["sim_time"])


def test_the_default_pace_is_a_tick_every_fifteen_seconds() -> None:
    pace = Pace(day_minutes=24.0, daily_budget_usd=2.0)
    assert pace.seconds_per_tick == pytest.approx(15.0)
    assert pace.window_s == 24 * 60
    assert Pace(0.0, 2.0).seconds_per_tick == 0.0


def test_a_second_writer_is_refused(conn: Connection[DictRow]) -> None:
    db.take_writer_lock(conn)
    db.take_writer_lock(conn)  # re-entrant: a daemon may seed its own world

    with db.connect() as intruder:
        with pytest.raises(db.WriterBusyError, match="another process is writing"):
            db.take_writer_lock(intruder)
        # Seeding truncates. Doing that under a running daemon destroys its
        # world mid-tick, so it has to fail here rather than succeed quietly.
        with pytest.raises(db.WriterBusyError):
            seed(intruder, root_seed=ROOT_SEED)


def test_the_lock_outlives_a_crash_only_briefly(conn: Connection[DictRow]) -> None:
    """After `kill -9` the dead backend holds the lock until Postgres notices.
    A supervisor restarting at once must wait that out, not give up."""

    holder = db.connect_autocommit()
    db.take_writer_lock(holder)
    with pytest.raises(db.WriterBusyError):
        db.take_writer_lock(conn, wait_s=0.3)

    holder.close()  # the predecessor's socket finally goes away
    db.take_writer_lock(conn, wait_s=5.0)


def test_the_daemon_stops_at_its_horizon_and_a_restart_carries_on(
    conn: Connection[DictRow],
) -> None:
    """`--until` makes a wall-clock process replayable, and restarting is just
    running it again: there is no resume procedure to get wrong."""

    assert daemon.main(["--seed-world", "--until-day", "2", *FLAT_OUT]) == 0
    assert sim_time(conn) == 2 * DAY
    straight_through = event_log_hash(conn)

    assert daemon.main(["--seed-world", "--until", str(at(0, 13)), *FLAT_OUT]) == 0
    assert sim_time(conn) == at(0, 13)
    assert daemon.main(["--until", str(at(1, 11)), *FLAT_OUT]) == 0
    assert daemon.main(["--until-day", "2", *FLAT_OUT]) == 0
    # Asking again for a horizon already reached does nothing.
    assert daemon.main(["--until-day", "2", *FLAT_OUT]) == 0

    assert sim_time(conn) == 2 * DAY
    assert event_log_hash(conn) == straight_through


def test_a_horizon_inside_the_night_is_not_overshot(conn: Connection[DictRow]) -> None:
    assert daemon.main(["--seed-world", "--until", str(at(0, 22)), *FLAT_OUT]) == 0
    assert sim_time(conn) == at(0, 22)


def test_burned_sequence_values_are_put_back(conn: Connection[DictRow]) -> None:
    """Sequences do not roll back. A tick that died after drawing ids leaves
    gaps, and the ids are content: they sit inside `causes`."""

    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    engine.tick()
    top = conn.execute("SELECT max(seq) AS seq FROM events").fetchone()
    assert top is not None

    for _ in range(7):  # what a rolled-back tick leaves behind
        conn.execute("SELECT nextval('events_seq_seq'), nextval('decisions_id_seq')")
    conn.commit()

    Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED).tick()
    after = conn.execute(
        "SELECT min(seq) AS seq FROM events WHERE seq > %s", (top["seq"],)
    ).fetchone()
    assert after is not None and int(after["seq"]) == int(top["seq"]) + 1
    gaps = conn.execute(
        "SELECT count(*) AS n FROM (SELECT seq - lag(seq) OVER (ORDER BY seq) AS step "
        "FROM events) s WHERE step > 1"
    ).fetchone()
    assert gaps is not None and int(gaps["n"]) == 0


def test_a_failed_tick_leaves_no_gap_either(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    engine.tick()

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the cafe caught fire")

    monkeypatch.setattr(engine, "_retail", explode)
    with pytest.raises(RuntimeError, match="caught fire"):
        engine.tick()
    monkeypatch.undo()
    engine.tick()

    gaps = conn.execute(
        "SELECT count(*) AS n FROM (SELECT seq - lag(seq) OVER (ORDER BY seq) AS step "
        "FROM events) s WHERE step > 1"
    ).fetchone()
    assert gaps is not None and int(gaps["n"]) == 0


def test_the_governor_stops_the_clock_when_the_days_budget_is_spent(
    conn: Connection[DictRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CORE-0002: budget governs clock speed. Spend is simulated here by
    billing each tick; what is under test is the governor, not the model."""

    spent = {"usd": 0.0}
    real_tick = Engine.tick

    def billed_tick(self: Engine) -> object:
        spent["usd"] += 0.60
        return real_tick(self)

    monkeypatch.setattr(Engine, "tick", billed_tick)
    monkeypatch.setattr(daemon, "_live_spend", lambda policy: spent["usd"])

    # A "day" of 1.5 real seconds with a $1 budget: two ticks fit, then a wait.
    horizon = at(0, 7) + 5 * TICK
    code = daemon.main(
        [
            "--seed-world",
            *("--until", str(horizon)),
            *("--policy", "rules"),
            *("--day-minutes", "0.025"),
            *("--daily-budget", "1.0"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("daily model budget of $1.00 spent") >= 1
    assert sim_time(conn) == horizon
    status = conn.execute("SELECT status FROM sim_meta").fetchone()
    assert status is not None and status["status"] == "paused"


def test_a_tick_is_committed_when_it_returns(conn: Connection[DictRow]) -> None:
    """Visible to another session the moment `tick()` returns — which is what
    lets an API serve a running world, and what a `kill -9` relies on. Asserted
    from a *second* connection: the writer always sees its own uncommitted rows,
    which is how this went unnoticed."""

    with db.connect() as writer:  # not autocommit: the case that was broken
        seed(writer, root_seed=ROOT_SEED)
        engine = Engine(writer, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
        writer.execute("SELECT sim_time FROM sim_meta").fetchone()  # opens a txn
        report = engine.tick()

        seen = conn.execute(
            "SELECT count(*) AS n, max(tick_seq) AS tick FROM events"
        ).fetchone()
        clock = conn.execute("SELECT tick_seq FROM sim_meta").fetchone()
        assert seen is not None and int(seen["n"]) == len(report.events) > 0
        assert int(seen["tick"]) == report.tick_seq
        assert clock is not None and int(clock["tick_seq"]) == report.tick_seq


# -- SIM-0002: the daemon outlives its model -----------------------------------


def _weather(monkeypatch: pytest.MonkeyPatch, fail_on: Mapping[int, Exception]) -> None:
    """Make the policy raise on chosen calls — from *inside* a tick, where a real
    model failure lands, so what is tested is the rollback and not a stub."""

    from jeve.decide.policy import DecisionContext

    real = RulesPolicy.decide
    calls = {"n": 0}

    def decide(self: RulesPolicy, ctx: DecisionContext) -> object:
        calls["n"] += 1
        if calls["n"] in fail_on:
            raise fail_on[calls["n"]]
        return real(self, ctx)

    monkeypatch.setattr(RulesPolicy, "decide", decide)
    monkeypatch.setattr(daemon, "BACKOFF_BASE_S", 0.01)


def test_a_failing_model_is_waited_for_and_leaves_no_trace(
    conn: Connection[DictRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One HTTP 520 used to end the process with the page still saying
    `running`. Now the tick is tried again, and the world that results is the
    world of a run in which nothing went wrong: no gap, no guess, no scar."""

    from jeve.errors import ResponseShapeError, TransportError

    horizon = ["--seed-world", "--until", str(at(0, 12)), *FLAT_OUT]
    assert daemon.main(horizon) == 0
    untroubled = event_log_hash(conn)

    seen: list[tuple[str, str | None]] = []
    real_status = daemon._status

    def status(
        c: Connection[DictRow],
        value: str,
        error: str | None = None,
        *,
        speed: float = 0.0,
    ) -> None:
        seen.append((value, error))
        real_status(c, value, error, speed=speed)

    monkeypatch.setattr(daemon, "_status", status)
    _weather(
        monkeypatch,
        {
            5: TransportError("/decisions returned 520: origin error"),
            6: TimeoutError(),  # the bridge's bare timeout, twice running
            40: ResponseShapeError("answers missing"),
        },
    )
    assert daemon.main(horizon) == 0

    assert event_log_hash(conn) == untroubled
    waits = [error for value, error in seen if value == "waiting_on_model"]
    assert len(waits) == 3
    assert waits[0] is not None and waits[0].startswith("TransportError: /decisions")
    assert waits[1] == "TimeoutError: "
    # Back to `running` after each spell, and the error is cleared with it.
    assert ("running", None) in seen[1:]
    row = conn.execute(
        "SELECT status, last_error, heartbeat_at FROM sim_meta"
    ).fetchone()
    assert row is not None
    assert (row["status"], row["last_error"]) == ("paused", None)
    assert row["heartbeat_at"] is not None
    assert "the model is back" in capsys.readouterr().out


def test_waiting_can_be_given_a_limit(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon waits for ever; a gate run in the small hours must not."""

    from jeve.errors import TransportError

    always = {n: TransportError("/decisions returned 503") for n in range(1, 500)}
    _weather(monkeypatch, always)
    code = daemon.main(
        ["--seed-world", "--until", str(at(0, 12)), "--max-wait", "0.2", *FLAT_OUT]
    )

    assert code == 6
    row = conn.execute("SELECT status, last_error FROM sim_meta").fetchone()
    assert row is not None and row["status"] == "halted"
    assert str(row["last_error"]).startswith("TransportError")


def test_a_spent_upstream_budget_waits_and_says_so(
    conn: Connection[DictRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SIM-0003: a 402 is not weather — it waits on a minutes clock, still
    beating, and the same tick is retried when credit returns. A run with
    `--max-wait` gives up deliberately, not on an exception."""

    from jeve.errors import ProviderBudgetError

    assert daemon.main(["--seed-world", "--until", str(at(0, 10)), *FLAT_OUT]) == 0

    seen: list[tuple[str, str | None]] = []
    real_status = daemon._status

    def status(
        c: Connection[DictRow],
        value: str,
        error: str | None = None,
        *,
        speed: float = 0.0,
    ) -> None:
        seen.append((value, error))
        real_status(c, value, error, speed=speed)

    monkeypatch.setattr(daemon, "_status", status)
    _weather(monkeypatch, {3: ProviderBudgetError("/decisions returned 402")})
    code = daemon.main(["--until", str(at(0, 12)), "--budget-wait", "0.01", *FLAT_OUT])

    assert code == 0
    waits = [error for value, error in seen if value == "waiting_on_budget"]
    assert len(waits) == 1
    assert waits[0] is not None and waits[0].startswith("ProviderBudgetError")
    assert ("running", None) in seen
    assert sim_time(conn) == at(0, 12)
    assert "waiting on the upstream budget" in capsys.readouterr().err


def test_a_budget_wait_can_also_be_given_a_limit(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--max-wait` covers the upstream cap too: gate runs cannot hang."""

    from jeve.errors import ProviderBudgetError

    always = {n: ProviderBudgetError("402") for n in range(1, 500)}
    _weather(monkeypatch, always)
    code = daemon.main(
        [
            "--seed-world",
            "--until",
            str(at(0, 12)),
            "--max-wait",
            "0.05",
            "--budget-wait",
            "0.05",
            *FLAT_OUT,
        ]
    )

    assert code == 6
    row = conn.execute("SELECT status, last_error FROM sim_meta").fetchone()
    assert row is not None and row["status"] == "halted"
    assert str(row["last_error"]).startswith("ProviderBudgetError")


def test_a_sleeping_daemon_still_has_a_pulse(conn: Connection[DictRow]) -> None:
    """Most of a daemon's life is a sleep loop. If only ticks beat, every night
    and every budget pause reads as a dead process."""

    with db.connect() as writer:
        seed(writer, root_seed=ROOT_SEED)
        writer.commit()
        before = daemon.HEARTBEAT_EVERY_S
        daemon.HEARTBEAT_EVERY_S = 0.05
        try:
            daemon._sleep(0.4, daemon._Stop(), writer)
        finally:
            daemon.HEARTBEAT_EVERY_S = before
    row = conn.execute(
        "SELECT heartbeat_at IS NOT NULL AND now() - heartbeat_at < interval '5 s' "
        "AS alive FROM sim_meta"
    ).fetchone()
    assert row is not None and row["alive"]


# -- SIM-0004: the night is configurable, and the clock says how fast it runs --

NIGHT_TICKS = (at(1) + DISTRICT_OPEN - (at(0) + DISTRICT_CLOSE)) // TICK
"""Ticks between the last shop closing and the first one opening again."""


def test_a_night_is_skipped_at_whatever_speedup_it_is_given() -> None:
    """The hole a night leaves in the usage graph is `NIGHT_SPEEDUP` wide, and
    for two sessions the only way to narrow it was to speed the whole world up
    — which costs money, because the open hours are where the spend is."""

    slow = Pace(day_minutes=24.0, daily_budget_usd=2.0, night_speedup=10.0)
    fast = Pace(day_minutes=24.0, daily_budget_usd=2.0, night_speedup=60.0)

    assert slow.seconds_per_tick == fast.seconds_per_tick  # open hours unmoved
    assert fast.night_speed == 6 * slow.night_speed
    # A weeknight on the district's clock, the gym's close to the cafe's
    # open, is eleven sim-hours: 44 ticks of dead time.
    assert NIGHT_TICKS == 44

    def night_at(pace: Pace) -> float:
        return NIGHT_TICKS * pace.seconds_per_tick / pace.night_speedup

    assert night_at(slow) == pytest.approx(66.0)
    assert night_at(fast) == pytest.approx(11.0)


def test_a_night_that_never_ends_is_refused() -> None:
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="night speedup must be positive"):
            Pace(day_minutes=24.0, daily_budget_usd=2.0, night_speedup=bad)


def test_the_speedup_reaches_the_sleep_the_daemon_actually_takes(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag is only worth having if the night is the thing it shortens."""

    naps: list[float] = []

    def sleep(seconds: float, stop: daemon._Stop, c: object = None) -> None:
        naps.append(seconds)

    monkeypatch.setattr(daemon, "_sleep", sleep)
    # The district shuts at 20:00 on day 0 and opens at 07:00 on day 1; stop
    # just inside the morning so exactly one night is skipped.
    run = [
        "--seed-world",
        "--until",
        str(at(1, 7)),
        "--policy",
        "rules",
        "--day-minutes",
        "24",
        "--night-speedup",
        "60",
    ]
    assert daemon.main(run) == 0

    # 44 ticks of night at 15s each, sixty times faster than the open hours.
    expected = NIGHT_TICKS * Pace(24.0, 2.0).seconds_per_tick / 60.0
    assert any(nap == pytest.approx(expected) for nap in naps), naps
    # And at sixty it is shorter than a single tick's own pacing sleep: the
    # night has stopped being the biggest hole in the graph.
    assert max(naps) <= Pace(24.0, 2.0).seconds_per_tick
    assert sim_time(conn) == at(1, 7)


def test_the_clock_says_how_fast_it_is_running(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sim_meta.speed` defaulted to 1.0 and nothing ever wrote it, so the API
    served `1.0` to a page watching a world running sixty times faster."""

    monkeypatch.setattr(daemon, "_sleep", lambda *a, **k: None)
    assert (
        daemon.main(
            [
                "--seed-world",
                "--until",
                str(at(0, 10)),
                "--policy",
                "rules",
                "--day-minutes",
                "24",
            ]
        )
        == 0
    )
    row = conn.execute("SELECT status, speed FROM sim_meta").fetchone()
    assert row is not None
    # Paused at the horizon: a stopped world is not a slow one.
    assert row["status"] == "paused"
    assert float(row["speed"]) == 0.0


def test_a_dropped_connection_is_weather_and_the_world_carries_on(
    conn: Connection[DictRow],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SIM-0004. A failover, a restart, a pooler dropping the session: the tick
    is one transaction, so the world is where the last commit left it and the
    run that results is the run in which nothing went wrong."""

    horizon = ["--seed-world", "--until", str(at(0, 12)), *FLAT_OUT]
    assert daemon.main(horizon) == 0
    untroubled = event_log_hash(conn)

    backends: list[int] = []
    real_prepare = daemon._prepare

    def prepare(c: Connection[DictRow], args: object, *, first: bool) -> None:
        backends.append(c.info.backend_pid)
        real_prepare(c, args, first=first)  # type: ignore[arg-type]

    monkeypatch.setattr(daemon, "_prepare", prepare)
    monkeypatch.setattr(daemon, "BACKOFF_BASE_S", 0.01)

    real_decide = RulesPolicy.decide
    calls = {"n": 0}

    def decide(self: RulesPolicy, ctx: object) -> object:
        calls["n"] += 1
        # Pull the rug out from under a tick, the way a failover does: from
        # another session, so the daemon finds out the way it really would.
        if calls["n"] == 20 and len(backends) == 1:
            conn.execute("SELECT pg_terminate_backend(%s)", (backends[0],))
        return real_decide(self, ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(RulesPolicy, "decide", decide)
    assert daemon.main(horizon) == 0

    assert len(backends) == 2, "the daemon never got a second connection"
    assert "waiting on the database" in capsys.readouterr().err
    # The rolled-back tick re-ran, and `--seed-world` was not honoured twice.
    assert event_log_hash(conn) == untroubled


def test_a_refused_start_says_so_and_summarises_nothing(
    conn: Connection[DictRow], capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that never began has no world to report on — and no cassette of
    its own to finalise, which would rewrite a file that is somebody else's."""

    db.take_writer_lock(conn)
    try:
        assert daemon.main(["--until-day", "1", *FLAT_OUT]) == 3
    finally:
        conn.execute("SELECT pg_advisory_unlock_all()")
    out = capsys.readouterr()
    assert "refusing to start" in out.err
    assert "ran 0 ticks" not in out.out
