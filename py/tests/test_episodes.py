"""Episodes: rounds that can do what one shot could not (WORLD-0006).

The hypothesis under test is narrow and falsifiable. An episode is worth its
extra calls only if round two can do something round one could not, and only if
what it does reaches the economy. So these tests are in two halves:

* **mechanism**, driven by a scripted policy, where the acts are fixed and what
  is being checked is that the machinery folds them back correctly — a promise
  becomes an obligation, a mention becomes knowledge, knowledge of an outage
  becomes an earlier notice;
* **world**, run on the rules twin (null model N1) over enough sim-days for all
  three stakes to occur, where what is being checked are invariants — every
  episode ends, nothing is counted twice, nothing nests past one level, and the
  ledger still balances.

Neither half asserts a *direction* for the macro effect. Whether episodes make
invoices go out sooner is the experiment in `ops/episodes.md`, not an invariant,
and a test that demanded a sign would be tuning the world until it agreed.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.core.clock import DAY, TICK, SimTime, at
from jeve.core.orgs import ORGS
from jeve.decide.policy import Decision, DecisionContext, Policy, RulesPolicy, Source
from jeve.sim import advance, daemon
from jeve.world import episodes, space
from jeve.world.engine import Engine, Made, TickReport
from jeve.world.seed_world import ROOT_SEED, seed
from tests.test_world import event_log_hash, ledger_total
from tests.worldcache import build_once

CAFE = next(org.id for org in ORGS if org.social and org.kind == "cafe")
"""Where the district's meetings happen, from the roster (CORE-0012)."""

pytestmark = pytest.mark.timeout(900)

# Long enough for all three stakes. Subscription bills fall due on day 14, and
# a stake is live from two days before that, so an invoice episode is not even
# possible before day 12 — a shorter window would test two thirds of the design
# and quietly pass.
WORLD_DAYS = 16


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def run(conn: Connection[DictRow], *, days: int, episodes_on: bool) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(
            conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, episodes=episodes_on
        )
        advance(conn, engine, until=at(days))

    build_once(conn, f"episodes:{days}d:on={episodes_on}", build)


# -- a policy that says what the test needs said --------------------------------


class Scripted:
    """Answers `episode.round` from a script; everything else from the rules.

    A mechanism test should not depend on a propensity landing the right way —
    that would be a test of the rules twin's constants, and it would go quiet
    the first time somebody tuned one. The script says what was decided; the
    assertions are about what the world did with it.
    """

    source: Source = "rules"

    def __init__(self, root_seed: int, script: dict[str, list[dict[str, object]]]):
        self._rules = RulesPolicy(root_seed)
        self._script = script
        self._turn: dict[str, int] = {}

    def decide(self, ctx: DecisionContext) -> Decision:
        if ctx.kind != "episode.round":
            return self._rules.decide(ctx)
        lines = self._script.get(ctx.person_id)
        if not lines:
            return Decision(
                chosen={"act": "small_talk", "settled": True, "mood": 2},
                source=self.source,
            )
        index = min(self._turn.get(ctx.person_id, 0), len(lines) - 1)
        self._turn[ctx.person_id] = index + 1
        chosen = {"act": "small_talk", "settled": False, "mood": 2, **lines[index]}
        return Decision(chosen=chosen, source=self.source)

    def decide_many(self, contexts: Sequence[DecisionContext]) -> list[Decision]:
        return [self.decide(ctx) for ctx in contexts]


def stage(
    engine: Engine, conn: Connection[DictRow], ids: list[str], zone: str
) -> tuple[list[space.Agent], list[Made], dict[str, space.Agent]]:
    """Put these people in one room and have the first two fall into talk.

    `episodes.run` takes exactly what `space.run` hands it — the people present,
    their `agent.tick` decisions and a lookup — so a test can drive the real
    entry point rather than reaching past it.
    """

    for index, person in enumerate(ids):
        conn.execute(
            "UPDATE positions SET zone = %s, x = %s, y = %s WHERE person_id = %s",
            (zone, 30 + index, 17, person),
        )
    present = [agent for agent in space.load_agents(engine) if agent.id in ids]
    present.sort(key=lambda agent: ids.index(agent.id))
    made = [
        Made(
            id=index,
            chosen=(
                {"interact": True, "with": ids[1]}
                if index == 0
                else {"interact": False, "with": None}
            ),
            source="rules",
        )
        for index in range(len(present))
    ]
    return present, made, {agent.id: agent for agent in present}


