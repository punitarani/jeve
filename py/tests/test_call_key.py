"""What the call cache's key can see (DECIDE-0004).

The old key hashed canonical, key-sorted JSON under an undated slug. The audit
reversed every question's options — 1,741 of 1,787 wire bodies changed — and
all 1,787 lookups still hit. These tests pin what is now a miss.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.policy import DecisionContext
from jeve.decide.recorder import Recorder, call_key
from jeve.errors import ModelVersionDriftError
from jeve.llm import DECISION_PIN, DecisionRequest, RawDecision
from jeve.llm.protocol import Choice, Noul, Usage
from jeve.sim import CASSETTE
from jeve.world.seed_world import ROOT_SEED

STATE: dict[str, object] = {"person": "a careful office manager", "bill": "due today"}


def _request(
    options: Mapping[str, str | None], wording: str = "What do they do?"
) -> bytes:
    return DecisionRequest(
        model="typesafe/jev-1.13",
        state=STATE,
        questions={"act": Choice(instructions=wording, criteria=dict(options))},
    ).wire_bytes()


def test_the_same_request_is_the_same_key() -> None:
    options = {"pay": "pays it now", "wait": "leaves it for another day"}
    assert call_key(DECISION_PIN, _request(options)) == call_key(
        DECISION_PIN, _request(dict(options))
    )


def test_option_order_is_part_of_the_question() -> None:
    forwards = {"pay": "pays it now", "wait": "leaves it for another day"}
    backwards = dict(reversed(forwards.items()))

    assert _request(forwards) != _request(backwards)
    assert call_key(DECISION_PIN, _request(forwards)) != call_key(
        DECISION_PIN, _request(backwards)
    )


def test_question_order_is_part_of_the_request() -> None:
    a = Noul(instructions="Do they pay today?")
    b = Noul(instructions="Do they complain first?")
    one = DecisionRequest(model="m", state=STATE, questions={"pay": a, "moan": b})
    two = DecisionRequest(model="m", state=STATE, questions={"moan": b, "pay": a})
    assert call_key(DECISION_PIN, one.wire_bytes()) != call_key(
        DECISION_PIN, two.wire_bytes()
    )


def test_a_reworded_question_is_a_different_call() -> None:
    options = {"pay": "pays it now", "wait": "leaves it for another day"}
    assert call_key(DECISION_PIN, _request(options)) != call_key(
        DECISION_PIN, _request(options, wording="What do they do next?")
    )


def test_another_build_of_the_model_is_a_different_call() -> None:
    wire = _request({"pay": "pays it now", "wait": "leaves it"})
    assert call_key(DECISION_PIN, wire) != call_key("typesafe/jev-1.13-20270101", wire)


def test_the_wire_is_compact_ordered_json() -> None:
    wire = _request({"pay": "pays it now", "wait": None})
    assert json.loads(wire)["questions"]["act"]["criteria"] == {
        "pay": "pays it now",
        "wait": None,
    }
    assert wire.index(b'"model"') < wire.index(b'"state"') < wire.index(b'"questions"')
    assert b": " not in wire and b", " not in wire.replace(b"it, ", b"")


# -- drift ---------------------------------------------------------------------


@pytest.fixture
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect(autocommit=True) as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


class _AnotherBuildAnswers:
    """Stands where the gateway's bridge stands and returns a *recorded* Jev
    response with only its build label changed. The answer is a real one; what
    is simulated is TypeSafe re-pointing the slug."""

    def __init__(self, payload: dict[str, Any], served: str) -> None:
        self._payload = {**payload, "model": served}

    def fetch(
        self, requests: Sequence[DecisionRequest], *, parent: str | None = None
    ) -> list[RawDecision]:
        return [
            RawDecision(payload=dict(self._payload), usage=Usage(), latency_s=0.1)
            for _ in requests
        ]

    def close(self) -> None:
        return None


def test_a_new_build_halts_the_run_and_keeps_what_was_paid_for(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    if not CASSETTE.exists():
        pytest.skip("no cassette to take a recorded response from")
    recorded = json.loads(CASSETTE.read_text().splitlines()[0])["response"]
    served = "typesafe/jev-1.13-29990101"
    conn.execute("DELETE FROM model_calls WHERE model = %s", (served,))

    # A slug nothing was ever recorded under, so the lookup is certain to miss
    # and the policy has to go to "the network": a customer noticing an outage is
    # among the most-recorded situations in the cassette.
    policy = JevPolicy(
        ROOT_SEED, Recorder(mode="record"), model="typesafe/jev-drift-test"
    )
    monkeypatch.setattr(policy, "_live", lambda: _AnotherBuildAnswers(recorded, served))
    ctx = DecisionContext(
        person_id="drift.test",
        role="subscriber",
        decision_seq=0,
        sim_time=0,
        kind="file.ticket",
        facts={"module_down": True, "already_open": False, "drift_test": True},
        traits={"vocality": 0.5, "patience": 0.5},
    )
    try:
        with pytest.raises(ModelVersionDriftError, match="move DECISION_PIN"):
            policy.decide(ctx)

        # Kept, under the build that served it...
        kept = conn.execute(
            "SELECT hash, wire FROM model_calls WHERE model = %s", (served,)
        ).fetchall()
        assert len(kept) == 1
        wire = str(kept[0]["wire"]).encode()
        assert kept[0]["hash"] == call_key(served, wire)
        # ...and invisible to a lookup under the pin, so it can never be read
        # back as the pinned build's answer.
        assert policy.recorder.lookup([call_key(DECISION_PIN, wire)]) == {}
    finally:
        policy.close()
        conn.execute("DELETE FROM model_calls WHERE model = %s", (served,))
