"""The degeneracy detectors on /report (API-0004).

A detector is instrumentation only once it has been seen to fire. Each test
here takes one healthy rules world, breaks it in exactly the way its detector
is meant to notice, and checks that detector fires. Every break is rolled back,
so each starts from the same healthy world.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.api import detectors
from jeve.core.clock import DAY, SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.map import ORG_ZONE
from jeve.world.seed_world import ROOT_SEED, seed
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(600)

DAYS = 10
NOW = SimTime(at(DAYS))


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)

            def build() -> None:
                seed(connection, root_seed=ROOT_SEED)
                engine = Engine(connection, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
                advance(connection, engine, until=NOW.seconds)

            build_once(connection, f"detectors-{DAYS}", build)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def readings(conn: Connection[DictRow]) -> dict[str, dict[str, object]]:
    return {str(r["name"]): r for r in detectors.run(conn, NOW)}


@pytest.fixture
def broken(conn: Connection[DictRow]) -> Iterator[Connection[DictRow]]:
    """The healthy world, to be broken inside a transaction that is undone."""

    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()


def test_a_healthy_world_trips_nothing(conn: Connection[DictRow]) -> None:
    found = readings(conn)
    assert set(found) == {
        "idle_with_backlog",
        "action_entropy",
        "role_information",
        "negative_events",
        "money_velocity",
        "persona_signal",
        "ontology_gaps",
        "tier1_redundant",
    }
    assert [name for name, r in found.items() if r["fires"]] == []
    # Measured, not merely quiet for want of data.
    for name in ("action_entropy", "role_information", "money_velocity"):
        assert found[name]["value"] is not None, name
    # No model has answered anything in a rules world: those two cannot tell.
    assert found["ontology_gaps"]["value"] is None
    assert found["tier1_redundant"]["value"] is None


def test_support_in_the_cafe_with_a_backlog(broken: Connection[DictRow]) -> None:
    reporter = broken.execute(
        "SELECT id FROM persons WHERE kind = 'counterparty' LIMIT 1"
    ).fetchone()
    assert reporter is not None
    since = NOW.seconds - detectors.WINDOW
    db.executemany(
        broken,
        "INSERT INTO tickets (opened_sim, reporter_id, subject, status) "
        "VALUES (%s, %s, 'stuck', 'open')",
        [(since, reporter["id"])] * 20,
    )
    # And every move support made this week ends in the cafe.
    broken.execute(
        "UPDATE events SET payload = jsonb_set(payload, '{to_zone}', '\"cafe\"') "
        "WHERE kind = 'agent.moved' AND sim_time >= %s AND payload->>'to_zone' = %s "
        "AND payload->>'person_id' IN (SELECT id FROM persons WHERE role = ANY(%s))",
        (since, ORG_ZONE["tallybird"].value, list(detectors.SUPPORT_ROLES)),
    )
    assert readings(broken)["idle_with_backlog"]["fires"]


def test_an_act_that_always_comes_out_the_same(broken: Connection[DictRow]) -> None:
    broken.execute(
        "UPDATE decisions SET chosen = jsonb_set(chosen, '{buy}', 'true') "
        "WHERE question_set = 'cafe.purchase'"
    )
    reading = readings(broken)["action_entropy"]
    assert reading["fires"]
    assert "cafe.purchase.buy" in str(reading["detail"])


def test_roles_that_all_go_to_the_same_place(broken: Connection[DictRow]) -> None:
    broken.execute(
        "UPDATE decisions SET chosen = jsonb_set(chosen, '{next_zone}', "
        "to_jsonb(CASE WHEN id % 2 = 0 THEN 'cafe' ELSE 'plaza' END)) "
        "WHERE question_set = 'agent.tick'"
    )
    assert readings(broken)["role_information"]["fires"]


def test_an_economy_without_friction(broken: Connection[DictRow]) -> None:
    broken.execute(
        "UPDATE events SET kind = 'calm.' || kind WHERE kind = ANY(%s)",
        (list(detectors.NEGATIVE_EVENTS),),
    )
    reading = readings(broken)["negative_events"]
    assert reading["fires"] and reading["value"] == 0


def test_money_that_stops_moving(broken: Connection[DictRow]) -> None:
    # The same cash, but none of it changed hands this week: every movement
    # is dated to before the window opened.
    broken.execute(
        "UPDATE ledger_txns SET sim_time = %s WHERE sim_time >= %s",
        (NOW.seconds - detectors.WINDOW - DAY, NOW.seconds - detectors.WINDOW),
    )
    assert readings(broken)["money_velocity"]["fires"]


def test_a_temperament_that_changes_nothing(broken: Connection[DictRow]) -> None:
    # Everyone does the same thing, whatever they are like.
    for kind, key, _ in detectors.PERSONAS:
        broken.execute(
            "UPDATE decisions SET chosen = jsonb_set(chosen, %s, 'true') "
            "WHERE question_set = %s AND jsonb_typeof(chosen->%s) = 'boolean'",
            ([key], kind, key),
        )
    assert readings(broken)["persona_signal"]["fires"]


def _modelled(broken: Connection[DictRow], n: int, other: float) -> list[int]:
    person = broken.execute("SELECT id FROM persons LIMIT 1").fetchone()
    assert person is not None
    ids = []
    for seq in range(n):
        row = broken.execute(
            "INSERT INTO decisions (person_id, decision_seq, sim_time, tick_seq, "
            "question_set, source, distributions) "
            "VALUES (%s, %s, %s, 0, 'dispute.resolution', 'jev', %s) RETURNING id",
            (
                person["id"],
                900_000 + seq,
                NOW.seconds - DAY,
                json.dumps({"resolution": {"stand_firm": 1 - other, "other": other}}),
            ),
        ).fetchone()
        assert row is not None
        ids.append(int(row["id"]))
    return ids


def test_options_that_do_not_fit(broken: Connection[DictRow]) -> None:
    _modelled(broken, 40, other=0.6)
    reading = readings(broken)["ontology_gaps"]
    assert reading["fires"] and reading["value"] == 1.0


def test_a_second_opinion_that_only_ever_agrees(broken: Connection[DictRow]) -> None:
    ids = _modelled(broken, detectors.TIER1_ROWS, other=0.0)
    db.executemany(
        broken,
        "INSERT INTO escalations (decision_id, question_set, sim_time, mode, "
        "asks, jev, llm, model, call_hash, agrees) VALUES (%s, "
        "'dispute.resolution', %s, 'shadow', ARRAY['resolution'], '{}', '{}', "
        "'m', 'h', true)",
        [(i, NOW.seconds - DAY) for i in ids],
    )
    reading = readings(broken)["tier1_redundant"]
    assert reading["fires"] and reading["value"] == 1.0
