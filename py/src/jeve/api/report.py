"""GET /report: the field report, kept current.

The first field report (the web app's `reports/day-1-in-prod`) was a morning of
read-only queries against production, run once and frozen into a page. This
module is those queries made standing: the same aggregations, recomputed from
whatever the world has done so far, so the numbers on `/reports` are never a
snapshot someone forgot to retake.

Everything here is read from typed rows: ledger entries, decisions' `chosen`
fields, event payloads, incidents. One section reads the decision *request*
(`mood_by_mind`), because the question it answers is what the model was shown,
and the request is the only place that is recorded. It never reads a response's
prose, and nothing here feeds back into the world (CORE-0008: `api` sits
outside the layering).

The whole report is a handful of full scans, so `app.py` memoises it per tick
rather than per request (API-0003).
"""

from __future__ import annotations

import re
from collections import defaultdict
from functools import cache
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.api import detectors
from jeve.core.clock import DAY, HOUR, SimTime
from jeve.decide.questions import MIND_WORDS
from jeve.world.map import BUILDINGS, ORG_ZONE, Zone, find_path, town

_OUTAGE_ON_MIND = re.compile(r"^The (\S+) software has been down")

QUEUE_LENGTH = 5
"""Tiles of queue drawn outside the cafe door in the town replay."""


