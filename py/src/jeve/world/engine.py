"""The tick loop: the core pipeline.

One transaction per tick (CORE-0007). Everything a tick does — events, domain
mutations, scheduler changes, the clock advance — commits together or not at
all, which is what makes `kill -9` recoverable: the interrupted tick simply
re-executes.

The referee is code. A policy decides *whether* an agent acts; the rules decide
what is possible and what it costs. Money is never moved by a model.
"""

from __future__ import annotations

import json
import math
import os
import signal
from dataclasses import dataclass, field, replace
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.core.clock import (
    DAY,
    HOUR,
    MINUTE,
    TICK,
    WORK_END,
    WORK_START,
    SimTime,
    next_open,
)
from jeve.core.orgs import (
    BY_ID,
    MODULES,
    ORGS,
    bank,
    module_owner,
    modules_of,
    retailers,
)
from jeve.core.seed import derive_rng
from jeve.decide.gates import ASK_FROM_DAYS_BEFORE_DUE
from jeve.decide.policy import Decision, DecisionContext, Policy
from jeve.decide.questions import trait_fraction
from jeve.memory import beliefs
from jeve.world import flows, scheduler, space

# Every rate in here is per *hour*, and turned into a chance for one tick where
# it is used: nothing in the world may depend on how long a tick is.

# A vendor's hazard: chance per business hour that a module falls over.
# Elevated because the fixture starts with debt high and a risky deploy queued.
HAZARD_PER_HOUR = 0.016
DEBT_MULTIPLIER = 2.5

# How quickly subscribers notice an outage: the old 12%-per-quarter-hour, as a
# rate. Drawn once per person per incident (CORE-0009), not once per tick for
# whoever happened to be among the first forty rows.
NOTICE_RATE_PER_HOUR = -math.log(1 - 0.12) * 4

# Who walks into a shop, and how often a client has work done in a month, are
# each firm's own (`jeve.core.orgs`). It used to be the same twelve clients
# every month (`ORDER BY id LIMIT 12`), which is most of why 251 of 400
# counterparties never did anything at all; now it is whoever had work done
# that month, keyed by (firm, client, month).

TICKET_TIMEOUT = 2 * DAY
REOPEN_WINDOW = 3 * DAY
CHASE_AFTER = 7 * DAY
WRITE_OFF_AFTER = 60 * DAY
AUTOPAY_ABOVE = 0.2
"""Clients in the four prompter fifths pay by standing instruction on the day a
bill falls due: a gate, not a question. The slowest fifth decide, daily."""


def per_tick(rate_per_hour: float) -> float:
    """The chance of at least one event in one tick, for an hourly rate."""

    return 1.0 - math.exp(-rate_per_hour * TICK / HOUR)


_DIE_AT_EVENT = int(os.environ.get("JEVE_TEST_DIE_AT_EVENT") or 0)


def _seq_of(value: object) -> list[int]:
    """A cause list from a nullable subquery result."""

    return [int(value)] if isinstance(value, int) else []


@dataclass(frozen=True, slots=True)
class Made:
    """A decision after it has been written down."""

    id: int
    chosen: dict[str, Any]
    source: str


@dataclass(slots=True)
class TickReport:
    """What one tick did. Aggregated into the run report."""

    tick_seq: int
    sim_time: int
    events: list[str] = field(default_factory=list)
    decisions: int = 0
    in_episode: set[str] = field(default_factory=set)
    """Who spent this tick in a conversation (WORLD-0006).

    Three rounds is most of a quarter of an hour. Somebody who was in one is not
    also at their desk clearing tickets in the same fifteen minutes, and the
    organisational-simulation literature is unanimous that a meeting costs
    attention — a model in which talking is free makes talking strictly
    dominant. Held for the tick, not stored: it is about now."""

    def add(self, kind: str) -> None:
        self.events.append(kind)


