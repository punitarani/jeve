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
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Connection
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool

from jeve import db, tracing
from jeve.api import report
from jeve.config import load_settings
from jeve.core.clock import SimTime

_pool: ConnectionPool[Connection[DictRow]] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """One shared pool for every read endpoint (OPS-0001).

    A fresh TLS connect per request is a hundred milliseconds of handshake the
    caller pays for; a pool pays it once. The sim daemon is untouched — its
    writer lock is a session lock and must ride a dedicated connection.
    """

    global _pool, _report_lock
    _report_lock = asyncio.Lock()
    pool = db.connect_pool()
    await asyncio.to_thread(pool.open)
    _pool = pool
    try:
        yield
    finally:
        _pool = None
        await asyncio.to_thread(pool.close)
        tracing.flush()


app = FastAPI(
    title="jeve",
    summary="A continuously-running simulation of a small interconnected economy.",
    version="0.1.0",
    lifespan=lifespan,
)

# No auth — the browser is the only client, so the origin list is the guard.
# JEVE_CORS_ORIGINS names the deployed frontends; without it, any localhost
# port (the dev app on 3000, e2e on another, whatever someone picks next — a
# hard-coded port reads as a broken app, not a CORS rule).
_cors_origins = load_settings().cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_cors_origins),
    allow_origin_regex=(
        None if _cors_origins else r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
    ),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def _db() -> Iterator[Connection[DictRow]]:
    """One pooled, autocommit connection for a read.

    Autocommit because every reader here is single-statement: an open read
    transaction holds locks the daemon waits on for ever, and holds a pooled
    slot nobody else can use.
    """

    if _pool is not None:
        with _pool.connection() as conn:
            yield conn
    else:
        # Tests without a lifespan, and one-off scripts, still work.
        with db.connect(autocommit=True) as conn:
            yield conn


def _conn() -> Iterator[Connection[DictRow]]:
    with _db() as connection:
        yield connection


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _db() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with _db() as conn:
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
        # Deliberately off-pool: a wedged pool and an unreachable database are
        # different failures, and this probe answers the question "can the
        # app serve at all" — which a borrowed connection could only hedge.
        with db.connect(autocommit=True) as conn:
            conn.execute("SELECT 1")
        return JSONResponse({"ok": True})
    except Exception as error:  # reporting any failure is this endpoint's job
        # Public endpoint: the class names the failure without echoing a DSN
        # or internal hostname the way str(error) would.
        return JSONResponse(
            {"ok": False, "error": type(error).__name__}, status_code=503
        )


# Polled every five seconds by every open page, so each must be an index range
# (tests/test_query_plans.py). The crowd count was a bitmap scan of every cafe
# event ever written until events (kind, tick_seq) existed: 11% of the
# production database's time (LLM-0010).
ORG_BALANCES_SQL = (
    "SELECT a.org_id, COALESCE(sum(e.amount_cents),0) AS cents "
    "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id = a.id "
    "WHERE a.kind = %s AND a.org_id IS NOT NULL GROUP BY a.org_id"
)
CROWD_SQL = (
    "SELECT count(*) AS n FROM events "
    "WHERE kind IN ('cafe.sale','cafe.walkout') "
    "AND tick_seq = (SELECT max(tick_seq) FROM events "
    "                WHERE kind IN ('cafe.sale','cafe.walkout') "
    "                  AND tick_seq > %s - 2)"
)


@app.get("/state")
def state() -> dict[str, object]:
    """Everything the dashboard needs for a first paint, in one read."""

    with _db() as conn:
        # The heartbeat's age is taken in SQL: this process may not read the
        # wall clock, and the database's `now()` is the clock the beat was
        # written with.
        meta = conn.execute(
            "SELECT *, EXTRACT(EPOCH FROM now() - heartbeat_at)::float8 "
            "AS heartbeat_age_s FROM sim_meta"
        ).fetchone()
        if meta is None:
            raise HTTPException(503, "the world has not been seeded")

        cash = {
            str(row["org_id"]): int(row["cents"])
            for row in conn.execute(ORG_BALANCES_SQL, ("cash",)).fetchall()
        }
        receivable = {
            str(row["org_id"]): int(row["cents"])
            for row in conn.execute(ORG_BALANCES_SQL, ("receivable",)).fetchall()
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
            "clock": _clock(meta),
            "health": _health(meta),
            "orgs": orgs,
            "modules": modules,
            "tickets": tickets,
            "unpaid_invoices": totals,
            "persons": {str(row["kind"]): int(row["n"]) for row in people},
        }


def _clock(meta: dict[str, Any]) -> dict[str, object]:
    return {
        **SimTime(int(meta["sim_time"])).describe(),
        "tick_seq": int(meta["tick_seq"]),
        "status": meta["status"],
        "speed": float(meta["speed"]),
        "run_id": meta["run_id"],
        "engine_sha": str(meta.get("engine_sha") or "unknown"),
    }


STALE_AFTER_S = 30.0
"""Six missed beats (SIM-0002). The daemon beats every five seconds whatever it
is doing, asleep for the night included, so silence this long means no process."""


