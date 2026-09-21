"""Dialogue is a projection of a typed encounter (GEN-0001).

Nothing here calls a model. What is tested is the contract around the prose:
the typed record is always returned, prose is only ever *added* to it, a missing
key degrades to the typed record with a reason, and cached prose is served
without opening a gateway.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from jeve import db
from jeve.api import app as api
from jeve.core.clock import at
from jeve.decide.policy import RulesPolicy
from jeve.decide.recorder import insert_call
from jeve.gen import dialogue
from jeve.llm import GENERATIVE_PREFERENCE, Gateway
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.conftest import RecordingSink
from tests.test_gateway import CHAT_BODY
from tests.test_gateway import Recorder as WireRecorder
from tests.test_gateway import _settings as wire_settings

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    try:
        with db.connect() as conn:
            db.migrate(conn)
            seed(conn, root_seed=ROOT_SEED)
            engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
            advance(conn, engine, until=at(1))
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture
def encounter_seq() -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT seq FROM events WHERE kind = 'encounter' ORDER BY seq LIMIT 1"
        ).fetchone()
    assert row is not None
    return int(row["seq"])


def test_without_a_key_the_typed_record_stands_alone(
    client: TestClient, encounter_seq: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    body = client.get(f"/encounters/{encounter_seq}/dialogue").json()
    assert body["prose"] is None
    assert "no API key" in body["reason"]
    typed = body["typed"]
    assert typed["seq"] == encounter_seq
    assert len(typed["between"]) == 2
    assert typed["zone"] in ("cafe", "plaza", "software_office", "law_office",
                             "accounting_office")  # fmt: skip
    assert typed["topic"]


def test_only_an_encounter_has_dialogue(client: TestClient) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT seq FROM events WHERE kind = 'cafe.sale' LIMIT 1"
        ).fetchone()
    assert row is not None
    assert client.get(f"/encounters/{row['seq']}/dialogue").status_code == 404


def test_cached_prose_is_served_without_a_gateway(
    client: TestClient, encounter_seq: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once rendered, never paid for again — and no key is needed to read it."""

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def refuse() -> None:
        raise AssertionError("cached prose opened a gateway")

    monkeypatch.setattr(api, "_open_gateway", refuse)

    model = GENERATIVE_PREFERENCE[1]
    with db.connect(autocommit=True) as conn:
        encounter = dialogue.load_encounter(conn, encounter_seq)
        assert encounter is not None
        key = dialogue.request_key(model, encounter)
        first = encounter.a_name.split()[0]
        insert_call(
            conn,
            {
                "hash": key,
                "kind": dialogue.KIND,
                "model": model,
                "response": {
                    "text": json.dumps(
                        {
                            "lines": [
                                {"speaker": first, "text": "Busy morning?"},
                                {"speaker": "Other", "text": "The usual."},
                            ]
                        }
                    )
                },
                "cost_usd": 0.0001,
            },
        )
    try:
        body = client.get(f"/encounters/{encounter_seq}/dialogue").json()
        assert body["prose"]["cached"] is True
        assert body["prose"]["model"] == model
        assert [line["speaker"] for line in body["prose"]["lines"]] == [first, "Other"]
        # The record is still there beside it: prose is added, never substituted.
        assert body["typed"]["seq"] == encounter_seq
    finally:
        with db.connect(autocommit=True) as conn:
            conn.execute("DELETE FROM model_calls WHERE hash = %s", (key,))


def test_the_cache_key_is_the_typed_fields_not_the_event() -> None:
    base = dialogue.Encounter(
        seq=10, a_name="Ann Lee", a_role="partner", a_org="halloran",
        b_name="Bo Ruiz", b_role="sre", b_org="tallybird",
        zone="cafe", topic="the_outage", mood=1, escalated=True,
    )  # fmt: skip
    same_but_later = replace(base, seq=999)
    calmer = replace(base, mood=3)
    assert dialogue.request_key("m", base) == dialogue.request_key("m", same_but_later)
    assert dialogue.request_key("m", base) != dialogue.request_key("m", calmer)
    assert dialogue.request_key("m", base) != dialogue.request_key("n", base)


