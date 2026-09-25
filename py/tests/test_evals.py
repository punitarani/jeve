"""The eval harness (EVAL-0001): every instrument is seen to work, and to fail.

A measure that cannot come out differently is not a measure (workbench L14).
So: the same world twice has the same digest and a changed one does not; a
band says ABSENT when the world cannot answer and FAIL outside it; each planted
defect changes the account in exactly the way it claims; a verdict counts both
orders; and the judge reads the cache without ever opening a gateway unless
told to. None of this needs a key.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, at
from jeve.decide.policy import DecisionContext, RulesPolicy
from jeve.decide.recorder import insert_call
from jeve.evals import casts, judge, report, stats, transcripts
from jeve.evals.metrics import measure
from jeve.evals.priors import BY_MEASURE, Prior
from jeve.sim import advance
from jeve.world.engine import Engine
from jeve.world.seed_world import ROOT_SEED, seed

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def conn() -> Iterator[Connection[DictRow]]:
    try:
        with db.connect() as connection:
            db.migrate(connection)
            connection.commit()
            yield connection
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")


def _world(conn: Connection[DictRow], root: int, days: int) -> str:
    seed(conn, root_seed=root)
    advance(conn, Engine(conn, RulesPolicy(root), root_seed=root), until=days * DAY)
    conn.commit()
    return measure(conn).digest


# -- a world, measured -------------------------------------------------------------


def test_a_world_is_measured_whole_and_the_same_world_twice_is_one_digest(
    conn: Connection[DictRow],
) -> None:
    first = _world(conn, ROOT_SEED, 3)
    m = measure(conn)
    assert m.days == 3
    assert m.checks_failed == [] and m.values["invariants_failed"] == 0.0
    for name in (*report.PLAUSIBILITY, *report.DEPTH, *report.COST):
        assert name in m.values, name
    # Rules decide everything, and it costs nothing.
    assert m.values["model_share"] == 0.0 and m.values["cost_per_day_usd"] == 0.0
    assert 0.0 <= (m.values["invoice_late_share"] or 0.0) <= 1.0

    # The A/A test: the same seed again is the same world, event for event...
    assert _world(conn, ROOT_SEED, 3) == first
    # ...and another seed is not, so the digest can tell worlds apart.
    assert _world(conn, ROOT_SEED + 1, 3) != first


# -- bands --------------------------------------------------------------------------


def test_a_band_passes_fails_and_says_when_it_cannot_tell() -> None:
    band = Prior("x", 1.0, 2.0, "u", "s", "n", min_days=28)
    assert band.verdict(1.5, 30) == "PASS"
    assert band.verdict(2.5, 30) == "FAIL"
    assert band.verdict(None, 30) == "ABSENT"
    # A week of zero cancellations is not a pass: it is nothing.
    assert band.verdict(1.5, 7) == "ABSENT"
    for prior in BY_MEASURE.values():
        assert prior.low < prior.high and prior.source, prior.measure


# -- effect sizes ----------------------------------------------------------------------


def test_the_scorecard_says_better_only_where_it_was_written_down() -> None:
    # A banded measure is scored by its distance from the band: into the band
    # is better, whichever side it came from.
    assert report.band_distance("invoice_late_share", 0.45) == 0.0
    assert report.band_distance("invoice_late_share", 0.15) == pytest.approx(0.5)
    late = ([0.13, 0.14, 0.15], [0.36, 0.34, 0.41])
    assert report.verdict("invoice_late_share", *late) == "better"
    assert report.verdict("invoice_late_share", late[1], late[0]) == "worse"
    # Lower is better for stalls, higher for settling; a noisy change is neither.
    stalls = ([0.06, 0.08, 0.05], [0.01, 0.012, 0.009])
    assert report.verdict("episode_stalled_share", *stalls) == "better"
    assert report.verdict("episode_settled_share", *stalls) == "worse"
    assert (
        report.verdict("episode_settled_share", [0.8, 0.9, 0.7], [0.9, 0.7, 0.8]) == ""
    )
    # Unscored: more entropy is not plainly a better town.
    assert report.verdict("action_entropy", [0.7, 0.7, 0.7], [0.8, 0.8, 0.8]) == ""


def test_a_contrast_is_paired_by_seed_and_its_interval_can_exclude_zero() -> None:
    same = stats.paired([1.0, 2.0, 3.0], [1.1, 2.1, 3.1])
    assert same.delta == pytest.approx(0.1)
    assert same.clear and same.low is not None and same.low > 0
    noisy = stats.paired([1.0, 2.0, 3.0], [1.5, 1.5, 3.0])
    assert not noisy.clear
    # A seed where either side cannot answer is dropped, not counted as zero.
    assert stats.paired([None, 1.0], [5.0, 2.0]).n == 1
    assert stats.summary([None, None]).mean is None
    low, high = stats.proportion_interval(9, 10) or (0.0, 0.0)
    assert low < 0.9 < high <= 1.0


# -- planted defects ------------------------------------------------------------------


def _record() -> transcripts.Record:
    people = (
        transcripts.Person("a", "Ann Vendor", "account_manager", "tallybird", {}),
        transcripts.Person("b", "Bo Client", "paralegal", "halloran", {}),
    )
    rounds = (
        (
            transcripts.Act("a", "explain", 2, False),
            transcripts.Act("b", "press", 0, False),
        ),
        (
            transcripts.Act("a", "promise", 2, False),
            transcripts.Act("b", "leave", 1, False),
        ),
    )
    return transcripts.Record(
        episode_id=1,
        zone="cafe",
        when=at(2, 12, 30),
        stake="outage",
        matter="Tallybird Software's invoicing feature has been down for 40 minutes.",
        holder_orgs=frozenset({"tallybird"}),
        holders=frozenset(),
        people=people,
        rounds=rounds,
        ending="settled",
        effects=("The outage was escalated to the software company's engineers.",),
    )


def test_each_defect_breaks_the_account_in_the_way_it_says() -> None:
    clean = _record()
    text = transcripts.render(clean)
    assert "Wednesday 12:30" in text and "Bo Client pushes the software" in text
    rng = random.Random(0)

    wrong = transcripts.plant(clean, "wrong_actor", rng)
    assert wrong is not None
    # Only the customer can be made to answer for the vendor's outage.
    said = transcripts.render(wrong)
    assert "Bo Client gives their word that it will be fixed" in said

    loop = transcripts.plant(clean, "loop", rng)
    assert loop is not None and len(loop.rounds) == 5
    assert len({acts for acts in loop.rounds}) == 1 and loop.ending == "settled"

    phantom = transcripts.plant(clean, "phantom_effect", rng)
    assert phantom is not None
    assert all(a.act == "small_talk" for acts in phantom.rounds for a in acts)
    assert phantom.effects  # something happened that nothing caused

    shut = transcripts.plant(clean, "closed_hours", rng)
    assert shut is not None and "Sunday 03:40" in transcripts.render(shut)
    # Everything the defect did not touch is word for word the same.
    assert transcripts.render(shut).split("\n")[1:] == text.split("\n")[1:]

    assert transcripts.plant(replace(clean, rounds=()), "loop", rng) is None


def test_padding_adds_one_unremarkable_exchange_and_nothing_else() -> None:
    clean = _record()
    longer = transcripts.padded(clean)
    assert longer is not None and len(longer.rounds) == 3
    # Inserted before the last round: the ending still follows what ended it.
    assert longer.rounds[0] == clean.rounds[0] and longer.rounds[2] == clean.rounds[1]
    # The vendor explains its own outage; the customer asks about it.
    assert [(a.person, a.act) for a in longer.rounds[1]] == [
        ("a", "explain"),
        ("b", "ask"),
    ]
    assert longer.effects == clean.effects and longer.ending == clean.ending
    assert transcripts.padded(replace(clean, rounds=())) is None


def test_arms_are_paired_only_on_accounts_of_the_same_shape() -> None:
    clean = _record()
    short = replace(clean, rounds=clean.rounds[:1])
    news = replace(clean, stake="news")
    three = replace(
        clean,
        people=(
            *clean.people,
            transcripts.Person("c", "Cy", "barista", "third_rail", {}),
        ),
    )
    a = [replace(r, episode_id=i) for i, r in enumerate([clean, short, news, three])]
    b = [replace(r, episode_id=10 + i) for i, r in enumerate([clean, clean, short])]
    pairs = transcripts.matched(a, b, 10, random.Random(1))
    assert all(transcripts.shape(x) == transcripts.shape(y) for x, y in pairs)
    # One two-round and one one-round pair: news and the three-person episode
    # have no partner, and each episode is used once.
    assert sorted(len(x.rounds) for x, _ in pairs) == [1, 2]
    assert len({y.episode_id for _, y in pairs}) == len(pairs)
    assert len(transcripts.matched(a, b, 1, random.Random(1))) == 1


def _moment(role: str) -> DecisionContext:
    return DecisionContext(
        person_id="halloran.paralegal.11",
        role="paralegal",
        sim_time=at(2, 12, 30),
        kind=casts.KIND,
        facts={"org": "halloran", "here": "cafe", "stake": "outage",
               "role_in_stake": role, "present": []},
        traits={"vocality": 0.5, "sociability": 0.5},
    )  # fmt: skip


def test_a_planted_cast_differs_only_in_what_the_person_did() -> None:
    moments = [("asker", _moment("asker")), ("holder", _moment("holder"))]
    pairs = casts.planted(moments, 1, random.Random(0))
    # The one who could act is never planted: what they ought to do is not plain.
    assert {p.id.split(":")[1] for p in pairs} == {"asker"}
    by = {p.label: p for p in pairs}
    assert set(by) == {"flattened", "swapped", "identical"}
    clean = by["swapped"].right.split("\n")
    did = [line for line in clean if line.startswith("What they did")]
    assert did == [
        "What they did: pushes the software company to fix it now.",
        "What they did: breaks off and heads back to work.",
    ]
    for label in ("flattened", "swapped"):
        broken = by[label].left.split("\n")
        changed = [a for a, b in zip(broken, clean, strict=True) if a != b]
        assert changed and all(c.startswith("What they did") for c in changed)
    flat = [x for x in by["flattened"].left.split("\n") if x.startswith("What they")]
    assert len(set(flat)) == 1
    assert by["identical"].left == by["identical"].right
    assert all(p.system == casts.SYSTEM for p in pairs)
    # The two versions differ in who the person is, and in nothing else.
    one, two = by["identical"].right.split("\n\nVersion 2:\n")
    assert "Talkative" in one and "Keeps to themselves" in two


# -- the judge ----------------------------------------------------------------------


def test_a_verdict_counts_both_orders_and_names_its_position_bias() -> None:
    pair = judge.Pair("p", "left", "right", "x")
    assert judge.Scored(pair, "B", "A").right_points == 1.0  # right both ways
    assert judge.Scored(pair, "A", "B").right_points == 0.0
    split = judge.Scored(pair, "A", "A")  # "whatever is shown first"
    assert split.right_points == 0.5 and split.consistent is False
    assert judge.Scored(pair, "tie", "tie").consistent is True
    assert judge.Scored(pair, None, "A").right_points is None
    assert judge.parse('{"more_plausible": "B", "least_plausible_detail": "x"}') == "B"
    assert judge.parse("not json") is None


def test_the_judge_reads_the_cache_and_asks_nothing_unless_told_to(
    conn: Connection[DictRow], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("opened a gateway")

    monkeypatch.setattr(judge, "Gateway", refuse)
    known = judge.Pair("known", "account one", "account two", "k")
    unknown = judge.Pair("unknown", "account three", "account four", "u")
    for first, second, says in (
        (known.left, known.right, "B"),
        (known.right, known.left, "A"),
    ):
        req = judge.request(first, second)
        body = req.model_dump(mode="json")
        insert_call(
            conn,
            {
                "hash": judge.request_key(req),
                "kind": judge.KIND,
                "model": judge.JUDGE,
                "request": body,
                "wire": json.dumps(body),
                "response": {"text": json.dumps({"more_plausible": says})},
            },
        )
    conn.commit()
    run = judge.judge(conn, [known, unknown])
    assert run.asked == 4 and run.missing == 2
    by_id = {s.pair.id: s for s in run.scored}
    assert by_id["known"].right_points == 1.0 and by_id["known"].consistent
    assert by_id["unknown"].right_points is None


# -- the report ----------------------------------------------------------------------


def test_the_report_is_rendered_from_the_run_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "RUNS", tmp_path)
    monkeypatch.setattr(report, "JUDGE_DIR", tmp_path / "judge")
    for arm, base in (("rules", 0.2), ("jev", 0.4)):
        for index, s in enumerate((20260920, 20260921, 20260922)):
            (tmp_path / f"{arm}-{s}.json").write_text(
                json.dumps(
                    {
                        "arm": arm,
                        "seed": s,
                        "days": 7,
                        "digest": f"{arm}{s}",
                        "checks_failed": [],
                        "values": {
                            "persona_signal": base + 0.01 * index,
                            "cafe_peak_hour": 12.0,
                        },
                    }
                )
            )
    text = report.render(["rules", "jev"])
    assert "#### `jev` against `rules`" in text
    assert "`persona_signal` | +0.200" in text and "**clear**" in text
    assert "12.000 ± 0.000 (0/3 in band)" in text
    assert "Held-out seeds: none yet" in text and "No judge results yet." in text
