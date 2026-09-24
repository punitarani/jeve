"""Tier 1: an uncertain typed answer, asked again of a flash LLM (DECIDE-0005).

The rule is tested as pure functions. The plumbing is tested at the policy
seam, where Jev's answer comes from `model_calls` exactly as in a replay and
the flash model is a stand-in bridge: what is under test is when a second
opinion is asked for, what is kept, and whether the world acts on it. None of
this needs a key.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, at
from jeve.decide import escalation, jev_policy
from jeve.decide.jev_policy import JevPolicy
from jeve.decide.policy import (
    Decision,
    DecisionContext,
    Escalated,
    RulesPolicy,
)
from jeve.decide.questions import QUESTION_SETS, Ask, Prepared
from jeve.decide.recorder import Mode as RecorderMode
from jeve.decide.recorder import Recorder, ReplayMissError, call_key, insert_call
from jeve.errors import TransportError
from jeve.llm import DECISION_PIN, GENERATIVE_PREFERENCE, ChatRequest, ChatResponse
from jeve.llm.protocol import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    Purpose,
    Score,
    ScoreAnswer,
    Usage,
)
from jeve.sim import advance
from jeve.sim import escalations as report
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed
from tests.test_questions import ASKING, TRAITS

pytestmark = pytest.mark.timeout(300)

FIRST, SECOND = GENERATIVE_PREFERENCE[0], GENERATIVE_PREFERENCE[1]


# -- the rule, as pure functions ----------------------------------------------


def _ask(key: str, mode: str, question: Noul | Choice | Score) -> Ask:
    return Ask(key=key, mode=mode, question=question)  # type: ignore[arg-type]


CHOICE = Choice(instructions="?", criteria={"a": None, "b": None, "c": None})
SCORE = Score(instructions="?", criteria=["low", "middling", "high", "very high"])
NOUL = Noul(instructions="?")


def _choice(**p: float) -> ChoiceAnswer:
    return ChoiceAnswer(choice=max(p, key=lambda k: p[k]), probabilities=p)


def test_a_choice_escalates_on_a_weak_top_or_a_thin_margin() -> None:
    ask = _ask("x", "J", CHOICE)
    kind = "payment.timing"  # medium: no widening
    fired = escalation.triggers(kind, [ask], {"x": _choice(a=0.45, b=0.3, c=0.25)})
    assert [t.rule for t in fired] == ["choice.confidence"]
    fired = escalation.triggers(kind, [ask], {"x": _choice(a=0.52, b=0.40, c=0.08)})
    assert [t.rule for t in fired] == ["choice.margin"]
    assert not escalation.triggers(kind, [ask], {"x": _choice(a=0.8, b=0.1, c=0.1)})


def test_high_stakes_widen_the_band() -> None:
    ask = _ask("x", "J", CHOICE)
    answer = {"x": _choice(a=0.6, b=0.3, c=0.1)}
    assert not escalation.triggers("payment.timing", [ask], answer)
    assert escalation.triggers("credit.decision", [ask], answer)


def test_a_score_escalates_only_when_it_straddles_a_boundary() -> None:
    ask = _ask("x", "J", SCORE)
    across = ScoreAnswer(
        score=1, probabilities={"0": 0.05, "1": 0.35, "2": 0.33, "3": 0.27}
    )
    assert [t.rule for t in escalation.triggers("chase.invoice", [ask], {"x": across})]
    # Just as unsure of the level, but all of it on one side: nothing the code
    # does differs, so nothing is worth asking again.
    lopsided = ScoreAnswer(
        score=2, probabilities={"0": 0.02, "1": 0.08, "2": 0.35, "3": 0.55}
    )
    assert not escalation.triggers("chase.invoice", [ask], {"x": lopsided})


def test_a_noul_escalates_near_its_threshold_and_a_propensity_only_at_high_stakes() -> (
    None
):
    judged = _ask("x", "J", NOUL)
    assert escalation.triggers("payment.timing", [judged], {"x": NoulAnswer(noul=0.55)})
    assert not escalation.triggers(
        "payment.timing", [judged], {"x": NoulAnswer(noul=0.8)}
    )
    felt = _ask("x", "P", NOUL)
    unsure = {"x": NoulAnswer(noul=0.5)}
    assert not escalation.triggers("file.ticket", [felt], unsure)
    assert escalation.triggers("subscription.renew", [felt], unsure)
    # And never at low stakes, however flat.
    assert not escalation.triggers("agent.tick", [judged], unsure)


def test_every_question_set_declares_its_stakes() -> None:
    assert set(escalation.STAKES) == set(QUESTION_SETS)
    assert escalation.stakes("agent.tick") == "low"


def test_a_reply_is_read_into_jevs_own_types() -> None:
    asks = [_ask("x", "J", CHOICE), _ask("y", "P", NOUL), _ask("z", "J", SCORE)]
    text = (
        "```json\n"
        + json.dumps(
            {
                "x": {"a": 1, "b": 3, "c": 0},
                "y": {"yes": 0.2, "no": 0.8},
                "z": {"0": 0, "1": 0, "2": 0.5, "3": 0.5},
            }
        )
        + "\n```"
    )
    answers = escalation.parse(text, asks)
    x = answers["x"]
    assert isinstance(x, ChoiceAnswer) and x.choice == "b"
    assert x.probabilities == {"a": 0.25, "b": 0.75, "c": 0.0}
    y = answers["y"]
    assert isinstance(y, NoulAnswer) and y.noul == pytest.approx(0.2)
    z = answers["z"]
    assert isinstance(z, ScoreAnswer) and z.score == 2.0
    with pytest.raises(ValueError, match="no answer for"):
        escalation.parse(json.dumps({"x": {"a": 1}}), asks)
    with pytest.raises(ValueError, match="no probability mass"):
        escalation.parse(json.dumps({"x": {"a": 0, "b": 0, "c": 0}}), asks[:1])
    with pytest.raises(ValueError, match="not JSON"):
        escalation.parse("I would say b.", asks[:1])


def test_live_takes_a_judgement_and_mixes_a_propensity() -> None:
    judged, felt = _ask("x", "J", NOUL), _ask("y", "P", NOUL)
    jev, llm = NoulAnswer(noul=0.45), NoulAnswer(noul=0.95)
    assert escalation.applied(judged, jev, llm) == llm
    mixed = escalation.applied(felt, jev, llm)
    assert isinstance(mixed, NoulAnswer)
    assert mixed.noul == pytest.approx(0.70)


def test_the_request_mirrors_the_questions_and_is_keyed_by_what_is_sent() -> None:
    prepared = _prepared("close.signoff")
    request = escalation.request_for(prepared, ["if_not_ready"], FIRST)
    schema = request.response_schema
    assert schema is not None
    assert schema["required"] == ["if_not_ready"]
    body = json.loads(request.messages[1].content)
    assert set(body["questions"]) == {"if_not_ready"}
    assert body["situation"] == prepared.state
    assert escalation.request_key(request) != escalation.request_key(
        escalation.request_for(prepared, ["if_not_ready"], SECOND)
    )


# -- at the policy seam --------------------------------------------------------


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect(autocommit=True) as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


@pytest.fixture(autouse=True)
def no_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("constructed a real gateway")

    monkeypatch.setattr(jev_policy, "_Bridge", refuse)


def _prepared(kind: str) -> Prepared:
    return QUESTION_SETS[kind].prepare(_ctx(kind))


def _ctx(
    kind: str, person: str = "p", *, facts: dict[str, object] | None = None
) -> DecisionContext:
    return DecisionContext(
        person_id=person,
        role="r",
        decision_seq=0,
        sim_time=at(3, 10),
        kind=kind,
        facts=ASKING[kind] if facts is None else facts,
        traits=TRAITS,
    )


def _teach_jev(
    conn: Connection[DictRow], policy: JevPolicy, ctx: DecisionContext, **answers: Any
) -> None:
    """What Jev said about this situation, stored where a replay reads it."""

    request = policy._request(policy._prepare(ctx))
    key = call_key(DECISION_PIN, request.wire_bytes())
    conn.execute("DELETE FROM model_calls WHERE hash = %s", (key,))
    insert_call(
        conn,
        {
            "hash": key,
            "kind": ctx.kind,
            "model": DECISION_PIN,
            "request": json.loads(request.wire_bytes()),
            "wire": request.wire_bytes().decode(),
            "response": {"model": DECISION_PIN, "answers": answers},
        },
    )


class _Flash:
    """Stands where the gateway's bridge stands, for chat completions only."""

    def __init__(self, replies: dict[str, dict[str, Any] | Exception]) -> None:
        self.replies = replies
        self.asked: list[tuple[str, Purpose]] = []

    generative_models = (FIRST, SECOND)

    def complete(
        self,
        requests: Sequence[tuple[ChatRequest, Purpose]],
        *,
        parent: str | None = None,
        timeout: float = 180.0,
    ) -> list[ChatResponse | BaseException]:
        out: list[ChatResponse | BaseException] = []
        for request, purpose in requests:
            self.asked.append((request.model, purpose))
            reply = self.replies[request.model]
            if isinstance(reply, TimeoutError):
                raise reply  # what the bridge does when the round runs out
            if isinstance(reply, Exception):
                out.append(reply)
                continue
            out.append(
                ChatResponse(
                    model=request.model,
                    text=json.dumps(reply),
                    usage=Usage(input_tokens=400, output_tokens=60, cost_usd=0.0002),
                    latency_s=1.5,
                )
            )
        return out

    def fetch(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("Jev was asked live; its answer is stored")

    def close(self) -> None:
        return None


def _policy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: escalation.Mode,
    live: frozenset[str] = frozenset(),
    calls: RecorderMode = "record",
    flash: _Flash | None = None,
) -> JevPolicy:
    policy = JevPolicy(
        ROOT_SEED,
        Recorder(mode=calls),
        tier1=escalation.Config(mode=mode, live=live),
    )
    if flash is not None:
        monkeypatch.setattr(policy, "_live", lambda: flash)
    return policy


