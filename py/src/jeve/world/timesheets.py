"""The law firm bills the hours it logs (WORLD-0010).

The scenario's table has Halloran & Pike's month-end invoices blocked by
Invoicing and "for the law firm also time entries in TimeTrack". The field
report's world drew each client's bill from a random number, so a TimeTrack
outage never reached the law firm's revenue at all.

Now a fee earner's day has billable minutes whether or not anybody writes them
down. Before going home they decide whether to log them (`time.log`, a
propensity with diligence in it). Hours logged late are partly forgotten; hours
never logged within a week are lost; and while TimeTrack is down nothing can be
logged at all — unless the firm has decided to keep hours on paper
(`outage.workaround`), in which case they can, and the paper has to be
reconciled at the month's close. At month-end the firm bills what was logged,
shared across the month's clients by the size of their matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jeve.core.clock import DAY, HOUR, SimTime
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import economy, scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, TickReport

FEE_EARNERS: dict[str, tuple[int, int]] = {
    "partner": (4 * 60, 260_00),
    "senior_associate": (5 * 60, 190_00),
    "junior_associate": (5 * 60, 140_00),
    "paralegal": (4 * 60, 85_00),
}
"""Role -> (billable minutes in a usual day, hourly rate in cents)."""

FORGET_PER_DAY = 0.10
"""Each day an entry waits, a tenth of it is forgotten."""

LOST_AFTER_DAYS = 5
"""An entry not logged within a working week is never logged."""

LOG_AT = 16 * HOUR + 30 * 60


@scheduler.job("time.day", office_hours_only=True)
def day(
    engine: Engine, report: TickReport, org_id: str, payload: dict[str, Any]
) -> None:
    """The end of a working day at the law firm."""

    now = SimTime(report.sim_time)
    following = now.day + 1
    while SimTime(following * DAY).is_weekend:
        following += 1
    engine.schedule(following * DAY + LOG_AT, "time.day", org_id, {})
    if economy.failed(engine, org_id):
        return

    earners = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = %s AND kind = 'staff' "
        "AND status <> 'left' AND role = ANY(%s) ORDER BY id",
        (org_id, list(FEE_EARNERS)),
    ).fetchall()
    at_work = {
        str(r["person_id"])
        for r in engine.conn.execute(
            "SELECT person_id FROM positions WHERE zone <> 'home'"
        ).fetchall()
    }
    for person in earners:
        person_id = str(person["id"])
        if person_id not in at_work:
            continue
        minutes, rate = FEE_EARNERS[str(person["role"])]
        rng = derive_rng(engine.root_seed, "billable", person_id, now.day)
        engine.conn.execute(
            "INSERT INTO timesheets (person_id, day, minutes, rate_cents) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (person_id, now.day, int(minutes * (0.7 + 0.6 * rng.random())), rate),
        )

    # What nobody logged within a week is gone.
    lost = engine.conn.execute(
        "UPDATE timesheets SET lost = true WHERE logged_day IS NULL AND NOT lost "
        "AND day <= %s AND person_id IN (SELECT id FROM persons WHERE org_id = %s) "
        "RETURNING minutes, rate_cents",
        (now.day - LOST_AFTER_DAYS, org_id),
    ).fetchall()
    if lost:
        engine.emit(
            report,
            "time.lost",
            org_id=org_id,
            payload={
                "entries": len(lost),
                "cents": sum(
                    int(r["minutes"]) * int(r["rate_cents"]) // 60 for r in lost
                ),
            },
        )

    down = engine.conn.execute(
        "SELECT 1 FROM modules WHERE id = 'timetrack' AND status = 'down'"
    ).fetchone()
    on_paper = down is not None and engine.by_hand(org_id, "timetrack")
    pending = engine.conn.execute(
        "SELECT t.person_id, count(*) AS n, p.role, p.traits FROM timesheets t "
        "JOIN persons p ON p.id = t.person_id WHERE p.org_id = %s "
        "AND t.logged_day IS NULL AND NOT t.lost AND p.status <> 'left' "
        "GROUP BY t.person_id, p.role, p.traits ORDER BY t.person_id",
        (org_id,),
    ).fetchall()
    if not pending:
        return
    contexts = [
        DecisionContext(
            person_id=str(row["person_id"]),
            role=str(row["role"]),
            sim_time=report.sim_time,
            kind="time.log",
            facts={
                "pending_days": int(row["n"]),
                "timetrack_down": down is not None,
                "on_paper": on_paper,
            },
            traits=dict(row["traits"] or {}),
        )
        for row in pending
    ]
    for row, made in zip(pending, engine.decide_many(report, contexts), strict=True):
        if not made.chosen.get("log"):
            continue
        logged = engine.conn.execute(
            "UPDATE timesheets SET logged_day = %s, on_paper = %s, logged_minutes = "
            "GREATEST(0, round(minutes * (1 - %s * (%s - day))))::int "
            "WHERE person_id = %s AND logged_day IS NULL AND NOT lost "
            "RETURNING minutes, logged_minutes",
            (
                now.day,
                on_paper,
                FORGET_PER_DAY,
                now.day,
                str(row["person_id"]),
            ),
        ).fetchall()
        engine.emit(
            report,
            "time.logged",
            actor_id=str(row["person_id"]),
            org_id=org_id,
            decision_id=made.id,
            payload={
                "entries": len(logged),
                "minutes": sum(int(r["logged_minutes"]) for r in logged),
                "forgotten": sum(
                    int(r["minutes"]) - int(r["logged_minutes"]) for r in logged
                ),
                "on_paper": on_paper,
                "decided_by": made.source,
            },
        )


def bill_hours(
    engine: Engine, org_id: str, month: int, engaged: list[tuple[str, int]]
) -> list[tuple[str, int]]:
    """This month's logged hours, as bills to this month's clients.

    Shared by the size of each client's matter (the drawn amount, which is
    keyed by firm, client and month: CORE-0009). Hours with no client to bill
    this month wait for the next.
    """

    if not engaged:
        return []
    row = engine.conn.execute(
        "SELECT COALESCE(sum(t.logged_minutes::bigint * t.rate_cents / 60), 0) AS c "
        "FROM timesheets t JOIN persons p ON p.id = t.person_id "
        "WHERE p.org_id = %s AND t.logged_day IS NOT NULL AND t.billed_month IS NULL",
        (org_id,),
    ).fetchone()
    total = int(row["c"]) if row else 0
    if total <= 0:
        return []
    engine.conn.execute(
        "UPDATE timesheets SET billed_month = %s WHERE logged_day IS NOT NULL "
        "AND billed_month IS NULL AND person_id IN "
        "(SELECT id FROM persons WHERE org_id = %s)",
        (month, org_id),
    )
    weight = sum(amount for _, amount in engaged)
    bills = [(client, total * amount // weight) for client, amount in engaged]
    return [(client, amount) for client, amount in bills if amount > 0]
