"""The instruments that read the world without changing it: the judge panel
(`jeve.sim.panel`) and the ontology-gap report (`jeve.gen.ontology`).

Both are tested on a cache and a decision log built to a known answer, so a
measurement that cannot see what it claims to measure fails here rather than
in a report nobody questions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.decide import escalation
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS
from jeve.decide.recorder import call_key, insert_call
from jeve.gen import ontology
from jeve.llm import DECISION_PIN, GENERATIVE_PREFERENCE, DecisionRequest
from jeve.sim import panel
from jeve.world.seed_world import ROOT_SEED, seed

pytestmark = pytest.mark.timeout(300)

KIND = "cafe.purchase"
MODEL = GENERATIVE_PREFERENCE[0]


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect(autocommit=True) as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def _record(conn: Connection[DictRow], patience: float, queue: int, p: float) -> str:
    """One Jev call, as the cache holds it."""

    prepared = QUESTION_SETS[KIND].prepare(
        DecisionContext(
            person_id="p",
            role="customer",
            decision_seq=0,
            sim_time=10 * 3600,
            kind=KIND,
            facts={"pos_down": False, "queue_length": queue},
            traits={"patience": patience},
        )
    )
    assert prepared.state is not None
    wire = DecisionRequest(
        model="typesafe/jev",
        state=prepared.state,
        questions={ask.key: ask.question for ask in prepared.asks},
    ).wire_bytes()
    key = call_key(DECISION_PIN, wire)
    insert_call(
        conn,
        {
            "hash": key,
            "kind": KIND,
            "model": DECISION_PIN,
            "request": json.loads(wire),
            "wire": wire.decode(),
            "response": {"answers": {"buy": {"type": "noul", "noul": p}}},
        },
    )
    return key


def test_the_panel_sees_temperament_outweigh_situation_where_it_does(
    conn: Connection[DictRow],
) -> None:
    conn.execute("DELETE FROM model_calls WHERE kind = ANY(%s)", ([KIND, "panel"],))
    # Jev, by construction: the patient buy, the impatient do not, and the
    # length of the queue barely matters.
    for patience in (0.0, 0.5, 1.0):
        for queue in (0, 2, 6):
            _record(conn, patience, queue, 0.2 + 0.6 * patience + 0.01 * queue)

    contexts = panel.load(conn, [KIND])
    assert len(contexts) == 9
    jev = panel.effects(contexts, lambda c: c.jev)
    assert jev.verdict == "temperament outweighs situation"
    assert jev.temperament is not None and jev.situation is not None
    assert jev.temperament > 5 * jev.situation

    sample = panel.pick(contexts, per_set=6)
    assert len(sample) == 6
    # Both kinds of pair survive the sampling, or the panel measures nothing.
    chosen = panel.effects(sample, lambda c: c.jev)
    assert chosen.situation_pairs and chosen.temperament_pairs

    # A panel model that reads the queue and not the person, answering through
    # tier 1's own request, cached where a real answer would be.
    for context in sample:
        line = str(context.state.get("line", ""))
        busy = 0.9 if "slow" in line or "several" in line else 0.1
        sent = panel.request(context, MODEL)
        insert_call(
            conn,
            {
                "hash": escalation.request_key(sent),
                "kind": panel.KIND,
                "model": MODEL,
                "request": sent.model_dump(mode="json"),
                "response": {
                    "text": json.dumps({"buy": {"yes": 1 - busy, "no": busy}})
                },
            },
        )
    answered = panel.cached(conn, sample, [MODEL])
    assert len(answered) == len(sample)
    theirs = panel.effects(sample, lambda c: answered.get((c.hash, MODEL)))
    assert theirs.verdict == "situation outweighs temperament"

    text = panel.render(contexts, sample, answered, [MODEL])
    assert "temperament outweighs situation" in text
    assert f"| {KIND} | {MODEL} | 6 |" in text


@pytest.fixture(scope="module")
def world() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            seed(connection, root_seed=ROOT_SEED)
            connection.commit()
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def test_a_choice_that_keeps_reaching_for_other_is_reported_too_small(
    world: Connection[DictRow],
) -> None:
    person = world.execute("SELECT id FROM persons ORDER BY id LIMIT 1").fetchone()
    assert person is not None
    state = {"person": "someone", "situation": "the reason none of it fitted"}
    world.execute(
        "INSERT INTO model_calls (hash, kind, model, request, response) "
        "VALUES ('gap-call', 'dispute.resolution', 'jev', %s, '{}') "
        "ON CONFLICT (hash) DO NOTHING",
        (json.dumps({"state": state, "questions": {"resolution": {}}}),),
    )
    rows: list[tuple[object, ...]] = []
    for seq in range(40):
        other = 0.6 if seq < 4 else 0.05  # a tenth of them: too small
        rows.append(
            (
                person["id"],
                10_000 + seq,
                "dispute.resolution",
                "gap-call",
                "jev",
                json.dumps(
                    {
                        "resolution": {
                            "stand_firm": 0.5 - other / 2,
                            "discount": 0.5 - other / 2,
                            "write_off": 0.0,
                            "other": other,
                        }
                    }
                ),
            )
        )
    # And the rules twin, which never counts: it has no mass to misplace.
    rows.append(
        (
            person["id"],
            10_100,
            "dispute.resolution",
            None,
            "rules",
            json.dumps({"resolution": {"stand_firm": 0.0, "other": 1.0}}),
        )
    )
    db.executemany(
        world,
        "INSERT INTO decisions (person_id, decision_seq, sim_time, tick_seq, "
        "question_set, model_call, source, distributions) "
        "VALUES (%s, %s, 0, 0, %s, %s, %s, %s)",
        rows,
    )
    world.commit()

    found = {(g.question_set, g.ask): g for g in ontology.gaps(world)}
    gap = found[("dispute.resolution", "resolution")]
    assert (gap.decisions, gap.gaps) == (40, 4)
    assert gap.too_small
    shown = ontology.examples(world, gap)
    assert shown == [{"state": state, "question": {}}]

    request = ontology.proposal_request(gap, shown, MODEL)
    assert request.response_schema == ontology.SCHEMA
    reply = json.dumps(
        {
            "verdict": "new_option",
            "option": "payment_plan",
            "definition": "Agree to take the money in instalments.",
            "why": "They wanted neither to give ground nor to lose the client.",
        }
    )
    proposal = ontology.parse_proposal(reply)
    assert proposal is not None and proposal["option"] == "payment_plan"
    assert ontology.parse_proposal("a payment plan, probably") is None
    assert ontology.parse_proposal(json.dumps({"verdict": "rename"})) is None

    text = ontology.render(
        list(found.values()), {("dispute.resolution", "resolution"): proposal}
    )
    assert "**too small**" in text and "`payment_plan`" in text
    world.execute("DELETE FROM decisions WHERE decision_seq >= 10000")
    world.commit()