def _health(meta: dict[str, Any]) -> dict[str, object]:
    """Is anybody driving, and is anyone watching? `status` is the daemon's
    word; this is the evidence.

    A status of `running` written by a process that has since been killed stays
    `running` for ever. The heartbeat is what lets a reader tell.
    """

    age = meta["heartbeat_age_s"]
    expected_alive = meta["status"] in (
        "running",
        "waiting_on_model",
        "waiting_on_budget",
        "paused_budget",
    )
    return {
        "heartbeat_age_s": None if age is None else round(float(age), 1),
        "lag_s": round(float(meta["lag_s"]), 2),
        "last_error": meta["last_error"],
        "stale": expected_alive and (age is None or float(age) > STALE_AFTER_S),
        # Read from settings rather than `tracing.enabled()`: that would
        # configure tracing — importing the SDK, building a logger — as a side
        # effect of a read endpoint. `api` and `sim` are one Fly app and share
        # its secrets, so this answers "does the deployment have the key"
        # honestly, which is the question that went unanswered for an hour
        # when the key sat in Doppler and never reached Fly (LLM-0009).
        "tracing": bool(load_settings().braintrust_api_key),
    }


# Hidden from the timeline unless asked for. They are real events, and the
# causal view still walks through them; but one line per person per change of
# room would bury the outage the dashboard exists to show.
#
# Retail joined them when the cafe got its arrival curve: a sale per customer is
# a couple of hundred lines a day, and the first outage of the week was no longer
# among the first four hundred events the timeline loaded.
BACKGROUND_EVENTS = ("agent.moved", "cafe.sale", "cafe.walkout")


@app.get("/events")
def events(
    after: int = Query(0, ge=0),
    before: int | None = Query(None, ge=1, description="older than this seq"),
    limit: int = Query(200, ge=1, le=1000),
    kind: str | None = None,
    org: str | None = None,
    kinds: str | None = Query(None, description="comma-separated; overrides `kind`"),
    background: bool = Query(False, description="include movement and retail"),
    latest: bool = Query(False, description="the newest `limit` instead of the oldest"),
) -> dict[str, object]:
    """A window of the log, always oldest first, with a cursor at each end.

    `after` walks forwards and `before` walks backwards, so one integer pages
    in either direction (API-0002). The rows are sorted ascending whichever way
    the window was taken: the wire order is a property of the endpoint, not of
    the query, and the timeline reverses at the point it renders.
    """

    clauses = ["seq > %s"]
    params: list[Any] = [after]
    if before is not None:
        clauses.append("seq < %s")
        params.append(before)
    wanted = [k for k in (kinds or kind or "").split(",") if k]
    if wanted:
        clauses.append("kind = ANY(%s)")
        params.append(wanted)
    elif not background:
        clauses.append("kind <> ALL(%s)")
        params.append(list(BACKGROUND_EVENTS))
    if org:
        clauses.append("org_id = %s")
        params.append(org)
    # One row past the window, to answer "is there more?" without spending a
    # round trip at the end of history discovering there is not.
    params.append(limit + 1)
    order = "DESC" if latest or before is not None else "ASC"
    rows = _rows(
        f"SELECT seq, sim_time, tick_seq, kind, actor_id, org_id, payload, causes "
        f"FROM events WHERE {' AND '.join(clauses)} ORDER BY seq {order} LIMIT %s",
        tuple(params),
    )
    # The probe row is the one beyond the window in whichever direction the
    # query travelled, so it is always the last — trim before the re-sort.
    more = len(rows) > limit
    del rows[limit:]
    rows.sort(key=lambda row: int(row["seq"]))
    for row in rows:
        row["label"] = SimTime(int(row["sim_time"])).label()
    return {
        "events": rows,
        "seq": rows[-1]["seq"] if rows else after,
        "oldest": rows[0]["seq"] if rows else 0,
        "more": more,
    }


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


# Bookkeeping events: real, but not things that happened *in the economy*.
# Counting them would flatter the per-1000-events figure for free.
NON_ECONOMIC_EVENTS = ("agent.moved",)


