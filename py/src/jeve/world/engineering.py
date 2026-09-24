"""Tallybird's engineering loop: the firefighting trap (WORLD-0011).

The scenario's behaviour #4: a ticket surge pushes the engineering lead to
spend the week firefighting, the debt that causes outages goes unpaid, and the
hazard rises until somebody chooses to pay it down. The field report's world
had none of it: `debt_level` was a constant, the hazard a fixed rate, and no
engineer made a decision all run.

Three decisions and one rule:

* **allocation**, weekly, by the engineering lead: roadmap, debt or firefight.
  A judgement, so J (DECIDE-0003).
* **deploy**, Tuesdays and Thursdays: ship this week's changes today or hold
  them. A propensity with the lead's appetite for risk in it, so P.
* **postmortem**, a rule: an outage that ran long adds debt, unless the team is
  paying debt down this week.
* the **hazard** reads `debt_level` (kept in `orgs.policy`), as it always
  claimed to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jeve.core.clock import DAY, HOUR, MINUTE, SimTime
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.world import economy, scheduler

if TYPE_CHECKING:
    from jeve.world.engine import Engine, TickReport

DEBT_START = 1.0
"""The fixture starts with debt elevated (the scenario's seed state)."""
DEBT_FLOOR = 0.3
DEBT_CEILING = 2.0

DEBT_BY_ALLOCATION: dict[str, float] = {
    "roadmap": 0.08,
    "firefight": 0.03,
    "debt": -0.15,
    "other": 0.0,
}
"""What a week of each kind of work does to the codebase."""

HELD_DEPLOY_DEBT = 0.02
"""Changes that pile up unshipped are their own kind of debt."""

POSTMORTEM_AFTER_MINUTES = 120
POSTMORTEM_DEBT = 0.05

FIREFIGHT_SPEEDUP = 0.6
"""While the team is firefighting, an outage takes this share of the time."""

DEPLOY_BREAKS = 0.2
"""Chance a deploy takes something down, per unit of debt: one in five at the
seeded level, one in sixteen in a clean codebase, two in five at the ceiling."""

DEPLOY_DAYS = (1, 3)
"""Tuesday and Thursday."""

ENGINEERING_ROLES = ("eng_lead", "engineer", "sre", "founder")


def debt(engine: Engine) -> float:
    """The codebase's debt: pinned by an experiment that asked for a fixed
    level, otherwise whatever engineering has made of it."""

    if engine.pinned_debt is not None:
        return engine.pinned_debt
    return float(economy.policy(engine, "tallybird").get("debt_level", DEBT_START))


def _move_debt(engine: Engine, delta: float) -> float:
    if engine.pinned_debt is not None:
        return engine.pinned_debt
    level = min(DEBT_CEILING, max(DEBT_FLOOR, round(debt(engine) + delta, 4)))
    economy.set_policy(engine, "tallybird", debt_level=level)
    return level


def firefighting(engine: Engine, now: int) -> bool:
    policy = economy.policy(engine, "tallybird")
    return policy.get("allocation") == "firefight" and now < int(
        policy.get("allocation_until", 0)
    )


def outage_minutes(engine: Engine, now: int, base: int) -> int:
    """How long a new outage is expected to run: longer in a fragile codebase,
    shorter while the whole team is on it."""

    minutes = base * (0.6 + 0.4 * debt(engine))
    if firefighting(engine, now):
        minutes *= FIREFIGHT_SPEEDUP
    return max(30, int(minutes))


def lead(engine: Engine) -> dict[str, Any] | None:
    row = engine.conn.execute(
        "SELECT id, role, traits FROM persons WHERE org_id = 'tallybird' "
        f"AND kind = 'staff' AND status <> 'left' AND role = ANY(%s) "
        f"AND {economy.AT_WORK} "
        "ORDER BY array_position(%s::text[], role), id LIMIT 1",
        (list(ENGINEERING_ROLES), list(ENGINEERING_ROLES)),
    ).fetchone()
    return dict(row) if row else None


def _week_so_far(engine: Engine, now: int) -> dict[str, int]:
    row = engine.conn.execute(
        "SELECT (SELECT count(*) FROM incidents WHERE started_sim > %s) AS incidents, "
        "(SELECT count(*) FROM tickets WHERE status IN ('open','triaged')) AS backlog, "
        "(SELECT count(*) FROM events WHERE kind = 'subscription.cancelled' "
        "  AND sim_time > %s) AS churned",
        (now - 7 * DAY, now - 28 * DAY),
    ).fetchone()
    assert row is not None
    return {k: int(v) for k, v in row.items()}


@scheduler.job("eng.allocate", office_hours_only=True)
def allocate(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """Monday morning: where does engineering spend the week?"""

    engine.schedule(report.sim_time + 7 * DAY, "eng.allocate", None, {})
    if economy.failed(engine, "tallybird"):
        return
    person = lead(engine)
    if person is None:
        return
    week = _week_so_far(engine, report.sim_time)
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(person["id"]),
            role=str(person["role"]),
            sim_time=report.sim_time,
            kind="eng.allocation",
            facts={
                "debt_level": debt(engine),
                "incidents_last_week": week["incidents"],
                "backlog": week["backlog"],
                "churned_last_month": week["churned"],
                "runway_days": engine.runway_days("tallybird"),
            },
            traits=dict(person["traits"] or {}),
        ),
    )
    choice = str(made.chosen.get("allocation", "roadmap"))
    level = _move_debt(engine, DEBT_BY_ALLOCATION.get(choice, 0.0))
    economy.set_policy(
        engine,
        "tallybird",
        allocation=choice,
        allocation_until=report.sim_time + 7 * DAY,
    )
    engine.emit(
        report,
        "eng.allocated",
        actor_id=str(person["id"]),
        org_id="tallybird",
        decision_id=made.id,
        payload={
            "allocation": choice,
            "debt_level": level,
            "decided_by": made.source,
        },
    )


