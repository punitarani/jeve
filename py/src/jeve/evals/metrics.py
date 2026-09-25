"""Every number the harness reads from one finished world.

One function, `measure`, and one query per figure, run against the world's own
database after its horizon. Three kinds of figure:

* **plausibility** — the stylized facts `priors.py` holds a band for. Most are
  set by rules (rent, hazards, pay terms), so they move only where a decision
  sits on the path: *who pays late*, not *what late costs*.
* **depth** — whether who someone is, what they remember and whom they have
  met changes what they do. The field report's detectors are reused as they
  are (`jeve.api.detectors`), so the harness and the live report cannot
  disagree about what "persona signal" means.
* **cost and integrity** — what the world cost from a cold cache, the soak's
  invariants at this horizon, and a digest of the event log, which is how two
  runs are shown to be the same run.

A figure a world cannot answer (no episodes, no late bills) is `None`, never
zero: "absent" is a finding of its own (workbench's fidelity bands) and must
not read as a measured value at the bottom of its range.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.api import detectors
from jeve.core.clock import DAY, HOUR, SimTime
from jeve.sim import soak

type Value = float | None


@dataclass(slots=True)
class Measures:
    """One world's numbers, by name, plus what cannot be a number."""

    days: int
    values: dict[str, Value] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    checks_failed: list[str] = field(default_factory=list)
    digest: str = ""

    def as_json(self) -> dict[str, object]:
        return {
            "days": self.days,
            "values": self.values,
            "notes": self.notes,
            "checks_failed": self.checks_failed,
            "digest": self.digest,
        }


def _scalar(
    conn: Connection[DictRow], query: str, params: tuple[object, ...] = ()
) -> Value:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type, unused-ignore]
    if row is None:
        return None
    value = next(iter(row.values()))
    return None if value is None else float(value)


def _ratio(numerator: Value, denominator: Value) -> Value:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


# -- plausibility ---------------------------------------------------------------


def _payments(conn: Connection[DictRow], m: Measures, end: int) -> None:
    """Late payment, the way the trade surveys count it: of the bills that fell
    due inside the run, how many were settled at least a day after their due
    date — counting one still unpaid a day past it at the end as late, since it
    is (right-censored). Days, not seconds: a bill paid on its due date, after
    the hour it fell due, is on time to anyone who keeps books."""

    row = conn.execute(
        "SELECT count(*) FILTER (WHERE paid_sim IS NOT NULL "
        "  AND paid_sim - due_sim < %s) AS on_time, "
        "count(*) FILTER (WHERE paid_sim IS NOT NULL AND paid_sim - due_sim >= %s) "
        "  AS late, "
        "count(*) FILTER (WHERE paid_sim IS NULL AND %s - due_sim >= %s) AS open, "
        "count(*) FILTER (WHERE paid_sim IS NULL AND %s - due_sim < %s) AS not_yet "
        "FROM invoices WHERE due_sim < %s AND written_off_sim IS NULL "
        "AND kind <> 'supplies'",
        (DAY, DAY, end, DAY, end, DAY, end),
    ).fetchone()
    assert row is not None
    due = int(row["on_time"]) + int(row["late"]) + int(row["open"])
    m.values["invoice_late_share"] = (
        (int(row["late"]) + int(row["open"])) / due if due else None
    )
    m.notes["invoice_late_share"] = (
        f"{row['late']} paid a day or more late + {row['open']} unpaid past their "
        f"date, of {due} bills due"
    )
    m.values["days_late_mean"] = _scalar(
        conn,
        "SELECT avg(floor((paid_sim - due_sim)::float / %s)) FROM invoices "
        "WHERE paid_sim - due_sim >= %s AND kind <> 'supplies'",
        (DAY, DAY),
    )
    issued = _scalar(conn, "SELECT count(*) FROM invoices WHERE kind = 'services'")
    disputed = _scalar(
        conn,
        "SELECT count(*) FROM invoices WHERE kind = 'services' "
        "AND disputed_sim IS NOT NULL",
    )
    m.values["dispute_share"] = _ratio(disputed, issued)
    # Why bills were left, as the payers said (WORLD-0013): each reason's share
    # of the bills that were ever left unpaid past their date. The engine
    # stores a gate's reason in the payer's vocabulary (LATE_REASON_OF_GATE).
    reasons: Counter[str] = Counter()
    for r in conn.execute(
        "SELECT late_reason, count(*) AS n FROM invoices "
        "WHERE late_reason IS NOT NULL GROUP BY 1"
    ).fetchall():
        reasons[str(r["late_reason"])] += int(r["n"])
    total = sum(reasons.values())
    for reason in (
        "cash_flow",
        "routine",
        "approval",
        "query",
        "forgot",
        "other_bills",
    ):
        m.values[f"late_reason_{reason}"] = (
            reasons.get(reason, 0) / total if total else None
        )