def fresh(conn: Connection[DictRow], policy: Policy) -> tuple[Engine, TickReport]:
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, policy, root_seed=ROOT_SEED, episodes=True)
    conn.execute("UPDATE sim_meta SET sim_time = %s", (at(0, 12),))
    return engine, TickReport(tick_seq=1, sim_time=at(0, 12))


def outage(engine: Engine, report: TickReport, module: str = "invoicing") -> int:
    """Start a real incident, through the handler the world uses."""

    engine.schedule(
        report.sim_time, "incident.start", module, {"expected_minutes": 600}
    )
    engine._run_due(report)
    row = engine.conn.execute(
        "SELECT id FROM incidents WHERE module_id = %s AND ended_sim IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (module,),
    ).fetchone()
    assert row is not None
    return int(row["id"])


# -- the shape of a round --------------------------------------------------------


def test_everybody_can_always_walk_away() -> None:
    """Whatever their part in it, leaving is on the table.

    An episode that somebody cannot leave can only end by running out of
    rounds, and `exit_reason` stops distinguishing "they were done" from "we
    stopped asking". It is also the only act that makes the round cap a
    backstop rather than the mechanism.
    """

    from jeve.decide.questions import _ACTS_BY_ROLE

    assert set(_ACTS_BY_ROLE) == {"holder", "asker", "bystander"}
    for role, acts in _ACTS_BY_ROLE.items():
        assert "leave" in acts, role
    # Only the person who can settle it may promise, and only somebody who
    # cannot may press. Offering either to the wrong side puts mass on an
    # option the world would have to throw away.
    assert "promise" in _ACTS_BY_ROLE["holder"]
    assert "promise" not in _ACTS_BY_ROLE["asker"]
    assert "press" in _ACTS_BY_ROLE["asker"]
    assert "press" not in _ACTS_BY_ROLE["holder"]


# -- mechanism -------------------------------------------------------------------


def test_a_meeting_with_nothing_between_them_stays_a_one_shot_encounter(
    conn: Connection[DictRow],
) -> None:
    """No stake, no episode. Refining where the cheap model has nothing to say
    is the cost with none of the fidelity."""

    engine, report = fresh(conn, RulesPolicy(ROOT_SEED))
    # Two people from the same firm, nothing down, nothing owed, and neither
    # holding news the other lacks.
    conn.execute("DELETE FROM knowledge")
    present, made, by_id = stage(
        engine,
        conn,
        ["halloran.paralegal.11", "halloran.junior_associate.10"],
        CAFE,
    )
    consumed = episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, []
    )
    assert consumed == set()
    assert _count(conn, "SELECT count(*) AS n FROM episodes") == 0
    conn.rollback()


def test_an_episode_replaces_the_encounter_it_grew_from(
    conn: Connection[DictRow],
) -> None:
    """The same meeting must not be resolved at both resolutions.

    Double counting across levels is the oldest trap in multi-resolution
    modelling: the pair would escalate once as an episode and once again as a
    one-shot, and the outage would be cut twice for one conversation.
    """

    engine, report = fresh(conn, RulesPolicy(ROOT_SEED))
    outage(engine, report)
    ids = ["halloran.office_manager.12", "tallybird.support.6"]
    present, made, by_id = stage(engine, conn, ids, CAFE)
    consumed = episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )

    assert consumed == {frozenset(ids)}
    # `space` seeds its dedupe set with exactly this, so the one-shot path skips.
    space._encounters(engine, report, present, made, by_id, ["invoicing"], consumed)
    assert (
        _count(conn, "SELECT count(*) AS n FROM events WHERE kind = 'encounter'") == 0
    )
    conn.rollback()