class Engine:
    def __init__(
        self,
        conn: Connection[DictRow],
        policy: Policy,
        *,
        root_seed: int,
        debt_level: float = 1.0,
        encounters: bool = True,
        spatial: bool = True,
        episodes: bool = True,
    ) -> None:
        self._conn = conn
        self._policy = policy
        self._root = root_seed
        self._debt = debt_level
        self.encounters = encounters
        """Off, people still move but meeting changes nothing: the control arm
        for "does space matter?"."""
        self.spatial = spatial
        self.episodes = episodes
        """On, a meeting with a stake gets rounds instead of one shot
        (WORLD-0006). On in every world the daemon runs; off only as the control
        arm `make episodes` compares against, as `encounters` and `spatial` are
        for their own experiments. The two resolutions disagree about how often
        a meeting escalates an outage (`ops/episodes.md`), so switching this off
        changes the world's base rates, not just its fidelity."""
        # Whatever ran before us may have died mid-tick (WORLD-0002).
        db.resync_sequences(self._conn)
        self._remember_outages_from_before_memory()
        self._conn.commit()

    def _remember_outages_from_before_memory(self) -> None:
        """Write down what code without MEM-0002 never did, for a world that ran
        on it before this code took over.

        An incident without a fact comes from that code and nowhere else:
        `_start_incident` writes both in one tick. The first upgraded tick in
        which somebody noticed one wrote their knowledge against a fact that did
        not exist, and the daemon died on the foreign key. Not a migration,
        because production migrates while the old daemon is still writing
        (`release_command`), and an outage it starts in that minute would be
        missed; the writer lock means nothing is still writing now. Only such
        incidents are touched, so a restart of a world this code wrote changes
        nothing (`test_resume`).
        """

        before = [
            int(row["id"])
            for row in self._conn.execute(
                "SELECT i.id FROM incidents i WHERE NOT EXISTS "
                "(SELECT 1 FROM facts f WHERE f.incident_id = i.id) ORDER BY i.id"
            ).fetchall()
        ]
        if not before:
            return
        # As `_start_incident` records it and `_end_incident` retires it.
        self._conn.execute(
            "INSERT INTO facts (id, topic, about_module_id, incident_id, born_sim, "
            "  born_seq, stale_sim) "
            "SELECT 'outage:' || id, 'outage', module_id, id, started_sim, "
            "  cause_event_seq, ended_sim FROM incidents WHERE id = ANY(%s)",
            (before,),
        )
        # The vendor's staff knew at once; everyone whose notice had come knew
        # first-hand, as `_customers` writes it down. Which vendor is the one
        # that sells the broken module (CORE-0012) — the district has two, and
        # Quill's engineers do not hear about Tallybird's register.
        self._conn.execute(
            "INSERT INTO knowledge (person_id, fact_id, learned_sim, learned_seq) "
            "SELECT p.id, 'outage:' || i.id, i.started_sim, i.cause_event_seq "
            "FROM incidents i "
            "JOIN modules m ON m.id = i.module_id "
            "JOIN persons p ON p.org_id = m.org_id AND p.kind = 'staff' "
            "WHERE i.id = ANY(%s)",
            (before,),
        )
        self._conn.execute(
            "INSERT INTO knowledge (person_id, fact_id, learned_sim) "
            "SELECT n.person_id, 'outage:' || i.id, n.notice_sim "
            "FROM incidents i JOIN outage_notices n ON n.incident_id = i.id "
            "CROSS JOIN sim_meta m WHERE i.id = ANY(%s) "
            "AND n.notice_sim <= coalesce(i.ended_sim, m.sim_time) "
            "ON CONFLICT (person_id, fact_id) DO NOTHING",
            (before,),
        )

    @property
    def conn(self) -> Connection[DictRow]:
        return self._conn

    @property
    def root_seed(self) -> int:
        return self._root

    # -- state helpers -----------------------------------------------------

    def _meta(self) -> DictRow:
        row = self._conn.execute("SELECT * FROM sim_meta").fetchone()
        if row is None:
            raise RuntimeError("sim_meta is empty; seed the world first")
        return row

    def _emit(
        self,
        report: TickReport,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        actor_id: str | None = None,
        org_id: str | None = None,
        causes: list[int] | None = None,
        decision_id: int | None = None,
    ) -> int:
        row = self._conn.execute(
            "INSERT INTO events (sim_time, tick_seq, kind, actor_id, org_id, "
            "payload, causes, decision_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING seq",
            (
                report.sim_time,
                report.tick_seq,
                kind,
                actor_id,
                org_id,
                json.dumps(payload or {}),
                causes or [],
                decision_id,
            ),
        ).fetchone()
        assert row is not None
        report.add(kind)
        seq = int(row["seq"])
        if _DIE_AT_EVENT and seq >= _DIE_AT_EVENT:
            # Test hook for tests/test_resume.py: die the hardest way there is,
            # with this tick's rows written and not committed. No handler runs,
            # nothing is flushed — what a power cut looks like to Postgres.
            os.kill(os.getpid(), signal.SIGKILL)
        return seq

    def _decide(self, report: TickReport, ctx: DecisionContext) -> Made:
        """Run a policy and record the decision."""

        return self._decide_many(report, [ctx])[0]

    def _decide_many(
        self, report: TickReport, contexts: list[DecisionContext]
    ) -> list[Made]:
        """Decide independent contexts together, record them in order."""

        contexts = self._numbered(contexts)
        decisions = self._policy.decide_many(contexts)
        return [
            self._record(report, ctx, decision)
            for ctx, decision in zip(contexts, decisions, strict=True)
        ]

    def _record(
        self, report: TickReport, ctx: DecisionContext, decision: Decision
    ) -> Made:
        row = self._conn.execute(
            "INSERT INTO decisions (person_id, decision_seq, sim_time, tick_seq, "
            "question_set, model_call, source, distributions, prng_path, draws, "
            "chosen) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                ctx.person_id,
                ctx.decision_seq,
                ctx.sim_time,
                report.tick_seq,
                ctx.kind,
                decision.model_call,
                decision.source,
                json.dumps(decision.distributions),
                decision.prng_path,
                json.dumps(decision.draws),
                json.dumps(decision.chosen),
            ),
        ).fetchone()
        assert row is not None
        self._conn.execute(
            "UPDATE persons SET decision_seq = decision_seq + 1 WHERE id = %s",
            (ctx.person_id,),
        )
        report.decisions += 1
        return Made(int(row["id"]), decision.chosen, decision.source)

    def _numbered(self, contexts: list[DecisionContext]) -> list[DecisionContext]:
        """Give each context its place in its person's sequence of decisions.

        The engine's job, not the caller's: someone with two bills to think
        about, or in two conversations, in one tick decides twice, and the
        second decision is their next one. Callers used to add their own
        offsets and any two that met would have collided.
        """

        people = sorted({ctx.person_id for ctx in contexts})
        rows = self._conn.execute(
            "SELECT id, decision_seq FROM persons WHERE id = ANY(%s)", (people,)
        ).fetchall()
        following = {str(row["id"]): int(row["decision_seq"]) for row in rows}
        numbered: list[DecisionContext] = []
        for ctx in contexts:
            numbered.append(replace(ctx, decision_seq=following[ctx.person_id]))
            following[ctx.person_id] += 1
        return numbered

    # -- the person's own calendar (CORE-0009) -------------------------------

    def slot(self, person_id: str, day: int, purpose: str) -> int:
        """The time of day this person gets round to `purpose` on `day`.

        Everyone does their bills, reads their inbox, makes their calls at a
        time of their own, and a different one each day. It replaces "a random
        quarter of whoever is first in the table, this tick".
        """

        rng = derive_rng(self._root, "slot", purpose, person_id, day)
        span = WORK_END - WORK_START - HOUR
        return WORK_START + int(rng.random() * span) // (5 * MINUTE) * (5 * MINUTE)

    def gets_to_it(
        self, person_id: str, now: SimTime, purpose: str, asked_day: object
    ) -> bool:
        """Has their moment for `purpose` come today, and not been used yet?"""

        if asked_day is not None and int(str(asked_day)) >= now.day:
            return False
        return now.time_of_day >= self.slot(person_id, now.day, purpose)

    def cash_of(self, account: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(sum(amount_cents),0) AS cents FROM ledger_entries "
            "WHERE account_id = %s",
            (account,),
        ).fetchone()
        return int(row["cents"]) if row else 0

    def payer_of(self, org_id: str) -> DictRow | None:
        """Who pays this firm's bills and chases what it is owed."""

        roles = list(BY_ID[org_id].payer_roles)
        return self._conn.execute(
            "SELECT id, org_id, role, traits FROM persons WHERE org_id = %s "
            "AND kind = 'staff' AND role = ANY(%s) "
            "ORDER BY array_position(%s::text[], role), id LIMIT 1",
            (org_id, roles, roles),
        ).fetchone()

    # What the rest of `jeve.world` needs of the engine, by its public name.
    emit = _emit
    decide = _decide
    decide_many = _decide_many

    def _post(
        self, sim_time: int, memo: str, legs: list[tuple[str, int]], event_seq: int
    ) -> int:
        """Write a balanced ledger transaction. The database checks it."""

        row = self._conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo, event_seq) VALUES (%s,%s,%s) "
            "RETURNING id",
            (sim_time, memo, event_seq),
        ).fetchone()
        assert row is not None
        txn = int(row["id"])
        db.executemany(
            self._conn,
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s,%s,%s)",
            [(txn, account, cents) for account, cents in legs],
        )
        return txn

    post = _post

    def _module_down(self, module_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM modules WHERE id = %s", (module_id,)
        ).fetchone()
        return row is not None and row["status"] == "down"

    def _blocked(self, org_id: str, category: str) -> str | None:
        """The module a firm depends on for `category` that is down, if any.

        A firm's dependency is on a category, whoever sells it: the law firm's
        month-end is blocked by *its* invoicing module, and a firm that keeps
        its books on paper is blocked by nothing.
        """

        for module_id in modules_of(org_id, category):
            if self._module_down(module_id):
                return module_id
        return None

    # -- the tick ----------------------------------------------------------

    def tick(self) -> TickReport:
        """Advance the world by one quantum, atomically and durably.

        The tick has to *own* its transaction. On a connection that is not in
        autocommit mode any earlier statement — even a SELECT — has already
        opened one implicitly, and `conn.transaction()` inside that is only a
        savepoint: the tick's writes then sit uncommitted until somebody else
        happens to commit. That is how "one transaction per tick" was, for a
        while, one transaction per sim-day: invisible to every other session
        until nightfall, and lost whole by a `kill -9`. So: end whatever is
        open, then do everything, including reading the clock, inside one real
        BEGIN...COMMIT.
        """

        self._conn.commit()
        try:
            with self._conn.transaction():
                meta = self._meta()
                report = TickReport(
                    tick_seq=int(meta["tick_seq"]) + 1, sim_time=int(meta["sim_time"])
                )
                self._advance(report, SimTime(report.sim_time))
        except BaseException:
            # The rows are gone but the ids they drew are not. Put the counters
            # back before anything retries, or the retry numbers its events
            # differently from a run that never failed.
            if not self._conn.closed:
                db.resync_sequences(self._conn)
                self._conn.commit()
            raise
        return report

    def _advance(self, report: TickReport, now: SimTime) -> None:
        """Everything one tick does. Runs inside the tick's transaction."""

        self._run_due(report)
        if now.in_office_hours:
            self._maybe_incident(report, now)
        if self.spatial:
            # Before the desks do their work: someone cornered in the cafe
            # this tick changes what support sees in the queue this tick.
            space.run(self, report, now)
        if now.in_office_hours:
            self._support(report, now)
            self._customers(report, now)
            self._followups(report, now)
            self._payments(report, now)
            self._client_payments(report, now)
            self._chase(report, now)
            self._credit(report, now)
        self._retail(report, now)

        self._conn.execute(
            "UPDATE sim_meta SET sim_time = %s, tick_seq = %s, updated_at = now()",
            (report.sim_time + TICK, report.tick_seq),
        )

    def run_until(
        self, end_sim_time: int, *, max_ticks: int = 20_000
    ) -> list[TickReport]:
        reports: list[TickReport] = []
        for _ in range(max_ticks):
            if int(self._meta()["sim_time"]) >= end_sim_time:
                break
            reports.append(self.tick())
        return reports

    # -- scheduled work ----------------------------------------------------

    def _run_due(self, report: TickReport) -> None:
        due = self._conn.execute(
            "SELECT id, kind, subject_id, payload FROM scheduled "
            "WHERE due_sim_time <= %s ORDER BY due_sim_time, ord, kind, subject_id, id",
            (report.sim_time,),
        ).fetchall()
        offices_open = SimTime(report.sim_time).in_office_hours
        # Office work that comes due while only the cafe is open, or on a
        # Saturday, waits for the office — in place, keeping its original due
        # time, so that on Monday morning it still runs before whatever was
        # due on Monday morning. Month-end invoices used to be able to go out
        # at seven because an outage ended then; and an accountant's nine
        # o'clock close must see the invoices that were waiting since Friday.
        ready = [
            row
            for row in due
            if offices_open or not scheduler.get(str(row["kind"])).office_hours_only
        ]
        # Taken off the queue before any of it runs: a handler that reschedules
        # itself for this same tick must not be run twice.
        self._conn.execute(
            "DELETE FROM scheduled WHERE id = ANY(%s)", ([int(r["id"]) for r in ready],)
        )
        for row in ready:
            scheduler.get(str(row["kind"])).run(
                self, report, str(row["subject_id"] or ""), dict(row["payload"] or {})
            )

    def _schedule(
        self, due: int, kind: str, subject: str | None, payload: dict[str, Any]
    ) -> None:
        self._conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s,%s,%s,%s)",
            (due, kind, subject, json.dumps(payload)),
        )

    schedule = _schedule
    # -- flow 1: incidents -------------------------------------------------

    def _maybe_incident(self, report: TickReport, now: SimTime) -> None:
        chance = per_tick(HAZARD_PER_HOUR * (1 + self._debt * (DEBT_MULTIPLIER - 1)))
        for module_id in sorted(MODULES):
            if self._module_down(module_id):
                continue
            # CORE-0009: about this module at this moment of this day, not about
            # how many ticks the run has taken to get here.
            rng = derive_rng(
                self._root, "hazard", module_id, now.day, now.time_of_day // MINUTE
            )
            if rng.random() < chance:
                self._start_incident(
                    report, module_id, {"severity": 1, "expected_minutes": 90}
                )

    def _start_incident(
        self, report: TickReport, module_id: str, payload: dict[str, Any]
    ) -> None:
        if self._module_down(module_id):
            return
        severity = int(payload.get("severity", 1))
        minutes = int(payload.get("expected_minutes", 90))
        seq = self._emit(
            report,
            "incident.started",
            org_id=module_owner(module_id),
            payload={
                "module_id": module_id,
                "severity": severity,
                "expected_minutes": minutes,
            },
        )
        row = self._conn.execute(
            "INSERT INTO incidents (module_id, started_sim, severity, cause_event_seq) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (module_id, report.sim_time, severity, seq),
        ).fetchone()
        assert row is not None
        self._conn.execute(
            "UPDATE modules SET status = 'down' WHERE id = %s", (module_id,)
        )
        self._schedule(
            report.sim_time + minutes * 60,
            "incident.end",
            module_id,
            {"incident_id": int(row["id"]), "cause": seq},
        )
        incident_id = int(row["id"])
        self._will_notice(incident_id, module_id, report.sim_time)

        # That the module is down is now a thing people can tell each other
        # (MEM-0002). The vendor's own staff know at once — it is their outage.
        fact = memory.Fact.outage(incident_id, module_id)
        memory.record_fact(self._conn, fact, sim_time=report.sim_time, seq=seq)
        for person in self._conn.execute(
            "SELECT id FROM persons WHERE org_id = %s AND kind = 'staff' ORDER BY id",
            (module_owner(module_id),),
        ).fetchall():
            memory.learn(
                self._conn,
                str(person["id"]),
                fact.id,
                sim_time=report.sim_time,
                seq=seq,
            )

    def _will_notice(self, incident_id: int, module_id: str, started: int) -> None:
        """Everyone who uses the module finds out it is down — each in their own
        time, drawn once per (person, incident) (CORE-0009)."""

        users = self._conn.execute(
            "SELECT person_id AS id FROM subscriptions "
            "WHERE module_id = %s AND active AND person_id IS NOT NULL "
            "UNION "
            # A firm that subscribes is represented by whoever pays its bills.
            "SELECT p.id FROM subscriptions s JOIN persons p ON p.org_id = s.org_id "
            "WHERE s.module_id = %s AND s.active AND p.kind = 'staff' "
            "AND p.role = ANY(%s) ORDER BY id",
            (module_id, module_id, [r for o in ORGS for r in o.payer_roles[:1]]),
        ).fetchall()
        rows = []
        for user in users:
            person_id = str(user["id"])
            rng = derive_rng(self._root, "notice", person_id, incident_id)
            delay = -math.log(1.0 - rng.random()) / NOTICE_RATE_PER_HOUR * HOUR
            rows.append((incident_id, person_id, started + int(delay)))
        db.executemany(
            self._conn,
            "INSERT INTO outage_notices (incident_id, person_id, notice_sim) "
            "VALUES (%s,%s,%s)",
            rows,
        )

    def _end_incident(
        self, report: TickReport, module_id: str, payload: dict[str, Any]
    ) -> None:
        incident_id = int(payload.get("incident_id", 0))
        row = self._conn.execute(
            "UPDATE incidents SET ended_sim = %s WHERE id = %s AND ended_sim IS NULL "
            "RETURNING started_sim, escalation_event_seq",
            (report.sim_time, incident_id),
        ).fetchone()
        if row is None:
            return
        # If someone got this fixed sooner by raising it in person, that is a
        # cause of *when* it ended, and everything downstream inherits it.
        causes = [int(payload["cause"])] if payload.get("cause") else []
        causes += _seq_of(row["escalation_event_seq"])
        self._conn.execute(
            "UPDATE modules SET status = 'up' WHERE id = %s", (module_id,)
        )
        # An outage that is over is gossip, not news: it stops travelling, and
        # stops creating notices for an incident nobody can still be stuck on.
        memory.make_stale(
            self._conn,
            memory.Fact.outage(incident_id, module_id).id,
            sim_time=report.sim_time,
        )
        minutes = (report.sim_time - int(row["started_sim"])) // 60
        ended_seq = self._emit(
            report,
            "incident.ended",
            org_id=module_owner(module_id),
            causes=causes,
            payload={
                "module_id": module_id,
                "incident_id": incident_id,
                "minutes": (report.sim_time - int(row["started_sim"])) // 60,
                "escalated": row["escalation_event_seq"] is not None,
            },
        )
        # What the outage cost its customers is decided the moment it ends.
        flows.credits(
            self,
            report,
            module_id=module_id,
            incident_id=incident_id,
            ended_seq=ended_seq,
            minutes=minutes,
            escalated=row["escalation_event_seq"] is not None,
        )

    # -- flow 2: customers file tickets, support triages and answers -------

    def _customers(self, report: TickReport, now: SimTime) -> None:
        """People who have noticed an outage decide whether to report it.

        Asked when they notice, and again each day it goes on, at a time of
        their own. Not every tick: someone who shrugged at ten is not asked
        again at quarter past.
        """

        waiting = self._conn.execute(
            "SELECT n.incident_id, n.person_id, n.asked_day, i.module_id, "
            "  i.started_sim, i.cause_event_seq, p.traits "
            "FROM outage_notices n JOIN incidents i ON i.id = n.incident_id "
            "JOIN persons p ON p.id = n.person_id "
            "WHERE i.ended_sim IS NULL AND n.ticket_id IS NULL "
            "  AND n.notice_sim <= %s ORDER BY n.incident_id, n.person_id",
            (report.sim_time,),
        ).fetchall()
        asked: list[DictRow] = []
        contexts: list[DecisionContext] = []
        for row in waiting:
            person_id = str(row["person_id"])
            # They have noticed it themselves, first hand. Written down whether
            # or not they go on to report it: knowing is not the same as acting,
            # and it is knowing that they can pass on (MEM-0002).
            memory.learn(
                self._conn,
                person_id,
                memory.Fact.outage(int(row["incident_id"]), str(row["module_id"])).id,
                sim_time=report.sim_time,
            )
            if row["asked_day"] is not None and not self.gets_to_it(
                person_id, now, "report", row["asked_day"]
            ):
                continue
            open_already = self._conn.execute(
                "SELECT 1 FROM tickets WHERE reporter_id = %s AND status <> 'closed' "
                "LIMIT 1",
                (person_id,),
            ).fetchone()
            asked.append(row)
            contexts.append(
                DecisionContext(
                    person_id=person_id,
                    role="subscriber",
                    sim_time=report.sim_time,
                    kind="file.ticket",
                    facts={
                        "module_down": True,
                        "already_open": open_already is not None,
                        "hours_down": (report.sim_time - int(row["started_sim"]))
                        // HOUR,
                    },
                    traits=dict(row["traits"] or {}),
                )
            )
        if not asked:
            return
        self._conn.execute(
            "UPDATE outage_notices SET asked_day = %s WHERE (incident_id, person_id) "
            "IN (SELECT * FROM unnest(%s::bigint[], %s::text[]))",
            (
                now.day,
                [int(r["incident_id"]) for r in asked],
                [str(r["person_id"]) for r in asked],
            ),
        )
        for row, made in zip(asked, self._decide_many(report, contexts), strict=True):
            # Noticing is knowing (MEM-0002): the fact spreads from here.
            beliefs.learn(
                self._conn,
                str(row["person_id"]),
                f"outage:{int(row['incident_id'])}",
                report.sim_time,
            )
            if made.chosen.get("file"):
                self._file(report, row, made)

    def _file(self, report: TickReport, row: DictRow, made: Made) -> None:
        person_id = str(row["person_id"])
        module_id = str(row["module_id"])
        incident_id = int(row["incident_id"])
        causes = _seq_of(row["cause_event_seq"])
        # The same person hitting the same module again within days of being
        # told it was fixed is the same complaint, reopened.
        recent = self._conn.execute(
            "UPDATE tickets SET status = 'triaged', closed_sim = NULL, "
            "  reopened = reopened + 1, incident_id = %s, answered_sim = NULL "
            "WHERE id = (SELECT id FROM tickets WHERE reporter_id = %s "
            "  AND module_id = %s AND status = 'closed' AND closed_sim >= %s "
            "  ORDER BY closed_sim DESC, id DESC LIMIT 1) RETURNING id",
            (incident_id, person_id, module_id, report.sim_time - REOPEN_WINDOW),
        ).fetchone()
        subject = f"{module_id} is not responding"
        if recent is not None:
            ticket_id = int(recent["id"])
            kind = "ticket.reopened"
        else:
            ticket = self._conn.execute(
                "INSERT INTO tickets (opened_sim, reporter_id, module_id, "
                "incident_id, subject) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (report.sim_time, person_id, module_id, incident_id, subject),
            ).fetchone()
            assert ticket is not None
            ticket_id = int(ticket["id"])
            kind = "ticket.opened"
        self._conn.execute(
            "UPDATE outage_notices SET ticket_id = %s "
            "WHERE incident_id = %s AND person_id = %s",
            (ticket_id, incident_id, person_id),
        )
        self._emit(
            report,
            kind,
            actor_id=person_id,
            org_id=module_owner(module_id),
            causes=causes,
            decision_id=made.id,
            payload={
                "ticket_id": ticket_id,
                "reporter_id": person_id,
                "module_id": module_id,
                "subject": subject,
            },
        )

    def _support(self, report: TickReport, now: SimTime) -> None:
        """Each vendor's support desk works its own queue: the tickets about
        the products it sells."""

        for org in ORGS:
            if org.archetype == "vendor" and org.support_roles:
                self._support_desk(report, org.id, list(org.support_roles))

    def _support_desk(self, report: TickReport, vendor: str, roles: list[str]) -> None:
        modules = list(modules_of(vendor))
        staff = self._conn.execute(
            "SELECT id, traits FROM persons WHERE org_id = %s "
            "AND role = ANY(%s) ORDER BY id",
            (vendor, roles),
        ).fetchall()
        if not staff:
            return
        backlog_row = self._conn.execute(
            "SELECT count(*) AS n FROM tickets WHERE status <> 'closed' "
            "AND module_id = ANY(%s)",
            (modules,),
        ).fetchone()
        backlog = int(backlog_row["n"]) if backlog_row else 0

        for agent in staff:
            person_id = str(agent["id"])
            if person_id in report.in_episode:
                # They spent this quarter of an hour in a conversation. A world
                # where talking is free makes talking strictly dominant.
                continue
            traits = dict(agent["traits"] or {})

            # Triage the oldest untriaged ticket.
            untriaged = self._conn.execute(
                "SELECT t.id, t.module_id, t.subject, "
                "  (SELECT seq FROM events e WHERE e.kind = 'ticket.opened' "
                "     AND (e.payload->>'ticket_id')::bigint = t.id "
                "   ORDER BY e.seq LIMIT 1) AS opened_seq "
                "FROM tickets t WHERE t.status = 'open' AND t.module_id = ANY(%s) "
                "ORDER BY t.opened_sim, t.id LIMIT 1",
                (modules,),
            ).fetchone()
            if untriaged is not None:
                module_id = untriaged["module_id"]
                made = self._decide(
                    report,
                    DecisionContext(
                        person_id=person_id,
                        role="support",
                        sim_time=report.sim_time,
                        kind="ticket.triage",
                        facts={
                            "subject": str(untriaged["subject"]),
                            "module_down": bool(
                                module_id and self._module_down(str(module_id))
                            ),
                            "mentions_billing": "invoic" in str(untriaged["subject"]),
                            "backlog": backlog,
                        },
                        traits=traits,
                    ),
                )
                self._conn.execute(
                    "UPDATE tickets SET status = 'triaged', assignee_id = %s, "
                    "queue = %s, severity = %s, decided_by = %s WHERE id = %s",
                    (
                        person_id,
                        made.chosen["queue"],
                        made.chosen["severity"],
                        made.source,
                        untriaged["id"],
                    ),
                )
                self._emit(
                    report,
                    "ticket.triaged",
                    actor_id=person_id,
                    org_id=vendor,
                    causes=(
                        [int(untriaged["opened_seq"])]
                        if untriaged["opened_seq"]
                        else []
                    ),
                    decision_id=made.id,
                    payload={
                        "ticket_id": int(untriaged["id"]),
                        "assignee_id": person_id,
                        "queue": made.chosen["queue"],
                        "severity": made.chosen["severity"],
                        "decided_by": made.source,
                    },
                )
                continue

            # Otherwise answer something already triaged.
            triaged = self._conn.execute(
                "SELECT id FROM tickets WHERE status = 'triaged' "
                "AND module_id = ANY(%s) "
                "ORDER BY severity DESC, opened_sim, id LIMIT 1",
                (modules,),
            ).fetchone()
            if triaged is None:
                continue
            made = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role="support",
                    sim_time=report.sim_time,
                    kind="ticket.answer",
                    facts={"backlog": backlog},
                    traits=traits,
                ),
            )
            if not made.chosen.get("answer_now"):
                continue
            answered = self._emit(
                report,
                "ticket.answered",
                actor_id=person_id,
                org_id=vendor,
                decision_id=made.id,
                payload={
                    "ticket_id": int(triaged["id"]),
                    "assignee_id": person_id,
                    "decided_by": made.source,
                },
            )
            self._conn.execute(
                "UPDATE tickets SET status = 'answered', answered_sim = %s, "
                "answered_seq = %s, asked_day = NULL WHERE id = %s",
                (report.sim_time, answered, triaged["id"]),
            )

    def _followups(self, report: TickReport, now: SimTime) -> None:
        """An answered ticket ends: confirmed by its reporter, or timed out.

        Without this an answered ticket stayed open for ever, its reporter
        counted as "already has one open" for ever, and support received three
        tickets in the last twenty-six days of a thirty-day run.
        """

        answered = self._conn.execute(
            "SELECT t.id, t.reporter_id, t.module_id, t.answered_sim, t.answered_seq, "
            "  t.asked_day, p.traits, m.status AS module_status, "
            "  COALESCE(i.ended_sim, %s) - i.started_sim AS outage_seconds "
            "FROM tickets t JOIN persons p ON p.id = t.reporter_id "
            "LEFT JOIN modules m ON m.id = t.module_id "
            "LEFT JOIN incidents i ON i.id = t.incident_id "
            "WHERE t.status = 'answered' ORDER BY t.id",
            (report.sim_time,),
        ).fetchall()
        asked: list[DictRow] = []
        contexts: list[DecisionContext] = []
        for row in answered:
            since = report.sim_time - int(row["answered_sim"] or report.sim_time)
            if since >= TICKET_TIMEOUT:
                self._close(report, row, reason="timeout")
                continue
            reporter = str(row["reporter_id"])
            if not self.gets_to_it(reporter, now, "inbox", row["asked_day"]):
                continue
            asked.append(row)
            contexts.append(
                DecisionContext(
                    person_id=reporter,
                    role="subscriber",
                    sim_time=report.sim_time,
                    kind="ticket.confirm",
                    facts={
                        "module_down": row["module_status"] == "down",
                        "days_since_answer": since // DAY,
                        "outage_hours": int(row["outage_seconds"] or 0) // HOUR,
                    },
                    traits=dict(row["traits"] or {}),
                )
            )
        if not asked:
            return
        self._conn.execute(
            "UPDATE tickets SET asked_day = %s WHERE id = ANY(%s)",
            (now.day, [int(r["id"]) for r in asked]),
        )
        for row, made in zip(asked, self._decide_many(report, contexts), strict=True):
            level = made.chosen.get("vendor_reliability")
            if level is not None and row["module_id"]:
                # What the outage did to their view of the vendor (MEM-0003).
                beliefs.set_level(
                    self._conn,
                    str(row["reporter_id"]),
                    "vendor_reliability",
                    module_owner(str(row["module_id"])),
                    int(str(level)),
                    report.sim_time,
                )
            if made.chosen.get("confirm"):
                self._close(report, row, reason="confirmed", made=made)

    def _close(
        self, report: TickReport, row: DictRow, *, reason: str, made: Made | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE tickets SET status = 'closed', closed_sim = %s WHERE id = %s",
            (report.sim_time, row["id"]),
        )
        self._emit(
            report,
            "ticket.closed",
            actor_id=str(row["reporter_id"]) if made else None,
            org_id=module_owner(str(row["module_id"])) if row["module_id"] else None,
            causes=_seq_of(row["answered_seq"]),
            decision_id=made.id if made else None,
            payload={
                "ticket_id": int(row["id"]),
                "reason": reason,
                "decided_by": made.source if made else "rules",
            },
        )

    # -- flow 3: month-end invoicing, blocked while Invoicing is down ------

    def _month_end(self, report: TickReport, payload: dict[str, Any]) -> None:
        month = int(payload.get("month", 0))
        seq = self._emit(
            report,
            "month.end",
            payload={"label": str(payload.get("label", "")), "month": month},
        )
        # Run in this same tick; a blocked run reschedules itself.
        for org in ORGS:
            if org.billing is not None:
                self._issue_invoices(report, org.id, cause=seq, month=month)
        # And the month after. It fired once, and the world ran down (audit B1).
        self._schedule(
            report.sim_time + 28 * DAY,
            "month.end",
            None,
            {"label": f"month {month + 2}", "month": month + 1},
        )

    def _issue_invoices(
        self,
        report: TickReport,
        org_id: str,
        *,
        cause: int,
        month: int,
        was_blocked: bool = False,
    ) -> None:
        """The cascade's first link: no invoicing module, no invoices."""

        billing = BY_ID[org_id].billing
        assert billing is not None
        blocked_by = self._blocked(org_id, "invoicing")
        if blocked_by is not None:
            pending = len(self.engaged_clients(org_id, month))
            # Two causes, and both are true: month-end is why a run was
            # attempted, the outage is why it failed. Citing only the calendar
            # would leave the outage with no billing consequences downstream,
            # which is the whole claim the simulation exists to show.
            outage = self._conn.execute(
                "SELECT cause_event_seq FROM incidents "
                "WHERE module_id = %s AND ended_sim IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (blocked_by,),
            ).fetchone()
            causes = [cause] if cause else []
            if outage is not None:
                causes += _seq_of(outage["cause_event_seq"])
            if not was_blocked:
                # Said once. It was said every tick the outage lasted, which
                # buried the one fact under a hundred copies of it.
                self._emit(
                    report,
                    "invoice.blocked",
                    org_id=org_id,
                    causes=causes,
                    payload={
                        "from_org_id": org_id,
                        "module_id": blocked_by,
                        "pending": pending,
                        "reason": "invoicing module is down",
                    },
                )
            # Try again next tick.
            self._schedule(
                report.sim_time + TICK,
                "invoice.run",
                org_id,
                {"cause": cause, "blocked": True, "month": month},
            )
            return

        # A run that had been blocked goes out *because the outage ended*, and
        # when it ended is itself caused. Citing only month-end here would cut
        # the chain exactly where an outage turns into late money.
        causes = [cause] if cause else []
        if was_blocked:
            ended = self._conn.execute(
                "SELECT seq FROM events WHERE kind = 'incident.ended' "
                "AND payload->>'module_id' = ANY(%s) ORDER BY seq DESC LIMIT 1",
                (list(modules_of(org_id, "invoicing")),),
            ).fetchone()
            causes += _seq_of(ended["seq"]) if ended else []
        for client_id, amount in self.engaged_clients(org_id, month):
            self.bill(
                report,
                from_org=org_id,
                to_person=client_id,
                amount=amount,
                terms_days=billing.terms_days,
                kind=billing.kind if billing.kind == "milestone" else "services",
                causes=causes,
            )

    def engaged_clients(self, org_id: str, month: int) -> list[tuple[str, int]]:
        """Who had work done this month, and what it came to.

        CORE-0009: keyed by (firm, client, month) and by nothing else, so the
        same invoice is for the same amount whether it goes out on the 3rd or,
        because of an outage, on the 4th. The amount used to come from the tick
        it was issued in; a counterfactual that delayed billing re-rolled every
        bill, and "the outage made the money late" could not be told apart from
        "the outage changed the money".
        """

        billing = BY_ID[org_id].billing
        if billing is None:
            return []
        clients = self._conn.execute(
            "SELECT id FROM persons WHERE org_id = %s AND kind = 'counterparty' "
            "ORDER BY id",
            (org_id,),
        ).fetchall()
        low, high = billing.amount_cents
        billed: list[tuple[str, int]] = []
        for client in clients:
            client_id = str(client["id"])
            rng = derive_rng(self._root, "engagement", org_id, client_id, month)
            if rng.random() < billing.engaged_per_month:
                billed.append((client_id, low + int(rng.random() * (high - low))))
        return billed

    def bill(
        self,
        report: TickReport,
        *,
        from_org: str,
        amount: int,
        terms_days: int,
        kind: str,
        causes: list[int],
        to_person: str | None = None,
        to_org: str | None = None,
    ) -> int:
        """Issue one invoice: the row, the event, the receivable. Returns its id."""

        invoice = self._conn.execute(
            "INSERT INTO invoices (from_org_id, to_org_id, to_person_id, issued_sim, "
            "due_sim, amount_cents, kind) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                from_org,
                to_org,
                to_person,
                report.sim_time,
                report.sim_time + terms_days * DAY,
                amount,
                kind,
            ),
        ).fetchone()
        assert invoice is not None
        seq = self._emit(
            report,
            "invoice.issued",
            org_id=from_org,
            causes=causes,
            payload={
                "invoice_id": int(invoice["id"]),
                "from_org_id": from_org,
                "to": to_person or to_org,
                "amount_cents": amount,
                "invoice_kind": kind,
            },
        )
        self._conn.execute(
            "UPDATE invoices SET issued_seq = %s WHERE id = %s", (seq, invoice["id"])
        )
        self._post(
            report.sim_time,
            f"{from_org} invoices {to_person or to_org}",
            [(f"{from_org}.receivable", amount), (f"{from_org}.revenue", -amount)],
            seq,
        )
        return int(invoice["id"])

    # -- flow 4: subscription invoices (automatic) -------------------------

    def _subscriptions(self, report: TickReport, vendor: str) -> None:
        """A vendor bills everyone on its products, in one run."""

        rows = self._conn.execute(
            "SELECT id, org_id, person_id, module_id, monthly_cents FROM subscriptions "
            "WHERE active AND module_id = ANY(%s) ORDER BY id",
            (list(modules_of(vendor)),),
        ).fetchall()
        rows = self._churn(report, vendor, rows)
        total = 0
        issued: list[int] = []
        for row in rows:
            amount = int(row["monthly_cents"])
            invoice = self._conn.execute(
                "INSERT INTO invoices (from_org_id, to_org_id, to_person_id, "
                "issued_sim, due_sim, amount_cents, kind) "
                "VALUES (%s,%s,%s,%s,%s,%s,'subscription') RETURNING id",
                (
                    vendor,
                    row["org_id"],
                    row["person_id"],
                    report.sim_time,
                    report.sim_time + 14 * DAY,
                    amount,
                ),
            ).fetchone()
            assert invoice is not None
            issued.append(int(invoice["id"]))
            total += amount
        if total:
            seq = self._emit(
                report,
                "invoice.issued",
                org_id=vendor,
                payload={
                    "invoice_id": 0,
                    "from_org_id": vendor,
                    "to": "all subscribers",
                    "amount_cents": total,
                    "invoice_kind": "subscription",
                },
            )
            self._conn.execute(
                "UPDATE invoices SET issued_seq = %s WHERE id = ANY(%s)", (seq, issued)
            )
            self._post(
                report.sim_time,
                f"{vendor} monthly subscriptions",
                [(f"{vendor}.receivable", total), (f"{vendor}.revenue", -total)],
                seq,
            )
        # Monthly, so the next run is 28 days out.
        self._schedule(report.sim_time + 28 * DAY, "subscription.run", vendor, {})

    def _churn(
        self, report: TickReport, vendor: str, rows: list[DictRow]
    ) -> list[DictRow]:
        """Renewal is where a belief about the vendor becomes a decision
        (MEM-0003): a subscriber whose people think the product unreliable,
        and who could buy the same thing from the other vendor, is asked once
        a month whether to. Returns the rows this vendor still bills."""

        asked: list[DictRow] = []
        contexts: list[DecisionContext] = []
        competitors: dict[str, str] = {}
        for row in rows:
            module = str(row["module_id"])
            category = MODULES[module].category
            rival = next(
                (
                    m
                    for m, spec in sorted(MODULES.items())
                    if spec.category == category and module_owner(m) != vendor
                ),
                None,
            )
            if rival is None:
                continue
            org_id = str(row["org_id"]) if row["org_id"] else None
            person = str(row["person_id"]) if row["person_id"] else None
            if org_id is not None:
                view = beliefs.firm_view(
                    self._conn, org_id, "vendor_reliability", vendor
                )
                payer = self.payer_of(org_id)
                decider = payer
            else:
                assert person is not None
                view = beliefs.get(self._conn, person, "vendor_reliability", vendor)
                decider = self._conn.execute(
                    "SELECT id, role, traits FROM persons WHERE id = %s", (person,)
                ).fetchone()
            if view is None or view > 1 or decider is None:
                continue
            competitors[str(row["id"])] = rival
            asked.append(row)
            contexts.append(
                DecisionContext(
                    person_id=str(decider["id"]),
                    role=str(decider["role"]),
                    sim_time=report.sim_time,
                    kind="subscription.switch",
                    facts={
                        "org": org_id or "",
                        "module": module,
                        "competitor": module_owner(rival),
                        "reliability": view,
                    },
                    traits=dict(decider["traits"] or {}),
                )
            )
        if not asked:
            return rows
        gone: set[int] = set()
        for row, made in zip(asked, self._decide_many(report, contexts), strict=True):
            if not made.chosen.get("switch"):
                continue
            rival = competitors[str(row["id"])]
            old = str(row["module_id"])
            ended = self._conn.execute(
                "SELECT seq FROM events WHERE kind = 'incident.ended' "
                "AND payload->>'module_id' = %s ORDER BY seq DESC LIMIT 1",
                (old,),
            ).fetchone()
            self._conn.execute(
                "UPDATE subscriptions SET module_id = %s, monthly_cents = %s "
                "WHERE id = %s",
                (rival, MODULES[rival].monthly_cents, int(row["id"])),
            )
            self._emit(
                report,
                "subscription.switched",
                actor_id=str(row["person_id"]) if row["person_id"] else None,
                org_id=str(row["org_id"]) if row["org_id"] else vendor,
                decision_id=made.id,
                causes=[int(ended["seq"])] if ended else [],
                payload={
                    "from_module": old,
                    "to_module": rival,
                    "from_vendor": vendor,
                    "to_vendor": module_owner(rival),
                    "subscriber": str(row["org_id"] or row["person_id"]),
                    "decided_by": made.source,
                },
            )
            gone.add(int(row["id"]))
        return [row for row in rows if int(row["id"]) not in gone]

    def _outside_income(self, report: TickReport, org_id: str) -> None:
        """A week's worth of what the firm earns beyond the district."""

        org = BY_ID[org_id]
        amount = org.outside_income_cents // 4
        if amount > 0:
            seq = self._emit(
                report,
                "income.outside",
                org_id=org_id,
                payload={"org_id": org_id, "amount_cents": amount},
            )
            self._post(
                report.sim_time,
                f"{org_id} income from beyond the district",
                [(f"{org_id}.cash", amount), (f"{org_id}.revenue", -amount)],
                seq,
            )
        self._schedule(report.sim_time + 7 * DAY, "income.outside", org_id, {})

    # -- flow 5: payments --------------------------------------------------

    def _open_bills(self, where: str, params: tuple[Any, ...]) -> list[DictRow]:
        """Unpaid bills whose payer has started thinking about them."""

        return self._conn.execute(
            "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, i.to_org_id, "
            "  i.to_person_id, i.issued_seq, i.asked_day, i.deferrals, i.chased_sim "
            "FROM invoices i WHERE i.paid_sim IS NULL AND i.written_off_sim IS NULL "
            f"  AND i.due_sim <= %s AND {where} ORDER BY i.due_sim, i.id",
            (params[0] + ASK_FROM_DAYS_BEFORE_DUE * DAY, *params[1:]),
        ).fetchall()

    def _payments(self, report: TickReport, now: SimTime) -> None:
        """Each firm's bill-payer sits down to the bills once a day.

        Every bill that is nearly due or overdue gets one answer a day: pay it
        today, or not. It used to be the single most overdue bill, asked every
        tick and thinned to a per-tick hazard; a run logged 1,591
        `payment.deferred` events, each one a die being rolled.
        """

        for org in ORGS:
            payer = self.payer_of(org.id)
            if payer is None:
                continue
            person_id = str(payer["id"])
            if person_id in report.in_episode:
                continue
            if now.time_of_day < self.slot(person_id, now.day, "bills"):
                continue
            bills = [
                bill
                for bill in self._open_bills(
                    "i.to_org_id = %s", (report.sim_time, org.id)
                )
                if bill["asked_day"] is None or int(bill["asked_day"]) < now.day
            ]
            if not bills:
                continue
            cash = self.cash_of(f"{org.id}.cash")
            contexts = [
                DecisionContext(
                    person_id=person_id,
                    role=str(payer["role"]),
                    sim_time=report.sim_time,
                    kind="payment.timing",
                    facts={
                        "days_until_due": (int(bill["due_sim"]) - report.sim_time)
                        // DAY,
                        "can_afford": cash >= int(bill["amount_cents"]),
                        "runway_days": cash / max(1, int(bill["amount_cents"])) * 7,
                        "chased": bill["chased_sim"] is not None,
                        "promised": memory.open_commitment(self._conn, int(bill["id"]))
                        is not None,
                    },
                    traits=dict(payer["traits"] or {}),
                )
                for bill in bills
            ]
            self._settle(report, now, bills, contexts, payer_account=f"{org.id}.cash")

    def _client_payments(self, report: TickReport, now: SimTime) -> None:
        """Outside clients settling what the firms invoiced them.

        Every client with a bill, not the eight oldest bills a quarter of the
        time. Most pay by standing instruction on the day (a gate); the slowest
        fifth are asked, daily, at an hour of their own.
        """

        bills: list[DictRow] = []
        contexts: list[DecisionContext] = []
        for bill in self._open_bills("i.to_person_id IS NOT NULL", (report.sim_time,)):
            person_id = str(bill["to_person_id"])
            if not self.gets_to_it(person_id, now, "bills", bill["asked_day"]):
                continue
            person = self._conn.execute(
                "SELECT traits FROM persons WHERE id = %s", (person_id,)
            ).fetchone()
            traits = dict((person or {}).get("traits") or {})
            days_until_due = (int(bill["due_sim"]) - report.sim_time) // DAY
            autopay = trait_fraction("promptness", traits.get("promptness")) >= (
                AUTOPAY_ABOVE
            )
            if autopay and days_until_due > 0:
                continue  # the instruction fires on the day, not before
            bills.append(bill)
            contexts.append(
                DecisionContext(
                    person_id=person_id,
                    role="client",
                    sim_time=report.sim_time,
                    kind="payment.timing",
                    facts={
                        "days_until_due": days_until_due,
                        "can_afford": True,
                        "runway_days": 60,
                        "chased": bill["chased_sim"] is not None,
                        "autopay": autopay,
                        "promised": memory.open_commitment(self._conn, int(bill["id"]))
                        is not None,
                    },
                    traits=traits,
                )
            )
        if bills:
            self._settle(report, now, bills, contexts, payer_account=None)

    def _settle(
        self,
        report: TickReport,
        now: SimTime,
        bills: list[DictRow],
        contexts: list[DecisionContext],
        *,
        payer_account: str | None,
    ) -> None:
        """Ask about each bill, then move the money for the ones being paid.

        Money is never moved by a model: a "pay" that the account cannot cover
        by the time its turn comes is deferred by the referee.
        """

        self._conn.execute(
            "UPDATE invoices SET asked_day = %s WHERE id = ANY(%s)",
            (now.day, [int(bill["id"]) for bill in bills]),
        )
        cash = self.cash_of(payer_account) if payer_account else None
        for bill, ctx, made in zip(
            bills, contexts, self._decide_many(report, contexts), strict=True
        ):
            amount = int(bill["amount_cents"])
            pays = bool(made.chosen.get("pay"))
            reason = str(made.chosen.get("reason", ""))
            if pays and cash is not None and cash < amount:
                pays, reason = False, "insufficient_cash"
            causes = _seq_of(bill["issued_seq"])
            days_late = max(0, (report.sim_time - int(bill["due_sim"])) // DAY)
            payee = str(bill["from_org_id"])
            payer_org = str(bill["to_org_id"]) if bill["to_org_id"] else payee
            if not pays:
                overdue = report.sim_time >= int(bill["due_sim"])
                if overdue and int(bill["deferrals"]) == 0:
                    # Said once, the first day a bill is left unpaid past its
                    # date. The days after are the same fact.
                    self._emit(
                        report,
                        "payment.deferred",
                        actor_id=ctx.person_id,
                        org_id=payer_org,
                        causes=causes,
                        decision_id=made.id,
                        payload={
                            "invoice_id": int(bill["id"]),
                            "days_late": days_late,
                            "reason": reason,
                            "decided_by": made.source,
                        },
                    )
                if overdue:
                    self._conn.execute(
                        "UPDATE invoices SET deferrals = deferrals + 1 WHERE id = %s",
                        (bill["id"],),
                    )
                continue

            seq = self._emit(
                report,
                "payment.made",
                actor_id=ctx.person_id,
                org_id=payer_org,
                causes=causes,
                decision_id=made.id,
                payload={
                    "invoice_id": int(bill["id"]),
                    "amount_cents": amount,
                    "days_late": days_late,
                    "reason": reason,
                    "decided_by": made.source,
                },
            )
            legs = [(f"{payee}.cash", amount), (f"{payee}.receivable", -amount)]
            if payer_account is not None:
                legs += [(payer_account, -amount), (f"{payer_org}.expense", amount)]
                assert cash is not None
                cash -= amount
            txn = self._post(
                report.sim_time, f"{ctx.person_id} pays {payee} invoice {bill['id']}",
                legs, seq,
            )  # fmt: skip
            self._conn.execute(
                "UPDATE invoices SET paid_sim = %s WHERE id = %s",
                (report.sim_time, bill["id"]),
            )
            self._conn.execute(
                "INSERT INTO payments (invoice_id, paid_sim, amount_cents, txn_id, "
                "days_late) VALUES (%s,%s,%s,%s,%s)",
                (bill["id"], report.sim_time, amount, txn, days_late),
            )
            # Anyone who gave their word about this bill has now kept it.
            memory.close_commitments_for(
                self._conn, int(bill["id"]), sim_time=report.sim_time, kept=True
            )

    def _chase(self, report: TickReport, now: SimTime) -> None:
        """A bill a week late gets chased — if whoever is owed is the type.

        And one sixty days late is written off, by rule: a receivable nobody
        will ever collect is not an asset, and a soak should not end with a
        balance sheet full of them.
        """

        late = self._conn.execute(
            "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, i.to_org_id, "
            "  i.to_person_id, i.issued_seq, i.chase_asked_day "
            "FROM invoices i WHERE i.paid_sim IS NULL AND i.written_off_sim IS NULL "
            "  AND i.due_sim <= %s AND (i.chased_sim IS NULL OR i.due_sim <= %s) "
            "ORDER BY i.from_org_id, i.due_sim, i.id",
            (report.sim_time - CHASE_AFTER, report.sim_time - WRITE_OFF_AFTER),
        ).fetchall()
        asked: list[DictRow] = []
        contexts: list[DecisionContext] = []
        chasers: dict[str, DictRow | None] = {}
        for bill in late:
            issuer = str(bill["from_org_id"])
            if int(bill["due_sim"]) <= report.sim_time - WRITE_OFF_AFTER:
                self._write_off(report, bill)
                continue
            if issuer not in chasers:
                chasers[issuer] = self.payer_of(issuer)
            chaser = chasers[issuer]
            if chaser is None or str(chaser["id"]) in report.in_episode:
                continue
            if not self.gets_to_it(
                str(chaser["id"]), now, "chasing", bill["chase_asked_day"]
            ):
                continue
            cash = self.cash_of(f"{issuer}.cash")
            debtor = str(bill["to_person_id"] or bill["to_org_id"])
            asked.append(bill)
            contexts.append(
                DecisionContext(
                    person_id=str(chaser["id"]),
                    role=str(chaser["role"]),
                    sim_time=report.sim_time,
                    kind="chase.invoice",
                    facts={
                        "org": issuer,
                        "days_late": (report.sim_time - int(bill["due_sim"])) // DAY,
                        "large": int(bill["amount_cents"]) >= 200_000,
                        "runway_days": cash / max(1, int(bill["amount_cents"])) * 7,
                        "debtor": debtor,
                        "trust_level": beliefs.get(
                            self._conn, str(chaser["id"]), "counterparty_trust", debtor
                        ),
                    },
                    traits=dict(chaser["traits"] or {}),
                )
            )
        if not asked:
            return
        self._conn.execute(
            "UPDATE invoices SET chase_asked_day = %s WHERE id = ANY(%s)",
            (now.day, [int(bill["id"]) for bill in asked]),
        )
        for bill, ctx, made in zip(
            asked, contexts, self._decide_many(report, contexts), strict=True
        ):
            trust = made.chosen.get("counterparty_trust")
            if trust is not None:
                beliefs.set_level(
                    self._conn,
                    ctx.person_id,
                    "counterparty_trust",
                    str(ctx.facts["debtor"]),
                    int(str(trust)),
                    report.sim_time,
                )
            if not made.chosen.get("chase"):
                continue
            self._emit(
                report,
                "invoice.chased",
                actor_id=ctx.person_id,
                org_id=str(bill["from_org_id"]),
                causes=_seq_of(bill["issued_seq"]),
                decision_id=made.id,
                payload={
                    "invoice_id": int(bill["id"]),
                    "to": str(bill["to_person_id"] or bill["to_org_id"]),
                    "days_late": ctx.facts["days_late"],
                    "decided_by": made.source,
                },
            )
            self._conn.execute(
                "UPDATE invoices SET chased_sim = %s WHERE id = %s",
                (report.sim_time, bill["id"]),
            )

    def _write_off(self, report: TickReport, bill: DictRow) -> None:
        issuer = str(bill["from_org_id"])
        amount = int(bill["amount_cents"])
        seq = self._emit(
            report,
            "invoice.written_off",
            org_id=issuer,
            causes=_seq_of(bill["issued_seq"]),
            payload={
                "invoice_id": int(bill["id"]),
                "amount_cents": amount,
                "days_late": (report.sim_time - int(bill["due_sim"])) // DAY,
            },
        )
        self._post(
            report.sim_time,
            f"{issuer} writes off invoice {bill['id']}",
            [(f"{issuer}.receivable", -amount), (f"{issuer}.expense", amount)],
            seq,
        )
        self._conn.execute(
            "UPDATE invoices SET written_off_sim = %s WHERE id = %s",
            (report.sim_time, bill["id"]),
        )

    # -- flow 6: the tills ---------------------------------------------------

    def _retail(self, report: TickReport, now: SimTime) -> None:
        """Every firm with a till, on its own hours: the cafe, the hardware
        store, the gym, the clinic's appointments."""

        for org in retailers():
            if now.open_for(org.hours):
                self._till(report, now, org.id)

    def _till(self, report: TickReport, now: SimTime, org_id: str) -> None:
        org = BY_ID[org_id]
        retail = org.retail
        assert retail is not None
        till_down = self._blocked(org_id, retail.till) is not None
        minute = now.time_of_day // MINUTE
        rng = derive_rng(self._root, "retail", org_id, now.day, minute)
        hourly = retail.arrivals_per_hour.get(now.time_of_day // HOUR, 0)
        if now.weekday == 5:
            hourly = hourly // 2  # Saturdays are quiet: the offices are shut
        expected = hourly * TICK / HOUR
        arrivals = int(expected) + (1 if rng.random() < expected % 1 else 0)

        customers = self._conn.execute(
            "SELECT id, traits FROM persons WHERE org_id = %s "
            "AND kind = 'counterparty' ORDER BY id",
            (org_id,),
        ).fetchall()
        walk_ins = (
            [customers[int(rng.random() * len(customers))] for _ in range(arrivals)]
            if customers
            else []
        )
        # People from the other firms who walked in this tick queue with
        # everyone else. Their coffee is paid for out of their wages
        # (households), which is how a payroll held by an outage reaches the
        # till. Only somewhere staff go on their own time has them.
        staff: list[DictRow] = []
        if org.social:
            staff = self._conn.execute(
                "SELECT p.id, p.traits FROM positions pos JOIN persons p "
                "ON p.id = pos.person_id WHERE pos.zone = %s AND pos.floor = 0 "
                "AND pos.moved_tick = %s AND p.org_id <> %s ORDER BY p.id",
                (org_id, report.tick_seq, org_id),
            ).fetchall()
        household_cash = self.cash_of("households.cash") if staff else 0
        # A retailer with a supplier sells from stock (WORLD-0010). An arrival
        # finds the shelf as the arrivals ahead of it would leave it: the same
        # independence that lets the whole tick's customers be asked at once.
        stock = self.stock_of(org_id) if org.supplier is not None else None

        servers = retail.servers / 2 if till_down else retail.servers
        low, high = retail.basket_cents
        # Who walks in, and what they find, is settled before anyone decides:
        # an arrival waits behind the arrivals ahead of it, not behind what
        # those people went on to choose. That independence is what lets the
        # whole tick's customers be asked at once.
        contexts: list[DecisionContext] = []
        baskets: list[int] = []
        employed: list[bool] = []
        for arrival, row in enumerate([*walk_ins, *staff]):
            person_id = str(row["id"])
            is_staff = arrival >= len(walk_ins)
            basket_rng = derive_rng(
                self._root, "basket", person_id, now.day, minute, arrival
            )
            basket = low + int(basket_rng.random() * (high - low))
            baskets.append(basket)
            employed.append(is_staff)
            contexts.append(
                DecisionContext(
                    person_id=person_id,
                    role="customer",
                    sim_time=report.sim_time,
                    kind="retail.purchase",
                    facts={
                        "org": org_id,
                        "till_down": till_down,
                        "queue_length": max(0, int(arrival - servers)),
                        "can_afford": (not is_staff) or household_cash >= basket,
                        "no_stock": stock is not None and stock - arrival <= 0,
                    },
                    traits=dict(row["traits"] or {}),
                )
            )
        if not contexts:
            return

        sold = 0
        for ctx, amount, is_staff, made in zip(
            contexts,
            baskets,
            employed,
            self._decide_many(report, contexts),
            strict=True,
        ):
            person_id = ctx.person_id
            if not made.chosen.get("buy"):
                self._emit(
                    report,
                    "retail.walkout",
                    actor_id=person_id,
                    org_id=org_id,
                    decision_id=made.id,
                    payload={
                        "person_id": person_id,
                        "reason": str(made.chosen.get("reason", "queue")),
                        "decided_by": made.source,
                    },
                )
                continue
            if is_staff and household_cash < amount:
                continue  # the referee: someone ahead of them spent the last of it
            sold += 1
            seq = self._emit(
                report,
                "retail.sale",
                actor_id=person_id,
                org_id=org_id,
                decision_id=made.id,
                payload={
                    "person_id": person_id,
                    "amount_cents": amount,
                    "till_down": till_down,
                    "decided_by": made.source,
                },
            )
            legs = [(f"{org_id}.cash", amount), (f"{org_id}.revenue", -amount)]
            if is_staff:
                legs += [("households.cash", -amount), ("households.spending", amount)]
                household_cash -= amount
            txn = self._post(report.sim_time, f"{org_id} sale", legs, seq)
            self._conn.execute(
                "INSERT INTO retail_sales (org_id, sim_time, person_id, amount_cents, "
                "txn_id, till_down) VALUES (%s,%s,%s,%s,%s,%s)",
                (org_id, report.sim_time, person_id, amount, txn, till_down),
            )
        if stock is not None and sold:
            self._conn.execute(
                "UPDATE orgs SET stock_units = greatest(0, stock_units - %s) "
                "WHERE id = %s",
                (sold, org_id),
            )

    def stock_of(self, org_id: str) -> int:
        row = self._conn.execute(
            "SELECT stock_units FROM orgs WHERE id = %s", (org_id,)
        ).fetchone()
        return int(row["stock_units"]) if row else 0

    # -- credit lines (WORLD-0010) ------------------------------------------

    def _credit(self, report: TickReport, now: SimTime) -> None:
        """Runway short and no line open: the bill-payer thinks about the bank,
        once a day at their own hour. And a line that can be cleared is
        cleared: repayment is a rule, the way affording anything is."""

        from jeve.world import flows

        lender = bank()
        if lender is None:
            return
        for org in ORGS:
            if org.landlord is None or org.id == lender:
                continue
            payer = self.payer_of(org.id)
            if payer is None:
                continue
            cash = self.cash_of(f"{org.id}.cash")
            weekly = org.wages_per_week_cents
            open_loan = self._conn.execute(
                "SELECT id, balance_cents FROM loans WHERE borrower_org_id = %s "
                "AND closed_sim IS NULL ORDER BY id LIMIT 1",
                (org.id,),
            ).fetchone()
            if open_loan is not None:
                if (
                    cash - int(open_loan["balance_cents"])
                    >= flows.REPAY_AT_WEEKS * weekly
                ):
                    flows.repay(self, report, org.id, open_loan)
                continue
            asked = self._conn.execute(
                "SELECT credit_asked_day FROM orgs WHERE id = %s", (org.id,)
            ).fetchone()
            if not self.gets_to_it(
                str(payer["id"]),
                now,
                "credit",
                asked["credit_asked_day"] if asked else None,
            ):
                continue
            runway_days = cash / max(1, weekly) * 7
            if runway_days >= flows.SHORT_RUNWAY_DAYS:
                continue
            self._conn.execute(
                "UPDATE orgs SET credit_asked_day = %s WHERE id = %s", (now.day, org.id)
            )
            flows.consider_credit(self, report, org.id, payer, runway_days=runway_days)


# -- scheduled work the engine itself does (WORLD-0005) ------------------------
# The flows register theirs where they are defined, in `jeve.world.flows`.


@scheduler.job("incident.start")
def _job_incident_start(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._start_incident(report, subject, payload)


@scheduler.job("incident.end")
def _job_incident_end(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._end_incident(report, subject, payload)


@scheduler.job("month.end", office_hours_only=True)
def _job_month_end(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._month_end(report, payload)


@scheduler.job("invoice.run", office_hours_only=True)
def _job_invoice_run(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._issue_invoices(
        report,
        subject,
        cause=int(payload.get("cause", 0)),
        month=int(payload.get("month", 0)),
        was_blocked=bool(payload.get("blocked")),
    )


@scheduler.job("subscription.run")
def _job_subscription_run(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._subscriptions(report, subject)


@scheduler.job("income.outside")
def _job_outside_income(
    engine: Engine, report: TickReport, subject: str, payload: dict[str, Any]
) -> None:
    engine._outside_income(report, subject)


def skip_to_next_open(conn: Connection[DictRow]) -> int:
    """Jump dead time (CORE-0003). Nothing calls a model while all is shut."""

    row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    assert row is not None
    target = next_open(int(row["sim_time"]))
    conn.execute("UPDATE sim_meta SET sim_time = %s", (target,))
    conn.commit()
    return target