def aggregate(conn: Connection[DictRow], now: SimTime) -> dict[str, object]:
    """Every section of the report except the clock, which the caller owns."""

    first_row = conn.execute("SELECT min(sim_time) AS first FROM events").fetchone()
    first = (
        int(first_row["first"])
        if first_row and first_row["first"] is not None
        else now.seconds
    )
    first_day = SimTime(first).day
    staff = [
        dict(row)
        for row in conn.execute(
            "SELECT id, name, org_id, role, traits FROM persons "
            "WHERE kind = 'staff' ORDER BY id"
        ).fetchall()
    ]
    return {
        "model": _model(conn),
        "vitals": _vitals(conn, now, first_day),
        "cash": _cash(conn, first_day, now.day),
        "cache_by_day": _cache_by_day(conn),
        "calls": _calls(conn),
        **_whereabouts(conn, staff, now),
        "cafe_by_hour": _cafe_by_hour(conn),
        "mood_by_mind": _mood_by_mind(conn),
        "payroll": _payroll(conn),
        "collections": _collections(conn, now),
        "households": _households(conn),
        "outages": _outages(conn),
        "topics": [
            {"topic": str(r["topic"]), "n": int(r["n"])}
            for r in conn.execute(
                "SELECT payload->>'topic' AS topic, count(*) AS n FROM events "
                "WHERE kind = 'encounter' AND payload ? 'topic' "
                "GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        ],
        "knowledge": _knowledge(conn),
        "detectors": detectors.run(conn, now),
        "answers": _answers(conn),
        "cast": cast(
            [
                (str(s["id"]), str(s["name"]), str(s["org_id"]), str(s["role"]))
                for s in staff
            ]
        ),
        "queue": [list(tile) for tile in queue()],
    }


def _model(conn: Connection[DictRow]) -> str | None:
    """The dated build that answered the most recent modelled decision."""

    row = conn.execute(
        "SELECT COALESCE(m.response->>'model', m.model) AS model "
        "FROM decisions d JOIN model_calls m ON m.hash = d.model_call "
        "ORDER BY d.id DESC LIMIT 1"
    ).fetchone()
    return str(row["model"]) if row else None


def _vitals(
    conn: Connection[DictRow], now: SimTime, first_day: int
) -> dict[str, object]:
    row = conn.execute(
        "SELECT (SELECT count(*) FROM events) AS events, "
        "       (SELECT count(*) FROM decisions) AS decisions, "
        "       (SELECT count(*) FROM decisions WHERE model_call IS NOT NULL) "
        "         AS modelled, "
        "       (SELECT count(DISTINCT model_call) FROM decisions) AS calls, "
        "       (SELECT count(*) FROM ledger_entries) AS entries, "
        "       (SELECT COALESCE(sum(amount_cents), 0) FROM ledger_entries) "
        "         AS imbalance, "
        # Priced as /economics prices it: each call this run used, once, at
        # what it cost when it was first made.
        "       (SELECT COALESCE(sum(cost_usd), 0) FROM model_calls WHERE hash IN "
        "          (SELECT DISTINCT model_call FROM decisions "
        "           WHERE model_call IS NOT NULL)) AS usd, "
        "       (SELECT count(*) FROM incidents) AS incidents, "
        "       (SELECT count(*) FROM incidents WHERE escalated_sim IS NOT NULL) "
        "         AS escalated, "
        "       (SELECT count(*) FROM events WHERE kind = 'ticket.escalated') "
        "         AS escalations, "
        "       (SELECT count(*) FROM events WHERE kind = 'ticket.escalated' "
        "          AND payload->>'zone' = 'cafe') AS escalations_in_cafe"
    ).fetchone()
    assert row is not None
    persons = {
        str(r["kind"]): int(r["n"])
        for r in conn.execute(
            "SELECT kind, count(*) AS n FROM persons GROUP BY kind"
        ).fetchall()
    }
    modelled, calls = int(row["modelled"]), int(row["calls"])
    return {
        "sim_days": max(1, now.day - first_day),
        "events": int(row["events"]),
        "decisions": int(row["decisions"]),
        "modelled": modelled,
        "distinct_calls": calls,
        "cache_hit_rate": round(1 - calls / modelled, 4) if modelled else 0.0,
        "spend_usd": round(float(row["usd"]), 6),
        "ledger_entries": int(row["entries"]),
        "ledger_imbalance_cents": int(row["imbalance"]),
        "incidents": int(row["incidents"]),
        "incidents_escalated": int(row["escalated"]),
        "escalations": int(row["escalations"]),
        "escalations_in_cafe": int(row["escalations_in_cafe"]),
        "persons": persons,
    }


def _cash(conn: Connection[DictRow], first_day: int, today: int) -> dict[str, object]:
    """Every cash account's balance at the end of each sim-day."""

    accounts = conn.execute(
        "SELECT id, org_id, name FROM accounts WHERE kind = 'cash' ORDER BY id"
    ).fetchall()
    moves: dict[str, dict[int, int]] = defaultdict(dict)
    opening: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        "SELECT e.account_id, t.sim_time / %s AS dd, sum(e.amount_cents) AS cents "
        "FROM ledger_entries e JOIN ledger_txns t ON t.id = e.txn_id "
        "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash' "
        "GROUP BY 1, 2",
        (DAY,),
    ).fetchall():
        day, cents = int(r["dd"]), int(r["cents"])
        if day < first_day:
            # Seeded before the first event: an opening balance, not a move.
            opening[str(r["account_id"])] += cents
        else:
            moves[str(r["account_id"])][day] = cents
    days = range(first_day, max(first_day, today) + 1)
    series = []
    for account in accounts:
        key = str(account["id"])
        balance, values = opening[key], []
        for day in days:
            balance += moves[key].get(day, 0)
            values.append(balance)
        series.append(
            {
                "account_id": key,
                "org_id": account["org_id"],
                "name": str(account["name"]),
                "values": values,
            }
        )
    return {"first_day": first_day, "series": series}


def _cache_by_day(conn: Connection[DictRow]) -> list[dict[str, int]]:
    """Modelled decisions per sim-day, and how many needed a call never made
    before. The difference is what the cache answered."""

    total = {
        int(r["dd"]): int(r["n"])
        for r in conn.execute(
            "SELECT sim_time / %s AS dd, count(*) AS n FROM decisions "
            "WHERE model_call IS NOT NULL GROUP BY 1",
            (DAY,),
        ).fetchall()
    }
    new = {
        int(r["dd"]): int(r["n"])
        for r in conn.execute(
            "SELECT dd, count(*) AS n FROM ("
            "  SELECT min(sim_time) / %s AS dd FROM decisions "
            "  WHERE model_call IS NOT NULL GROUP BY model_call"
            ") first_use GROUP BY dd",
            (DAY,),
        ).fetchall()
    }
    return [
        {"day": day, "decisions": n, "new_calls": new.get(day, 0)}
        for day, n in sorted(total.items())
    ]


def _calls(conn: Connection[DictRow]) -> list[dict[str, object]]:
    cost = {
        str(r["qs"]): float(r["usd"])
        for r in conn.execute(
            "SELECT u.question_set AS qs, sum(m.cost_usd) AS usd FROM "
            "  (SELECT DISTINCT question_set, model_call FROM decisions "
            "   WHERE model_call IS NOT NULL) u "
            "JOIN model_calls m ON m.hash = u.model_call GROUP BY 1"
        ).fetchall()
    }
    return [
        {
            "question_set": str(r["qs"]),
            "decisions": int(r["decisions"]),
            "gated": int(r["gated"]),
            "calls": int(r["calls"]),
            "usd": round(cost.get(str(r["qs"]), 0.0), 6),
        }
        for r in conn.execute(
            "SELECT question_set AS qs, count(*) AS decisions, "
            "       count(*) FILTER (WHERE model_call IS NULL) AS gated, "
            "       count(DISTINCT model_call) AS calls "
            "FROM decisions GROUP BY 1 ORDER BY calls DESC, decisions DESC, 1"
        ).fetchall()
    ]


def _whereabouts(
    conn: Connection[DictRow], staff: list[dict[str, Any]], now: SimTime
) -> dict[str, object]:
    """Where staff spent their time, and how they spent their ticks.

    Time at the cafe is walked from `agent.moved`: each move opens an interval
    in its `to_zone` that the person's next move closes. That is typed, and it
    holds for a rules-only world where no decision has a request to read.
    """

    on_map: dict[str, float] = defaultdict(float)
    at_cafe: dict[str, float] = defaultdict(float)
    hour_on_map: dict[int, float] = defaultdict(float)
    hour_at_cafe: dict[int, float] = defaultdict(float)
    office = {str(s["id"]) for s in staff if s["org_id"] != "thirdrail"}
    # Each move opens an interval its person's next move closes (the last is
    # still open, until now); intervals at home are off the map. Each is cut
    # at the hour boundaries it crosses, so the database returns a few rows
    # per person and hour of the day rather than every move ever made.
    for r in conn.execute(
        "WITH moves AS ("
        "  SELECT payload->>'person_id' AS person, payload->>'to_zone' AS zone, "
        "         sim_time AS start, lead(sim_time, 1, %(now)s) OVER "
        "           (PARTITION BY payload->>'person_id' ORDER BY seq) AS stop "
        "  FROM events WHERE kind = 'agent.moved'"
        "), spans AS ("
        "  SELECT person, zone, h, LEAST(stop, (h + 1) * %(hour)s) "
        "         - GREATEST(start, h * %(hour)s) AS secs "
        "  FROM moves, generate_series(start / %(hour)s, (stop - 1) / %(hour)s) AS h "
        "  WHERE zone <> %(home)s AND stop > start"
        ") "
        "SELECT person, h %% 24 AS hour, zone = %(cafe)s AS at_cafe, sum(secs) AS secs "
        "FROM spans GROUP BY 1, 2, 3",
        {
            "now": now.seconds,
            "hour": HOUR,
            "home": Zone.HOME.value,
            "cafe": Zone.CAFE.value,
        },
    ).fetchall():
        person, hour, secs = str(r["person"]), int(r["hour"]), float(r["secs"])
        on_map[person] += secs
        if r["at_cafe"]:
            at_cafe[person] += secs
        if person in office:
            hour_on_map[hour] += secs
            if r["at_cafe"]:
                hour_at_cafe[hour] += secs

    ticks = {
        str(r["person_id"]): r
        for r in conn.execute(
            "SELECT person_id, count(*) AS n, "
            "       avg((chosen->>'mood')::float8) AS mood, "
            "       count(*) FILTER (WHERE (chosen->>'interact')::boolean) AS talk "
            "FROM decisions WHERE question_set = 'agent.tick' GROUP BY 1"
        ).fetchall()
    }
    raised: dict[str, int] = defaultdict(int)
    received: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        "SELECT payload->>'raised_by' AS by, payload->>'raised_with' AS with_, "
        "       count(*) AS n FROM events WHERE kind = 'ticket.escalated' GROUP BY 1, 2"
    ).fetchall():
        raised[str(r["by"])] += int(r["n"])
        received[str(r["with_"])] += int(r["n"])

    people = []
    for s in staff:
        pid, traits = str(s["id"]), dict(s["traits"] or {})
        tick = ticks.get(pid)
        n = int(tick["n"]) if tick else 0
        people.append(
            {
                "id": pid,
                "name": str(s["name"]),
                "org_id": str(s["org_id"]),
                "role": str(s["role"]),
                "decisions": n,
                "mood": round(float(tick["mood"]), 3) if tick and n else None,
                "talk_share": round(int(tick["talk"]) / n, 4) if tick and n else 0.0,
                "cafe_share": round(at_cafe[pid] / on_map[pid], 4)
                if on_map[pid]
                else 0.0,
                "raised": raised[pid],
                "received": received[pid],
                "sociability": float(traits.get("sociability", 0.0)),
                "diligence": float(traits.get("diligence", 0.0)),
            }
        )
    return {
        "people": people,
        "office_at_cafe": [
            {
                "hour": hour,
                "share": round(hour_at_cafe[hour] / hour_on_map[hour], 4),
            }
            for hour in sorted(hour_on_map)
            if hour_on_map[hour]
        ],
    }