def test_a_promise_needs_the_press_to_have_landed_first(
    conn: Connection[DictRow],
) -> None:
    """The whole hypothesis, as one assertion.

    Round two sees what round one did. A holder who is pressed can give their
    word; a holder asked cold, in a single shot, never sees the press at all.
    If this passes and the macro measurement still shows nothing, the finding is
    that the extra resolution does not matter — not that it was never there.
    """

    seen: list[dict[str, object]] = []

    class Watching(Scripted):
        def decide(self, ctx: DecisionContext) -> Decision:
            if ctx.kind == "episode.round":
                seen.append(dict(ctx.facts))
            return super().decide(ctx)

    policy = Watching(
        ROOT_SEED,
        {
            "halloran.office_manager.12": [{"act": "press"}, {"act": "ask"}],
            "tallybird.support.6": [{"act": "explain"}, {"act": "promise"}],
        },
    )
    engine, report = fresh(conn, policy)
    outage(engine, report)
    ids = ["halloran.office_manager.12", "tallybird.support.6"]
    present, made, by_id = stage(engine, conn, ids, CAFE)
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )

    first_round = [facts for facts in seen[:2]]
    later = [facts for facts in seen[2:]]
    assert all(not facts["pressed"] for facts in first_round), (
        "nobody can have been pressed before the first round ran"
    )
    assert any(facts["pressed"] for facts in later), (
        "the second round must see the press the first one made"
    )
    conn.rollback()


def test_word_of_mouth_reaches_a_ticket(conn: Connection[DictRow]) -> None:
    """Being told the software is down makes you notice it now.

    This is the channel that carries an episode to money. Someone who hears
    about the outage over coffee gets a notice at once instead of whenever their
    own draw was going to arrive, and a notice is what the ticket flow reads.
    """

    teller = "halloran.office_manager.12"
    hearer = "halloran.junior_associate.10"
    policy = Scripted(
        ROOT_SEED,
        {
            teller: [{"act": "explain", "mention": True}],
            hearer: [{"act": "ask"}],
        },
    )
    engine, report = fresh(conn, policy)
    incident = outage(engine, report)

    fact = memory.Fact.outage(incident, "invoicing")
    memory.learn(conn, teller, fact.id, sim_time=report.sim_time)
    conn.execute(
        "DELETE FROM knowledge WHERE person_id = %s AND fact_id = %s", (hearer, fact.id)
    )
    # Their own notice is hours away; hearing about it should overtake it.
    conn.execute(
        "INSERT INTO outage_notices (incident_id, person_id, notice_sim) "
        "VALUES (%s,%s,%s) ON CONFLICT (incident_id, person_id) "
        "DO UPDATE SET notice_sim = EXCLUDED.notice_sim",
        (incident, hearer, report.sim_time + 6 * 3600),
    )

    present, made, by_id = stage(engine, conn, [teller, hearer], CAFE)
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )

    assert fact.id in memory.facts_known_by(conn, hearer)
    assert memory.facts_known_by(conn, hearer)[fact.id] == 1, "one hop from the teller"
    notice = conn.execute(
        "SELECT notice_sim FROM outage_notices WHERE incident_id = %s "
        "AND person_id = %s",
        (incident, hearer),
    ).fetchone()
    assert notice is not None and int(notice["notice_sim"]) == report.sim_time
    heard = conn.execute(
        "SELECT causes FROM events WHERE kind = 'outage.heard' AND actor_id = %s",
        (hearer,),
    ).fetchone()
    assert heard is not None, "hearing about an outage is an event, or it is invisible"
    closed = conn.execute(
        "SELECT seq FROM events WHERE kind = 'episode.closed' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert closed is not None and int(closed["seq"]) in list(heard["causes"]), (
        "the chain from a conversation to a notice has to be walkable"
    )
    conn.rollback()