UNSURE = {
    "resolution": {
        "type": "choice",
        "choice": "stand_firm",
        "probabilities": {
            "stand_firm": 0.40,
            "discount": 0.35,
            "write_off": 0.20,
            "other": 0.05,
        },
    }
}
FLASH_SAYS = {
    "resolution": {"stand_firm": 0.1, "discount": 0.8, "write_off": 0.1, "other": 0}
}


@pytest.fixture(autouse=True)
def forget_tier1(conn: Connection[DictRow]) -> None:
    conn.execute("DELETE FROM model_calls WHERE kind = %s", (escalation.KIND,))


def test_shadow_keeps_both_answers_and_jev_decides(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    ctx = _ctx("dispute.resolution")
    _teach_jev(conn, policy, ctx, **UNSURE)

    made = policy.decide(ctx)
    assert made.chosen["resolution"] == "stand_firm"
    assert made.source == "jev"
    second = made.escalation
    assert second is not None
    assert second.mode == "shadow" and not second.sampled
    assert second.triggers == [
        {"ask": "resolution", "rule": "choice.confidence", "value": 0.4}
    ]
    assert second.llm["resolution"]["discount"] == pytest.approx(0.8)
    assert second.jev["resolution"]["stand_firm"] == pytest.approx(0.4)
    assert second.model == FIRST and not second.agrees
    # Measurement is `explore`: the first thing the budget ladder refuses.
    assert flash.asked == [(FIRST, "explore")]
    kept = conn.execute(
        "SELECT model, cost_usd FROM model_calls WHERE hash = %s",
        (second.call_hash,),
    ).fetchone()
    assert kept is not None and kept["model"] == FIRST


def test_live_acts_on_it_and_a_replay_reads_the_same_answer_back(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    live = frozenset({"dispute.resolution"})
    policy = _policy(monkeypatch, mode="live", live=live, flash=flash)
    ctx = _ctx("dispute.resolution")
    _teach_jev(conn, policy, ctx, **UNSURE)

    made = policy.decide(ctx)
    assert made.chosen["resolution"] == "discount"
    assert made.source == "llm"
    assert made.escalation is not None and made.escalation.mode == "live"
    assert flash.asked == [(FIRST, "gate")]

    replayed = _policy(monkeypatch, mode="live", live=live, calls="replay")
    again = replayed.decide(ctx)
    assert again.chosen == made.chosen
    assert again.escalation == made.escalation
    assert again.draws == made.draws


def test_a_replay_that_cannot_find_a_second_opinion(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx("dispute.resolution")
    shadow = _policy(monkeypatch, mode="shadow", calls="replay")
    _teach_jev(conn, shadow, ctx, **UNSURE)
    # Shadow is measurement: nothing to read back is no row, not a failure.
    made = shadow.decide(ctx)
    assert made.escalation is None and made.source == "jev"

    live = _policy(
        monkeypatch,
        mode="live",
        live=frozenset({"dispute.resolution"}),
        calls="replay",
    )
    with pytest.raises(ReplayMissError, match="tier-1"):
        live.decide(ctx)


def test_the_generative_order_is_walked_and_what_was_recorded_is_kept(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: TransportError("down"), SECOND: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    ctx = _ctx("dispute.resolution")
    _teach_jev(conn, policy, ctx, **UNSURE)

    made = policy.decide(ctx)
    assert made.escalation is not None and made.escalation.model == SECOND
    assert flash.asked == [(FIRST, "explore"), (SECOND, "explore")]

    # The first model is back. The answer the run already has is the one it
    # keeps: a rerun reads it rather than paying for a different one.
    firm = {"stand_firm": 1, "discount": 0, "write_off": 0, "other": 0}
    back = _Flash({FIRST: {"resolution": firm}})
    rerun = _policy(monkeypatch, mode="shadow", flash=back)
    again = rerun.decide(ctx)
    assert again.escalation == made.escalation
    assert back.asked == []


def test_an_unreadable_reply_moves_on_and_a_live_set_waits_when_none_answers(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx("dispute.resolution")
    garbled = _Flash({FIRST: {"verdict": "discount"}, SECOND: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=garbled)
    _teach_jev(conn, policy, ctx, **UNSURE)
    made = policy.decide(ctx)
    assert made.escalation is not None and made.escalation.model == SECOND

    conn.execute("DELETE FROM model_calls WHERE kind = %s", (escalation.KIND,))
    dead = _Flash({FIRST: TransportError("down"), SECOND: TransportError("down")})
    shadow = _policy(monkeypatch, mode="shadow", flash=dead)
    assert shadow.decide(ctx).escalation is None
    live = _policy(
        monkeypatch, mode="live", live=frozenset({"dispute.resolution"}), flash=dead
    )
    # A live set's answer is a decision: no model means the tick waits
    # (SIM-0002), never that Jev's answer is quietly used instead.
    with pytest.raises(TransportError):
        live.decide(ctx)


def test_a_slow_model_costs_shadow_a_row_and_a_live_set_its_tick(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx("dispute.resolution")
    slow = _Flash({FIRST: TimeoutError(), SECOND: FLASH_SAYS})
    shadow = _policy(monkeypatch, mode="shadow", flash=slow)
    _teach_jev(conn, shadow, ctx, **UNSURE)
    # Not retried as weather: the world does not wait on its own measurement.
    assert shadow.decide(ctx).escalation is None
    live = _policy(
        monkeypatch, mode="live", live=frozenset({"dispute.resolution"}), flash=slow
    )
    with pytest.raises(TimeoutError):
        live.decide(ctx)


def test_confident_and_low_stakes_answers_are_not_asked_again(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    person = next(
        f"p{n}"
        for n in range(100)
        if not escalation.sampled(ROOT_SEED, f"p{n}", 0, "dispute.resolution")
    )
    ctx = _ctx("dispute.resolution", person)
    sure = {
        "resolution": {
            "type": "choice",
            "choice": "discount",
            "probabilities": {
                "stand_firm": 0.05,
                "discount": 0.9,
                "write_off": 0.05,
                "other": 0.0,
            },
        }
    }
    _teach_jev(conn, policy, ctx, **sure)
    assert policy.decide(ctx).escalation is None
    assert flash.asked == []


def test_the_uniform_sample_asks_about_confident_answers_too(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    person = next(
        f"p{n}"
        for n in range(1000)
        if escalation.sampled(ROOT_SEED, f"p{n}", 0, "dispute.resolution")
    )
    ctx = _ctx("dispute.resolution", person)
    sure = {
        "resolution": {
            "type": "choice",
            "choice": "discount",
            "probabilities": {
                "stand_firm": 0.05,
                "discount": 0.9,
                "write_off": 0.05,
                "other": 0.0,
            },
        }
    }
    _teach_jev(conn, policy, ctx, **sure)
    made = policy.decide(ctx)
    assert made.escalation is not None
    assert made.escalation.sampled and made.escalation.triggers == []
    assert made.escalation.agrees


def test_a_propensity_escalated_live_samples_the_mixture(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: {"renew": {"yes": 0.9, "no": 0.1}}})
    policy = _policy(
        monkeypatch,
        mode="live",
        live=frozenset({"subscription.renew"}),
        flash=flash,
    )
    ctx = _ctx("subscription.renew")
    _teach_jev(conn, policy, ctx, renew={"type": "noul", "noul": 0.5})
    made = policy.decide(ctx)
    assert made.source == "llm"
    assert made.distributions["renew"]["yes"] == pytest.approx(0.7)


def test_no_room_left_today_means_no_second_opinion(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    ctx = _ctx("dispute.resolution")
    _teach_jev(conn, policy, ctx, **UNSURE)
    monkeypatch.setattr(
        escalation, "room", lambda conn, now: escalation.Room(any=0, acting=0)
    )
    assert policy.decide(ctx).escalation is None
    assert flash.asked == []


def test_off_asks_nothing(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="off", flash=flash)
    ctx = _ctx("dispute.resolution")
    _teach_jev(conn, policy, ctx, **UNSURE)
    assert policy.decide(ctx).escalation is None
    assert flash.asked == []


# -- in the world ----------------------------------------------------------------


class _Seconded(RulesPolicy):
    """The rules twin, with every chase decision "escalated" in shadow: enough
    to see what the engine keeps and what the room and the report make of it."""

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        made = super().decide_many(contexts)
        return [
            replace(
                decision,
                escalation=Escalated(
                    mode="shadow",
                    sampled=ctx.decision_seq % 2 == 0,
                    triggers=[],
                    asks=["pay"],
                    jev={"pay": {"yes": 0.5, "no": 0.5}},
                    llm={"pay": {"yes": 0.9, "no": 0.1}},
                    model=FIRST,
                    call_hash="0" * 64,
                    agrees=ctx.decision_seq % 3 != 0,
                ),
            )
            if ctx.kind == "payment.timing"
            else decision
            for ctx, decision in zip(contexts, made, strict=True)
        ]


@pytest.fixture(scope="module")
def world() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def test_the_engine_keeps_a_second_opinion_beside_its_decision_and_it_counts(
    world: Connection[DictRow],
) -> None:
    seed(world, root_seed=ROOT_SEED)
    engine = Engine(world, _Seconded(ROOT_SEED), root_seed=ROOT_SEED)
    advance(world, engine, until=at(4))
    world.commit()

    kept = world.execute(
        "SELECT e.question_set, e.sim_time, d.sim_time AS decided, e.applied "
        "FROM escalations e JOIN decisions d ON d.id = e.decision_id"
    ).fetchall()
    timings = world.execute(
        "SELECT count(*) AS n FROM decisions WHERE question_set = 'payment.timing'"
    ).fetchone()
    assert timings is not None and timings["n"] > 0
    assert len(kept) == timings["n"]
    assert all(row["sim_time"] == row["decided"] for row in kept)
    assert not any(row["applied"] for row in kept)

    # Today's room is five percent of yesterday, less what today used.
    day = max(int(row["sim_time"]) for row in kept)
    day -= day % DAY
    before = world.execute(
        "SELECT count(*) AS n FROM decisions WHERE sim_time >= %s AND sim_time < %s",
        (day - DAY, day),
    ).fetchone()
    used = sum(1 for row in kept if day <= int(row["sim_time"]) < day + DAY)
    assert before is not None
    allowance = max(escalation.DAILY_FLOOR, -(-int(before["n"]) // 20))
    # Shadow rows use the room; only rows that acted use the live room.
    assert escalation.room(world, day + 10 * 3600) == escalation.Room(
        any=max(0, allowance - used), acting=allowance
    )

    text = report.render(world)
    assert "payment.timing" in text
    assert "| set |" in text
    world.commit()

    # A reseed takes them with it.
    seed(world, root_seed=ROOT_SEED)
    left = world.execute("SELECT count(*) AS n FROM escalations").fetchone()
    assert left is not None and left["n"] == 0
    world.commit()


# -- what the review found (each would fail on the first version of tier 1) ------


def _two_unsure(conn: Connection[DictRow], policy: JevPolicy) -> list[DecisionContext]:
    """Two uncertain decisions in different situations, in one batch."""

    first = _ctx("dispute.resolution", "p1")
    second = _ctx(
        "dispute.resolution",
        "p2",
        facts={**ASKING["dispute.resolution"], "large": False},
    )
    for ctx in (first, second):
        _teach_jev(conn, policy, ctx, **UNSURE)
    return [first, second]


class _PerRequest(_Flash):
    """Replies by model and by whether the situation was a large bill."""

    def __init__(self, replies: dict[tuple[str, bool], dict[str, Any] | Exception]):
        super().__init__({})
        self.by = replies

    def complete(
        self,
        requests: Sequence[tuple[ChatRequest, Purpose]],
        *,
        parent: str | None = None,
        timeout: float = 180.0,
    ) -> list[ChatResponse | BaseException]:
        out: list[ChatResponse | BaseException] = []
        for request, purpose in requests:
            self.asked.append((request.model, purpose))
            large = "larger bills" in request.messages[1].content
            reply = self.by[(request.model, large)]
            if isinstance(reply, TimeoutError):
                raise reply
            if isinstance(reply, Exception):
                out.append(reply)
                continue
            out.append(
                ChatResponse(
                    model=request.model,
                    text=json.dumps(reply),
                    usage=Usage(cost_usd=0.0001),
                    latency_s=1.0,
                )
            )
        return out


def test_a_later_round_timing_out_keeps_what_an_earlier_round_found(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _PerRequest(
        {
            (FIRST, True): FLASH_SAYS,
            (FIRST, False): {"verdict": "garbled"},
            (SECOND, False): TimeoutError(),
        }
    )
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    contexts = _two_unsure(conn, policy)
    made = policy.decide_many(contexts)
    assert made[0].escalation is not None and made[0].escalation.model == FIRST
    assert made[1].escalation is None
    # And a replay of the same moment sees exactly that.
    again = _policy(monkeypatch, mode="shadow", calls="replay").decide_many(contexts)
    assert [d.escalation for d in again] == [d.escalation for d in made]


def test_nothing_is_paid_for_twice(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx("dispute.resolution")
    dead = _Flash({FIRST: TransportError("down"), SECOND: TransportError("down")})
    shadow = _policy(monkeypatch, mode="shadow", flash=dead)
    _teach_jev(conn, shadow, ctx, **UNSURE)
    assert shadow.decide(ctx).escalation is None
    assert len(dead.asked) == 2
    # The same situation again: both failures are on record for shadow.
    again = _Flash({FIRST: FLASH_SAYS, SECOND: FLASH_SAYS})
    assert (
        _policy(monkeypatch, mode="shadow", flash=again).decide(ctx).escalation is None
    )
    assert again.asked == []


def test_a_live_set_whose_every_reply_is_unreadable_keeps_jevs_answer(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx("dispute.resolution")
    live = frozenset({"dispute.resolution"})
    garbled = _Flash({FIRST: {"verdict": "x"}, SECOND: TransportError("down")})
    policy = _policy(monkeypatch, mode="live", live=live, flash=garbled)
    _teach_jev(conn, policy, ctx, **UNSURE)
    with pytest.raises(TransportError):
        policy.decide(ctx)  # the second model may yet answer: the tick waits

    # The retry asks only the model that has not answered. It garbles too:
    # every reply is on record and unreadable, so Jev's answer stands, and
    # stands the same way in a replay.
    retry = _Flash({FIRST: FLASH_SAYS, SECOND: {"verdict": "y"}})
    made = _policy(monkeypatch, mode="live", live=live, flash=retry).decide(ctx)
    assert retry.asked == [(SECOND, "gate")]
    assert made.source == "jev" and made.escalation is None
    replayed = _policy(monkeypatch, mode="live", live=live, calls="replay")
    assert replayed.decide(ctx).chosen == made.chosen


def test_the_sample_measures_and_never_acts(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    person = next(
        f"p{n}"
        for n in range(1000)
        if escalation.sampled(ROOT_SEED, f"p{n}", 0, "dispute.resolution")
    )
    ctx = _ctx("dispute.resolution", person)
    sure = {
        "resolution": {
            "type": "choice",
            "choice": "discount",
            "probabilities": {
                "stand_firm": 0.05,
                "discount": 0.9,
                "write_off": 0.05,
                "other": 0.0,
            },
        }
    }
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(
        monkeypatch, mode="live", live=frozenset({"dispute.resolution"}), flash=flash
    )
    _teach_jev(conn, policy, ctx, **sure)
    made = policy.decide(ctx)
    assert made.escalation is not None and made.escalation.mode == "shadow"
    assert made.source == "jev"
    assert flash.asked == [(FIRST, "explore")]


def test_a_batch_decides_as_the_same_decisions_one_at_a_time(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        escalation, "room", lambda conn, now: escalation.Room(any=1, acting=1)
    )
    flash = _Flash({FIRST: FLASH_SAYS})
    batch = _policy(monkeypatch, mode="shadow", flash=flash)
    contexts = _two_unsure(conn, batch)
    together = [d.escalation is not None for d in batch.decide_many(contexts)]
    single = _policy(monkeypatch, mode="shadow", flash=flash)
    apart = [single.decide(ctx).escalation is not None for ctx in contexts]
    assert together == apart == [True, False]
    # A new tick, or a retry of this one, starts with the room whole again.
    single.begin_tick(contexts[1].sim_time)
    assert single.decide(contexts[1]).escalation is not None


def test_the_same_situation_twice_in_a_batch_is_one_call(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    flash = _Flash({FIRST: FLASH_SAYS})
    policy = _policy(monkeypatch, mode="shadow", flash=flash)
    one, two = _ctx("dispute.resolution", "p1"), _ctx("dispute.resolution", "p2")
    _teach_jev(conn, policy, one, **UNSURE)
    made = policy.decide_many([one, two])
    assert all(d.escalation is not None for d in made)
    assert flash.asked == [(FIRST, "explore")]