@scheduler.job("eng.deploy", office_hours_only=True)
def deploy(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    """Tuesday and Thursday afternoon: ship what is ready, or hold it."""

    now = SimTime(report.sim_time)
    following = next(d for d in range(1, 8) if (now.weekday + d) % 7 in DEPLOY_DAYS)
    engine.schedule(now.day * DAY + following * DAY + 14 * HOUR, "eng.deploy", None, {})
    if economy.failed(engine, "tallybird"):
        return
    person = lead(engine)
    if person is None:
        return
    level = debt(engine)
    made = engine.decide(
        report,
        DecisionContext(
            person_id=str(person["id"]),
            role=str(person["role"]),
            sim_time=report.sim_time,
            kind="deploy.decision",
            facts={
                "debt_level": level,
                "incidents_last_week": _week_so_far(engine, report.sim_time)[
                    "incidents"
                ],
                "allocation": str(
                    economy.policy(engine, "tallybird").get("allocation", "roadmap")
                ),
            },
            traits=dict(person["traits"] or {}),
        ),
    )
    if not made.chosen.get("deploy"):
        level = _move_debt(engine, HELD_DEPLOY_DEBT)
        engine.emit(
            report,
            "deploy.held",
            actor_id=str(person["id"]),
            org_id="tallybird",
            decision_id=made.id,
            payload={"debt_level": level, "decided_by": made.source},
        )
        return
    shipped = int(economy.policy(engine, "tallybird").get("features_shipped", 0)) + 1
    economy.set_policy(engine, "tallybird", features_shipped=shipped)
    seq = engine.emit(
        report,
        "deploy.shipped",
        actor_id=str(person["id"]),
        org_id="tallybird",
        decision_id=made.id,
        payload={
            "debt_level": level,
            "features_shipped": shipped,
            "decided_by": made.source,
        },
    )
    # Whether it breaks something is the codebase's business, not a choice:
    # drawn about this deploy (CORE-0009), likelier the more fragile it is.
    rng = derive_rng(engine.root_seed, "deploy", now.day)
    if rng.random() < DEPLOY_BREAKS * level:
        module = ("invoicing", "timetrack", "pos")[int(rng.random() * 3)]
        after = (30 + int(rng.random() * 90)) // 15 * 15 * MINUTE
        engine.schedule(
            report.sim_time + after,
            "incident.start",
            module,
            {"severity": 2, "expected_minutes": 90, "cause": seq, "deploy": True},
        )


def postmortem(engine: Engine, report: TickReport, *, minutes: int) -> float | None:
    """A long outage leaves debt behind it, unless the team is paying debt
    down this week. Returns the new level if it moved."""

    if minutes < POSTMORTEM_AFTER_MINUTES:
        return None
    policy = economy.policy(engine, "tallybird")
    if policy.get("allocation") == "debt" and report.sim_time < int(
        policy.get("allocation_until", 0)
    ):
        return None
    return _move_debt(engine, POSTMORTEM_DEBT)
