"""Degeneracy detectors: is this still a world, or has it settled into a rut?
(API-0004; validation survey 02 §3.2 and §3.8.)

The golden field report found a world that ran, balanced its books and meant
little: nobody ever disputed a bill, a support agent chatted in the cafe with
fourteen tickets waiting, and temperament said more about what someone did
than anything that happened to them. Each of those is a number that can be
computed every tick, so each is one here, with the line past which it fires.

A detector is only instrumentation if it has been seen to fire:
`tests/test_detectors.py` breaks a healthy world one way per detector and
checks that the right one, and only it, notices.

Every detector reads the last seven sim-days, so a long-running world is
judged on how it behaves now, not on an average over its whole life.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.clock import DAY, HOUR, SimTime
from jeve.decide.questions import trait_level
from jeve.world.map import ORG_ZONE, Zone

WINDOW = 7 * DAY
MIN_DECISIONS = 50
"""Below this, a share is noise, and the detector says it cannot tell."""

SUPPORT_ROLES = ("support", "support_lead")
BACKLOG = 8
IDLE_SHARE = 0.30

ACTIONS: tuple[tuple[str, str], ...] = (
    # The main act of each decision a lot of people take: if one of these
    # always comes out the same, the question has stopped deciding anything.
    ("agent.tick", "next_zone"),
    ("agent.tick", "interact"),
    ("agent.tick", "mood"),
    ("cafe.purchase", "buy"),
    ("payment.timing", "pay"),
    ("file.ticket", "file"),
    ("file.ticket", "workaround"),
    ("ticket.answer", "answer_now"),
    ("ticket.triage", "severity"),
    ("ticket.confirm", "confirm"),
    ("vendor.trust", "trust"),
    ("time.log", "log"),
    ("invoice.dispute", "dispute"),
    ("subscription.renew", "renew"),
    ("episode.round", "act"),
)
ROLE_INFORMATION = 0.05

NEGATIVE_EVENTS: tuple[str, ...] = (
    # Friction between people and firms. Outages are weather, not conflict,
    # and are left out: a world where the software breaks and nobody minds is
    # exactly the degenerate one.
    "cafe.walkout",
    "catering.declined",
    "close.deferred",
    "close.rework",
    "escalation.dropped",
    "firm.failed",
    "insolvency.warning",
    "invoice.blocked",
    "invoice.disputed",
    "invoice.written_off",
    "payroll.held",
    "payroll.missed",
    "promise.broken",
    "rent.late",
    "staff.left",
    "subscription.cancelled",
    "supplier.unpaid",
    "time.lost",
)

MONEY_VELOCITY = 0.05
"""Share of the cash in the town that changes hands in a week."""

PERSONAS: tuple[tuple[str, str, str], ...] = (
    # A trait and the act it ought to show in: the persona classifier's
    # cheapest form. If the top and bottom tertiles act alike, the trait is
    # decoration (DECIDE-0003).
    ("payment.timing", "pay", "promptness"),
    ("cafe.purchase", "buy", "patience"),
    ("agent.tick", "interact", "sociability"),
    ("ticket.answer", "answer_now", "diligence"),
    ("file.ticket", "file", "vocality"),
)
PERSONA_Z = 2.0

GAP_MASS = 0.35
ONTOLOGY_GAPS = 0.05

TIER1_ROWS = 200
TIER1_REDUNDANT = 0.95


@dataclass(frozen=True, slots=True)
class Reading:
    name: str
    label: str
    value: float | None
    threshold: float
    fires: bool
    detail: str

    def row(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "value": None if self.value is None else round(self.value, 4),
            "threshold": self.threshold,
            "fires": self.fires,
            "detail": self.detail,
        }


WORKING_HOURS = (9, 10, 11, 14, 15, 16)
"""Sampled at half past: the working day, less lunch, when a desk is where
support belongs."""


def idle_with_backlog(conn: Connection[DictRow], since: int, now: int) -> Reading:
    """Support somewhere other than the desk, or home, while tickets wait.

    Measured where people *are*, sampled at half past each working hour, not
    from what they decided: since WORLD-0008 an agent is asked mostly at
    decision points such as lunch, so a count of decisions would be a count of
    lunchtimes.
    """

    desk = ORG_ZONE["tallybird"].value
    people = [
        str(r["id"])
        for r in conn.execute(
            "SELECT id FROM persons WHERE role = ANY(%s)", (list(SUPPORT_ROLES),)
        ).fetchall()
    ]
    moves: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in conn.execute(
        # Two days back: everyone goes home at night, so where each person
        # stood when the window opened is in there.
        "SELECT sim_time, payload->>'person_id' AS person, payload->>'to_zone' AS zone "
        "FROM events WHERE kind = 'agent.moved' AND sim_time BETWEEN %s AND %s "
        "AND payload->>'person_id' = ANY(%s) ORDER BY seq",
        (since - 2 * DAY, now, people),
    ).fetchall():
        moves[str(r["person"])].append((int(r["sim_time"]), str(r["zone"])))
    tickets = [
        (int(r["opened_sim"]), r["answered_sim"])
        for r in conn.execute(
            "SELECT opened_sim, answered_sim FROM tickets WHERE opened_sim <= %s "
            "AND (answered_sim IS NULL OR answered_sim > %s)",
            (now, since),
        ).fetchall()
    ]
    busy = away = 0
    for t in range(since - since % HOUR + HOUR // 2, now, HOUR):
        when = SimTime(t)
        if when.weekday >= 5 or when.time_of_day // HOUR not in WORKING_HOURS:
            continue
        backlog = sum(
            1
            for opened, answered in tickets
            if opened <= t and (answered is None or answered > t)
        )
        if backlog < BACKLOG:
            continue
        for person in people:
            zone = next((z for at, z in reversed(moves[person]) if at <= t), None)
            if zone is None or zone == Zone.HOME.value:
                continue  # not in yet, off sick, or off shift: not idling
            busy += 1
            away += zone != desk
    share = away / busy if busy else None
    return Reading(
        "idle_with_backlog",
        "Support away from the desk with a backlog",
        share,
        IDLE_SHARE,
        share is not None and busy >= 10 and share > IDLE_SHARE,
        f"{away} of {busy} working-hour samples with {BACKLOG}+ tickets waiting "
        "found support somewhere other than the desk",
    )


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0 or len(counts) < 2:
        return 0.0
    h = -sum((n / total) * math.log2(n / total) for n in counts.values() if n)
    return h / math.log2(len(counts))


def action_entropy(conn: Connection[DictRow], since: int) -> Reading:
    """Has any main act collapsed to a single outcome?"""

    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in conn.execute(
        "SELECT d.question_set, e.key, e.value::text AS value, count(*) AS n "
        "FROM decisions d, jsonb_each(d.chosen) e "
        "WHERE d.sim_time >= %s AND d.question_set = ANY(%s) GROUP BY 1, 2, 3",
        (since, sorted({kind for kind, _ in ACTIONS})),
    ).fetchall():
        pair = (str(row["question_set"]), str(row["key"]))
        if pair in ACTIONS and row["value"] != "null":
            counts[pair][str(row["value"])] += int(row["n"])
    measured = {
        pair: _entropy(c) for pair, c in counts.items() if c.total() >= MIN_DECISIONS
    }
    collapsed = sorted(f"{k}.{a}" for (k, a), h in measured.items() if h == 0.0)
    mean = sum(measured.values()) / len(measured) if measured else None
    return Reading(
        "action_entropy",
        "Acts that always come out the same",
        mean,
        0.0,
        bool(collapsed),
        (
            "collapsed: " + ", ".join(collapsed)
            if collapsed
            else f"{len(measured)} main acts measured, none collapsed"
        ),
    )


def role_information(conn: Connection[DictRow], since: int) -> Reading:
    """Does knowing someone's job tell you where they go? Mutual information
    between role and destination, as a share of the destination's entropy."""

    joint: Counter[tuple[str, str]] = Counter()
    for row in conn.execute(
        "SELECT p.role, d.chosen->>'next_zone' AS zone, count(*) AS n "
        "FROM decisions d JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'agent.tick' AND d.sim_time >= %s GROUP BY 1, 2",
        (since,),
    ).fetchall():
        joint[(str(row["role"]), str(row["zone"]))] += int(row["n"])
    total = joint.total()
    if total < MIN_DECISIONS:
        return Reading(
            "role_information",
            "What a person's job says about where they go",
            None,
            ROLE_INFORMATION,
            False,
            "too few decisions to tell",
        )
    roles: Counter[str] = Counter()
    zones: Counter[str] = Counter()
    for (role, zone), n in joint.items():
        roles[role] += n
        zones[zone] += n
    h_zone = -sum((n / total) * math.log2(n / total) for n in zones.values())
    mutual = sum(
        (n / total) * math.log2((n / total) / ((roles[r] / total) * (zones[z] / total)))
        for (r, z), n in joint.items()
    )
    share = mutual / h_zone if h_zone > 0 else 0.0
    return Reading(
        "role_information",
        "What a person's job says about where they go",
        share,
        ROLE_INFORMATION,
        share < ROLE_INFORMATION,
        f"{mutual:.3f} of {h_zone:.3f} bits of destination explained by role",
    )