def _support(conn: Connection[DictRow], m: Measures) -> None:
    """Escalation here is of an outage, not of a ticket: to an engineer in
    person (`ticket.escalated`) or relayed by whoever was cornered
    (`escalation.relayed`, WORLD-0012). Counted per ticket opened, the nearest
    thing to a help desk's escalation rate the world keeps."""

    opened = _scalar(conn, "SELECT count(*) FROM tickets")
    escalated = _scalar(
        conn,
        "SELECT count(*) FROM events "
        "WHERE kind IN ('ticket.escalated', 'escalation.relayed')",
    )
    m.values["ticket_escalation_share"] = _ratio(escalated, opened)
    m.values["ticket_close_hours_median"] = _scalar(
        conn,
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY closed_sim - opened_sim) "
        "/ %s FROM tickets WHERE closed_sim IS NOT NULL",
        (HOUR,),
    )


def _cafe(conn: Connection[DictRow], m: Measures) -> None:
    """The intraday shape of trade: share before eleven, share over lunch."""

    by_hour: Counter[int] = Counter()
    for row in conn.execute(
        "SELECT ((sim_time %% %s) / %s)::int AS h, count(*) AS n FROM cafe_sales "
        "GROUP BY 1",
        (DAY, HOUR),
    ).fetchall():
        by_hour[int(row["h"])] += int(row["n"])
    total = by_hour.total()
    if not total:
        m.values["cafe_morning_share"] = None
        m.values["cafe_lunch_share"] = None
        m.values["cafe_peak_hour"] = None
        return
    m.values["cafe_morning_share"] = sum(by_hour[h] for h in range(0, 11)) / total
    m.values["cafe_lunch_share"] = sum(by_hour[h] for h in (11, 12, 13)) / total
    m.values["cafe_peak_hour"] = float(max(by_hour, key=lambda h: (by_hour[h], -h)))
    walkouts = _scalar(conn, "SELECT count(*) FROM events WHERE kind = 'cafe.walkout'")
    m.values["cafe_walkout_share"] = _ratio(walkouts, (walkouts or 0.0) + total)


def _churn(conn: Connection[DictRow], m: Measures) -> None:
    """Monthly rates, from a run of `days`: subscribers who cancelled, and staff
    who left, each over the population that could have."""

    subs = _scalar(conn, "SELECT count(*) FROM subscriptions")
    cancelled = _scalar(
        conn, "SELECT count(*) FROM subscriptions WHERE cancelled_sim IS NOT NULL"
    )
    # Over the staff the world started with: a replacement hired after a
    # departure is not another person who could have left all along.
    staff = _scalar(
        conn,
        "SELECT (SELECT count(*) FROM persons WHERE kind = 'staff') - "
        "(SELECT count(*) FROM events WHERE kind = 'staff.hired')",
    )
    left = _scalar(
        conn, "SELECT count(*) FROM persons WHERE kind = 'staff' AND status = 'left'"
    )
    month = 30 / m.days if m.days else 0.0
    churn = _ratio(cancelled, subs)
    turnover = _ratio(left, staff)
    m.values["subscription_churn_monthly"] = None if churn is None else churn * month
    m.values["staff_turnover_monthly"] = None if turnover is None else turnover * month


