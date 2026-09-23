"""Jev behind the policy seam, exercised from the recorded cassette.

Every model response in here is one Jev actually gave: the cassette is loaded
and the policy runs in strict replay. Nothing pretends to be a model. What is
under test is everything *around* the model — hashing, caching, sampling, the
engine's bookkeeping — and that replaying a recording reproduces the run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, tracing
from jeve.api.app import app
from jeve.config import load_settings
from jeve.core.clock import at
from jeve.decide import jev_policy

# Captured before `no_network` swaps the name out: these tests want the real
# thread, because the thread is what they are about.
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.jev_policy import _Bridge as Bridge
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.decide.recorder import (
    Recorder,
    ReplayMissError,
    finalize_cassette,
    load_cassette,
)
from jeve.llm import Gateway
from jeve.sim import CASSETTE, advance
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.conftest import RecordingSink
from tests.test_gateway import Recorder as WireRecorder
from tests.test_gateway import _decision_request as wire_request
from tests.test_gateway import _settings as wire_settings
from tests.test_world import event_log_hash
from tests.worldcache import build_once

pytestmark = pytest.mark.timeout(300)

DAYS = 2


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    if not CASSETTE.exists():
        pytest.skip(f"no cassette at {CASSETTE}; record one with LIVE=1 make e2e")
    try:
        with db.connect() as connection:
            db.migrate(connection)
            load_cassette(connection, CASSETTE)
            connection.commit()
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replay that opens a gateway needs a key, and a clean clone has none."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay constructed a gateway")

    monkeypatch.setattr(jev_policy, "_Bridge", refuse)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def replay(conn: Connection[DictRow], *, days: int = DAYS) -> JevPolicy:
    seed(conn, root_seed=ROOT_SEED)
    policy = JevPolicy(ROOT_SEED, Recorder(mode="replay"))
    engine = Engine(conn, policy, root_seed=ROOT_SEED)
    advance(conn, engine, until=at(days))
    return policy


def replayed(conn: Connection[DictRow]) -> None:
    """The replayed world, for tests that only read it."""

    build_once(conn, f"jev-replay:{DAYS}d", lambda: replay(conn).close())


def test_a_replay_reproduces_itself_without_a_key(conn: Connection[DictRow]) -> None:
    first = replay(conn)
    first_hash = event_log_hash(conn)
    decisions = conn.execute(
        "SELECT person_id, decision_seq, source, model_call, chosen, draws "
        "FROM decisions ORDER BY id"
    ).fetchall()

    second = replay(conn)
    assert event_log_hash(conn) == first_hash
    assert (
        decisions
        == conn.execute(
            "SELECT person_id, decision_seq, source, model_call, chosen, draws "
            "FROM decisions ORDER BY id"
        ).fetchall()
    )

    for policy in (first, second):
        assert policy.recorder.stats.live_calls == 0
        assert policy.recorder.stats.hits == policy.recorder.stats.lookups > 0
        policy.close()


def test_most_decisions_are_made_by_the_model(conn: Connection[DictRow]) -> None:
    replayed(conn)
    by_source = {
        str(r["source"]): int(r["n"])
        for r in conn.execute(
            "SELECT source, count(*) AS n FROM decisions GROUP BY source"
        ).fetchall()
    }
    assert by_source["jev"] > 3 * by_source.get("rules", 0)

    # Every model-made decision names a call we hold, and carries what Jev
    # said — not just what was drawn from it.
    orphans = conn.execute(
        "SELECT count(*) AS n FROM decisions d WHERE source = 'jev' AND NOT EXISTS "
        "(SELECT 1 FROM model_calls m WHERE m.hash = d.model_call)"
    ).fetchone()
    assert orphans is not None and int(orphans["n"]) == 0
    empty = conn.execute(
        "SELECT count(*) AS n FROM decisions "
        "WHERE source = 'jev' AND distributions = '{}'::jsonb"
    ).fetchone()
    assert empty is not None and int(empty["n"]) == 0


def test_a_gated_decision_is_credited_to_rules(conn: Connection[DictRow]) -> None:
    """No model was consulted, so none is credited — or the share of decisions
    "made by Jev" would be padded with ones it never saw."""

    replayed(conn)
    gated = conn.execute(
        "SELECT source, model_call, chosen FROM decisions "
        "WHERE question_set = 'payment.timing' AND chosen->>'reason' = 'not_due' "
        "LIMIT 1"
    ).fetchone()
    if gated is None:
        pytest.skip("no invoice was asked about before its due date in this window")
    assert gated["source"] == "rules"
    assert gated["model_call"] is None


def test_events_say_who_really_decided(conn: Connection[DictRow]) -> None:
    replayed(conn)
    mismatched = conn.execute(
        "SELECT count(*) AS n FROM events e JOIN decisions d ON d.id = e.decision_id "
        "WHERE e.payload ? 'decided_by' AND e.payload->>'decided_by' <> d.source"
    ).fetchone()
    linked = conn.execute(
        "SELECT count(*) AS n FROM events WHERE decision_id IS NOT NULL"
    ).fetchone()
    assert mismatched is not None and int(mismatched["n"]) == 0
    assert linked is not None and int(linked["n"]) > 100


def test_someone_who_walks_in_twice_in_a_tick_decides_twice(
    conn: Connection[DictRow],
) -> None:
    """Arrivals are drawn with replacement. Batched naively, both visits get the
    same place in that person's sequence: a unique violation at best, the same
    draw twice at worst."""

    replayed(conn)
    doubles = conn.execute(
        "SELECT person_id, tick_seq, array_agg(decision_seq ORDER BY decision_seq) "
        "  AS seqs, array_agg(prng_path ORDER BY decision_seq) AS paths "
        "FROM decisions WHERE question_set = 'retail.purchase' "
        "GROUP BY person_id, tick_seq HAVING count(*) > 1"
    ).fetchall()
    assert doubles, "no repeat visitor in the window; lengthen DAYS"
    for row in doubles:
        assert row["seqs"] == sorted(set(row["seqs"]))
        assert row["seqs"][1] == row["seqs"][0] + 1
        assert len(set(row["paths"])) == len(row["paths"])


def test_strict_replay_fails_on_a_miss_and_names_the_question_set(
    conn: Connection[DictRow],
) -> None:
    policy = JevPolicy(ROOT_SEED, Recorder(mode="replay"))
    unseen = DecisionContext(
        person_id="tallybird.support.support.0",
        role="support",
        decision_seq=0,
        sim_time=at(0, 10),
        kind="ticket.triage",
        facts={"subject": "the office parrot has learned my password"},
    )
    with pytest.raises(ReplayMissError, match=r"ticket\.triage"):
        policy.decide(unseen)
    policy.close()


def test_a_batch_equals_deciding_one_at_a_time(conn: Connection[DictRow]) -> None:
    contexts = [
        DecisionContext(
            person_id=f"thirdrail.customer.{index}",
            role="customer",
            decision_seq=index,
            sim_time=at(0, 10),
            kind="retail.purchase",
            facts={"org": "thirdrail", "till_down": False, "queue_length": queue},
            traits={"patience": patience},
        )
        for index, (queue, patience) in enumerate(
            [(0, 0.35), (0, 0.85), (2, 0.35), (4, 0.85), (4, 0.35), (4, 0.35)]
        )
    ]
    policy = JevPolicy(ROOT_SEED, Recorder(mode="replay"))
    together = policy.decide_many(contexts)
    alone = [policy.decide(ctx) for ctx in contexts]
    policy.close()

    assert together == alone
    # Same situation, same distribution, different person: a different draw.
    assert together[4].distributions == together[5].distributions
    assert together[4].draws != together[5].draws


def test_rules_and_jev_disagree_about_the_world(conn: Connection[DictRow]) -> None:
    """If swapping the decider changed nothing, the seam would be decorative."""

    replayed(conn)
    jev_hash = event_log_hash(conn)

    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    advance(conn, engine, until=at(DAYS))
    assert event_log_hash(conn) != jev_hash


def test_economics_prices_the_run_from_the_calls_it_used(
    conn: Connection[DictRow],
) -> None:
    replayed(conn)
    conn.commit()
    with TestClient(app) as client:
        body = client.get("/economics").json()

    assert body["counts"]["modelled"] > 0
    assert 0 < body["model_calls"] < body["counts"]["modelled"]
    assert body["spend_usd"] > 0.0
    assert body["spend_is_estimated_calls"] == 0
    assert body["unpriced_decisions"] == 0
    assert 0.0 < body["dedup_rate"] < 1.0
    # Ignoring the cache can only cost more, never less.
    assert body["without_dedup"]["spend_usd"] > body["spend_usd"]
    assert [m["model"] for m in body["decisions_by_model"]] == [
        "typesafe/jev-1.13-20260917"
    ]
    assert sum(k["decisions"] for k in body["by_kind"]) == body["counts"]["decisions"]


def test_the_first_recording_of_a_call_wins(conn: Connection[DictRow]) -> None:
    recorder = Recorder(mode="record")
    common: dict[str, Any] = {
        "kind": "test",
        "model": "m",
        "provider": None,
        "request": {},
        "wire": "{}",
        "input_tokens": 1,
        "output_tokens": 0,
        "cost_usd": 0.5,
        "cost_estimated": False,
        "latency_s": 0.1,
    }
    try:
        recorder.store("test-hash", response={"answers": {"a": 1}}, **common)
        recorder.store("test-hash", response={"answers": {"a": 2}}, **common)
        assert recorder.lookup(["test-hash"])["test-hash"].response == {
            "answers": {"a": 1}
        }
    finally:
        conn.execute("DELETE FROM model_calls WHERE hash = 'test-hash'")
        conn.commit()
        recorder.close()


def test_a_cassette_finalises_to_the_same_bytes_in_any_order(tmp_path: Path) -> None:
    """Append order is network-completion order. Committed as-is, the same set
    of calls would diff differently after every recording."""

    rows = [{"hash": h, "response": {"n": i}} for i, h in enumerate("cabdc")]
    one, two = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    one.write_text("".join(json.dumps(r) + "\n" for r in rows))
    two.write_text("".join(json.dumps(r) + "\n" for r in reversed(rows)) + '{"torn')

    assert finalize_cassette(one) == 4
    hashes = [json.loads(line)["hash"] for line in one.read_text().splitlines()]
    assert hashes == ["a", "b", "c", "d"]
    finalize_cassette(two)
    assert [json.loads(x)["hash"] for x in two.read_text().splitlines()] == hashes


def test_the_committed_cassette_is_already_final() -> None:
    if not CASSETTE.exists():
        # Between a change to the cache key and the recording that follows it.
        pytest.skip(f"no cassette at {CASSETTE}; record one with LIVE=1 make e2e")
    before = CASSETTE.read_bytes()
    copy = CASSETTE.with_suffix(".check")
    try:
        copy.write_bytes(before)
        finalize_cassette(copy)
        assert copy.read_bytes() == before
    finally:
        copy.unlink(missing_ok=True)


# -- spans (LLM-0008) ------------------------------------------------------


def test_a_replayed_batch_is_one_span_that_counts_its_cache(
    conn: Connection[DictRow], spans: RecordingSink
) -> None:
    """A cache hit never reaches the gateway, so it is counted, not spanned.

    `live_calls` is the whole cost story for this project, and a replay's is
    zero by definition — which is what makes this the cheap check that the
    counters mean what they say.
    """

    replay(conn, days=1).close()

    batches = spans.named("decide.batch")
    assert batches
    assert not spans.named("jev.decide")
    for batch in batches:
        assert batch.type == "task"
        data = batch.fields["metadata"]
        assert data["mode"] == "replay"
        assert data["live_calls"] == 0
        assert data["cache_hits"] == data["lookups"]
        assert data["distinct_requests"] <= data["lookups"]
    assert sum(b.fields["metadata"]["lookups"] for b in batches) > 0
    assert any(b.fields["metadata"]["kinds"] for b in batches)


def test_a_call_is_parented_by_its_batch_across_the_gateway_thread(
    spend_table: Connection[DictRow],
    spans: RecordingSink,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The one place an ambient parent cannot reach (LLM-0008).

    `_Bridge` runs the gateway on its own loop on its own thread, and
    `run_coroutine_threadsafe` copies the context over there — so the batch
    span open on this thread is not the current span in the gateway. The
    handle has to be carried. The second half of this test is the proof that
    it is doing something: with no handle, the same call is a root.
    """

    wire = WireRecorder()

    def gateway(**_: object) -> Gateway:
        return Gateway(
            settings=wire_settings(tmp_path),
            transport=wire.transport(),
            backoff_base_s=0.0,
        )

    monkeypatch.setattr(jev_policy, "Gateway", gateway)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    bridge = Bridge(load_settings())
    try:
        with tracing.span("decide.batch", type="task") as batch:
            handle = batch.export()
        carried = bridge.fetch([wire_request()], parent=handle)
        orphaned = bridge.fetch([wire_request()])
    finally:
        bridge.close()

    assert not any(isinstance(r, BaseException) for r in carried + orphaned)
    under_batch = spans.only("decide.batch").children
    assert [child.name for child in under_batch] == ["jev.decide"]
    assert under_batch[0].fields["metadata"]["endpoint"] == "decisions"

    roots = [root.name for root in spans.roots]
    assert roots == ["decide.batch", "jev.decide"]