@app.get("/economics")
def economics() -> dict[str, object]:
    """Measured unit cost of *this run*, from the calls its decisions used.

    Not from the spend ledger: that is the whole project's history, so it would
    report tonight's total against five sim-days, and $0 on a clean clone. A
    decision row names the call that answered it, and the call row carries what
    OpenRouter billed when it was first made — so the join prices exactly the
    calls this world needed, whether they were live or replayed.

    Tier 1's calls count too — a second opinion in shadow, one that acts, and a
    routed set's answers (DECIDE-0006) — found through `escalations`, which is
    where a decision names the LLM call beside Jev's. Before routing they were
    a rounding error; routed conversations are most of the bill.
    """

    with _db() as conn:
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM persons) AS persons, "
            "       (SELECT count(*) FROM orgs) AS orgs, "
            "       (SELECT count(*) FROM events WHERE kind <> ALL(%s)) AS events, "
            "       (SELECT count(*) FROM decisions) AS decisions, "
            "       (SELECT count(*) FROM decisions WHERE source <> 'rules') "
            "         AS modelled",
            (list(NON_ECONOMIC_EVENTS),),
        ).fetchone()
        meta = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
        span = conn.execute(
            "SELECT min(sim_time) AS first, max(sim_time) AS last FROM events"
        ).fetchone()
        calls = conn.execute(
            "SELECT count(*) AS calls, COALESCE(sum(m.cost_usd),0) AS usd, "
            "       COALESCE(sum(m.input_tokens),0) AS input_tokens, "
            "       count(*) FILTER (WHERE m.cost_estimated) AS estimated "
            "FROM model_calls m WHERE m.hash IN "
            "  (SELECT model_call FROM decisions WHERE model_call IS NOT NULL "
            "   UNION SELECT call_hash FROM escalations)"
        ).fetchone()
        undeduped = conn.execute(
            "SELECT (SELECT COALESCE(sum(m.cost_usd),0) FROM decisions d "
            "        JOIN model_calls m ON m.hash = d.model_call) "
            "     + (SELECT COALESCE(sum(m.cost_usd),0) FROM escalations x "
            "        JOIN model_calls m ON m.hash = x.call_hash) AS usd"
        ).fetchone()
        unpriced = conn.execute(
            "SELECT count(*) AS n FROM decisions d WHERE d.model_call IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM model_calls m WHERE m.hash = d.model_call)"
        ).fetchone()
        by_model = conn.execute(
            "SELECT m.model, count(*) AS decisions, "
            "       count(DISTINCT m.hash) AS calls "
            "FROM (SELECT model_call AS h FROM decisions WHERE model_call IS NOT NULL "
            "      UNION ALL SELECT call_hash FROM escalations) u "
            "JOIN model_calls m ON m.hash = u.h "
            "GROUP BY m.model ORDER BY m.model"
        ).fetchall()
        by_kind = conn.execute(
            "SELECT question_set AS kind, source, count(*) AS decisions, "
            "       count(DISTINCT model_call) AS calls "
            "FROM decisions GROUP BY question_set, source "
            "ORDER BY question_set, source"
        ).fetchall()
        kind_cost = {
            (str(r["kind"]), str(r["source"])): float(r["usd"])
            for r in conn.execute(
                "SELECT u.question_set AS kind, u.source, sum(m.cost_usd) AS usd "
                "FROM (SELECT DISTINCT question_set, source, model_call AS h "
                "      FROM decisions WHERE model_call IS NOT NULL "
                "      UNION SELECT DISTINCT d.question_set, d.source, x.call_hash "
                "      FROM escalations x JOIN decisions d ON d.id = x.decision_id) u "
                "JOIN model_calls m ON m.hash = u.h "
                "GROUP BY u.question_set, u.source"
            ).fetchall()
        }

    assert counts is not None and calls is not None and undeduped is not None
    first = int(span["first"]) if span and span["first"] is not None else 0
    now = int(meta["sim_time"]) if meta else first
    # Whole sim-days the run has covered, counted from the day it began.
    sim_days = max(1, SimTime(now).day - SimTime(first).day)
    persons, orgs = int(counts["persons"]), int(counts["orgs"])
    events_n, modelled = int(counts["events"]), int(counts["modelled"])
    total, n_calls = float(calls["usd"]), int(calls["calls"])

    def per_day(usd: float) -> dict[str, float]:
        daily = usd / sim_days
        return {
            "usd": round(daily, 6),
            "usd_per_100_persons": round(daily / max(1, persons) * 100, 6),
            "usd_per_10_orgs": round(daily / max(1, orgs) * 10, 6),
            # Days cancel: (usd per day) over (events per day).
            "usd_per_1000_events": round(usd / max(1, events_n) * 1000, 6),
        }

    return {
        "spend_usd": round(total, 6),
        "spend_is_estimated_calls": int(calls["estimated"]),
        "model_calls": n_calls,
        "input_tokens": int(calls["input_tokens"]),
        "sim_days": sim_days,
        "counts": {k: int(v) for k, v in dict(counts).items()},
        "per_sim_day": per_day(total),
        "without_dedup": {
            "spend_usd": round(float(undeduped["usd"]), 6),
            "per_sim_day": per_day(float(undeduped["usd"])),
        },
        "dedup_rate": round(1 - n_calls / modelled, 4) if modelled else 0.0,
        "unpriced_decisions": int(unpriced["n"]) if unpriced else 0,
        "decisions_by_model": [
            {
                "model": str(r["model"]),
                "decisions": int(r["decisions"]),
                "calls": int(r["calls"]),
            }
            for r in by_model
        ],
        "by_kind": [
            {
                "kind": str(r["kind"]),
                "source": str(r["source"]),
                "decisions": int(r["decisions"]),
                "calls": int(r["calls"]),
                "usd": round(kind_cost.get((str(r["kind"]), str(r["source"])), 0.0), 6),
            }
            for r in by_kind
        ],
        "note": (
            "Priced from the calls this run's decisions used, at what OpenRouter "
            "billed when each was first made. `without_dedup` prices every "
            "decision as its own call; it is an upper bound, not a measurement."
        ),
    }


_report_lock: asyncio.Lock | None = None
_report_memo: tuple[tuple[str, str, str, int, int], dict[str, object]] | None = None


def _report_meta() -> tuple[dict[str, Any], int]:
    with _db() as conn:
        meta = conn.execute(
            "SELECT *, EXTRACT(EPOCH FROM now() - heartbeat_at)::float8 "
            "AS heartbeat_age_s, current_database() AS db, "
            "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') "
            "AS as_of FROM sim_meta"
        ).fetchone()
        if meta is None:
            raise HTTPException(503, "the world has not been seeded")
        return dict(meta), _max_seq(conn)