def test_a_promise_is_recorded_and_raises_the_pressure_on_the_bill(
    conn: Connection[DictRow],
) -> None:
    """A promise is not prose and it is not money: it is an obligation.

    Money never moves because somebody said it would — the referee is still
    code. What changes is the state the payer's next decision is taken against,
    and both policies have to see it or the rules twin stops being a control.
    """

    payer = "thirdrail.owner.18"
    creditor = "ledgerline.client_admin.17"
    policy = Scripted(
        ROOT_SEED,
        {payer: [{"act": "promise", "settled": True}], creditor: [{"act": "press"}]},
    )
    engine, report = fresh(conn, policy)
    bill = conn.execute(
        "SELECT id FROM invoices WHERE from_org_id = 'ledgerline' "
        "AND to_org_id = 'thirdrail' AND paid_sim IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    assert bill is not None, "the seed owes Ledgerline from the cafe"
    conn.execute(
        "UPDATE invoices SET due_sim = %s WHERE id = %s", (report.sim_time, bill["id"])
    )

    present, made, by_id = stage(engine, conn, [payer, creditor], CAFE)
    episodes.run(engine, report, SimTime(report.sim_time), present, made, by_id, [])

    promise = memory.open_commitment(conn, int(bill["id"]))
    assert promise is not None and promise.from_person_id == payer
    assert promise.due_sim == report.sim_time + episodes.PROMISE_HORIZON
    assert (
        _count(conn, "SELECT count(*) AS n FROM events WHERE kind = 'promise.made'")
        == 1
    )
    # And the payer's next decision is taken against a different world.
    assert (
        _count(
            conn,
            "SELECT count(*) AS n FROM scheduled WHERE kind = 'commitment.due'",
        )
        == 1
    )
    conn.rollback()


def test_a_promise_is_scored_either_way(conn: Connection[DictRow]) -> None:
    """Paying keeps it; the promised day passing unpaid breaks it.

    A promise nobody ever scores is decoration, and a broken one has to be
    distinguishable from one that was never made.
    """

    engine, report = fresh(conn, RulesPolicy(ROOT_SEED))
    bill = conn.execute(
        "SELECT id FROM invoices WHERE paid_sim IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    assert bill is not None
    invoice_id = int(bill["id"])
    seq = engine.emit(report, "episode.closed", payload={})
    conn.execute(
        "INSERT INTO episodes (id, zone, depth, stake, stake_ref, opened_sim, "
        "opened_seq) VALUES (1, 'cafe', 0, 'invoice', %s, %s, %s)",
        (f"invoice:{invoice_id}", report.sim_time, seq),
    )
    memory.promise(
        conn,
        episode_id=1,
        from_person_id="thirdrail.owner.18",
        to_person_id="ledgerline.client_admin.17",
        invoice_id=invoice_id,
        sim_time=report.sim_time,
        seq=seq,
        due_sim=report.sim_time + DAY,
    )

    episodes.commitment_due(engine, report, "1", {"invoice": invoice_id})
    row = conn.execute(
        "SELECT kept FROM commitments WHERE invoice_id = %s", (invoice_id,)
    ).fetchone()
    assert row is not None and row["kept"] is False
    assert (
        _count(conn, "SELECT count(*) AS n FROM events WHERE kind = 'promise.broken'")
        == 1
    )

    # And the other way: paying settles it as kept.
    memory.promise(
        conn,
        episode_id=1,
        from_person_id="thirdrail.owner.18",
        to_person_id="ledgerline.client_admin.17",
        invoice_id=invoice_id,
        sim_time=report.sim_time,
        seq=seq,
        due_sim=report.sim_time + DAY,
    )
    memory.close_commitments_for(
        conn, invoice_id, sim_time=report.sim_time + 100, kept=True
    )
    assert memory.open_commitment(conn, invoice_id) is None
    conn.rollback()


def test_an_episode_can_escalate_an_outage_and_still_only_once(
    conn: Connection[DictRow],
) -> None:
    """The consequence a meeting has always had, reached from the other arm."""

    asker = "halloran.office_manager.12"
    vendor = "tallybird.support.6"
    policy = Scripted(
        ROOT_SEED, {asker: [{"act": "press"}], vendor: [{"act": "explain"}]}
    )
    engine, report = fresh(conn, policy)
    outage(engine, report)
    present, made, by_id = stage(engine, conn, [asker, vendor], CAFE)
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )

    escalations = conn.execute(
        "SELECT payload->>'decided_by' AS by, causes FROM events "
        "WHERE kind = 'ticket.escalated'"
    ).fetchall()
    assert len(escalations) == 1
    assert escalations[0]["by"] == "episode"

    # A second conversation about the same incident changes nothing: the
    # rule is once per incident however many people complain.
    conn.execute("DELETE FROM episode_participants")
    conn.execute("DELETE FROM episodes")
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )
    assert (
        _count(
            conn,
            "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated'",
        )
        == 1
    )
    conn.rollback()