def test_the_prompt_carries_only_typed_facts() -> None:
    encounter = dialogue.Encounter(
        seq=1, a_name="Ann Lee", a_role="partner", a_org="halloran",
        b_name="Bo Ruiz", b_role="sre", b_org="tallybird",
        zone="cafe", topic="the_outage", mood=0, escalated=True,
    )  # fmt: skip
    system, user = dialogue.messages_for(encounter)
    assert "invent no names, numbers" in system.content
    assert "Ann Lee, a partner at the law firm" in user.content
    assert "the neighbourhood cafe" in user.content
    assert "presses for the outage to be fixed" in user.content
    # No ids, no sim time, no money: nothing the model could echo back as fact.
    assert "halloran." not in user.content and "$" not in user.content


@pytest.mark.parametrize(
    "reply",
    ["not json", "[]", '{"lines": "no"}', '{"lines": [{"speaker": "A"}]}', "{}"],
)
def test_bad_prose_is_dropped_not_raised(reply: str) -> None:
    assert dialogue.parse_lines(reply) == []


# -- spans (LLM-0008) ------------------------------------------------------


def test_rendering_prose_is_one_trace_over_the_fallback_ladder(
    client: TestClient,
    encounter_seq: int,
    spans: RecordingSink,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """LLM-0005/0006: which models were tried, and which one answered.

    The first model returns prose nobody can read, so the endpoint falls
    through to the second. Both attempts are on the trace — a ladder you
    cannot see is a ladder you cannot tune.
    """

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    usable = json.dumps(
        {
            "lines": [
                {"speaker": "A", "text": "Morning."},
                {"speaker": "B", "text": "Hi."},
            ]
        }
    )
    replies = iter(
        [
            httpx.Response(200, json={**CHAT_BODY, "choices": []}),
            httpx.Response(
                200,
                json={
                    **CHAT_BODY,
                    "choices": [
                        {"message": {"content": usable}, "finish_reason": "stop"}
                    ],
                },
            ),
        ]
    )
    wire = WireRecorder(chat=replies)
    gateway = Gateway(
        settings=wire_settings(tmp_path),
        transport=wire.transport(),
        backoff_base_s=0.0,
    )

    async def opened() -> Gateway:
        await gateway.start()
        return gateway

    monkeypatch.setattr(api, "_open_gateway", opened)
    try:
        body = client.get(f"/encounters/{encounter_seq}/dialogue").json()
    finally:
        # `model_calls` is a cache that outlives the test run, and a cached
        # render would make every later dialogue test read prose instead of
        # asking for it.
        with db.connect(autocommit=True) as conn:
            encounter = dialogue.load_encounter(conn, encounter_seq)
            assert encounter is not None
            conn.execute(
                "DELETE FROM model_calls WHERE hash = ANY(%s)",
                (
                    [
                        dialogue.request_key(model, encounter)
                        for model in GENERATIVE_PREFERENCE
                    ],
                ),
            )

    assert body["prose"]["lines"][0] == {"speaker": "A", "text": "Morning."}
    root = spans.only("dialogue")
    assert root.type == "task"
    assert root.fields["input"]["seq"] == encounter_seq
    assert root.fields["metadata"]["outcome"] == "ok"
    # The order the gateway resolved, not the preference constant: a slug that
    # does not resolve drops out of the ladder (LLM-0005).
    ladder = gateway.generative_models
    assert root.fields["metadata"]["model"] == ladder[1]

    calls = [child for child in root.children if child.name == "chat.completion"]
    assert [call.fields["metadata"]["model"] for call in calls] == list(ladder[:2])
    # Prose is never gate work, so it is the first thing the ladder refuses.
    assert calls[0].fields["metadata"]["purpose"] == "explore"
    # Paid for and unreadable: the cost is on the span even though the reply
    # never became prose.
    assert calls[0].fields["metrics"]["estimated_cost"] > 0.0
    assert "ResponseShapeError" in (calls[0].error or "")
