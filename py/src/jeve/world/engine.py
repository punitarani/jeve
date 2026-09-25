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
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory, tracing
from jeve.core.clock import (
    DAY,
    HOUR,
    MINUTE,
    TICK,
    WORK_END,
    WORK_START,
    SimTime,
    after_working_time,
    next_open,
)
from jeve.core.orgs import BY_ID, ORGS
from jeve.core.seed import derive_rng
from jeve.decide.gates import ASK_FROM_DAYS_BEFORE_DUE
from jeve.decide.policy import Decision, DecisionContext, Policy
from jeve.decide.questions import trait_fraction
from jeve.world import (
    customers,
    economy,
    engineering,
    episodes,
    flows,
    scheduler,
    shocks,
    space,
    timesheets,
)

# Every rate in here is per *hour*, and turned into a chance for one tick where
# it is used: nothing in the world may depend on how long a tick is.

# Tallybird's hazard: chance per business hour that a module falls over, at no
# debt; `DEBT_MULTIPLIER` scales it with the codebase's debt, which engineering
# now moves (WORLD-0011). It was 0.016, which at the seeded debt is about one
# outage a day: harmless while an outage changed nothing lasting, and a
# certain death spiral once customers remember them. At 0.006 the seeded debt
# gives about two a week, before deploys and shocks add theirs.
HAZARD_PER_HOUR = 0.006
DEBT_MULTIPLIER = 2.5

USES_PER_HOUR: dict[str, float] = {"pos": 4.0, "timetrack": 1.0, "invoicing": 0.5}
"""How often somebody touches each feature in an hour they are working, which is
how soon they find out it is down. A till is rung up every few minutes;
time is logged between tasks; invoices go out a few times a day.

It replaces one rate for everything (a mean of 117 minutes, drawn against a
90-minute outage), which put 61% of all notices after the fix: people
"noticing" an outage of a feature they did not touch until it worked again
(field report, defect 4). The delay is still drawn once per (person, incident)
(CORE-0009), but in hours of *use*, so nobody notices overnight; and a notice
that would have landed after the fix is withdrawn when the incident ends,
because by the time they tried the feature it worked."""

# Walk-ins per hour, by the hour. The same 192 across office hours as the flat
# six-a-tick it replaces, shaped like a cafe: a rush before work, a bigger one
# at lunch.
CAFE_ARRIVALS_PER_HOUR: dict[int, int] = {
    7: 24, 8: 42, 9: 36, 10: 26, 11: 18, 12: 28,
    13: 20, 14: 14, 15: 12, 16: 12, 17: 10,
}  # fmt: skip
"""The same 242 walk-ins a day, reshaped (WORLD-0014): cafes are busiest from
8 to 10 in the morning (Square POS data, 2018), and this table put its peak at
noon, so the world's busiest hour was lunch. Office staff still come at lunch,
on top of these."""

CLIENT_ENGAGED_PER_MONTH = 0.12
"""A firm bills about twelve of its hundred clients in a month. It was always the
same twelve (`ORDER BY id LIMIT 12`), which is most of why 251 of 400
counterparties never did anything at all. Now it is whoever had work done that
month, keyed by (firm, client, month)."""

TICKET_TIMEOUT = 2 * DAY
REOPEN_WINDOW = 3 * DAY
CHASE_AFTER = 7 * DAY
CHASE_HARDER_AFTER = 3 * DAY
WRITE_OFF_AFTER = 60 * DAY
AUTOPAY_ABOVE = 0.5
"""Clients this far up the promptness range pay by standing instruction on the
day. It was 0.2 — four clients in five — and the world paid its bills about on
time, where real small businesses are paid 7.8 days late (Xero, Dec quarter
2025) and 43% of B2B invoice value is overdue (Atradius US 2025). Half now pay
by instruction; the other half decide, daily, from their own cash (WORLD-0014)."""
CHASE_AGAIN_AFTER = 7 * DAY
REMINDER_LASTS = 14 * DAY
"""A bill raised in person weighs on the payer for a fortnight."""
CLIENT_CAN_PAY_DAYS = 5.0
"""Under five days of cash in hand, a client cannot pay a bill today."""
"""A dunning cadence: a bill still unpaid a week after it was chased is chased
again. It used to be chased once, ever."""
CLIENT_BUFFER_MEDIAN_DAYS = 27.0
CLIENT_BUFFER_SIGMA = 1.16
"""A client's cash buffer, in days of outgoings, drawn each month from a
log-normal fitted to JPMorgan Chase Institute's 597,000 small businesses
("Cash is King", 2016): median 27 days, a quarter under 13, a quarter over 62.
About 29% fall under the 14 days `runway_words` calls tight. Clients were told
they had 60 days, always."""
"""Clients in the four prompter fifths pay by standing instruction on the day a
bill falls due: a gate, not a question. The slowest fifth decide, daily."""


def per_tick(rate_per_hour: float) -> float:
    """The chance of at least one event in one tick, for an hourly rate."""

    return 1.0 - math.exp(-rate_per_hour * TICK / HOUR)


_DIE_AT_EVENT = int(os.environ.get("JEVE_TEST_DIE_AT_EVENT") or 0)