def _cafe_by_hour(conn: Connection[DictRow]) -> list[dict[str, int]]:
    return [
        {"hour": int(r["hr"]), "sales": int(r["sales"]), "walkouts": int(r["walkouts"])}
        for r in conn.execute(
            "SELECT (sim_time %% %s) / %s AS hr, "
            "       count(*) FILTER (WHERE kind = 'cafe.sale') AS sales, "
            "       count(*) FILTER (WHERE kind = 'cafe.walkout') AS walkouts "
            "FROM events WHERE kind IN ('cafe.sale', 'cafe.walkout') "
            "GROUP BY 1 ORDER BY 1",
            (DAY, HOUR),
        ).fetchall()
    ]


_MIND_KEYS: dict[str, str] = {
    words: ("ordinary" if key == "nothing" else key)
    for key, words in MIND_WORDS.items()
}


def mind_of(on_their_mind: str | None) -> str:
    """`on_their_mind` as a key: `ordinary`, the id of the module that is down,
    one of the money and people states (`unpaid`, `short`, `payday`, ...: see
    `decide.questions.MIND_WORDS`), or `other` for wording this reader has not
    been taught."""

    if on_their_mind in _MIND_KEYS:
        return _MIND_KEYS[on_their_mind]
    found = _OUTAGE_ON_MIND.match(on_their_mind or "")
    return found.group(1) if found else "other"


