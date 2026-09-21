"""Gate 4: the API over the world.

Uses FastAPI's TestClient against the real database, because the endpoints are
mostly SQL and mocking it would test nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from jeve import db
from jeve.api.app import app
from jeve.core.clock import SimTime, at
from jeve.decide.policy import RulesPolicy
from jeve.world.engine import Engine, skip_to_next_open
from jeve.world.seed_world import ROOT_SEED, seed

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    try:
        with db.connect() as conn:
            db.migrate(conn)
            seed(conn, root_seed=ROOT_SEED)
            engine = Engine(conn, RulesPolicy(ROOT_SEED), root_seed=ROOT_SEED)
            end = at(4)
            while True:
                row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
                assert row is not None
                now = SimTime(int(row["sim_time"]))
                if now.seconds >= end:
                    break
                if not now.anything_open:
                    if skip_to_next_open(conn) >= end:
                        break
                    continue
                engine.tick()
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["ok"] is True


def test_health_is_not_200_when_the_database_is_gone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """e2e waits on this endpoint. A 200 here means "go", whatever the body says."""

    monkeypatch.setenv("JEVE_DATABASE_URL", "postgresql://jeve:jeve@127.0.0.1:1/nope")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_state_is_one_read_with_a_cursor(client: TestClient) -> None:
    body = client.get("/state").json()
    assert body["seq"] > 0, "state must say what seq it is current as of"
    assert len(body["orgs"]) == 4
    assert {o["id"] for o in body["orgs"]} == {
        "tallybird",
        "halloran",
        "ledgerline",
        "thirdrail",
    }
    assert body["persons"]["staff"] == 24
    assert body["persons"]["counterparty"] == 400
    assert body["clock"]["label"].startswith("d")
    assert len(body["modules"]) == 3


def test_state_tells_a_dead_daemon_from_a_sleeping_one(client: TestClient) -> None:
    """SIM-0002: `status` is what the daemon last said; a killed process goes on
    saying `running` for ever. The heartbeat is the evidence."""

    with db.connect() as conn:
        conn.execute(
            "UPDATE sim_meta SET status = 'running', last_error = NULL, "
            "heartbeat_at = now() - interval '2 seconds', lag_s = 1.25"
        )
        conn.commit()
    health = client.get("/state").json()["health"]
    assert health["stale"] is False
    assert health["lag_s"] == 1.25 and 1.0 < health["heartbeat_age_s"] < 30.0

    with db.connect() as conn:
        conn.execute("UPDATE sim_meta SET heartbeat_at = now() - interval '5 minutes'")
        conn.commit()
    assert client.get("/state").json()["health"]["stale"] is True

    # A world that was stopped on purpose is not stale, however long ago.
    with db.connect() as conn:
        conn.execute(
            "UPDATE sim_meta SET status = 'waiting_on_model', "
            "last_error = 'TransportError: /decisions returned 520'"
        )
        conn.commit()
    health = client.get("/state").json()["health"]
    assert health["stale"] is True and health["last_error"].startswith("TransportError")
    with db.connect() as conn:
        conn.execute("UPDATE sim_meta SET status = 'paused', last_error = NULL")
        conn.commit()
    assert client.get("/state").json()["health"]["stale"] is False


def test_money_is_an_integer_everywhere_on_the_wire(client: TestClient) -> None:
    """Postgres `sum()` over bigint returns numeric, which serialises as a
    string. Money is integer cents on the wire; a string here means a client
    silently comparing "10518000" to a number."""

    body = client.get("/state").json()
    assert isinstance(body["unpaid_invoices"]["cents"], int)
    assert isinstance(body["unpaid_invoices"]["n"], int)
    assert isinstance(body["tickets"]["open"], int)
    for org in body["orgs"]:
        assert isinstance(org["cash_cents"], int)
        assert isinstance(org["receivable_cents"], int)


def test_every_org_reports_cash(client: TestClient) -> None:
    for org in client.get("/state").json()["orgs"]:
        assert isinstance(org["cash_cents"], int)
        assert org["cash_cents"] > 0, f"{org['id']} is broke or missing"


def test_events_paginate_by_seq(client: TestClient) -> None:
    # Everything, movement and retail included: that is the stream whose `seq`
    # is dense. The default listing leaves the background out, so it has gaps.
    everything = {"limit": 10, "background": True}
    first = client.get("/events", params=everything).json()
    assert len(first["events"]) == 10
    second = client.get("/events", params={**everything, "after": first["seq"]}).json()
    assert all(e["seq"] > first["seq"] for e in second["events"])
    # No gap and no duplicate: the contract the SSE stream relies on.
    assert second["events"][0]["seq"] == first["events"][-1]["seq"] + 1

    foreground = client.get("/events", params={"limit": 50}).json()["events"]
    assert not {e["kind"] for e in foreground} & {"agent.moved", "cafe.sale"}
    seqs = [e["seq"] for e in foreground]
    assert seqs == sorted(seqs)


def test_events_filter_by_kind(client: TestClient) -> None:
    body = client.get("/events", params={"kind": "incident.started"}).json()
    assert body["events"]
    assert {e["kind"] for e in body["events"]} == {"incident.started"}


def test_the_cascade_endpoint_walks_downstream(client: TestClient) -> None:
    incident = client.get(
        "/events", params={"kind": "incident.started", "limit": 1}
    ).json()["events"][0]
    body = client.get(f"/causal/{incident['seq']}").json()

    kinds = {e["kind"] for e in body["events"]}
    assert "incident.started" in kinds
    assert "invoice.blocked" in kinds or "ticket.opened" in kinds, (
        f"an outage with no consequences: {kinds}"
    )
    assert max(e["depth"] for e in body["events"]) >= 1


def test_the_cascade_endpoint_walks_upstream(client: TestClient) -> None:
    blocked = client.get(
        "/events", params={"kind": "invoice.blocked", "limit": 1}
    ).json()["events"]
    if not blocked:
        pytest.skip("no blocked invoices in this window")
    body = client.get(f"/causal/{blocked[0]['seq']}", params={"direction": "up"}).json()
    kinds = {e["kind"] for e in body["events"]}
    assert "incident.started" in kinds, (
        "a blocked invoice run must trace back to the outage that caused it"
    )


def test_a_missing_event_is_404(client: TestClient) -> None:
    assert client.get("/causal/999999999").status_code == 404


def test_person_decisions_carry_the_draw(client: TestClient) -> None:
    staff = client.get("/persons", params={"org": "tallybird"}).json()["persons"]
    assert staff
    for person in staff:
        body = client.get(f"/persons/{person['id']}/decisions").json()
        if not body["decisions"]:
            continue
        decision = body["decisions"][0]
        assert decision["prng_path"], "a decision with no PRNG path is unexplainable"
        assert decision["source"] in {"rules", "jev", "llm"}
        assert decision["chosen"]
        return
    pytest.fail("no Tallybird staff made a decision in four sim-days")


def test_an_unknown_person_is_404(client: TestClient) -> None:
    assert client.get("/persons/nobody/decisions").status_code == 404


def test_responses_match_the_pydantic_contract(client: TestClient) -> None:
    """`jeve.api.contracts` is the source of truth for the zod schemas the
    browser parses with. Without this, the models could drift from the SQL
    and nobody would know until a page broke — validation here keeps the
    contract honest."""

    from jeve.api import contracts

    contracts.WorldState.model_validate(client.get("/state").json())
    contracts.EventPage.model_validate(client.get("/events").json())
    contracts.EventPage.model_validate(
        client.get("/events", params={"background": True, "limit": 500}).json()
    )

    event = client.get("/events", params={"limit": 1}).json()["events"][0]
    contracts.CausalChain.model_validate(client.get(f"/causal/{event['seq']}").json())
    contracts.CausalChain.model_validate(
        client.get(f"/causal/{event['seq']}", params={"direction": "up"}).json()
    )

    persons = contracts.PersonsResponse.model_validate(client.get("/persons").json())
    assert persons.persons
    contracts.PersonsResponse.model_validate(
        client.get("/persons", params={"kind": "all", "limit": 500}).json()
    )
    contracts.PersonDecisions.model_validate(
        client.get(f"/persons/{persons.persons[0].id}/decisions").json()
    )

    contracts.Economics.model_validate(client.get("/economics").json())

    # The spatial surface (WORLD-0003): the map is static, the frame and the
    # detail panels are live reads.
    contracts.TownMap.model_validate(client.get("/world/map").json())
    frame = contracts.AgentsFrame.model_validate(client.get("/world/agents").json())
    assert frame.agents
    contracts.AgentDetail.model_validate(
        client.get(f"/world/agents/{frame.agents[0].id}").json()
    )
    contracts.OrgDetail.model_validate(client.get("/orgs/tallybird").json())

    # The dialogue endpoint always carries the typed record; prose is absent
    # for an encounter nobody paid to render. `generate=false` keeps the test
    # offline.
    encounter = client.get(
        "/events", params={"kinds": "encounter", "latest": "true", "limit": 1}
    ).json()["events"]
    assert encounter, "the fixture runs through four open days with no encounters?"
    contracts.EncounterDialogue.model_validate(
        client.get(
            f"/encounters/{encounter[0]['seq']}/dialogue",
            params={"generate": "false"},
        ).json()
    )


def test_economics_reports_measured_spend(client: TestClient) -> None:
    body = client.get("/economics").json()
    assert body["sim_days"] >= 1
    assert body["counts"]["persons"] == 424
    # A rules-only run costs nothing, and saying so is the honest answer.
    assert body["spend_usd"] == 0.0
    assert body["model_calls"] == 0
    assert body["decisions_by_model"] == []
    assert body["counts"]["modelled"] == 0
    assert "usd_per_100_persons" in body["per_sim_day"]


def test_the_stream_replays_from_a_cursor(client: TestClient) -> None:
    """A reconnect must resume exactly where it left off."""

    import json

    seqs: list[int] = []
    # A short lifetime so the stream ends on its own; the endpoint closes
    # itself and the client is expected to resume from the last seq.
    with client.stream(
        "GET", "/stream", params={"after": 0, "lifetime_s": 2}
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                seqs.append(json.loads(line[6:])["seq"])

    assert len(seqs) > 1
    assert seqs == sorted(seqs), "the stream must be ordered by seq"
    assert seqs[0] == 1, "after=0 must start at the first event"

    # Resuming from a cursor skips what was already delivered.
    resumed: list[int] = []
    with client.stream(
        "GET", "/stream", params={"after": seqs[4], "lifetime_s": 2}
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                resumed.append(json.loads(line[6:])["seq"])
    assert resumed[0] == seqs[5], "a reconnect must not gap or duplicate"


def test_cors_allows_any_local_port(client: TestClient) -> None:
    """The web app is not always on 3000, and a hard-coded port fails as a
    page that renders and then does nothing."""

    for origin in (
        "http://localhost:3000",
        "http://localhost:3010",
        "http://127.0.0.1:4173",
    ):
        response = client.get("/state", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin, (
            f"{origin} was refused"
        )


def test_cors_refuses_a_remote_origin(client: TestClient) -> None:
    response = client.get("/state", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


# -- the spatial world -----------------------------------------------------


def test_the_map_is_served_as_data(client: TestClient) -> None:
    body = client.get("/world/map").json()
    assert (body["width"], body["height"]) == (40, 28)
    assert len(body["tiles"]) == 28 and len(body["tiles"][0]) == 40
    assert {b["org_id"] for b in body["buildings"]} == {
        "tallybird",
        "halloran",
        "ledgerline",
        "thirdrail",
    }
    for building in body["buildings"]:
        x, y = building["door"]
        assert body["tiles"][y][x] == "door"
        assert body["zones"][y][x] == building["zone"]
    assert body["crowd_spots"]["cafe"]
    # WEB-0004: where one sits, per zone, so the client can draw people sitting.
    # Offices and the plaza's benches have some; every one is a chair or a bench.
    assert set(body["seats"]) == {b["zone"] for b in body["buildings"]} | {"plaza"}
    for zone in ("software_office", "law_office", "accounting_office", "plaza"):
        assert body["seats"][zone], zone
    for tiles in body["seats"].values():
        for x, y in tiles:
            assert body["tiles"][y][x] in ("chair", "bench")


def test_the_agents_frame_places_all_staff(client: TestClient) -> None:
    body = client.get("/world/agents").json()
    assert len(body["agents"]) == 24
    assert body["seq"] > 0 and body["tick_seq"] > 0
    world = client.get("/world/map").json()
    for agent in body["agents"]:
        if agent["zone"] == "home":
            assert agent["x"] is None and agent["y"] is None
        else:
            assert world["zones"][agent["y"]][agent["x"]] == agent["zone"]


def test_an_agent_shows_the_decision_and_the_draw_behind_it(client: TestClient) -> None:
    body = client.get("/world/agents/tallybird.support.6").json()
    assert body["name"] == "Kwame Boateng"
    assert body["org_name"] == "Tallybird Software"
    # The words a model is shown, alongside the number they stand for.
    assert set(body["trait_words"]) <= set(body["traits"])
    assert body["trait_words"]["diligence"]
    decision = body["last_decision"]
    assert decision is not None
    assert decision["source"] in ("rules", "jev")
    assert decision["chosen"]
    assert client.get("/world/agents/nobody.at.all").status_code == 404


def test_an_org_panel_has_its_books_and_its_people(client: TestClient) -> None:
    body = client.get("/orgs/thirdrail").json()
    assert body["name"] == "Third Rail Cafe"
    assert body["zone"] == "cafe"
    assert body["staff_total"] == 6
    assert body["cash_cents"] > 0
    assert client.get("/orgs/nowhere").status_code == 404


def test_movement_stays_out_of_the_timeline_unless_asked_for(
    client: TestClient,
) -> None:
    """One line per person per change of room would bury the outage."""

    default = client.get("/events?limit=1000").json()["events"]
    assert default
    assert all(e["kind"] != "agent.moved" for e in default)

    moves = client.get("/events?kinds=agent.moved&limit=50&latest=true").json()
    assert moves["events"]
    assert all(e["kind"] == "agent.moved" for e in moves["events"])
    seqs = [e["seq"] for e in moves["events"]]
    assert seqs == sorted(seqs)
    # Each carries the tiles walked: what a client animates, live or replayed.
    walked = moves["events"][-1]["payload"]["path"]
    assert len(walked) >= 2 and all(len(step) == 2 for step in walked)

    everything = client.get("/events?limit=1000&background=true").json()["events"]
    assert any(e["kind"] == "agent.moved" for e in everything)