def negative_events(conn: Connection[DictRow], since: int, days: float) -> Reading:
    """A conflict-free economy is degenerate (the scenario, §6)."""

    rows = conn.execute(
        "SELECT kind, count(*) AS n FROM events WHERE sim_time >= %s "
        "AND kind = ANY(%s) GROUP BY 1 ORDER BY 2 DESC",
        (since, list(NEGATIVE_EVENTS)),
    ).fetchall()
    total = sum(int(r["n"]) for r in rows)
    per_week = total / days * 7 if days else 0.0
    return Reading(
        "negative_events",
        "Friction per week",
        per_week,
        0.0,
        days >= 7 and total == 0,
        ", ".join(f"{r['kind']} {r['n']}" for r in rows[:6]) or "none at all",
    )


def money_velocity(conn: Connection[DictRow], since: int, days: float) -> Reading:
    """How much of the town's cash changes hands in a week."""

    row = conn.execute(
        """
        SELECT
          (SELECT COALESCE(sum(e.amount_cents), 0) FROM ledger_entries e
             JOIN ledger_txns t ON t.id = e.txn_id
             JOIN accounts a ON a.id = e.account_id
           WHERE a.kind = 'cash' AND e.amount_cents > 0 AND t.sim_time >= %s)
            AS moved,
          (SELECT COALESCE(sum(e.amount_cents), 0) FROM ledger_entries e
             JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash')
            AS stock
        """,
        (since,),
    ).fetchone()
    moved = int(row["moved"]) if row else 0
    stock = int(row["stock"]) if row else 0
    weekly = moved / days * 7 if days else 0.0
    velocity = weekly / stock if stock > 0 else None
    return Reading(
        "money_velocity",
        "Share of the town's cash that changes hands in a week",
        velocity,
        MONEY_VELOCITY,
        velocity is not None and days >= 7 and velocity < MONEY_VELOCITY,
        f"${weekly / 100:,.0f} a week moving through ${stock / 100:,.0f} of cash",
    )