def _mood_by_mind(conn: Connection[DictRow]) -> list[dict[str, object]]:
    """Mean mood by what the prompt said was on the person's mind.

    Grouped by call before the join, so each request is read once per call
    rather than once per decision that reused it.
    """

    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in conn.execute(
        "WITH t AS ("
        "  SELECT model_call, count(*) AS n, sum((chosen->>'mood')::int) AS mood "
        "  FROM decisions WHERE question_set = 'agent.tick' "
        "  AND model_call IS NOT NULL GROUP BY 1"
        ") "
        "SELECT m.request->'state'->>'on_their_mind' AS mind, "
        "       sum(t.n) AS n, sum(t.mood) AS mood "
        "FROM t JOIN model_calls m ON m.hash = t.model_call GROUP BY 1"
    ).fetchall():
        bucket = totals[mind_of(r["mind"])]
        bucket[0] += float(r["n"])
        bucket[1] += float(r["mood"] or 0)
    return [
        {"mind": mind, "decisions": int(n), "mood": round(mood / n, 3)}
        for mind, (n, mood) in sorted(totals.items(), key=lambda kv: -kv[1][0])
        if n
    ]


def _payroll(conn: Connection[DictRow]) -> list[dict[str, object]]:
    counts = {
        str(r["org"]): r
        for r in conn.execute(
            "SELECT payload->>'org_id' AS org, "
            "  count(*) FILTER (WHERE kind = 'payroll.paid') AS paid, "
            "  count(*) FILTER (WHERE kind = 'payroll.held') AS held, "
            "  max(sim_time) FILTER (WHERE kind = 'payroll.paid') AS last_paid "
            "FROM events WHERE kind IN ('payroll.paid', 'payroll.held') GROUP BY 1"
        ).fetchall()
    }
    warnings = {
        str(r["org_id"]): int(r["n"])
        for r in conn.execute(
            "SELECT org_id, count(*) AS n FROM events "
            "WHERE kind = 'insolvency.warning' GROUP BY 1"
        ).fetchall()
    }
    out = []
    for org in conn.execute("SELECT id, name FROM orgs ORDER BY id").fetchall():
        row = counts.get(str(org["id"]))
        last = row["last_paid"] if row else None
        out.append(
            {
                "org_id": str(org["id"]),
                "name": str(org["name"]),
                "paid": int(row["paid"]) if row else 0,
                "held": int(row["held"]) if row else 0,
                "last_paid_day": SimTime(int(last)).day if last is not None else None,
                "insolvency_warnings": warnings.get(str(org["id"]), 0),
            }
        )
    return out


