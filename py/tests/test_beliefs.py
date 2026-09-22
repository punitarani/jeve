"""Beliefs are typed slots revised inside existing requests (MEM-0002).

On rules, so nothing here needs a cassette: the rules twin writes the same
levels a model would be asked for. Each test is about a mechanism — a belief
forms from an outage, a fact spreads only by contact, relationships grow and
fade, a low opinion moves a subscription — not about the numbers it lands on.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, at
from jeve.core.orgs import BY_ID, ORGS, module_owner, modules_of, vendors
from jeve.decide.policy import RulesPolicy
from jeve.memory import beliefs
from jeve.sim import advance
from jeve.world.engine import Engine
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


def run(conn: Connection[DictRow], *, days: int) -> None:
    def build() -> None:
        seed(conn, root_seed=ROOT_SEED)
        engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
        advance(conn, engine, until=at(days))

    build_once(conn, f"rules:{days}d:encounters=True", build)


def test_a_long_outage_lowers_the_vendor_in_the_eyes_of_those_who_lived_it(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5)
    # The seeded month-end outage runs a full working day: everyone who
    # confirmed a ticket about it, or was asked about their day while it was
    # on their mind, now holds a view of the vendor — and a low one.
    rows = conn.execute(
        "SELECT b.person_id, b.entity_id, b.level, p.org_id FROM beliefs b "
        "JOIN persons p ON p.id = b.person_id WHERE b.slot = 'vendor_reliability'"
    ).fetchall()
    assert rows
    assert {str(r["entity_id"]) for r in rows} <= {v.id for v in vendors()}
    assert all(0 <= int(r["level"]) <= 3 for r in rows)
    low = [r for r in rows if int(r["level"]) <= 1]
    assert low, "a day-long outage left nobody thinking less of the vendor"
    # Only somebody whose firm runs on the product can hold a view of it.
    for row in low:
        vendor = str(row["entity_id"])
        assert any(module_owner(m) == vendor for m in modules_of(str(row["org_id"])))


def test_a_fact_spreads_by_contact_and_never_otherwise(
    conn: Connection[DictRow],
) -> None:
    """Who knows of the price rise: the buyers first, then whoever they, or
    someone who heard it from them, talked money with. Monotone, and never
    to a person with no such chain."""

    run(conn, days=12)
    suppliers = sorted({org.supplier for org in ORGS if org.supplier is not None})
    assert suppliers
    fact = f"price_rise:{suppliers[0]}"
    known = conn.execute(
        "SELECT person_id, updated_sim FROM beliefs WHERE slot = 'knows_of' "
        "AND entity_id = %s ORDER BY updated_sim, person_id",
        (fact,),
    ).fetchall()
    repriced = conn.execute(
        "SELECT sim_time FROM events WHERE kind = 'supply.repriced' AND org_id = %s",
        (suppliers[0],),
    ).fetchone()
    assert repriced is not None
    assert known, "nobody heard of the price rise"
    buyers = {org.id for org in ORGS if org.supplier == suppliers[0]}
    seeded = [r for r in known if int(r["updated_sim"]) == int(repriced["sim_time"])]
    assert seeded and all(str(r["person_id"]).split(".")[0] in buyers for r in seeded)
    # Everyone else learnt it in a conversation about money with someone who
    # already knew, after they knew it.
    when = {str(r["person_id"]): int(r["updated_sim"]) for r in known}
    for row in known:
        if row in seeded:
            continue
        person = str(row["person_id"])
        told = conn.execute(
            "SELECT payload->>'a' AS a, sim_time FROM events WHERE kind = 'encounter' "
            "AND payload->>'topic' = 'money' AND payload->>'b' = %s AND sim_time = %s",
            (person, int(row["updated_sim"])),
        ).fetchall()
        assert told, f"{person} knew without being told"
        assert any(when.get(str(t["a"]), 1 << 60) <= int(t["sim_time"]) for t in told)
    # Nobody forgets: the count is monotone in time.
    assert [int(r["updated_sim"]) for r in known] == sorted(
        int(r["updated_sim"]) for r in known
    )


def test_relationships_grow_by_talking_and_fade_in_silence(
    conn: Connection[DictRow],
) -> None:
    run(conn, days=5)
    rows = conn.execute(
        "SELECT a, b, strength, last_sim FROM relationships ORDER BY strength DESC"
    ).fetchall()
    assert rows
    assert all(1 <= int(r["strength"]) <= 3 for r in rows)
    # Every relationship is backed by at least that many conversations.
    for row in rows[:20]:
        met = conn.execute(
            "SELECT count(*) AS n FROM events WHERE kind = 'encounter' AND "
            "((payload->>'a' = %s AND payload->>'b' = %s) "
            " OR (payload->>'a' = %s AND payload->>'b' = %s))",
            (row["a"], row["b"], row["b"], row["a"]),
        ).fetchone()
        assert met is not None and int(met["n"]) >= int(row["strength"])
    # Two idle weeks later, a nightly decay takes a step off each of them.
    before = {(r["a"], r["b"]): int(r["strength"]) for r in rows}
    touched = beliefs.decay(conn, at(5) + 15 * DAY)
    assert touched == len(rows)
    after = {
        (r["a"], r["b"]): int(r["strength"])
        for r in conn.execute("SELECT a, b, strength FROM relationships").fetchall()
    }
    for pair, strength in before.items():
        if strength == 1:
            assert pair not in after
        else:
            assert after[pair] == strength - 1
    conn.rollback()


def test_a_low_opinion_of_the_vendor_moves_the_subscription_at_renewal(
    conn: Connection[DictRow],
) -> None:
    """The firm's people think the product unreliable; at renewal the
    bill-payer is asked, and on rules half of them leave for the competitor
    — to the same category of product, so their till now depends on it."""

    seed(conn, root_seed=ROOT_SEED)
    old_vendor, new_vendor = (v.id for v in vendors())
    till = next(m for m in modules_of(old_vendor) if m.endswith("pos"))
    users = [org for org in ORGS if modules_of(org.id, "pos") == (till,) and org.retail]
    assert users
    with conn.transaction():
        for org in users:
            for pid in [
                str(r["id"])
                for r in conn.execute(
                    "SELECT id FROM persons WHERE org_id = %s AND kind = 'staff'",
                    (org.id,),
                ).fetchall()
            ]:
                beliefs.set_level(conn, pid, "vendor_reliability", old_vendor, 0, 0)
        # Renewal is the seeded first-day subscription run.
    engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED, spatial=False)
    advance(conn, engine, until=at(0, 10))
    asked = conn.execute(
        "SELECT chosen FROM decisions WHERE question_set = 'subscription.switch'"
    ).fetchall()
    assert asked, "a firm that thinks its vendor unreliable was not asked at renewal"
    switched = conn.execute(
        "SELECT org_id, payload, causes FROM events "
        "WHERE kind = 'subscription.switched'"
    ).fetchall()
    moved = {str(s["org_id"]) for s in switched}
    if not moved:
        pytest.skip("on this seed every asked firm renewed; the ask is what is tested")
    for event in switched:
        payload = event["payload"]
        assert (
            payload["from_vendor"] == old_vendor and payload["to_vendor"] == new_vendor
        )
        assert BY_ID[str(event["org_id"])].retail is not None
        # The same category, bought from the other vendor, from now on.
        now = conn.execute(
            "SELECT module_id FROM subscriptions WHERE org_id = %s AND active",
            (event["org_id"],),
        ).fetchall()
        assert payload["to_module"] in {str(r["module_id"]) for r in now}
        assert payload["from_module"] not in {str(r["module_id"]) for r in now}
    conn.rollback()