def _report_body(now: SimTime) -> dict[str, object]:
    with _db() as conn:
        return report.aggregate(conn, now)


@app.get("/report")
async def field_report() -> dict[str, object]:
    """The field report: the world's aggregates, as `/reports` draws them (API-0003).

    A handful of full scans, so the aggregates are memoised on what would
    change them — which world, which tick, which last event — and a
    page left open, or a crowd arriving at once, costs one computation per
    tick rather than one per request. The lock makes the crowd wait for that
    one instead of each starting its own. Clock and health are read fresh
    every time: they are cheap, and a stale heartbeat is the one thing a
    reader must not be shown.
    """

    global _report_lock, _report_memo
    meta, seq = await asyncio.to_thread(_report_meta)
    # Which world (a reseed truncates sim_meta, so started_at is new even
    # when the run_id is not), then how far along it is.
    world = (str(meta["db"]), str(meta["run_id"]), str(meta["started_at"]))
    key = (*world, int(meta["tick_seq"]), seq)
    # An asyncio lock, so the crowd waits on the event loop. A threading lock
    # in a sync endpoint parks each waiter on a worker thread, and forty of
    # those is the whole threadpool: /state and /health would stall behind
    # one slow report. Made per event loop, which is what an asyncio lock is
    # bound to — each TestClient, and each server, runs its own.
    if _report_lock is None:
        _report_lock = asyncio.Lock()
    async with _report_lock:
        # A memo at least as new as this request's key will do: a reader who
        # read the clock just before a tick is not owed the older world, and
        # recomputing it would evict the newer one everyone else is asking for.
        memo = _report_memo
        if memo is None or memo[0][:3] != world or memo[0][3:] < key[3:]:
            now = SimTime(int(meta["sim_time"]))
            memo = (key, await asyncio.to_thread(_report_body, now))
            _report_memo = memo
        body = memo[1]
    return {
        "seq": seq,
        "as_of": str(meta["as_of"]),
        "clock": _clock(meta),
        "health": _health(meta),
        **body,
    }


# -- the spatial world (WORLD-0003, WEB-0002) ------------------------------


@app.get("/world/map")
def world_map() -> dict[str, object]:
    """The town, as data. Static: safe to cache for the life of the page."""

    from jeve.world.map import BUILDINGS, HEIGHT, WIDTH, ZONE_ORG, Zone, town
    from jeve.world.seed_world import ORGS

    names = {org_id: name for org_id, name, _ in ORGS}
    plan = town()
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "tiles": [list(row) for row in plan.tiles],
        "zones": [list(row) for row in plan.zones],
        "buildings": [
            {
                "zone": b.zone.value,
                "org_id": ZONE_ORG[b.zone],
                "name": names[ZONE_ORG[b.zone]],
                "x0": b.x0,
                "y0": b.y0,
                "x1": b.x1,
                "y1": b.y1,
                "door": list(b.door),
            }
            for b in BUILDINGS
        ],
        # Where the sampled crowd of counterparties may stand.
        "crowd_spots": {
            Zone.CAFE.value: [list(t) for t in plan.visitor_spots[Zone.CAFE]],
            Zone.PLAZA.value: [list(t) for t in plan.visitor_spots[Zone.PLAZA]],
        },
        # WEB-0004: the tiles somebody sits on, so a client can draw them
        # sitting. Not `plan.seats`, which is where staff *work*: a barista's
        # place is behind the counter, on her feet.
        "seats": {
            zone.value: [list(t) for t in plan.sittable(zone)]
            for zone in plan.visitor_spots
        },
    }