def _collections(conn: Connection[DictRow], now: SimTime) -> dict[str, object]:
    paid = conn.execute(
        "SELECT count(*) AS n, avg(days_late)::float8 AS mean, max(days_late) AS max "
        "FROM payments"
    ).fetchone()
    book = conn.execute(
        "SELECT count(*) FILTER (WHERE paid_sim IS NULL AND written_off_sim IS NULL) "
        "         AS open, "
        "       count(*) FILTER (WHERE paid_sim IS NULL AND written_off_sim IS NULL "
        "                        AND due_sim < %s) AS overdue, "
        "       count(*) FILTER (WHERE written_off_sim IS NOT NULL) AS written_off "
        "FROM invoices",
        (now.seconds,),
    ).fetchone()
    assert paid is not None and book is not None
    return {
        "paid": int(paid["n"]),
        "mean_days_late": round(float(paid["mean"]), 2)
        if paid["mean"] is not None
        else None,
        "max_days_late": int(paid["max"]) if paid["max"] is not None else None,
        "open": int(book["open"]),
        "overdue": int(book["overdue"]),
        "written_off": int(book["written_off"]),
    }


def _households(conn: Connection[DictRow]) -> dict[str, int]:
    """Wages in, spending out, from the household sector's own accounts."""

    sums = {
        str(r["kind"]): int(r["cents"])
        for r in conn.execute(
            "SELECT a.kind, COALESCE(sum(e.amount_cents), 0) AS cents "
            "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id = a.id "
            "WHERE a.org_id IS NULL AND a.kind IN ('revenue', 'expense') "
            "GROUP BY 1"
        ).fetchall()
    }
    # Income is a credit, so it sums negative.
    return {
        "wages_cents": -sums.get("revenue", 0),
        "spending_cents": sums.get("expense", 0),
    }


def _outages(conn: Connection[DictRow]) -> list[dict[str, object]]:
    tickets = {
        str(r["module_id"]): int(r["n"])
        for r in conn.execute(
            "SELECT module_id, count(*) AS n FROM tickets GROUP BY 1"
        ).fetchall()
    }

    def minutes(value: object) -> float | None:
        return round(float(value) / 60, 1) if value is not None else None  # type: ignore[arg-type]

    return [
        {
            "module_id": str(r["id"]),
            "name": str(r["name"]),
            "incidents": int(r["n"]),
            "escalated": int(r["escalated"]),
            "minutes_to_escalate": minutes(r["to_escalate"]),
            "minutes_escalated": minutes(r["long_escalated"]),
            "minutes_not_escalated": minutes(r["long_not"]),
            "tickets": tickets.get(str(r["id"]), 0),
        }
        for r in conn.execute(
            "SELECT m.id, m.name, count(i.id) AS n, "
            "  count(i.escalated_sim) AS escalated, "
            "  avg(i.escalated_sim - i.started_sim)::float8 AS to_escalate, "
            "  avg(i.ended_sim - i.started_sim) FILTER "
            "    (WHERE i.escalated_sim IS NOT NULL)::float8 AS long_escalated, "
            "  avg(i.ended_sim - i.started_sim) FILTER "
            "    (WHERE i.escalated_sim IS NULL)::float8 AS long_not "
            "FROM modules m LEFT JOIN incidents i ON i.module_id = m.id "
            "GROUP BY 1, 2 ORDER BY 1"
        ).fetchall()
    ]


def _knowledge(conn: Connection[DictRow]) -> dict[str, int]:
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE hops = 0) AS first_hand, "
        "       count(*) FILTER (WHERE hops > 0) AS relayed, "
        "       (SELECT count(*) FROM events WHERE kind = 'encounter') AS encounters "
        "FROM knowledge"
    ).fetchone()
    assert row is not None
    return {k: int(v) for k, v in dict(row).items()}