def test_the_vendor_cannot_escalate_to_itself(conn: Connection[DictRow]) -> None:
    """Tallybird's staff know about every outage and are stuck on none. Before
    episodes ran in every world, a second one in the room counted as somebody
    affected and could press a colleague — which `test_space` caught the first
    time the shipped world ran them."""

    engineer = "tallybird.engineer.2"
    vendor = "tallybird.support.6"
    policy = Scripted(
        ROOT_SEED, {engineer: [{"act": "press"}], vendor: [{"act": "promise"}]}
    )
    engine, report = fresh(conn, policy)
    outage(engine, report)
    present, made, by_id = stage(engine, conn, [engineer, vendor], CAFE)
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )

    assert (
        _count(conn, "SELECT count(*) AS n FROM episodes WHERE stake = 'outage'") == 0
    )
    assert (
        _count(conn, "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated'")
        == 0
    )
    conn.rollback()


def test_nobody_is_pulled_into_two_conversations_at_once(
    conn: Connection[DictRow],
) -> None:
    """A cooldown, because a group that enjoys each other's company would
    otherwise hold one conversation per tick for ever."""

    engine, report = fresh(conn, RulesPolicy(ROOT_SEED))
    outage(engine, report)
    ids = ["halloran.office_manager.12", "tallybird.support.6"]
    present, made, by_id = stage(engine, conn, ids, CAFE)
    episodes.run(
        engine, report, SimTime(report.sim_time), present, made, by_id, ["invoicing"]
    )
    first = _count(conn, "SELECT count(*) AS n FROM episodes")
    assert first == 1

    later = TickReport(tick_seq=2, sim_time=report.sim_time + TICK)
    episodes.run(
        engine, later, SimTime(later.sim_time), present, made, by_id, ["invoicing"]
    )
    assert _count(conn, "SELECT count(*) AS n FROM episodes") == first, (
        "the same people met again one tick later and should have been refused"
    )
    conn.rollback()


def test_the_seeded_fact_starts_in_exactly_one_head(
    conn: Connection[DictRow],
) -> None:
    """The diffusion measure means something only because nobody else began
    with it (the scenario's behaviour #6)."""

    seed(conn, root_seed=ROOT_SEED)
    holders = memory.holders_of(conn, memory.Fact.price_rise("tallybird").id)
    assert holders == ["tallybird.engineer.2"]
    conn.commit()


# -- the world -------------------------------------------------------------------


def test_every_episode_ends_and_says_how(conn: Connection[DictRow]) -> None:
    """Settled, emptied, or out of rounds. An episode with no exit reason is one
    that is still running when the tick that spawned it has committed."""

    run(conn, days=WORLD_DAYS, episodes_on=True)
    rows = conn.execute(
        "SELECT exit_reason, count(*) AS n, max(rounds) AS longest FROM episodes "
        "GROUP BY exit_reason ORDER BY exit_reason"
    ).fetchall()
    assert rows, "no episode ran at all over the whole window"
    unfinished = _count(
        conn, "SELECT count(*) AS n FROM episodes WHERE closed_sim IS NULL"
    )
    assert unfinished == 0
    for row in rows:
        assert row["exit_reason"] in ("settled", "emptied", "rounds")
        assert int(row["longest"]) <= episodes.MAX_ROUNDS
    # All three ways out are reachable, or one of them is dead code.
    assert {str(row["exit_reason"]) for row in rows} == {"settled", "emptied", "rounds"}