def _seq_of(value: object) -> list[int]:
    """A cause list from a nullable subquery result."""

    return [int(value)] if isinstance(value, int) else []


SUPPORT_ROLES = ("support", "support_lead")

FRICTION: tuple[str, ...] = (
    # One party failing, refusing or falling out with another. The golden field
    # report counted none of them in a month: "a conflict-free economy is
    # degenerate" (the scenario, §6). Measured on the base commit's rules world,
    # a month held one. Left out on purpose: cafe walkouts (a queue, not a
    # quarrel, and hundreds a week in any world), insolvency warnings (an alert
    # to oneself), and outages and what they block (weather). Read by the soak
    # and by `/report`.
    "catering.declined",
    "escalation.dropped",
    "firm.failed",
    "invoice.disputed",
    "invoice.written_off",
    # A bill left unpaid past its date, once per bill (WORLD-0005): the same
    # failure as `rent.late` and `supplier.unpaid`, owed to another firm or a
    # client's supplier instead of a landlord. Left out while deferrals were a
    # die rolled every tick; counted since WORLD-0014 put real late payment in.
    "payment.deferred",
    "payroll.held",
    "payroll.missed",
    "promise.broken",
    "relationship.soured",
    "rent.late",
    "staff.left",
    "subscription.cancelled",
    "supplier.unpaid",
)


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

    def clock(self) -> dict[str, object]:
        """When this tick is: the input of its trace (LLM-0009)."""

        now = SimTime(self.sim_time)
        return {
            **now.describe(),
            "tick_seq": self.tick_seq,
            "cafe_open": now.cafe_open,
        }

    def summary(self) -> dict[str, object]:
        """What this tick did: the output of its trace (LLM-0009)."""

        return {
            "decisions": self.decisions,
            "event_count": len(self.events),
            "events": dict(sorted(Counter(self.events).items())),
            "in_episode": sorted(self.in_episode),
        }


