"""Who has met whom (MEM-0004): one row per pair, written by what happened."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.decide.policy import approach_weight
from jeve.world.seed_world import ROOT_SEED, seed

pytestmark = pytest.mark.timeout(120)


@pytest.fixture
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            seed(connection, root_seed=ROOT_SEED)
            yield connection
            connection.rollback()
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def _two(conn: Connection[DictRow]) -> tuple[str, str]:
    rows = conn.execute(
        "SELECT id FROM persons WHERE kind = 'staff' ORDER BY id LIMIT 2"
    ).fetchall()
    return str(rows[0]["id"]), str(rows[1]["id"])


def test_a_pair_is_one_row_whichever_way_round(conn: Connection[DictRow]) -> None:
    x, y = _two(conn)
    before = memory.meet(conn, y, x, sim_time=100, warmth=1, topic="small_talk")
    assert before == memory.Tie()  # strangers until now
    memory.meet(conn, x, y, sim_time=200, topic="money")
    rows = conn.execute("SELECT a, b, met, warmth, last_topic FROM ties").fetchall()
    assert len(rows) == 1
    assert (rows[0]["a"], rows[0]["b"]) == tuple(sorted((x, y)))
    assert (rows[0]["met"], rows[0]["warmth"], rows[0]["last_topic"]) == (
        2,
        1,
        "money",
    )
    assert memory.ties_of(conn, x, [y]) == {y: memory.Tie(2, 1)}
    assert memory.ties_of(conn, y, [x]) == {x: memory.Tie(2, 1)}


def test_warmth_stays_inside_its_scale(conn: Connection[DictRow]) -> None:
    x, y = _two(conn)
    for _ in range(5):
        memory.warm(conn, x, y, 2, sim_time=10)
    assert memory.ties_of(conn, x, [y])[y].warmth == 3
    for _ in range(5):
        memory.warm(conn, x, y, -2, sim_time=20)
    tie = memory.ties_of(conn, x, [y])[y]
    assert tie.warmth == -3 and tie.fallen_out and not tie.friend
    # Warming is not meeting: a kept promise is not a conversation.
    assert tie.met == 0


def test_strangers_are_absent_and_self_is_never_a_tie(
    conn: Connection[DictRow],
) -> None:
    x, y = _two(conn)
    assert memory.ties_of(conn, x, [y, x]) == {}


def test_people_are_likelier_to_approach_someone_they_know_and_like() -> None:
    stranger = approach_weight({})
    acquaintance = approach_weight({"met": 4, "warmth": 0})
    friend = approach_weight({"met": 4, "warmth": 2})
    fallen_out = approach_weight({"met": 4, "warmth": -3})
    assert fallen_out < stranger < acquaintance < friend
    # Never zero: an enemy can still be the one somebody has to talk to.
    assert fallen_out > 0
