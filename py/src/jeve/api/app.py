"""Read endpoints over the world, plus an event stream.

The browser talks only to this. Next.js never touches Postgres — two owners of
one schema is how a schema stops being trustworthy (CORE-0007).

Every list endpoint reports the `seq` it is current as of, and the stream is
resumed by `seq`, so a dropped connection reconnects with no gap and no
duplicate. That is the whole reason `seq` is a bigserial and not a timestamp.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import SimTime

app = FastAPI(
    title="jeve",
    summary="A continuously-running simulation of a small interconnected economy.",
    version="0.1.0",
)

# Single instance, no auth, localhost only — a stated constraint.
#
# Any local port, not a fixed list: the dev app is on 3000, the end-to-end run
# uses another to avoid colliding with it, and someone will pick a third. A
# hard-coded port produces a page that renders from the server and then fails
# every client fetch, which reads as a broken app rather than a CORS rule.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _conn() -> Iterator[Connection[DictRow]]:
    with db.connect() as connection:
        yield connection


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with db.connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with db.connect() as conn:
        found = conn.execute(sql, params).fetchone()
        return dict(found) if found else None


def _max_seq(conn: Connection[DictRow]) -> int:
    row = conn.execute("SELECT COALESCE(max(seq), 0) AS seq FROM events").fetchone()
    return int(row["seq"]) if row else 0


@app.get("/health")
def health() -> JSONResponse:
    """200 only when the database answers.

    A wait loop polls this for a 2xx. Reporting a dead database as 200 with
    `ok: false` in the body let a stale server pass for a healthy one.
    """

    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        return JSONResponse({"ok": True})
    except Exception as error:  # reporting any failure is this endpoint's job
        return JSONResponse({"ok": False, "error": str(error)}, status_code=503)


@app.get("/state")
def state() -> dict[str, object]:
    """Everything the dashboard needs for a first paint, in one read."""

    with db.connect() as conn:
        meta = conn.execute("SELECT * FROM sim_meta").fetchone()
        if meta is None:
            raise HTTPException(503, "the world has not been seeded")
        now = SimTime(int(meta["sim_time"]))

        cash = {
            str(row["org_id"]): int(row["cents"])
            for row in conn.execute(
                "SELECT a.org_id, COALESCE(sum(e.amount_cents),0) AS cents "
                "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id = a.id "
                "WHERE a.kind = 'cash' AND a.org_id IS NOT NULL GROUP BY a.org_id"
            ).fetchall()
        }
        receivable = {
            str(row["org_id"]): int(row["cents"])
            for row in conn.execute(
                "SELECT a.org_id, COALESCE(sum(e.amount_cents),0) AS cents "
                "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id = a.id "
                "WHERE a.kind = 'receivable' AND a.org_id IS NOT NULL GROUP BY a.org_id"
            ).fetchall()
        }
        orgs = [
            {
                **dict(row),
                "cash_cents": cash.get(str(row["id"]), 0),
                "receivable_cents": receivable.get(str(row["id"]), 0),
            }
            for row in conn.execute(
                "SELECT id, name, kind FROM orgs ORDER BY id"
            ).fetchall()
        ]

        backlog = conn.execute(
            "SELECT count(*) FILTER (WHERE status = 'open') AS untriaged, "
            "       count(*) FILTER (WHERE status <> 'closed') AS open "
            "FROM tickets"
        ).fetchone()
        unpaid = conn.execute(
            "SELECT count(*) AS n, COALESCE(sum(amount_cents),0) AS cents "
            "FROM invoices WHERE paid_sim IS NULL"
        ).fetchone()
        # sum() over a bigint returns `numeric`, which arrives as Decimal and
        # serialises as a *string*. Money is integer cents on the wire, so the
        # coercion happens here rather than being papered over in the client.
        totals = {
            "n": int(unpaid["n"]) if unpaid else 0,
            "cents": int(unpaid["cents"]) if unpaid else 0,
        }
        tickets = {
            "untriaged": int(backlog["untriaged"]) if backlog else 0,
            "open": int(backlog["open"]) if backlog else 0,
        }
        modules = [
            dict(row)
            for row in conn.execute(
                "SELECT id, name, status FROM modules ORDER BY id"
            ).fetchall()
        ]
        people = conn.execute(
            "SELECT kind, count(*) AS n FROM persons GROUP BY kind"
        ).fetchall()

        return {
            "seq": _max_seq(conn),
            "clock": {
                "sim_time": now.seconds,
                "label": now.label(),
                "day": now.day,
                "weekday": now.weekday,
                "in_office_hours": now.in_office_hours,
                "tick_seq": int(meta["tick_seq"]),
                "status": meta["status"],
                "speed": float(meta["speed"]),
                "run_id": meta["run_id"],
            },
            "orgs": orgs,
            "modules": modules,
            "tickets": tickets,
            "unpaid_invoices": totals,
            "persons": {str(row["kind"]): int(row["n"]) for row in people},
        }


@app.get("/events")
def events(
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    kind: str | None = None,
    org: str | None = None,
) -> dict[str, object]:
    clauses = ["seq > %s"]
    params: list[Any] = [after]
    if kind:
        clauses.append("kind = %s")
        params.append(kind)
    if org:
        clauses.append("org_id = %s")
        params.append(org)
    params.append(limit)
    rows = _rows(
        f"SELECT seq, sim_time, tick_seq, kind, actor_id, org_id, payload, causes "
        f"FROM events WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT %s",
        tuple(params),
    )
    for row in rows:
        row["label"] = SimTime(int(row["sim_time"])).label()
    return {"events": rows, "seq": rows[-1]["seq"] if rows else after}


@app.get("/causal/{seq}")
def causal(
    seq: int, direction: str = Query("down", pattern="^(up|down)$")
) -> dict[str, object]:
    """The cascade around one event.

    `down` walks effects, `up` walks causes. This is the endpoint the timeline
    is built on, and the reason `causes` is a column rather than a join table.
    """

    if direction == "down":
        sql = """
            WITH RECURSIVE chain AS (
                SELECT seq, sim_time, kind, org_id, actor_id, payload, causes,
                       0 AS depth
                  FROM events WHERE seq = %s
                UNION ALL
                SELECT e.seq, e.sim_time, e.kind, e.org_id, e.actor_id, e.payload,
                       e.causes, c.depth + 1
                  FROM events e JOIN chain c ON c.seq = ANY (e.causes)
                 WHERE c.depth < 12
            )
            SELECT DISTINCT ON (seq) * FROM chain ORDER BY seq, depth
        """
    else:
        sql = """
            WITH RECURSIVE chain AS (
                SELECT seq, sim_time, kind, org_id, actor_id, payload, causes,
                       0 AS depth
                  FROM events WHERE seq = %s
                UNION ALL
                SELECT e.seq, e.sim_time, e.kind, e.org_id, e.actor_id, e.payload,
                       e.causes, c.depth + 1
                  FROM events e JOIN chain c ON e.seq = ANY (c.causes)
                 WHERE c.depth < 12
            )
            SELECT DISTINCT ON (seq) * FROM chain ORDER BY seq, depth
        """
    rows = _rows(sql, (seq,))
    if not rows:
        raise HTTPException(404, f"no event {seq}")
    for row in rows:
        row["label"] = SimTime(int(row["sim_time"])).label()
    return {"root": seq, "direction": direction, "events": rows}


@app.get("/persons")
def persons(
    org: str | None = None,
    kind: str = Query("staff", pattern="^(staff|counterparty|all)$"),
    limit: int = Query(60, ge=1, le=500),
) -> dict[str, object]:
    clauses: list[str] = []
    params: list[Any] = []
    if org:
        clauses.append("org_id = %s")
        params.append(org)
    if kind != "all":
        clauses.append("kind = %s")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return {
        "persons": _rows(
            f"SELECT id, org_id, name, role, kind, traits, decision_seq, status "
            f"FROM persons {where} ORDER BY org_id, role, id LIMIT %s",
            tuple(params),
        )
    }


@app.get("/persons/{person_id}/decisions")
def person_decisions(
    person_id: str, limit: int = Query(40, ge=1, le=200)
) -> dict[str, object]:
    """Why an agent did what it did.

    Carries the whole distribution the policy produced and the draw that was
    taken from it, so a viewer can see what the model thought *and* what the
    dice did with it — the research question, made inspectable.
    """

    person = _row(
        "SELECT id, org_id, name, role, kind, traits FROM persons WHERE id = %s",
        (person_id,),
    )
    if person is None:
        raise HTTPException(404, f"no person {person_id}")
    rows = _rows(
        "SELECT id, decision_seq, sim_time, tick_seq, question_set, source, "
        "distributions, prng_path, draws, chosen, model_call "
        "FROM decisions WHERE person_id = %s ORDER BY decision_seq DESC LIMIT %s",
        (person_id, limit),
    )
    for row in rows:
        row["label"] = SimTime(int(row["sim_time"])).label()
    return {"person": person, "decisions": rows}


@app.get("/economics")
def economics() -> dict[str, object]:
    """Measured unit cost, read from the ledger — never a projection."""

    with db.connect() as conn:
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM persons) AS persons, "
            "       (SELECT count(*) FROM orgs) AS orgs, "
            "       (SELECT count(*) FROM events) AS events, "
            "       (SELECT count(*) FROM decisions) AS decisions, "
            "       (SELECT count(*) FROM decisions WHERE source <> 'rules') "
            "         AS modelled"
        ).fetchone()
        meta = conn.execute("SELECT sim_time, tick_seq FROM sim_meta").fetchone()

    from jeve.config import load_settings
    from jeve.llm.ledger import SpendLedger

    settings = load_settings()
    spend = SpendLedger(settings.ledger_path, checkpoint=settings.spend_path).read()

    sim_days = max(1.0, SimTime(int(meta["sim_time"])).day if meta else 1)
    persons = int(counts["persons"]) if counts else 0
    orgs = int(counts["orgs"]) if counts else 0
    events_n = int(counts["events"]) if counts else 0
    total = spend.settled_usd

    return {
        "spend_usd": round(total, 6),
        "spend_is_estimated_calls": spend.estimated_calls,
        "model_calls": spend.calls,
        "sim_days": sim_days,
        "counts": dict(counts) if counts else {},
        "per_sim_day": {
            "usd_per_100_persons": round(total / sim_days / max(1, persons) * 100, 6),
            "usd_per_10_orgs": round(total / sim_days / max(1, orgs) * 10, 6),
            "usd_per_1000_events": round(total / sim_days / max(1, events_n) * 1000, 6),
        },
        "note": (
            "Read from the spend ledger. Decisions made by rules cost nothing, "
            "so a run with `modelled` = 0 reports $0 — that is honest, not a bug."
        ),
    }


@app.get("/stream")
async def stream(
    after: int = Query(0, ge=0),
    lifetime_s: float = Query(900.0, gt=0, le=3600),
) -> StreamingResponse:
    """Server-sent events, resumed by `seq`.

    Polling rather than LISTEN/NOTIFY for the MVP: one reader, a tick every few
    seconds at most, and a poll cannot miss an event because the cursor is the
    sequence itself.

    The connection closes itself after `lifetime_s`. Long-lived streams get
    killed by proxies and sleeping laptops anyway, and a server that recycles
    on its own terms is easier to reason about than one that waits to be cut
    off. Resuming costs nothing because the client already tracks `seq`.
    """

    async def source() -> AsyncIterator[str]:
        cursor = after
        idle = 0
        deadline = asyncio.get_running_loop().time() + lifetime_s
        while asyncio.get_running_loop().time() < deadline:
            rows = await asyncio.to_thread(
                _rows,
                "SELECT seq, sim_time, kind, actor_id, org_id, payload, causes "
                "FROM events WHERE seq > %s ORDER BY seq LIMIT 200",
                (cursor,),
            )
            if rows:
                idle = 0
                for row in rows:
                    row["label"] = SimTime(int(row["sim_time"])).label()
                    cursor = int(row["seq"])
                    yield f"data: {json.dumps(row, default=str)}\n\n"
            else:
                idle += 1
                # A comment frame keeps proxies and the browser from timing the
                # connection out during a quiet stretch of sim-night.
                if idle % 10 == 0:
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
        yield ": reconnect\n\n"

    return StreamingResponse(
        source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