def test_every_stake_a_room_can_hold_actually_occurs(
    conn: Connection[DictRow],
) -> None:
    """Three reasons to give a meeting rounds, and all three have to happen or
    the design carries a branch nothing exercises."""

    run(conn, days=WORLD_DAYS, episodes_on=True)
    rows = conn.execute("SELECT DISTINCT stake FROM episodes ORDER BY stake").fetchall()
    assert {str(row["stake"]) for row in rows} == {"invoice", "news", "outage"}


def test_a_side_conversation_never_has_a_side_conversation(
    conn: Connection[DictRow],
) -> None:
    """Depth is capped at one, in code and in the schema.

    Unbounded nesting is what the multi-resolution literature calls chain
    disaggregation: one refinement forces its neighbours to refine, and the run
    stops being a simulation and becomes a fan-out.
    """

    run(conn, days=WORLD_DAYS, episodes_on=True)
    deepest = _count(conn, "SELECT COALESCE(max(depth), 0) AS n FROM episodes")
    assert deepest <= episodes.MAX_DEPTH
    assert _count(conn, "SELECT count(*) AS n FROM episodes WHERE depth = 1") > 0, (
        "a side conversation never happened, so the recursion is untested"
    )
    orphans = _count(
        conn,
        "SELECT count(*) AS n FROM episodes c "
        "LEFT JOIN episodes p ON p.id = c.parent_id "
        "WHERE c.depth = 1 AND (p.id IS NULL OR p.depth <> 0)",
    )
    assert orphans == 0


def test_the_day_has_a_ceiling_on_conversations(conn: Connection[DictRow]) -> None:
    """Spend is a decision, not a surprise. Episodes are the expensive arm, and
    a busy Tuesday must not be able to cost an arbitrary amount."""

    run(conn, days=WORLD_DAYS, episodes_on=True)
    rows = conn.execute(
        "SELECT opened_sim / %s AS day, count(*) AS n FROM episodes "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
        (DAY,),
    ).fetchall()
    assert rows and int(rows[0]["n"]) <= episodes.PER_DAY


def test_a_conversation_costs_the_time_it_takes(conn: Connection[DictRow]) -> None:
    """Somebody in a conversation is not also at their desk in the same fifteen
    minutes. A world where talking is free makes talking strictly dominant."""

    run(conn, days=WORLD_DAYS, episodes_on=True)
    clash = conn.execute(
        """
        SELECT count(*) AS n
        FROM events e
        JOIN episode_participants p ON p.person_id = e.actor_id
        JOIN episodes ep ON ep.id = p.episode_id
        WHERE e.kind IN ('ticket.triaged', 'ticket.answered', 'invoice.chased')
          AND e.sim_time = ep.opened_sim
        """
    ).fetchone()
    assert clash is not None and int(clash["n"]) == 0


def test_the_books_still_balance_with_episodes_on(
    conn: Connection[DictRow],
) -> None:
    """Nothing an episode does may move money. A promise is an obligation; the
    referee that pays it is still code."""

    run(conn, days=WORLD_DAYS, episodes_on=True)
    assert ledger_total(conn) == 0
    dangling = _count(
        conn,
        "SELECT count(*) AS n FROM commitments c LEFT JOIN episodes e "
        "ON e.id = c.episode_id WHERE e.id IS NULL",
    )
    assert dangling == 0