class Engine:
    def __init__(
        self,
        conn: Connection[DictRow],
        policy: Policy,
        *,
        root_seed: int,
        debt_level: float | None = None,
        encounters: bool = True,
        spatial: bool = True,
        episodes: bool = True,
    ) -> None:
        self._conn = conn
        self._policy = policy
        self._root = root_seed
        self.pinned_debt = debt_level
        """None: the codebase's debt is what engineering makes of it
        (WORLD-0011). A number pins it, for an experiment about the hazard."""
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
        # A world seeded before WORLD-0010 gets its accounts, prices and
        # recurring jobs here, under the writer lock, once.
        economy.install(self._conn, root_seed=root_seed)
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
        # first-hand, as `_customers` writes it down.
        self._conn.execute(
            "INSERT INTO knowledge (person_id, fact_id, learned_sim, learned_seq) "
            "SELECT p.id, 'outage:' || i.id, i.started_sim, i.cause_event_seq "
            "FROM incidents i CROSS JOIN persons p "
            "WHERE i.id = ANY(%s) AND p.org_id = 'tallybird' AND p.kind = 'staff'",
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
            "chosen, facts) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING id",
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
                # WORLD-0013: what the decision was asked from, so the row is
                # evidence on its own. Typed facts, not the rendered words.
                json.dumps(ctx.facts, sort_keys=True, default=str),
            ),
        ).fetchone()
        assert row is not None
        if decision.escalation is not None:
            # DECIDE-0005: measurement beside the decision, read by nothing in
            # the world. In the tick's transaction, so it rolls back with it.
            second = decision.escalation
            self._conn.execute(
                "INSERT INTO escalations (decision_id, question_set, sim_time, "
                "mode, sampled, triggers, asks, jev, llm, model, call_hash, "
                "agrees, applied) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    ctx.kind,
                    ctx.sim_time,
                    second.mode,
                    second.sampled,
                    json.dumps(second.triggers),
                    second.asks,
                    json.dumps(second.jev),
                    json.dumps(second.llm),
                    second.model,
                    second.call_hash,
                    second.agrees,
                    second.mode == "live",
                ),
            )
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

    def weekly_wages(self, org_id: str) -> int:
        return flows.weekly_wages(self, org_id)

    def payroll_held(self, org_id: str) -> bool:
        return flows.payroll_held(self, org_id)

    def weekly_outgoings(self, org_id: str) -> int:
        """What a week costs this firm to keep open: its wage bill and its
        fixed costs. The denominator of every runway in the world."""

        return flows.weekly_outgoings(self, org_id)

    def runway_days(self, org_id: str, cash: int | None = None) -> float:
        """How many days the firm's cash lasts at its usual weekly outgoings.

        It was `cash / this bill * 7`, a multiple of whatever was being paid,
        so a firm with a month of payroll in the bank read as flush in front of
        a small bill and broke in front of a large one (field report).
        """

        cash = self.cash_of(f"{org_id}.cash") if cash is None else cash
        return cash / max(1, self.weekly_outgoings(org_id)) * 7

    def payer_of(self, org_id: str) -> DictRow | None:
        """Who pays this firm's bills and chases what it is owed."""

        roles = list(BY_ID[org_id].payer_roles)
        # Whoever is left, if the people whose job it is have gone: somebody
        # still has to open the post (WORLD-0010).
        return self._conn.execute(
            "SELECT id, org_id, role, traits FROM persons WHERE org_id = %s "
            f"AND kind = 'staff' AND status <> 'left' AND {economy.AT_WORK} "
            "ORDER BY COALESCE(array_position(%s::text[], role), 99), id LIMIT 1",
            (org_id, roles),
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
        # LLM-0009: the tick is the root of its trace. Every decision batch it
        # asks for nests under it, so one trace reads as fifteen minutes of the
        # town. A tick that raises carries the error on this span, and its
        # retry is a trace of its own.
        with tracing.span("sim.tick", type="task", metadata=self._run()) as span:
            try:
                with self._conn.transaction():
                    meta = self._meta()
                    report = TickReport(
                        tick_seq=int(meta["tick_seq"]) + 1,
                        sim_time=int(meta["sim_time"]),
                    )
                    # Logged once known: the clock is read inside the
                    # transaction, never before it.
                    span.log(input=report.clock())
                    self._policy.begin_tick(report.sim_time)
                    self._advance(report, SimTime(report.sim_time))
                    # Summarised inside the transaction, so nothing after the
                    # commit can fail and reach the daemon as a tick that had
                    # in fact advanced; logged after it, so a tick whose COMMIT
                    # fails does not claim work that was rolled back.
                    done = report.summary()
            except BaseException:
                # The rows are gone but the ids they drew are not. Put the
                # counters back before anything retries, or the retry numbers
                # its events differently from a run that never failed.
                if not self._conn.closed:
                    db.resync_sequences(self._conn)
                    self._conn.commit()
                raise
            span.log(output=done)
        return report

    def _run(self) -> dict[str, object]:
        """Which world a tick belongs to, for its trace (LLM-0009).

        A local key traces soak arms, episode studies and replays into the
        same project as the daemon; these are what tell them apart. The
        database is named, never located: no host, no credentials.
        """

        return {
            "policy": type(self._policy).__name__,
            "root_seed": self._root,
            "database": self._conn.info.dbname,
            "encounters": self.encounters,
            "spatial": self.spatial,
            "episodes": self.episodes,
        }

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
            customers.disputes(self, report, now)
            self._payments(report, now)
            self._client_payments(report, now)
            self._chase(report, now)
        if now.cafe_open and not economy.failed(self, "thirdrail"):
            self._cafe(report, now)

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
        if economy.failed(self, "tallybird"):
            return  # its customers have moved to another vendor (WORLD-0010)
        debt = engineering.debt(self)
        chance = per_tick(HAZARD_PER_HOUR * (1 + debt * (DEBT_MULTIPLIER - 1)))
        for module_id in ("timetrack", "invoicing", "pos"):
            if self._module_down(module_id):
                continue
            # CORE-0009: about this module at this moment of this day, not about
            # how many ticks the run has taken to get here.
            rng = derive_rng(
                self._root, "hazard", module_id, now.day, now.time_of_day // MINUTE
            )
            if rng.random() < chance:
                self._start_incident(
                    report,
                    module_id,
                    {
                        "severity": 1,
                        "expected_minutes": engineering.outage_minutes(
                            self, report.sim_time, 90
                        ),
                    },
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
            org_id="tallybird",
            # A deploy that broke something is the cause of what it broke.
            causes=[int(payload["cause"])] if payload.get("cause") else [],
            payload={
                "module_id": module_id,
                "severity": severity,
                "expected_minutes": minutes,
                "deploy": bool(payload.get("deploy")),
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
            "SELECT id FROM persons WHERE org_id = 'tallybird' AND kind = 'staff' "
            "ORDER BY id"
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
        rate = USES_PER_HOUR.get(module_id, 1.0)
        for user in users:
            person_id = str(user["id"])
            rng = derive_rng(self._root, "notice", person_id, incident_id)
            use = -math.log(1.0 - rng.random()) / rate * HOUR
            # People on a till keep the cafe's hours; everyone else an office's.
            noticed = after_working_time(started, use, till=module_id == "pos")
            rows.append((incident_id, person_id, noticed))
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
        # Whoever had not tried the feature by now never found it broken.
        self._conn.execute(
            "DELETE FROM outage_notices WHERE incident_id = %s AND notice_sim > %s "
            "AND ticket_id IS NULL",
            (incident_id, report.sim_time),
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
            org_id="tallybird",
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
        # A long outage leaves debt behind it (WORLD-0011)...
        level = engineering.postmortem(self, report, minutes=minutes)
        if level is not None:
            self._emit(
                report,
                "postmortem.debt",
                org_id="tallybird",
                causes=[ended_seq],
                payload={"incident_id": incident_id, "debt_level": level},
            )
        # ...and everyone who ran into it trusts the vendor a little differently.
        customers.after_outage(
            self,
            report,
            incident_id=incident_id,
            module_id=module_id,
            minutes=minutes,
            escalated=row["escalation_event_seq"] is not None,
            cause=ended_seq,
        )

    # -- flow 2: customers file tickets, support triages and answers -------

    def _customers(self, report: TickReport, now: SimTime) -> None:
        """People who have noticed an outage decide whether to report it.

        Asked when they notice, and again each day it goes on, at a time of
        their own. Not every tick: someone who shrugged at ten is not asked
        again at quarter past.
        """

        # `heard_hops` is read before this tick writes anyone's first-hand
        # knowledge below: somebody who was told before they noticed knows it
        # at second hand, and that is what their first decision should see.
        waiting = self._conn.execute(
            "SELECT n.incident_id, n.person_id, n.asked_day, i.module_id, "
            "  i.started_sim, i.cause_event_seq, p.traits, p.org_id, p.kind, "
            "  k.hops AS heard_hops "
            "FROM outage_notices n JOIN incidents i ON i.id = n.incident_id "
            "JOIN persons p ON p.id = n.person_id "
            "LEFT JOIN knowledge k ON k.person_id = n.person_id "
            "  AND k.fact_id = 'outage:' || n.incident_id "
            "WHERE i.ended_sim IS NULL AND n.ticket_id IS NULL "
            "  AND n.notice_sim <= %s ORDER BY n.incident_id, n.person_id",
            (report.sim_time,),
        ).fetchall()
        # Month-end is close, or a month-end run is already waiting on the
        # outage: what makes an invoicing outage matter this week (WORLD-0011).
        month_end = (
            self._conn.execute(
                "SELECT 1 FROM scheduled WHERE (kind = 'month.end' AND "
                "due_sim_time <= %s) OR kind = 'invoice.run' LIMIT 1",
                (report.sim_time + 2 * DAY,),
            ).fetchone()
            is not None
        )
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
                        "module": str(row["module_id"]),
                        "month_end": month_end,
                        # Only the first time they are asked. A day later they
                        # have had every chance to hit it themselves.
                        "heard_hops": int(row["heard_hops"] or 0)
                        if row["asked_day"] is None
                        else 0,
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
            if made.chosen.get("file"):
                self._file(report, row, made)
            if "workaround" in made.chosen:
                self._work_around(report, row, made)

    def _work_around(self, report: TickReport, row: DictRow, made: Made) -> None:
        """How somebody gets their work done while a feature is down
        (the scenario's behaviour #5). Recorded, and where it reaches the world
        it does so by rule: work done by hand goes out, and may not reconcile
        at the month's close; ringing the account manager is an escalation
        that has to be passed on to be worth anything (WORLD-0012)."""

        how = str(made.chosen["workaround"])
        person_id = str(row["person_id"])
        changed = self._conn.execute(
            "UPDATE outage_notices SET workaround = %s WHERE incident_id = %s "
            "AND person_id = %s AND workaround IS DISTINCT FROM %s RETURNING 1",
            (how, int(row["incident_id"]), person_id, how),
        ).fetchone()
        if changed is None:
            # The same answer as yesterday is not something that happened.
            return
        self._emit(
            report,
            "outage.workaround",
            actor_id=person_id,
            org_id=str(row["org_id"]) if row["kind"] == "staff" else None,
            causes=_seq_of(row["cause_event_seq"]),
            decision_id=made.id,
            payload={
                "incident_id": int(row["incident_id"]),
                "module_id": str(row["module_id"]),
                "workaround": how,
                "decided_by": made.source,
            },
        )
        if how == "by_hand" and self._runs_the_books(person_id, row):
            count = int(
                economy.policy(self, str(row["org_id"])).get("paper_records", 0)
            )
            economy.set_policy(self, str(row["org_id"]), paper_records=count + 1)
        if how == "call_account_manager":
            manager = self._conn.execute(
                "SELECT id FROM persons WHERE org_id = 'tallybird' AND kind = 'staff' "
                "AND status <> 'left' AND role = ANY(ARRAY['account_manager', "
                "'support_lead', 'founder']) ORDER BY array_position(ARRAY["
                "'account_manager', 'support_lead', 'founder'], role), id LIMIT 1"
            ).fetchone()
            if manager is not None:
                episodes.escalate(
                    self,
                    report,
                    raised_by=person_id,
                    org_id=str(row["org_id"]),
                    raised_with=str(manager["id"]),
                    zone="phone",
                    cause_seq=int(row["cause_event_seq"] or 0) or None,
                    decision_id=made.id,
                    decided_by=made.source,
                    module=str(row["module_id"]),
                )

    def _runs_the_books(self, person_id: str, row: DictRow) -> bool:
        if row["kind"] != "staff":
            return False
        payer = self.payer_of(str(row["org_id"]))
        return payer is not None and str(payer["id"]) == person_id

    def by_hand(self, org_id: str, module_id: str) -> bool:
        """Is this firm doing by hand what a feature that is down would do?

        The firm's decision, so the answer of whoever pays its bills: a junior
        associate who has heard the invoicing is down may do their own work by
        hand, but does not switch the firm's billing to paper.
        """

        payer = self.payer_of(org_id)
        if payer is None:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM outage_notices n JOIN incidents i ON i.id = n.incident_id "
            "WHERE i.ended_sim IS NULL AND i.module_id = %s AND n.person_id = %s "
            "AND n.workaround = 'by_hand' LIMIT 1",
            (module_id, str(payer["id"])),
        ).fetchone()
        return row is not None

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
            org_id="tallybird",
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
        staff = self._conn.execute(
            "SELECT id, traits FROM persons WHERE org_id = 'tallybird' "
            "AND role = ANY(%s) ORDER BY id",
            (list(SUPPORT_ROLES),),
        ).fetchall()
        if not staff:
            return
        # Work support can still do: an answered ticket is waiting on its
        # reporter, not on the desk, and counting it made the queue look
        # deepest just after support had cleared it.
        backlog_row = self._conn.execute(
            "SELECT count(*) AS n FROM tickets WHERE status IN ('open','triaged')"
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
                "FROM tickets t WHERE t.status = 'open' "
                "ORDER BY t.opened_sim, t.id LIMIT 1"
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
                triaged_seq = self._emit(
                    report,
                    "ticket.triaged",
                    actor_id=person_id,
                    org_id="tallybird",
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
                self._escalate_internally(report, person_id, module_id, triaged_seq)
                continue

            # Otherwise answer something already triaged.
            triaged = self._conn.execute(
                "SELECT id FROM tickets WHERE status = 'triaged' "
                "ORDER BY severity DESC, opened_sim, id LIMIT 1"
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
                org_id="tallybird",
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

    INTERNAL_ESCALATION_TICKETS = 3
    """Blocked customers on one outage before support takes it to engineering
    without anybody having to be cornered (WORLD-0012). Triage severity had no
    consequence; now enough of it is a priority."""

    def _escalate_internally(
        self, report: TickReport, person_id: str, module_id: object, cause: int
    ) -> None:
        if not module_id or not self._module_down(str(module_id)):
            return
        incident = episodes.open_incident(self, [str(module_id)])
        if incident is None:
            return
        blocked = self._conn.execute(
            "SELECT count(*) AS n FROM tickets WHERE incident_id = %s "
            "AND severity >= 2 AND status IN ('triaged', 'answered')",
            (incident["id"],),
        ).fetchone()
        if blocked is None or int(blocked["n"]) < self.INTERNAL_ESCALATION_TICKETS:
            return
        episodes.prioritise(
            self,
            report,
            module=str(module_id),
            actor_id=person_id,
            cause=cause,
            route="queue",
        )

    def _followups(self, report: TickReport, now: SimTime) -> None:
        """An answered ticket ends: confirmed by its reporter, or timed out.

        Without this an answered ticket stayed open for ever, its reporter
        counted as "already has one open" for ever, and support received three
        tickets in the last twenty-six days of a thirty-day run.
        """

        answered = self._conn.execute(
            "SELECT t.id, t.reporter_id, t.module_id, t.answered_sim, t.answered_seq, "
            "  t.asked_day, p.traits, m.status AS module_status "
            "FROM tickets t JOIN persons p ON p.id = t.reporter_id "
            "LEFT JOIN modules m ON m.id = t.module_id "
            "WHERE t.status = 'answered' ORDER BY t.id"
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
            org_id="tallybird",
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
            if org.bills_clients_monthly and not economy.failed(self, org.id):
                self._issue_invoices(report, org.id, cause=seq, month=month)
        # Everyone weighs whether to stay (WORLD-0014).
        economy.careers(self, report)
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
        """The cascade's first link: no Invoicing module, no invoices — unless
        the firm has chosen to do them by hand (WORLD-0011), in which case they
        go out, and have to be reconciled at the close."""

        manual = self._module_down("invoicing") and self.by_hand(org_id, "invoicing")
        if self._module_down("invoicing") and not manual:
            pending = len(self.engaged_clients(org_id, month))
            # Two causes, and both are true: month-end is why a run was
            # attempted, the outage is why it failed. Citing only the calendar
            # would leave the outage with no billing consequences downstream,
            # which is the whole claim the simulation exists to show.
            outage = self._conn.execute(
                "SELECT cause_event_seq FROM incidents "
                "WHERE module_id = 'invoicing' AND ended_sim IS NULL "
                "ORDER BY id DESC LIMIT 1"
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
                        "module_id": "invoicing",
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
                "AND payload->>'module_id' = 'invoicing' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            causes += _seq_of(ended["seq"]) if ended else []
        # The work is drawn about the client and the month (CORE-0009); what
        # the firm charges for it is its price list, which it may have raised.
        index = economy.price_index(self, org_id)
        for client_id, amount in self.billed_work(org_id, month):
            invoice = self.bill(
                report,
                from_org=org_id,
                to_person=client_id,
                amount=round(amount * index),
                terms_days=30,
                kind="services",
                causes=causes,
                work_cents=amount,
            )
            if manual:
                self._conn.execute(
                    "UPDATE invoices SET manual = true WHERE id = %s", (invoice,)
                )

    def billed_work(self, org_id: str, month: int) -> list[tuple[str, int]]:
        """What each engaged client is billed this month.

        The law firm bills the hours it logged (WORLD-0011), shared across the
        month's clients by the size of their matters; everyone else bills the
        work drawn for the month.
        """

        engaged = self.engaged_clients(org_id, month)
        if org_id != "halloran":
            return engaged
        return timesheets.bill_hours(self, org_id, month, engaged)

    def engaged_clients(self, org_id: str, month: int) -> list[tuple[str, int]]:
        """Who had work done this month, and what it came to.

        CORE-0009: keyed by (firm, client, month) and by nothing else, so the
        same invoice is for the same amount whether it goes out on the 3rd or,
        because of an outage, on the 4th. The amount used to come from the tick
        it was issued in; a counterfactual that delayed billing re-rolled every
        bill, and "the outage made the money late" could not be told apart from
        "the outage changed the money".
        """

        clients = self._conn.execute(
            "SELECT id FROM persons WHERE org_id = %s AND kind = 'counterparty' "
            "ORDER BY id",
            (org_id,),
        ).fetchall()
        billed: list[tuple[str, int]] = []
        for client in clients:
            client_id = str(client["id"])
            rng = derive_rng(self._root, "engagement", org_id, client_id, month)
            if rng.random() < CLIENT_ENGAGED_PER_MONTH:
                billed.append((client_id, 80_000 + int(rng.random() * 540_000)))
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
        work_cents: int | None = None,
    ) -> int:
        """Issue one invoice: the row, the event, the receivable. Returns its id.

        `work_cents` is what the work came to before the firm's price list,
        which it may have raised (WORLD-0010): the draw a counterfactual must
        find unchanged, whatever the firm decided about its prices.
        """

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
                **({"work_cents": work_cents} if work_cents is not None else {}),
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

    def _subscriptions(self, report: TickReport) -> None:
        # Monthly, so the next run is 28 days out.
        self._schedule(report.sim_time + 28 * DAY, "subscription.run", None, {})
        if economy.failed(self, "tallybird"):
            return
        # Before the month is billed, customers at risk decide whether to stay,
        # and some who left come back (WORLD-0011).
        month = report.sim_time // (28 * DAY)
        customers.win_back(self, report, month)
        discounts = customers.renewals(self, report)
        rows = self._conn.execute(
            "SELECT id, org_id, person_id, module_id, monthly_cents FROM subscriptions "
            "WHERE active ORDER BY id"
        ).fetchall()
        total = 0
        issued: list[int] = []
        for row in rows:
            amount = round(
                int(row["monthly_cents"]) * (1 - discounts.get(int(row["id"]), 0.0))
            )
            invoice = self._conn.execute(
                "INSERT INTO invoices (from_org_id, to_org_id, to_person_id, "
                "issued_sim, due_sim, amount_cents, kind) "
                "VALUES ('tallybird',%s,%s,%s,%s,%s,'subscription') RETURNING id",
                (
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
                org_id="tallybird",
                payload={
                    "invoice_id": 0,
                    "from_org_id": "tallybird",
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
                "tallybird monthly subscriptions",
                [("tallybird.receivable", total), ("tallybird.revenue", -total)],
                seq,
            )

    # -- flow 5: payments --------------------------------------------------

    def _open_bills(self, where: str, params: tuple[Any, ...]) -> list[DictRow]:
        """Unpaid bills whose payer has started thinking about them."""

        return self._conn.execute(
            "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, i.to_org_id, "
            "  i.to_person_id, i.issued_seq, i.asked_day, i.deferrals, i.chased_sim, "
            "  i.chases, i.reminded_sim, i.kind, i.late_reason, "
            "  (i.disputed_sim IS NOT NULL AND i.dispute_resolution IS NULL) "
            "    AS disputed "
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
            runway = self.runway_days(org.id, cash)
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
                        "runway_days": runway,
                        **self._pressure_on(bill, report.sim_time),
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
            buffer = self.client_buffer_days(person_id, now)
            bills.append(bill)
            contexts.append(
                DecisionContext(
                    person_id=person_id,
                    role="client",
                    sim_time=report.sim_time,
                    kind="payment.timing",
                    facts={
                        "days_until_due": days_until_due,
                        "can_afford": buffer >= CLIENT_CAN_PAY_DAYS,
                        "runway_days": round(buffer, 1),
                        "autopay": autopay,
                        **self._pressure_on(bill, report.sim_time),
                    },
                    traits=traits,
                )
            )
        if bills:
            self._settle(report, now, bills, contexts, payer_account=None)

    def client_buffer_days(self, person_id: str, now: SimTime) -> float:
        """How many days of outgoings this client could cover this month
        (WORLD-0014): keyed by the client and the month (CORE-0009), so a
        client's cash is tight for a month, not for a tick."""

        rng = derive_rng(
            self.root_seed, "client.cash", person_id, now.seconds // economy.MONTH
        )
        return math.exp(
            math.log(CLIENT_BUFFER_MEDIAN_DAYS)
            + CLIENT_BUFFER_SIGMA * rng.gauss(0.0, 1.0)
        )

    def _pressure_on(self, bill: DictRow, sim_time: int) -> dict[str, object]:
        """What has been done to get this bill paid, as the payer knows it."""

        reminded = bill["reminded_sim"]
        return {
            "chased": bill["chased_sim"] is not None,
            "times_chased": int(bill["chases"] or 0),
            "reminded_in_person": reminded is not None
            and sim_time - int(reminded) <= REMINDER_LASTS,
            "promised": memory.open_commitment(self._conn, int(bill["id"])) is not None,
            "disputed": bool(bill["disputed"]),
        }

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
            # What was known when it was decided, on the event (WORLD-0013):
            # a payment can be explained from its own row.
            context = {
                "to": payee,
                "invoice_kind": str(bill["kind"]),
                "amount_cents": amount,
                "days_late": days_late,
                "deferrals": int(bill["deferrals"]),
                "times_chased": ctx.facts.get("times_chased", 0),
                "reminded_in_person": ctx.facts.get("reminded_in_person", False),
                "promised": ctx.facts.get("promised", False),
                "runway_days": ctx.facts.get("runway_days"),
            }
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
                            **context,
                            "reason": reason,
                            "decided_by": made.source,
                        },
                    )
                if overdue:
                    self._conn.execute(
                        "UPDATE invoices SET deferrals = deferrals + 1, "
                        "late_reason = %s WHERE id = %s",
                        (reason, bill["id"]),
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
                    **context,
                    # Why it had been left, when it was: the last reason given.
                    "late_reason": bill["late_reason"] if days_late > 0 else None,
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
            # Who decided goes on the row as well as the event. It was left to
            # the column default, so every payment in production read "rules"
            # whatever had made it (field report, defect 2).
            self._conn.execute(
                "INSERT INTO payments (invoice_id, paid_sim, amount_cents, txn_id, "
                "days_late, decided_by) VALUES (%s,%s,%s,%s,%s,%s)",
                (bill["id"], report.sim_time, amount, txn, days_late, made.source),
            )
            # Anyone who gave their word about this bill has now kept it, and
            # the creditor thinks the better of them for it (MEM-0004).
            kept = memory.open_commitment(self._conn, int(bill["id"]))
            memory.close_commitments_for(
                self._conn, int(bill["id"]), sim_time=report.sim_time, kept=True
            )
            if kept is not None:
                memory.warm(
                    self._conn,
                    kept.from_person_id,
                    kept.to_person_id,
                    1,
                    sim_time=report.sim_time,
                )

    def _chase(self, report: TickReport, now: SimTime) -> None:
        """A bill a week late gets chased — if whoever is owed is the type.

        And one sixty days late is written off, by rule: a receivable nobody
        will ever collect is not an asset, and a soak should not end with a
        balance sheet full of them.
        """

        late = self._conn.execute(
            "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, i.to_org_id, "
            "  i.to_person_id, i.issued_seq, i.chase_asked_day, i.chases "
            "FROM invoices i WHERE i.paid_sim IS NULL AND i.written_off_sim IS NULL "
            # A bill under dispute is argued over, not chased.
            "  AND (i.disputed_sim IS NULL OR i.dispute_resolution IS NOT NULL) "
            "  AND i.due_sim <= %s AND (i.chased_sim IS NULL OR i.chased_sim <= %s "
            "    OR i.due_sim <= %s) "
            "ORDER BY i.from_org_id, i.due_sim, i.id",
            (
                report.sim_time - CHASE_HARDER_AFTER,
                report.sim_time - CHASE_AGAIN_AFTER,
                report.sim_time - WRITE_OFF_AFTER,
            ),
        ).fetchall()
        # A week late, or three days while the firm has decided to chase
        # harder (WORLD-0010).
        after = {
            org.id: economy.chase_after_days(self, org.id, report.sim_time) * DAY
            for org in ORGS
        }
        late = [
            bill
            for bill in late
            if int(bill["due_sim"]) <= report.sim_time - after[str(bill["from_org_id"])]
            or int(bill["due_sim"]) <= report.sim_time - WRITE_OFF_AFTER
        ]
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
            if (
                chaser is None
                or str(chaser["id"]) in report.in_episode
                or economy.failed(self, issuer)
            ):
                continue
            if not self.gets_to_it(
                str(chaser["id"]), now, "chasing", bill["chase_asked_day"]
            ):
                continue
            cash = self.cash_of(f"{issuer}.cash")
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
                        "runway_days": self.runway_days(issuer, cash),
                        "times_chased": int(bill["chases"] or 0),
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
                    "amount_cents": int(bill["amount_cents"]),
                    "attempt": int(bill["chases"] or 0) + 1,
                    "decided_by": made.source,
                },
            )
            self._conn.execute(
                "UPDATE invoices SET chased_sim = %s, chases = chases + 1 "
                "WHERE id = %s",
                (report.sim_time, bill["id"]),
            )

    def write_off(self, report: TickReport, bill: DictRow) -> None:
        self._write_off(report, bill)

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

    # -- flow 6: the cafe --------------------------------------------------

    def _cafe(self, report: TickReport, now: SimTime) -> None:
        pos_down = self._module_down("pos")
        minute = now.time_of_day // MINUTE
        rng = derive_rng(self._root, "cafe", now.day, minute)
        hourly = CAFE_ARRIVALS_PER_HOUR.get(now.time_of_day // HOUR, 0)
        if now.weekday == 5:
            hourly = hourly // 2  # Saturdays are quiet: the offices are shut
        expected = hourly * TICK / HOUR
        arrivals = int(expected) + (1 if rng.random() < expected % 1 else 0)

        customers = self._conn.execute(
            "SELECT id, traits FROM persons WHERE org_id = 'thirdrail' "
            "AND kind = 'counterparty' ORDER BY id"
        ).fetchall()
        walk_ins = (
            [customers[int(rng.random() * len(customers))] for _ in range(arrivals)]
            if customers
            else []
        )
        # People from the offices who walked in this tick queue with everyone
        # else. Their coffee is paid for out of their wages (households), which
        # is how a payroll held by an outage reaches the cafe's till.
        staff = self._conn.execute(
            "SELECT p.id, p.org_id, p.traits FROM positions pos JOIN persons p "
            "ON p.id = pos.person_id WHERE pos.zone = 'cafe' AND pos.moved_tick = %s "
            "AND p.org_id <> 'thirdrail' ORDER BY p.id",
            (report.tick_seq,),
        ).fetchall()
        # Each from their own employer's households (WORLD-0010): an unpaid
        # engineer's coffee used to come out of the lawyers' wages.
        purse = {
            org: self.cash_of(economy.household(org))
            for org in sorted({str(row["org_id"]) for row in staff})
        }
        index = economy.price_index(self, "thirdrail")
        cafe = economy.policy(self, "thirdrail")
        short = report.sim_time < int(cafe.get("stock_short_until") or 0)
        sold_out_share = float(cafe.get("stock_short_share", 0.0)) if short else 0.0

        # Service is a queue whose rate depends on who is behind the counter
        # (the scenario's Third Rail row, WORLD-0011): somebody off sick and not
        # covered is a slower line. A card reader that is down halves it,
        # unless the cafe has chosen to write sales down by hand.
        behind = self._conn.execute(
            "SELECT count(*) AS n FROM positions s JOIN persons p "
            "ON p.id = s.person_id WHERE s.zone = 'cafe' AND p.org_id = 'thirdrail' "
            "AND p.role = ANY(%s)",
            (list(shocks.COUNTER_ROLES),),
        ).fetchone()
        servers = float(max(1, min(3, int(behind["n"]) if behind else 0)))
        if pos_down and not self.by_hand("thirdrail", "pos"):
            servers = max(1.0, servers / 2)
        # Who walks in, and what they find, is settled before anyone decides:
        # an arrival waits behind the arrivals ahead of it, not behind what
        # those people went on to choose. That independence is what lets the
        # whole tick's customers be asked at once.
        contexts: list[DecisionContext] = []
        baskets: list[int] = []
        employers: list[str | None] = []
        for arrival, row in enumerate([*walk_ins, *staff]):
            person_id = str(row["id"])
            employer = str(row["org_id"]) if arrival >= len(walk_ins) else None
            basket_rng = derive_rng(
                self._root, "basket", person_id, now.day, minute, arrival
            )
            basket = round((350 + int(basket_rng.random() * 600)) * index)
            # Short of stock, some find nothing they want. A rule, drawn about
            # the visit, as the basket is.
            sold_out = basket_rng.random() < sold_out_share
            baskets.append(basket)
            employers.append(employer)
            contexts.append(
                DecisionContext(
                    person_id=person_id,
                    role="customer",
                    sim_time=report.sim_time,
                    kind="cafe.purchase",
                    facts={
                        "pos_down": pos_down,
                        "queue_length": max(0, int(arrival - servers)),
                        "can_afford": employer is None or purse[employer] >= basket,
                        "sold_out": sold_out,
                        "prices_up": index > 1.0,
                    },
                    traits=dict(row["traits"] or {}),
                )
            )
        if not contexts:
            return

        for ctx, amount, employer, made in zip(
            contexts,
            baskets,
            employers,
            self._decide_many(report, contexts),
            strict=True,
        ):
            person_id = ctx.person_id
            if not made.chosen.get("buy"):
                self._emit(
                    report,
                    "cafe.walkout",
                    actor_id=person_id,
                    org_id="thirdrail",
                    decision_id=made.id,
                    payload={
                        "person_id": person_id,
                        "reason": str(made.chosen.get("reason", "queue")),
                        "decided_by": made.source,
                    },
                )
                continue
            if employer is not None and purse[employer] < amount:
                continue  # the referee: someone ahead of them spent the last of it
            seq = self._emit(
                report,
                "cafe.sale",
                actor_id=person_id,
                org_id="thirdrail",
                decision_id=made.id,
                payload={
                    "person_id": person_id,
                    "amount_cents": amount,
                    "pos_down": pos_down,
                    "decided_by": made.source,
                },
            )
            legs = [("thirdrail.cash", amount), ("thirdrail.revenue", -amount)]
            if employer is not None:
                legs += [
                    (economy.household(employer), -amount),
                    (economy.household(employer, "spending"), amount),
                ]
                purse[employer] -= amount
            txn = self._post(report.sim_time, "cafe sale", legs, seq)
            self._conn.execute(
                "INSERT INTO cafe_sales (sim_time, person_id, amount_cents, txn_id, "
                "pos_down) VALUES (%s,%s,%s,%s,%s)",
                (report.sim_time, person_id, amount, txn, pos_down),
            )


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
    engine._subscriptions(report)


def skip_to_next_open(conn: Connection[DictRow]) -> int:
    """Jump dead time (CORE-0003). Nothing calls a model while all is shut."""

    row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    assert row is not None
    target = next_open(int(row["sim_time"]))
    conn.execute("UPDATE sim_meta SET sim_time = %s", (target,))
    conn.commit()
    return target