@app.get("/world/agents")
def world_agents() -> dict[str, object]:
    """The current frame: where every member of staff is, and how they got there."""

    with _db() as conn:
        meta = conn.execute(
            "SELECT sim_time, tick_seq, status FROM sim_meta"
        ).fetchone()
        if meta is None:
            raise HTTPException(503, "the world has not been seeded")
        agents = conn.execute(
            "SELECT p.id, p.name, p.org_id, p.role, s.zone, s.x, s.y, s.path, "
            "       s.moved_tick, s.mood "
            "FROM persons p JOIN positions s ON s.person_id = p.id ORDER BY p.id"
        ).fetchall()
        # Counterparties have no positions; they are demand. Draw as many as
        # actually turned up at the cafe in the last tick that had any.
        crowd = conn.execute(CROWD_SQL, (int(meta["tick_seq"]),)).fetchone()
        down = conn.execute(
            "SELECT id FROM modules WHERE status = 'down' ORDER BY id"
        ).fetchall()
        seq = _max_seq(conn)

    in_cafe = int(crowd["n"]) if crowd else 0
    now = SimTime(int(meta["sim_time"]))
    return {
        "seq": seq,
        "tick_seq": int(meta["tick_seq"]),
        "sim_time": now.seconds,
        "label": now.label(),
        "status": str(meta["status"]),
        "agents": [dict(row) for row in agents],
        "crowd": {"cafe": in_cafe, "plaza": in_cafe // 2 if now.in_office_hours else 0},
        "down_modules": [str(row["id"]) for row in down],
    }


@app.get("/world/agents/{person_id}")
def world_agent(person_id: str) -> dict[str, object]:
    """One person: who they are, what they last decided, and whom they last met.

    The distribution is what Jev returned; the draw is what was sampled from it.
    Both are typed fields off the decision row — nothing here is generated text.
    """

    from jeve.decide.questions import _TRAIT_WORDS, trait_words

    with _db() as conn:
        person = conn.execute(
            "SELECT p.id, p.name, p.org_id, p.role, p.traits, o.name AS org_name, "
            "       s.zone, s.mood "
            "FROM persons p JOIN orgs o ON o.id = p.org_id "
            "JOIN positions s ON s.person_id = p.id WHERE p.id = %s",
            (person_id,),
        ).fetchone()
        if person is None:
            raise HTTPException(404, f"no staff member {person_id!r}")
        decision = conn.execute(
            "SELECT d.id, d.sim_time, d.question_set, d.source, d.chosen, "
            "       d.distributions, d.draws, m.model "
            "FROM decisions d LEFT JOIN model_calls m ON m.hash = d.model_call "
            "WHERE d.person_id = %s ORDER BY d.id DESC LIMIT 1",
            (person_id,),
        ).fetchone()
        met = conn.execute(
            "SELECT e.seq, e.sim_time, e.payload, "
            "  ARRAY(SELECT DISTINCT c.kind FROM events c WHERE e.seq = ANY(c.causes)) "
            "    AS led_to "
            "FROM events e WHERE e.kind = 'encounter' "
            "AND (e.payload->>'a' = %s OR e.payload->>'b' = %s) "
            "ORDER BY e.seq DESC LIMIT 1",
            (person_id, person_id),
        ).fetchone()
        other_name = None
        if met is not None:
            payload = met["payload"]
            other_id = payload["b"] if payload["a"] == person_id else payload["a"]
            other = conn.execute(
                "SELECT name FROM persons WHERE id = %s", (other_id,)
            ).fetchone()
            other_name = (other_id, str(other["name"]) if other else other_id)

    traits = {k: float(v) for k, v in dict(person["traits"] or {}).items()}
    return {
        "id": person["id"],
        "name": person["name"],
        "org_id": person["org_id"],
        "org_name": person["org_name"],
        "role": person["role"],
        "zone": person["zone"],
        "mood": int(person["mood"]),
        "traits": traits,
        # The words Jev is actually shown, not the numbers behind them.
        "trait_words": {
            k: trait_words(k, v) for k, v in traits.items() if k in _TRAIT_WORDS
        },
        "last_decision": (
            None
            if decision is None
            else {
                "id": int(decision["id"]),
                "sim_time": int(decision["sim_time"]),
                "label": SimTime(int(decision["sim_time"])).label(),
                "question_set": decision["question_set"],
                "source": decision["source"],
                "model": decision["model"],
                "chosen": decision["chosen"],
                "distributions": decision["distributions"],
                "draws": decision["draws"],
            }
        ),
        "last_encounter": (
            None
            if met is None or other_name is None
            else {
                "seq": int(met["seq"]),
                "label": SimTime(int(met["sim_time"])).label(),
                "with_id": other_name[0],
                "with_name": other_name[1],
                "zone": met["payload"]["zone"],
                "topic": met["payload"]["topic"],
                "initiated": met["payload"]["a"] == person_id,
                "led_to": sorted(met["led_to"] or []),
            }
        ),
    }


@app.get("/episodes")
def episode_list(
    limit: int = Query(20, ge=1, le=100),
    before: int | None = Query(None, description="episodes with an id below this"),
) -> dict[str, object]:
    """Meetings that got more than one round, newest first (WORLD-0006)."""

    with _db() as conn:
        # Cast the cursor: an untyped NULL leaves Postgres unable to infer the
        # parameter's type at all, and the first unpaged request is the one that
        # sends it.
        rows = conn.execute(
            "SELECT id FROM episodes WHERE (%s::bigint IS NULL OR id < %s::bigint) "
            "ORDER BY id DESC LIMIT %s",
            (before, before, limit + 1),
        ).fetchall()
        more = len(rows) > limit
        return {
            "episodes": [_episode(conn, int(row["id"])) for row in rows[:limit]],
            "more": more,
        }


@app.get("/episodes/{episode_id}")
def episode_detail(episode_id: int) -> dict[str, object]:
    """One episode: who was there, what each of them did each round, and what
    it changed.

    There is no prose here and none is rendered on request. An encounter has a
    dialogue endpoint because a single exchange reads as a line or two; an
    episode's record *is* the acts, and a reader following what a conversation
    changed wants `led_to`, not a transcript (GEN-0001).
    """

    with _db() as conn:
        return _episode(conn, episode_id)


def _episode(conn: Connection[DictRow], episode_id: int) -> dict[str, object]:
    row = conn.execute(
        "SELECT id, zone, stake, stake_ref, depth, parent_id, opened_sim, opened_seq, "
        "closed_sim, closed_seq, rounds, exit_reason, outcome FROM episodes "
        "WHERE id = %s",
        (episode_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no episode {episode_id}")

    people = conn.execute(
        "SELECT p.person_id, p.seat, p.left_round, s.name, s.org_id, s.role "
        "FROM episode_participants p JOIN persons s ON s.id = p.person_id "
        "WHERE p.episode_id = %s ORDER BY p.seat",
        (episode_id,),
    ).fetchall()
    rounds = conn.execute(
        "SELECT payload FROM events WHERE kind = 'episode.round' "
        "AND (payload->>'episode_id')::bigint = %s ORDER BY seq",
        (episode_id,),
    ).fetchall()

    # Who could have settled it, from the acts they were actually offered. The
    # role is not stored: it is a property of the stake, and storing it twice
    # would let the two copies disagree.
    acts_by_person: dict[str, set[str]] = {}
    for entry in rounds:
        for act in entry["payload"].get("acts", []):
            acts_by_person.setdefault(str(act["person_id"]), set()).add(str(act["act"]))

    def role_in_stake(person_id: str) -> str:
        acts = acts_by_person.get(person_id, set())
        if "promise" in acts or "decline" in acts:
            return "holder"
        if "press" in acts:
            return "asker"
        return "bystander"

    led_to: list[dict[str, Any]] = []
    if row["closed_seq"] is not None:
        led_to = _rows(
            "SELECT seq, sim_time, kind, actor_id, org_id, payload, causes FROM events "
            "WHERE %s = ANY(causes) ORDER BY seq",
            (int(row["closed_seq"]),),
        )
        for event in led_to:
            event["label"] = SimTime(int(event["sim_time"])).label()

    return {
        "id": int(row["id"]),
        "zone": row["zone"],
        "stake": row["stake"],
        "stake_ref": row["stake_ref"],
        "depth": int(row["depth"]),
        "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
        "opened_sim": int(row["opened_sim"]),
        "opened_label": SimTime(int(row["opened_sim"])).label(),
        "opened_seq": int(row["opened_seq"]),
        "closed_sim": int(row["closed_sim"]) if row["closed_sim"] is not None else None,
        "closed_seq": int(row["closed_seq"]) if row["closed_seq"] is not None else None,
        "rounds": int(row["rounds"]),
        "exit_reason": row["exit_reason"],
        "outcome": {
            "pressed": bool(row["outcome"].get("pressed")),
            "promised": bool(row["outcome"].get("promised")),
            "refused": bool(row["outcome"].get("refused")),
            "tension": int(row["outcome"].get("tension", 0)),
            "facts_passed": int(row["outcome"].get("facts_passed", 0)),
            "ontology_gaps": int(row["outcome"].get("ontology_gaps", 0)),
        },
        "participants": [
            {
                "person_id": str(person["person_id"]),
                "name": str(person["name"]),
                "org_id": person["org_id"],
                "role": str(person["role"]),
                "seat": int(person["seat"]),
                "left_round": (
                    int(person["left_round"])
                    if person["left_round"] is not None
                    else None
                ),
                "role_in_stake": role_in_stake(str(person["person_id"])),
            }
            for person in people
        ],
        "round_log": [
            {
                "round": int(entry["payload"].get("round", index)),
                "acts": [
                    {
                        "person_id": str(act["person_id"]),
                        "act": str(act["act"]),
                        "seat": int(act["seat"]),
                    }
                    for act in entry["payload"].get("acts", [])
                ],
                "left": list(entry["payload"].get("left", [])),
                "tension": int(entry["payload"].get("tension", 0)),
                "decided_by": str(entry["payload"].get("decided_by", "rules")),
            }
            for index, entry in enumerate(rounds)
        ],
        "led_to": led_to,
    }


@app.get("/orgs/{org_id}")
def org_detail(org_id: str) -> dict[str, object]:
    """One firm: its books, its people, and what is going on there."""

    from jeve.world.map import ORG_ZONE

    with _db() as conn:
        org = conn.execute(
            "SELECT id, name, kind FROM orgs WHERE id = %s", (org_id,)
        ).fetchone()
        if org is None or org_id not in ORG_ZONE:
            raise HTTPException(404, f"no org {org_id!r}")
        money = conn.execute(
            "SELECT a.kind, COALESCE(sum(e.amount_cents),0) AS cents "
            "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id = a.id "
            "WHERE a.org_id = %s AND a.kind IN ('cash','receivable') GROUP BY a.kind",
            (org_id,),
        ).fetchall()
        staff = conn.execute(
            "SELECT count(*) AS total, "
            "       count(*) FILTER (WHERE s.zone = %s) AS present "
            "FROM persons p JOIN positions s ON s.person_id = p.id WHERE p.org_id = %s",
            (ORG_ZONE[org_id].value, org_id),
        ).fetchone()
        tickets = conn.execute(
            "SELECT count(*) AS n FROM tickets t "
            "WHERE t.status <> 'closed' AND (%s = 'tallybird' OR t.module_id IN "
            "  (SELECT module_id FROM subscriptions WHERE org_id = %s))",
            (org_id, org_id),
        ).fetchone()
        unpaid = conn.execute(
            "SELECT count(*) AS n FROM invoices WHERE paid_sim IS NULL "
            "AND (from_org_id = %s OR to_org_id = %s)",
            (org_id, org_id),
        ).fetchone()
        affected = conn.execute(
            "SELECT m.id FROM modules m WHERE m.status = 'down' AND (%s = 'tallybird' "
            "  OR m.id IN (SELECT module_id FROM subscriptions WHERE org_id = %s)) "
            "ORDER BY m.id",
            (org_id, org_id),
        ).fetchall()
        blocked = conn.execute(
            "SELECT 1 FROM scheduled WHERE kind = 'invoice.run' AND subject_id = %s "
            "AND (payload->>'blocked')::boolean LIMIT 1",
            (org_id,),
        ).fetchone()

    cents = {str(r["kind"]): int(r["cents"]) for r in money}
    active = [f"{row['id']} outage" for row in affected]
    if blocked is not None:
        active.append("month-end invoicing blocked")
    assert staff is not None and tickets is not None and unpaid is not None
    return {
        "id": org["id"],
        "name": org["name"],
        "kind": org["kind"],
        "zone": ORG_ZONE[org_id].value,
        "cash_cents": cents.get("cash", 0),
        "receivable_cents": cents.get("receivable", 0),
        "staff_present": int(staff["present"]),
        "staff_total": int(staff["total"]),
        "open_tickets": int(tickets["n"]),
        "unpaid_invoices": int(unpaid["n"]),
        "active": active,
    }


# -- prose, on demand (GEN-0001) -------------------------------------------

_gateway: Any = None
_gateway_lock = asyncio.Lock()


async def _open_gateway() -> Any:
    """The API's own gateway, opened the first time prose is asked for.

    This is the only endpoint in the API that can spend money, and it does so
    through the same budget-guarded module as everything else (LLM-0004).
    """

    global _gateway
    from jeve.llm import Gateway

    async with _gateway_lock:
        if _gateway is None:
            gateway = Gateway()
            await gateway.start()
            _gateway = gateway
    return _gateway


@app.get("/encounters/{seq}/dialogue")
async def encounter_dialogue(
    seq: int, generate: bool = Query(True, description="false: cached prose only")
) -> dict[str, object]:
    """One encounter: the typed record always, and prose if it can be had.

    The typed record is what happened. The prose is a rendering of it for a
    reader — generated on demand, cached by content hash, and read by nothing.
    """

    from jeve.config import load_settings
    from jeve.decide.recorder import insert_call
    from jeve.errors import JeveError
    from jeve.gen import dialogue
    from jeve.llm import GENERATIVE_PREFERENCE, ChatRequest

    def look() -> tuple[Any, Any]:
        with _db() as conn:
            found = dialogue.load_encounter(conn, seq)
            if found is None:
                return None, None
            return found, dialogue.cached(conn, found, GENERATIVE_PREFERENCE)

    encounter, prose = await asyncio.to_thread(look)
    if encounter is None:
        raise HTTPException(404, f"event {seq} is not an encounter")
    body: dict[str, object] = {
        "typed": encounter.typed(),
        "prose": prose,
        "reason": None,
    }
    if prose is not None or not generate:
        if prose is None:
            body["reason"] = "not rendered yet"
        return body

    # GEN-0001/OPS-0001: this endpoint can spend money and the API is public.
    # Production runs with JEVE_DIALOGUE_GENERATE=off — the frontend is
    # read-only, so prose is rendered by whoever runs the daemon, not by
    # anyone who can reach a URL.
    settings = load_settings()
    if not settings.dialogue_generate:
        body["reason"] = "prose generation is off on this deployment"
        return body
    if not settings.openrouter_api_key:
        body["reason"] = "no API key here, so only the typed record is shown"
        return body

    # The root of this trace, opened only once prose is actually going to be
    # asked for: a cached hit or a read-only deployment returns above, and
    # neither is worth a span. The per-model `chat.completion` spans nest
    # under it on their own — same task, same loop, so the ambient parent is
    # already right (LLM-0009).
    with tracing.span(
        "dialogue", type="task", input={"seq": seq, "typed": encounter.typed()}
    ) as span:
        failures: list[str] = []
        try:
            gateway = await _open_gateway()
            models = gateway.generative_models
        except JeveError as error:
            body["reason"] = f"the model gateway would not start: {error}"
            span.log(
                output={"reason": body["reason"]},
                metadata={"outcome": "gateway-unavailable"},
            )
            return body

        for model in models:
            request = ChatRequest(
                model=model,
                messages=dialogue.messages_for(encounter),
                max_tokens=dialogue.MAX_TOKENS,
                seed=seq,
                response_schema=dialogue.SCHEMA,
            )
            try:
                # `explore`: prose is never gate work, so it is the first thing the
                # budget ladder refuses.
                reply = await gateway.complete(request, purpose="explore")
            except JeveError as error:
                failures.append(f"{model}: {type(error).__name__}")
                continue
            lines = dialogue.parse_lines(reply.text)
            if not lines:
                failures.append(f"{model}: unusable reply")
                continue

            def keep(model: str = model, reply: Any = reply) -> None:
                with _db() as conn:
                    insert_call(
                        conn,
                        {
                            "hash": dialogue.request_key(model, encounter),
                            "kind": dialogue.KIND,
                            "model": model,
                            "provider": reply.provider,
                            "request": {"typed": encounter.typed()},
                            "response": {"text": reply.text},
                            "input_tokens": reply.usage.input_tokens,
                            "output_tokens": reply.usage.output_tokens,
                            "cost_usd": reply.usage.cost_usd,
                            "cost_estimated": reply.usage.cost_is_estimated,
                            "latency_s": reply.latency_s,
                        },
                    )

            await asyncio.to_thread(keep)
            # Always an object, so `output` has one shape whichever path the
            # render took: `lines` when it worked, `reason` when it did not.
            span.log(
                output={"lines": lines},
                metadata={"model": model, "outcome": "ok", "skipped": failures},
            )
            body["prose"] = {
                "lines": lines,
                "model": model,
                "cost_usd": reply.usage.cost_usd,
                "cached": False,
                # Models earlier in the preference order that did not deliver.
                "skipped": failures,
            }
            return body

        body["reason"] = "no model produced usable dialogue: " + "; ".join(failures)
        span.log(
            output={"reason": body["reason"]},
            metadata={"outcome": "no-usable-reply", "skipped": failures},
        )
        return body


# -- /stream: one poll for every viewer ------------------------------------

_POLL_S = 0.5
_BATCH = 500
_QUEUE_DEPTH = 1000
_KEEPALIVE_S = 5.0

_RESYNC = None
"""Sentinel in a subscriber queue: it fell 1000 events behind, so the frames it
was holding are dropped and it refetches from its own cursor instead."""


class _StreamHub:
    """One database poll, fanning out to every subscriber.

    Per-viewer polling was the audit's worst number: each open stream cost a
    fresh TLS connection every half second. The poll loop owns `_high`, the
    greatest `seq` it has fetched; a subscriber catches itself up to that
    watermark directly, then takes what comes after off its queue. Dedup is a
    `seq` comparison, so an item queued mid-catch-up can never repeat a frame.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._subs: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._high = 0

    def subscribe(self, after: int) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=_QUEUE_DEPTH
        )
        self._subs.add(queue)
        alive = (
            self._task is not None
            and not self._task.done()
            and self._task.get_loop() is asyncio.get_running_loop()
        )
        if not alive:
            # Keep `_high`: a stale poller's watermark is still history this
            # subscriber catches up itself, and two live pollers could push
            # the same events out of order — a gap dedup cannot fix.
            self._high = max(self._high, after)
            self._task = asyncio.create_task(self._poll())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._subs.discard(queue)

    async def _poll(self) -> None:
        while self._subs:
            try:
                rows = await asyncio.to_thread(
                    _rows,
                    "SELECT seq, sim_time, tick_seq, kind, actor_id, org_id, "
                    "payload, causes FROM events "
                    "WHERE seq > %s ORDER BY seq LIMIT %s",
                    (self._high, _BATCH),
                )
            except Exception:
                # A dead database is /health's story to tell; the stream just
                # waits for it to come back.
                await asyncio.sleep(_POLL_S)
                continue
            for row in rows:
                row["label"] = SimTime(int(row["sim_time"])).label()
                self._high = int(row["seq"])
                for queue in self._subs:
                    try:
                        queue.put_nowait(row)
                    except asyncio.QueueFull:
                        while not queue.empty():
                            queue.get_nowait()
                        queue.put_nowait(_RESYNC)
            await asyncio.sleep(_POLL_S)


_hub = _StreamHub()


@app.get("/stream")
async def stream(
    after: int = Query(0, ge=0),
    lifetime_s: float = Query(900.0, gt=0, le=3600),
) -> StreamingResponse:
    """Server-sent events, resumed by `seq`.

    Polling rather than LISTEN/NOTIFY: a tick every few seconds at most, and a
    poll cannot miss an event because the cursor is the sequence itself.

    The connection closes itself after `lifetime_s`. Long-lived streams get
    killed by proxies and sleeping laptops anyway, and a server that recycles
    on its own terms is easier to reason about than one that waits to be cut
    off. Resuming costs nothing because the client already tracks `seq`.
    """

    async def source() -> AsyncIterator[str]:
        cursor = after
        queue = _hub.subscribe(after)
        deadline = asyncio.get_running_loop().time() + lifetime_s
        try:
            while asyncio.get_running_loop().time() < deadline:
                if cursor < _hub._high:
                    # Behind the watermark: catch up straight from the table.
                    rows = await asyncio.to_thread(
                        _rows,
                        "SELECT seq, sim_time, tick_seq, kind, actor_id, "
                        "org_id, payload, causes FROM events "
                        "WHERE seq > %s ORDER BY seq LIMIT %s",
                        (cursor, _BATCH),
                    )
                    for row in rows:
                        row["label"] = SimTime(int(row["sim_time"])).label()
                        cursor = int(row["seq"])
                        yield f"data: {json.dumps(row, default=str)}\n\n"
                    continue
                try:
                    item = await asyncio.wait_for(queue.get(), _KEEPALIVE_S)
                except TimeoutError:
                    # A comment frame keeps proxies and the browser from
                    # timing the connection out during a quiet sim-night.
                    yield ": keepalive\n\n"
                    continue
                if item is _RESYNC or int(item["seq"]) <= cursor:
                    continue
                cursor = int(item["seq"])
                yield f"data: {json.dumps(item, default=str)}\n\n"
            yield ": reconnect\n\n"
        finally:
            _hub.unsubscribe(queue)

    return StreamingResponse(
        source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