def test_knowledge_only_ever_travels_from_somebody_who_had_it(
    conn: Connection[DictRow],
) -> None:
    """Diffusion, checked as a graph rather than as a count.

    Every second-hand holder must name a teller who held it first, and no more
    recently than they did. Without this the share of the town that "knows"
    could rise on its own, which would make the measure meaningless.
    """

    run(conn, days=WORLD_DAYS, episodes_on=True)
    assert _count(conn, "SELECT count(*) AS n FROM knowledge WHERE hops > 0") > 0
    impossible = _count(
        conn,
        """
        SELECT count(*) AS n
        FROM knowledge k JOIN knowledge teller
          ON teller.person_id = k.from_person_id AND teller.fact_id = k.fact_id
        WHERE k.hops > 0
          AND (teller.learned_sim > k.learned_sim OR teller.hops <> k.hops - 1)
        """,
    )
    assert impossible == 0
    missing = _count(
        conn,
        "SELECT count(*) AS n FROM knowledge k LEFT JOIN knowledge t "
        "ON t.person_id = k.from_person_id AND t.fact_id = k.fact_id "
        "WHERE k.hops > 0 AND t.person_id IS NULL",
    )
    assert missing == 0


def test_the_api_serves_an_episode_against_its_contract(
    conn: Connection[DictRow],
) -> None:
    """A conversation a reader can open, and no prose in it.

    An encounter has a dialogue endpoint because one exchange reads as a line
    or two. An episode's record *is* the acts: what a reader wants is who was
    there, what each of them did, and what it changed — which is `led_to`,
    followed through `causes` exactly as the timeline does.
    """

    from fastapi.testclient import TestClient

    from jeve.api import contracts
    from jeve.api.app import app

    run(conn, days=WORLD_DAYS, episodes_on=True)
    conn.commit()

    with TestClient(app) as client:
        page = contracts.EpisodePage.model_validate(client.get("/episodes").json())
        assert page.episodes, "the world held episodes but the API served none"

        detail = contracts.Episode.model_validate(
            client.get(f"/episodes/{page.episodes[0].id}").json()
        )
        assert detail.rounds >= 1
        assert len(detail.participants) >= 2
        assert len(detail.round_log) == detail.rounds
        # Seats are a total order, so a replay speaks in the order the live run
        # did; iterating a set would not.
        seats = [person.seat for person in detail.participants]
        assert seats == sorted(seats) == list(range(len(seats)))

        assert client.get("/episodes/999999").status_code == 404

        # At least one episode in the window reached something, and the reader
        # can see what: an escalation, a fact passed on, or a promise.
        reached = [
            contracts.Episode.model_validate(
                client.get(f"/episodes/{episode.id}").json()
            )
            for episode in page.episodes
        ]
        assert any(episode.led_to for episode in reached), (
            "no episode on the first page caused anything a reader could follow"
        )


def test_switching_episodes_on_changes_the_world(conn: Connection[DictRow]) -> None:
    """The A/B, stated as an invariant rather than as a direction.

    Same seed, same people, same routes: the only difference is whether a
    meeting with a stake gets rounds. If the log came out identical, episodes
    would be an expensive way to produce the one-shot encounter. Which *way*
    the billing timeline moves is a measurement, not an invariant, and it lives
    in `ops/episodes.md` — a test that demanded a sign would be tuning.
    """

    run(conn, days=WORLD_DAYS, episodes_on=True)
    with_episodes = event_log_hash(conn)
    channels = {
        kind: _count(conn, "SELECT count(*) AS n FROM events WHERE kind = %s", (kind,))
        for kind in ("episode.closed", "fact.passed", "outage.heard", "promise.made")
    }
    by_episode = _count(
        conn,
        "SELECT count(*) AS n FROM events WHERE kind = 'ticket.escalated' "
        "AND payload->>'decided_by' = 'episode'",
    )

    run(conn, days=WORLD_DAYS, episodes_on=False)
    assert event_log_hash(conn) != with_episodes
    assert _count(conn, "SELECT count(*) AS n FROM episodes") == 0

    assert all(count > 0 for count in channels.values()), (
        f"a fold-back channel never fired: {channels}"
    )
    assert by_episode > 0, "no episode ever reached the outage it was about"


# -- the world that ships (WORLD-0007) ---------------------------------------------

# The command a deploy runs: a policy and a clock, and nothing about episodes.
DAEMON = ["--policy", "rules", "--day-minutes", "0"]