def persona_signal(conn: Connection[DictRow], since: int) -> Reading:
    """Do the top and bottom tertiles of a trait act differently?

    Judged by whether any trait shows a gap clear of sampling noise (|z| of a
    two-proportion test at least 2), not by the gap's size: a few hundred
    decisions of pure chance show gaps of a few points, and a threshold on the
    size alone let a world where temperament did nothing pass.
    """

    gaps: list[str] = []
    values: list[float] = []
    clear = 0
    for kind, key, trait in PERSONAS:
        rates: dict[int, list[int]] = {0: [0, 0], 2: [0, 0]}
        for row in conn.execute(
            "SELECT p.traits->%s AS trait, (d.chosen->>%s)::boolean AS did, "
            "count(*) AS n FROM decisions d JOIN persons p ON p.id = d.person_id "
            "WHERE d.question_set = %s AND d.sim_time >= %s "
            "AND jsonb_typeof(d.chosen->%s) = 'boolean' GROUP BY 1, 2",
            (trait, key, kind, since, key),
        ).fetchall():
            level = trait_level(trait, _number(row["trait"]))
            if level in rates:
                rates[level][0] += int(row["n"]) if row["did"] else 0
                rates[level][1] += int(row["n"])
        (low_yes, low_n), (high_yes, high_n) = rates[0], rates[2]
        if low_n < MIN_DECISIONS // 2 or high_n < MIN_DECISIONS // 2:
            continue
        gap = abs(high_yes / high_n - low_yes / low_n)
        pooled = (low_yes + high_yes) / (low_n + high_n)
        noise = math.sqrt(pooled * (1 - pooled) * (1 / low_n + 1 / high_n))
        z = gap / noise if noise > 0 else 0.0
        clear += z >= PERSONA_Z
        values.append(gap)
        gaps.append(f"{trait}→{kind} {gap:.2f} (z {z:.1f})")
    mean = sum(values) / len(values) if values else None
    return Reading(
        "persona_signal",
        "How differently the two ends of a trait act",
        mean,
        PERSONA_Z,
        bool(values) and clear == 0,
        "; ".join(gaps) or "too few decisions at either end of any trait",
    )


