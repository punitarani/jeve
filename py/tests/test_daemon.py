"""The simulation process: one writer, a horizon, a governor (SIM-0001)."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, TICK, at
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

    monkeypatch.setattr(engine, "_cafe", explode)
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