def test_the_shipped_world_runs_episodes_with_no_switch(
    conn: Connection[DictRow],
) -> None:
    """Driven through `daemon.main`, so a switch reintroduced anywhere between the
    entry point and the engine shows up here as a world without episodes."""

    _hand_the_world_to_the_daemon(conn)
    with pytest.raises(SystemExit):
        daemon.main(["--episodes", "--until-day", "1", *DAEMON])
    assert daemon.main(["--seed-world", "--until-day", "3", *DAEMON]) == 0

    with db.connect(autocommit=True) as watch:
        closed = _count(
            watch, "SELECT count(*) AS n FROM events WHERE kind = 'episode.closed'"
        )
        assert closed > 0, "the daemon ran three days and no meeting got rounds"
        assert ledger_total(watch) == 0


def test_a_world_begun_before_episodes_carries_on_with_them(
    conn: Connection[DictRow],
) -> None:
    """The deploy that ships this. A world has run for days on code that had no
    episodes, and its database has never seen migration 0009; the daemon is
    restarted on the new code. It migrates, carries on with episodes — through an
    outage that began before facts existed — and the books still balance.

    The old world is reproduced, not approximated: an engine with episodes off
    writes the same event log as the code before them (checked against that
    commit when WORLD-0007 was written), and dropping 0009's tables returns the
    schema to what that code had.
    """

    conn.commit()
    seed(conn, root_seed=ROOT_SEED)
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, episodes=False)
    # Down before the switch and still down after it, so the new code has to end
    # an incident whose outage it never recorded as a fact.
    engine.schedule(
        at(2, 14), "incident.start", "invoicing", {"expected_minutes": 2000}
    )
    advance(conn, engine, until=at(3))
    conn.execute(
        "DROP TABLE commitments, episode_participants, episodes, knowledge, facts "
        "CASCADE"
    )
    conn.execute("DELETE FROM schema_migrations WHERE name = '0009_episodes.sql'")
    _hand_the_world_to_the_daemon(conn)

    assert daemon.main(["--until-day", "6", *DAEMON]) == 0

    with db.connect(autocommit=True) as watch:
        assert "0009_episodes.sql" in db.applied(watch)
        incident = watch.execute(
            "SELECT id, ended_sim FROM incidents WHERE module_id = 'invoicing' "
            "AND started_sim < %s ORDER BY started_sim DESC LIMIT 1",
            (at(3),),
        ).fetchone()
        assert incident is not None and incident["ended_sim"] is not None
        # Its news was written down when the new code took over, and retired
        # when the new code ended it.
        fact = watch.execute(
            "SELECT stale_sim FROM facts WHERE incident_id = %s", (incident["id"],)
        ).fetchone()
        assert fact is not None and fact["stale_sim"] == incident["ended_sim"]
        after = _count(
            watch,
            "SELECT count(*) AS n FROM episodes WHERE opened_sim >= %s",
            (at(3),),
        )
        assert after > 0, "the restarted world never gave a meeting rounds"
        unfinished = _count(
            watch, "SELECT count(*) AS n FROM episodes WHERE closed_sim IS NULL"
        )
        assert unfinished == 0
        assert ledger_total(watch) == 0
        known = _count(watch, "SELECT count(*) AS n FROM knowledge")

    # Every incident now has its fact, so starting again writes nothing: a
    # restart of a world this code wrote is not an upgrade.
    Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
    assert _count(conn, "SELECT count(*) AS n FROM knowledge") == known


# -- helpers ---------------------------------------------------------------------


def _hand_the_world_to_the_daemon(conn: Connection[DictRow]) -> None:
    """`seed` took the writer lock on this connection and a session keeps it until
    it closes, so an in-process daemon would refuse to start (SIM-0001)."""

    conn.commit()
    conn.execute("SELECT pg_advisory_unlock_all()")
    conn.commit()


def _count(
    conn: Connection[DictRow], query: str, params: tuple[object, ...] = ()
) -> int:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type, unused-ignore]
    assert row is not None
    return int(next(iter(row.values())) or 0)