# -- depth ------------------------------------------------------------------------


def _jsd(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Jensen-Shannon divergence in bits, 0 identical to 1 disjoint."""

    keys = set(a) | set(b)
    ta, tb = sum(a.values()) or 1.0, sum(b.values()) or 1.0
    total = 0.0
    for key in keys:
        p, q = a.get(key, 0.0) / ta, b.get(key, 0.0) / tb
        mid = (p + q) / 2
        if p > 0:
            total += 0.5 * p * math.log2(p / mid)
        if q > 0:
            total += 0.5 * q * math.log2(q / mid)
    return total


PROFILE_KEYS = ("interact", "mood", "topic", "next_zone")
MIN_HALF = 12
"""A person needs this many `agent.tick` answers in each half of the run to
have a profile worth comparing."""


def _consistency(conn: Connection[DictRow], m: Measures) -> None:
    """Can people be told apart by what they do, better than a person can be
    told apart from themselves?

    A profile is how often someone's `agent.tick` came out each way. Each
    person's answers are split in two by the parity of their own decision
    number, so both halves sample the same hours and weekdays and differ only
    by chance (a first-half/second-half split measured the calendar: Monday is
    not Thursday). *Retest* is how far a person's two halves are apart — the
    noise floor. *Distinct* is how far two people are apart in the same half.
    Their ratio is above one exactly when individual differences stand clear
    of sampling noise: persona flattening drives it towards one.
    """

    halves: dict[str, list[Counter[str]]] = defaultdict(lambda: [Counter(), Counter()])
    asked: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in conn.execute(
        "SELECT d.person_id, d.decision_seq, d.chosen FROM decisions d "
        "JOIN persons p ON p.id = d.person_id "
        "WHERE d.question_set = 'agent.tick' AND p.kind = 'staff'"
    ).fetchall():
        person = str(row["person_id"])
        side = int(row["decision_seq"]) % 2
        chosen = row["chosen"] or {}
        asked[person][side] += 1
        for key in PROFILE_KEYS:
            if key in chosen and chosen[key] is not None:
                halves[person][side][f"{key}={json.dumps(chosen[key])}"] += 1
    eligible = {p: h for p, h in halves.items() if min(asked[p]) >= MIN_HALF}
    retest = [_jsd(h[0], h[1]) for h in eligible.values()]
    distinct: list[float] = []
    people = sorted(eligible)
    for i, a in enumerate(people):
        for b in people[i + 1 :]:
            distinct.extend(_jsd(eligible[a][k], eligible[b][k]) for k in (0, 1))
    floor = statistics.fmean(retest) if retest else None
    spread = statistics.fmean(distinct) if distinct else None
    m.values["persona_retest_jsd"] = floor
    m.values["persona_distinct_jsd"] = spread
    m.values["identifiability_ratio"] = (
        spread / floor if floor and spread is not None else None
    )
    m.notes["identifiability_ratio"] = (
        f"{len(eligible)} staff with at least {MIN_HALF} answers in each half"
    )


def _memory(conn: Connection[DictRow], m: Measures) -> None:
    """Whether anything travels, is promised, or is believed differently."""

    held = _scalar(conn, "SELECT count(*) FROM knowledge")
    second = _scalar(conn, "SELECT count(*) FROM knowledge WHERE hops > 0")
    m.values["knowledge_secondhand_share"] = _ratio(second, held)
    m.values["knowledge_max_hops"] = _scalar(conn, "SELECT max(hops) FROM knowledge")
    made = _scalar(conn, "SELECT count(*) FROM commitments")
    kept = _scalar(conn, "SELECT count(*) FROM commitments WHERE kept")
    settled = _scalar(conn, "SELECT count(*) FROM commitments WHERE kept IS NOT NULL")
    m.values["promises_per_week"] = (
        None if made is None or not m.days else made * 7 / m.days
    )
    m.values["promise_kept_share"] = _ratio(kept, settled)
    m.values["trust_spread"] = _scalar(
        conn,
        "SELECT stddev_pop((beliefs->>'vendor_reliability')::float) FROM persons "
        "WHERE beliefs ? 'vendor_reliability'",
    )


def _episodes(conn: Connection[DictRow], m: Measures) -> None:
    row = conn.execute(
        "SELECT count(*) AS n, "
        "count(*) FILTER (WHERE exit_reason = 'settled') AS settled, "
        "count(*) FILTER (WHERE exit_reason = 'stalled') AS stalled, "
        "avg(rounds) AS rounds, "
        "count(*) FILTER (WHERE (outcome->>'pressed')::boolean "
        "  OR (outcome->>'promised')::boolean OR (outcome->>'refused')::boolean "
        "  OR (outcome->>'facts_passed')::int > 0) AS moved "
        "FROM episodes WHERE closed_sim IS NOT NULL"
    ).fetchone()
    assert row is not None
    n = int(row["n"])
    m.values["episodes_per_day"] = n / m.days if m.days else None
    m.values["episode_settled_share"] = int(row["settled"]) / n if n else None
    m.values["episode_stalled_share"] = int(row["stalled"]) / n if n else None
    m.values["episode_rounds_mean"] = float(row["rounds"]) if n else None
    m.values["episode_moved_share"] = int(row["moved"]) / n if n else None


def _detectors(conn: Connection[DictRow], m: Measures) -> None:
    """The field report's own readings, over the whole run."""

    since = 0
    days = float(m.days or 1)
    for reading in (
        detectors.action_entropy(conn, since),
        detectors.role_information(conn, since),
        detectors.persona_signal(conn, since),
        detectors.negative_events(conn, since, days),
        detectors.money_velocity(conn, since, days),
        detectors.ontology_gaps(conn, since),
    ):
        m.values[reading.name] = reading.value
        m.notes[reading.name] = reading.detail


def _warnings(conn: Connection[DictRow], m: Measures, end: int) -> None:
    """Every field-report detector over the last week of the run, as the live
    report reads them, and how many of them fire."""

    firing = 0
    for row in detectors.run(conn, SimTime(end)):
        name = str(row["name"])
        value = row["value"]
        m.values[f"detector_{name}"] = None if value is None else float(value)  # type: ignore[arg-type]
        firing += bool(row["fires"])
        if row["fires"]:
            m.notes[f"detector_{name}"] = f"FIRES: {row['detail']}"
    m.values["detectors_firing"] = float(firing)


def _health(conn: Connection[DictRow], m: Measures) -> None:
    """Whether the economy holds up over the run, and how fast money comes in."""

    def count(kind: str) -> float:
        return float(
            _scalar(conn, "SELECT count(*) FROM events WHERE kind = %s", (kind,)) or 0
        )

    m.values["insolvency_warnings"] = count("insolvency.warning")
    m.values["firms_failed"] = count("firm.failed")
    m.values["payroll_held_or_missed"] = count("payroll.held") + count("payroll.missed")
    m.values["staff_left"] = count("staff.left")
    m.values["subscriptions_cancelled"] = count("subscription.cancelled")
    m.values["days_to_collect_mean"] = _scalar(
        conn,
        "SELECT avg((paid_sim - issued_sim)::float / %s) FROM invoices "
        "WHERE paid_sim IS NOT NULL AND kind <> 'supplies'",
        (DAY,),
    )
    m.values["receivables_open_share"] = _scalar(
        conn,
        "SELECT sum(amount_cents) FILTER (WHERE paid_sim IS NULL "
        "AND written_off_sim IS NULL)::float / NULLIF(sum(amount_cents), 0) "
        "FROM invoices WHERE kind <> 'supplies'",
    )


def _drift(conn: Connection[DictRow], m: Measures, end: int) -> None:
    """Does the town behave in its last week as in its first? The population's
    `agent.tick` profile, first seven days against last seven, in bits. A run
    of one week has nothing to compare."""

    if end < 14 * DAY:
        m.values["drift_first_last_week"] = None
        return
    weeks: list[Counter[str]] = [Counter(), Counter()]
    for row in conn.execute(
        "SELECT sim_time, chosen FROM decisions WHERE question_set = 'agent.tick' "
        "AND (sim_time < %s OR sim_time >= %s)",
        (7 * DAY, end - 7 * DAY),
    ).fetchall():
        side = 0 if int(row["sim_time"]) < 7 * DAY else 1
        chosen = row["chosen"] or {}
        for key in PROFILE_KEYS:
            if key in chosen and chosen[key] is not None:
                weeks[side][f"{key}={json.dumps(chosen[key])}"] += 1
    m.values["drift_first_last_week"] = _jsd(weeks[0], weeks[1])


def _ties(conn: Connection[DictRow], m: Measures) -> None:
    """How social life is structured: of all meetings (encounters, and
    episodes' pairs), how many are between people who had met before, and how
    concentrated meetings are on a few pairs. People with friends meet them
    again; stateless agents meet whoever is there (docs/research/04 §3.4)."""

    pairs: list[tuple[str, str]] = []
    for row in conn.execute(
        "SELECT payload->>'a' AS a, payload->>'b' AS b FROM events "
        "WHERE kind = 'encounter' ORDER BY seq"
    ).fetchall():
        if row["a"] and row["b"]:
            pairs.append(tuple(sorted((str(row["a"]), str(row["b"])))))  # type: ignore[arg-type]
    if not pairs:
        m.values["repeat_meeting_share"] = None
        m.values["meetings_top10_pair_share"] = None
        return
    seen: set[tuple[str, str]] = set()
    repeats = 0
    for pair in pairs:
        repeats += pair in seen
        seen.add(pair)
    counts = Counter(pairs)
    top = sum(n for _, n in counts.most_common(10))
    m.values["repeat_meeting_share"] = repeats / len(pairs)
    m.values["meetings_top10_pair_share"] = top / len(pairs)
    m.values["distinct_pairs_met"] = float(len(counts))


def _signal(conn: Connection[DictRow], m: Measures) -> None:
    """How much each record says (WORLD-0013), and how far a consequence
    travels. A decision that kept its facts can be explained after the fact;
    an event that names its causes can be followed; a bill left late with a
    reason can be told apart from one forgotten."""

    m.values["event_payload_fields_mean"] = _scalar(
        conn,
        "SELECT avg((SELECT count(*) FROM jsonb_object_keys(payload))) FROM events "
        "WHERE jsonb_typeof(payload) = 'object'",
    )
    m.values["event_caused_share"] = _scalar(
        conn, "SELECT avg((cardinality(causes) > 0)::int) FROM events"
    )
    m.values["decision_facts_share"] = _scalar(
        conn, "SELECT avg((facts IS NOT NULL)::int) FROM decisions"
    )
    m.values["decision_facts_fields_mean"] = _scalar(
        conn,
        "SELECT avg((SELECT count(*) FROM jsonb_object_keys(facts))) FROM decisions "
        "WHERE jsonb_typeof(facts) = 'object'",
    )
    late = conn.execute(
        "SELECT count(*) AS n, count(late_reason) AS reasoned, "
        "count(reminded_sim) AS reminded, avg(chases) AS chases FROM invoices "
        "WHERE kind <> 'supplies' AND written_off_sim IS NULL AND due_sim < ("
        "  SELECT sim_time FROM sim_meta) - %s AND (paid_sim IS NULL "
        "  OR paid_sim - due_sim >= %s)",
        (DAY, DAY),
    ).fetchone()
    assert late is not None
    n = int(late["n"])
    m.values["late_bill_reason_share"] = int(late["reasoned"]) / n if n else None
    m.values["late_bill_reminded_share"] = int(late["reminded"]) / n if n else None
    m.values["late_bill_chases_mean"] = (
        float(late["chases"]) if n and late["chases"] is not None else None
    )
    # Depth of the causal graph: an event with no causes is depth 0, and one
    # caused by others is one deeper than the deepest of them. Walked in seq
    # order, which is causal order: a cause is always emitted first.
    depth: dict[int, int] = {}
    deep: list[int] = []
    for row in conn.execute("SELECT seq, causes FROM events ORDER BY seq"):
        causes = [int(c) for c in row["causes"] or []]
        d = 1 + max((depth.get(c, 0) for c in causes), default=-1)
        depth[int(row["seq"])] = d
        if d:
            deep.append(d)
    m.values["causal_depth_mean"] = statistics.fmean(deep) if deep else None
    m.values["causal_depth_max"] = float(max(deep)) if deep else None


# -- cost and integrity -------------------------------------------------------------


def _cost(conn: Connection[DictRow], m: Measures) -> None:
    """Cold-cache cost: every distinct call this world's decisions and second
    opinions rest on, priced at what it was billed, once."""

    m.values["cost_per_day_usd"] = _scalar(
        conn,
        "WITH used AS (SELECT model_call AS h FROM decisions WHERE model_call IS NOT "
        "NULL UNION SELECT call_hash FROM escalations) "
        "SELECT COALESCE(sum(c.cost_usd), 0) / %s FROM model_calls c "
        "JOIN used ON used.h = c.hash",
        (max(m.days, 1),),
    )
    decisions = _scalar(conn, "SELECT count(*) FROM decisions")
    by_model = _scalar(
        conn, "SELECT count(*) FROM decisions WHERE source IN ('jev', 'llm')"
    )
    by_llm = _scalar(conn, "SELECT count(*) FROM decisions WHERE source = 'llm'")
    m.values["decisions_per_day"] = (
        None if decisions is None or not m.days else decisions / m.days
    )
    m.values["model_share"] = _ratio(by_model, decisions)
    m.values["llm_share"] = _ratio(by_llm, decisions)


def digest(conn: Connection[DictRow]) -> str:
    """The event log as one hash: kind, time, actor, org, payload, causes, in
    order. Two runs with the same digest ran the same world."""

    h = hashlib.blake2b(b"jeve.events.v1", digest_size=16)
    for row in conn.execute(
        "SELECT sim_time, kind, actor_id, org_id, payload, causes FROM events "
        "ORDER BY seq"
    ):
        h.update(
            json.dumps(
                [
                    row["sim_time"],
                    row["kind"],
                    row["actor_id"],
                    row["org_id"],
                    row["payload"],
                    list(row["causes"] or []),
                ],
                sort_keys=True,
                default=str,
            ).encode()
        )
    return h.hexdigest()


def measure(conn: Connection[DictRow]) -> Measures:
    """Everything, from a world whose run has ended."""

    row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    assert row is not None, "not a seeded world"
    end = int(row["sim_time"])
    m = Measures(days=end // DAY)
    _payments(conn, m, end)
    _support(conn, m)
    _cafe(conn, m)
    _churn(conn, m)
    _consistency(conn, m)
    _memory(conn, m)
    _episodes(conn, m)
    _detectors(conn, m)
    _warnings(conn, m, end)
    _health(conn, m)
    _drift(conn, m, end)
    _ties(conn, m)
    _signal(conn, m)
    _cost(conn, m)
    m.checks_failed = [c.name for c in soak.checks(conn, days=m.days) if not c.ok]
    m.values["invariants_failed"] = float(len(m.checks_failed))
    m.digest = digest(conn)
    return m