def answer(distributions: dict[str, Any]) -> dict[str, object]:
    """A decision's distributions as the answer table shows them: a yes/no
    question collapses to P(yes); anything else keeps its distribution."""

    out: dict[str, object] = {}
    for question, dist in distributions.items():
        if isinstance(dist, dict) and set(dist) == {"yes", "no"}:
            out[question] = float(dist["yes"])
        else:
            out[question] = dist
    return out


ANSWER_ROWS = 60
"""Calls per question set in the answer tables, most used first. The small sets
are well under it; `episode.round` carries a roster and a history, so it mints
a new call per meeting and would otherwise grow without bound."""


def _answers(conn: Connection[DictRow]) -> dict[str, list[dict[str, object]]]:
    """The distinct calls outside `agent.tick`: the state each was asked about
    and what came back. Those sets are small enough to read as lookup tables;
    `agent.tick` is tens of thousands of rows and is left out."""

    out: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in conn.execute(
        "WITH u AS ("
        "  SELECT model_call, question_set, count(*) AS uses, min(id) AS first, "
        "         row_number() OVER (PARTITION BY question_set "
        "                            ORDER BY count(*) DESC, min(id)) AS rank "
        "  FROM decisions WHERE question_set <> 'agent.tick' "
        "  AND model_call IS NOT NULL GROUP BY 1, 2"
        ") "
        "SELECT u.question_set, u.uses, m.request->'state' AS state, d.distributions "
        "FROM u JOIN model_calls m ON m.hash = u.model_call "
        "JOIN decisions d ON d.id = u.first WHERE u.rank <= %s "
        "ORDER BY u.question_set, u.rank",
        (ANSWER_ROWS,),
    ).fetchall():
        out[str(r["question_set"])].append(
            {
                "uses": int(r["uses"]),
                "state": dict(r["state"] or {}),
                "ans": answer(dict(r["distributions"] or {})),
            }
        )
    return dict(out)


@cache
def queue() -> tuple[tuple[int, int], ...]:
    """The tiles a queue forms on outside the cafe door, nearest first."""

    cafe = next(b for b in BUILDINGS if b.zone is Zone.CAFE)
    step = 1 if cafe.faces_south else -1
    x, y = cafe.door
    return tuple((x, y + step * k) for k in range(1, QUEUE_LENGTH + 1))


type Staff = tuple[str, str, str, str]
"""(id, name, org_id, role), in id order: the order the engine hands out seats."""


def cast(staff: list[Staff]) -> list[dict[str, object]]:
    """Who the town replay draws, where they sit, and their walk to the cafe."""

    return [
        {
            "id": pid,
            "name": name,
            "org_id": org,
            "role": role,
            "seat": list(seat),
            "spot": list(spot),
            "path": [list(tile) for tile in path],
        }
        for (pid, name, org, role), (seat, spot, path) in zip(
            staff, _routes(tuple(staff)), strict=True
        )
    ]


type Tile = tuple[int, int]


@cache
def _routes(
    staff: tuple[Staff, ...],
) -> tuple[tuple[Tile, Tile, tuple[Tile, ...]], ...]:
    """Seat, cafe spot and the path between them, per person.

    Seats follow `world.space.load_agents`: the n-th of an org's staff by id
    works at the n-th seat of its zone. Office staff take the cafe's visitor
    spots in turn; the cafe's own staff are already there. Static for a given
    staff list, so it is worked out once per process.
    """

    plan = town()
    visitors = plan.visitor_spots[Zone.CAFE]
    seen: dict[str, int] = defaultdict(int)
    routes: list[tuple[Tile, Tile, tuple[Tile, ...]]] = []
    guests = 0
    for _, _, org, _ in staff:
        zone = ORG_ZONE[org]
        seats = plan.seats[zone]
        seat = seats[seen[org] % len(seats)]
        seen[org] += 1
        if zone is Zone.CAFE:
            routes.append((seat, seat, (seat,)))
            continue
        spot = visitors[guests % len(visitors)]
        guests += 1
        routes.append((seat, spot, tuple(find_path(seat, spot))))
    return tuple(routes)
