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
                if not now.in_office_hours and not now.cafe_open:
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
    first = client.get("/events", params={"limit": 10}).json()
    assert len(first["events"]) == 10
    second = client.get("/events", params={"limit": 10, "after": first["seq"]}).json()
    assert all(e["seq"] > first["seq"] for e in second["events"])
    # No gap and no duplicate: the contract the SSE stream relies on.
    assert second["events"][0]["seq"] == first["events"][-1]["seq"] + 1


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
