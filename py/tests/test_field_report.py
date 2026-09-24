"""The defects the golden-20260920 field report found, each pinned.

The report ran production for 232 sim-days and read the world back out of the
API. Seven things it found were plainly wrong rather than questions of
calibration; each test below fails on the code the report was run against.
Rules policy throughout: what is under test is the plumbing.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import (
    DAY,
    HOUR,
    MINUTE,
    WORK_END,
    WORK_START,
    SimTime,
    after_working_time,
    at,
)
from jeve.decide import gates
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.decide.questions import trait_fraction
from jeve.sim import advance, daemon
from jeve.world.engine import AUTOPAY_ABOVE, Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(600)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def two_weeks(conn: Connection[DictRow]) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
        advance(conn, engine, until=14 * DAY)

    build_once(conn, "field-report:14d", build)


# -- defect 1: a standing instruction is a gate --------------------------------


def _bill(days: int, *, autopay: bool) -> DecisionContext:
    return DecisionContext(
        person_id="halloran.client.1",
        role="client",
        sim_time=at(3, 10),
        kind="payment.timing",
        facts={"days_until_due": days, "can_afford": True, "autopay": autopay},
    )


def test_a_standing_instruction_pays_on_the_day_without_asking() -> None:
    assert gates.settle(_bill(0, autopay=True)) == {
        "pay": True,
        "reason": "standing_instruction",
    }
    assert gates.settle(_bill(-3, autopay=True)) == {
        "pay": True,
        "reason": "standing_instruction",
    }
    # Before the day, and for the slowest fifth, it is still a question.
    assert gates.settle(_bill(1, autopay=True)) is None
    assert gates.settle(_bill(0, autopay=False)) is None


def test_prompt_clients_are_never_asked_about_a_bill(
    conn: Connection[DictRow],
) -> None:
    two_weeks(conn)
    rows = conn.execute(
        "SELECT d.chosen, d.source, p.traits FROM decisions d "
        "JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'payment.timing' AND p.kind = 'counterparty'"
    ).fetchall()
    prompt = [
        r
        for r in rows
        if trait_fraction("promptness", dict(r["traits"]).get("promptness"))
        >= AUTOPAY_ABOVE
    ]
    assert prompt, "no prompt client had a bill fall due in two weeks"
    reasons = {str(r["chosen"]["reason"]) for r in prompt}
    assert reasons == {"standing_instruction"}
    assert {str(r["source"]) for r in prompt} == {"rules"}


# -- defect 2: a payment says who decided it -----------------------------------


def test_a_payment_row_and_its_event_agree_about_who_decided(
    conn: Connection[DictRow],
) -> None:
    two_weeks(conn)
    disagree = conn.execute(
        "SELECT count(*) AS n FROM payments p JOIN events e "
        "ON e.kind = 'payment.made' "
        "AND (e.payload->>'invoice_id')::bigint = p.invoice_id "
        "WHERE e.payload->>'decided_by' <> p.decided_by"
    ).fetchone()
    assert disagree is not None and int(disagree["n"]) == 0
    paid = conn.execute("SELECT count(*) AS n FROM payments").fetchone()
    assert paid is not None and int(paid["n"]) > 0


# -- defect 3: an episode's outcome counts its rounds --------------------------


def test_an_episode_outcome_carries_how_many_rounds_it_ran(
    conn: Connection[DictRow],
) -> None:
    two_weeks(conn)
    rows = conn.execute(
        "SELECT rounds, outcome FROM episodes WHERE closed_sim IS NOT NULL"
    ).fetchall()
    assert rows, "no episode closed in two weeks"
    for row in rows:
        counted = row["outcome"]["rounds"]
        assert isinstance(counted, int) and not isinstance(counted, bool)
        assert counted == int(row["rounds"])


# -- defect 4: nobody notices an outage after it is fixed ------------------------


def test_nobody_notices_an_outage_after_it_ended(conn: Connection[DictRow]) -> None:
    two_weeks(conn)
    late = conn.execute(
        "SELECT count(*) AS n FROM outage_notices n JOIN incidents i "
        "ON i.id = n.incident_id WHERE i.ended_sim IS NOT NULL "
        "AND n.notice_sim > i.ended_sim AND n.ticket_id IS NULL"
    ).fetchone()
    assert late is not None and int(late["n"]) == 0
    noticed = conn.execute("SELECT count(*) AS n FROM outage_notices").fetchone()
    assert noticed is not None and int(noticed["n"]) > 0


def test_working_time_skips_the_night_and_the_weekend() -> None:
    friday_late = at(4, 16, 30)
    # Half an hour left on Friday, then Monday morning.
    assert after_working_time(friday_late, HOUR) == at(7, 9, 30)
    # Before the offices open, the clock starts at nine.
    assert after_working_time(at(1, 6), 30 * MINUTE) == at(1, 9, 30)
    # A till keeps the cafe's hours, Saturday included.
    assert after_working_time(at(5, 17, 30), HOUR, till=True) == at(7, 7, 30)
    for start in range(0, 7 * DAY, 97 * MINUTE):
        moment = SimTime(after_working_time(start, 2 * HOUR))
        assert moment.is_workday
        assert WORK_START <= moment.time_of_day <= WORK_END


# -- defect 10: runway is time, not a multiple of the bill ---------------------


def test_runway_is_cash_over_what_a_week_costs(conn: Connection[DictRow]) -> None:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    weekly = engine.weekly_outgoings("tallybird")
    assert weekly > 0
    assert engine.runway_days("tallybird", 4 * weekly) == pytest.approx(28.0)
    # Whatever is being paid: the old figure was cash / this bill * 7.
    assert engine.runway_days("tallybird", 0) == 0.0
    conn.rollback()


# -- defect 6: the engine says which build it is --------------------------------


def test_the_daemon_stamps_its_build_and_records_a_change(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(conn, root_seed=ROOT_SEED)
    conn.commit()

    def events() -> list[DictRow]:
        return conn.execute(
            "SELECT payload FROM events WHERE kind = 'engine.changed' ORDER BY seq"
        ).fetchall()

    monkeypatch.setenv("JEVE_ENGINE_SHA", "a" * 40)
    daemon._stamp_engine(conn)
    stamped = conn.execute("SELECT engine_sha FROM sim_meta").fetchone()
    assert stamped is not None and stamped["engine_sha"] == "a" * 40
    # First stamp of a world: nothing to have changed from.
    assert events() == []

    daemon._stamp_engine(conn)
    assert events() == []

    monkeypatch.setenv("JEVE_ENGINE_SHA", "b" * 40)
    daemon._stamp_engine(conn)
    changed = events()
    assert [dict(r["payload"]) for r in changed] == [{"from": "a" * 40, "to": "b" * 40}]
    conn.execute("DELETE FROM events WHERE kind = 'engine.changed'")
    conn.commit()