def _number(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.5


def ontology_gaps(conn: Connection[DictRow], since: int) -> Reading:
    """How often no offered option fitted (tier 2; `jeve.gen.ontology`)."""

    row = conn.execute(
        "SELECT count(*) AS n, count(*) FILTER (WHERE (q.value->>'other')::float "
        ">= %s) AS gaps FROM decisions d, jsonb_each(d.distributions) q "
        "WHERE d.source IN ('jev', 'llm') AND d.sim_time >= %s AND q.value ? 'other'",
        (GAP_MASS, since),
    ).fetchone()
    n = int(row["n"]) if row else 0
    found = int(row["gaps"]) if row else 0
    rate = found / n if n else None
    return Reading(
        "ontology_gaps",
        "Model answers that reached for 'other'",
        rate,
        ONTOLOGY_GAPS,
        rate is not None and rate > ONTOLOGY_GAPS,
        f"{found} of {n} modelled choices" if n else "no modelled choice yet",
    )


def tier1_redundant(conn: Connection[DictRow], since: int) -> Reading:
    """Tier 1 agreeing with Jev nearly always inside the band buys nothing
    (DECIDE-0005)."""

    row = conn.execute(
        "SELECT count(*) AS n, avg(agrees::int) AS agree FROM escalations "
        "WHERE NOT sampled AND sim_time >= %s",
        (since,),
    ).fetchone()
    n = int(row["n"]) if row else 0
    agree = float(row["agree"]) if row and row["agree"] is not None else None
    return Reading(
        "tier1_redundant",
        "Second opinions that only ever agree",
        agree,
        TIER1_REDUNDANT,
        agree is not None and n >= TIER1_ROWS and agree > TIER1_REDUNDANT,
        f"{n} escalations in band this week" if n else "tier 1 has not run",
    )


def run(conn: Connection[DictRow], now: SimTime) -> list[dict[str, object]]:
    first = conn.execute("SELECT min(sim_time) AS t FROM events").fetchone()
    start = int(first["t"]) if first and first["t"] is not None else now.seconds
    since = max(start, now.seconds - WINDOW)
    days = (now.seconds - since) / DAY
    readings: list[Callable[[], Reading]] = [
        lambda: idle_with_backlog(conn, since, now.seconds),
        lambda: action_entropy(conn, since),
        lambda: role_information(conn, since),
        lambda: negative_events(conn, since, days),
        lambda: money_velocity(conn, since, days),
        lambda: persona_signal(conn, since),
        lambda: ontology_gaps(conn, since),
        lambda: tier1_redundant(conn, since),
    ]
    return [read().row() for read in readings]
