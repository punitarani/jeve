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
from dataclasses import dataclass, field
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, TICK, SimTime, next_office_open
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext, Policy

# Tallybird's hazard: chance per business-hours tick that a module falls over.
# Elevated because the fixture starts with debt high and a risky deploy queued.
BASE_HAZARD = 0.004
DEBT_MULTIPLIER = 2.5

CAFE_ARRIVALS_PER_TICK = 6


def _seq_of(value: object) -> list[int]:
    """A cause list from a nullable subquery result."""

    return [int(value)] if isinstance(value, int) else []


SUPPORT_ROLES = ("support", "support_lead")


@dataclass(slots=True)
class TickReport:
    """What one tick did. Aggregated into the run report."""

    tick_seq: int
    sim_time: int
    events: list[str] = field(default_factory=list)
    decisions: int = 0

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
    ) -> None:
        self._conn = conn
        self._policy = policy
        self._root = root_seed
        self._debt = debt_level

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
        return int(row["seq"])

    def _decide(self, report: TickReport, ctx: DecisionContext) -> dict[str, Any]:
        """Run a policy and record the decision. Returns what was chosen."""

        decision = self._policy.decide(ctx)
        self._conn.execute(
            "INSERT INTO decisions (person_id, decision_seq, sim_time, tick_seq, "
            "question_set, model_call, source, distributions, prng_path, draws, "
            "chosen) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        )
        self._conn.execute(
            "UPDATE persons SET decision_seq = decision_seq + 1 WHERE id = %s",
            (ctx.person_id,),
        )
        report.decisions += 1
        return decision.chosen

    def _next_seq(self, person_id: str) -> int:
        row = self._conn.execute(
            "SELECT decision_seq FROM persons WHERE id = %s", (person_id,)
        ).fetchone()
        assert row is not None
        return int(row["decision_seq"])

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

    def _module_down(self, module_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM modules WHERE id = %s", (module_id,)
        ).fetchone()
        return row is not None and row["status"] == "down"

    # -- the tick ----------------------------------------------------------

    def tick(self) -> TickReport:
        """Advance the world by one quantum, atomically."""

        meta = self._meta()
        report = TickReport(
            tick_seq=int(meta["tick_seq"]) + 1, sim_time=int(meta["sim_time"])
        )
        now = SimTime(report.sim_time)

        with self._conn.transaction():
            self._run_due(report)
            if now.in_office_hours:
                self._maybe_incident(report, now)
                self._support(report, now)
                self._customers(report, now)
                self._payments(report, now)
                self._client_payments(report, now)
            if now.cafe_open:
                self._cafe(report, now)

            self._conn.execute(
                "UPDATE sim_meta SET sim_time = %s, tick_seq = %s, updated_at = now()",
                (report.sim_time + TICK, report.tick_seq),
            )
        return report

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
        rows = self._conn.execute(
            "DELETE FROM scheduled WHERE due_sim_time <= %s "
            "RETURNING kind, subject_id, payload",
            (report.sim_time,),
        ).fetchall()
        # Deterministic order regardless of how the database returned them.
        for row in sorted(rows, key=lambda r: (str(r["kind"]), str(r["subject_id"]))):
            kind = str(row["kind"])
            payload = row["payload"] or {}
            if kind == "incident.start":
                self._start_incident(report, str(row["subject_id"]), payload)
            elif kind == "incident.end":
                self._end_incident(report, str(row["subject_id"]), payload)
            elif kind == "month.end":
                self._month_end(report, payload)
            elif kind == "invoice.run":
                self._issue_invoices(
                    report, str(row["subject_id"]), cause=int(payload.get("cause", 0))
                )
            elif kind == "subscription.run":
                self._subscriptions(report)

    def _schedule(
        self, due: int, kind: str, subject: str | None, payload: dict[str, Any]
    ) -> None:
        self._conn.execute(
            "INSERT INTO scheduled (due_sim_time, kind, subject_id, payload) "
            "VALUES (%s,%s,%s,%s)",
            (due, kind, subject, json.dumps(payload)),
        )

    # -- flow 1: incidents -------------------------------------------------

    def _maybe_incident(self, report: TickReport, now: SimTime) -> None:
        rng = derive_rng(self._root, "hazard", report.tick_seq)
        for module_id, _ in (("timetrack", 0), ("invoicing", 0), ("pos", 0)):
            if self._module_down(module_id):
                continue
            if rng.random() < BASE_HAZARD * (1 + self._debt * (DEBT_MULTIPLIER - 1)):
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
            org_id="tallybird",
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

    def _end_incident(
        self, report: TickReport, module_id: str, payload: dict[str, Any]
    ) -> None:
        incident_id = int(payload.get("incident_id", 0))
        row = self._conn.execute(
            "UPDATE incidents SET ended_sim = %s WHERE id = %s AND ended_sim IS NULL "
            "RETURNING started_sim",
            (report.sim_time, incident_id),
        ).fetchone()
        if row is None:
            return
        self._conn.execute(
            "UPDATE modules SET status = 'up' WHERE id = %s", (module_id,)
        )
        self._emit(
            report,
            "incident.ended",
            org_id="tallybird",
            causes=[int(payload["cause"])] if payload.get("cause") else [],
            payload={
                "module_id": module_id,
                "incident_id": incident_id,
                "minutes": (report.sim_time - int(row["started_sim"])) // 60,
            },
        )

    # -- flow 2: customers file tickets, support triages and answers -------

    def _customers(self, report: TickReport, now: SimTime) -> None:
        """Counterparties who depend on a downed module may file a ticket."""

        down = [
            str(row["id"])
            for row in self._conn.execute(
                "SELECT id FROM modules WHERE status = 'down'"
            ).fetchall()
        ]
        if not down:
            return
        cause = self._conn.execute(
            "SELECT seq FROM events WHERE kind = 'incident.started' "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        causes = [int(cause["seq"])] if cause else []

        rng = derive_rng(self._root, "customers", report.tick_seq)
        candidates = self._conn.execute(
            "SELECT p.id, p.traits FROM persons p "
            "WHERE p.kind = 'counterparty' AND p.org_id = 'tallybird' "
            "ORDER BY p.id LIMIT 40"
        ).fetchall()
        # A slice of the subscriber base notices per tick, not all of them.
        for row in candidates:
            if rng.random() > 0.12:
                continue
            person_id = str(row["id"])
            open_already = self._conn.execute(
                "SELECT 1 FROM tickets WHERE reporter_id = %s AND status <> 'closed' "
                "LIMIT 1",
                (person_id,),
            ).fetchone()
            chosen = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role="subscriber",
                    decision_seq=self._next_seq(person_id),
                    sim_time=report.sim_time,
                    kind="file.ticket",
                    facts={
                        "module_down": True,
                        "already_open": open_already is not None,
                    },
                    traits=dict(row["traits"] or {}),
                ),
            )
            if not chosen.get("file"):
                continue
            module_id = down[0]
            ticket = self._conn.execute(
                "INSERT INTO tickets (opened_sim, reporter_id, module_id, subject) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (
                    report.sim_time,
                    person_id,
                    module_id,
                    f"{module_id} is not responding",
                ),
            ).fetchone()
            assert ticket is not None
            self._emit(
                report,
                "ticket.opened",
                actor_id=person_id,
                org_id="tallybird",
                causes=causes,
                payload={
                    "ticket_id": int(ticket["id"]),
                    "reporter_id": person_id,
                    "module_id": module_id,
                    "subject": f"{module_id} is not responding",
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
        backlog_row = self._conn.execute(
            "SELECT count(*) AS n FROM tickets WHERE status <> 'closed'"
        ).fetchone()
        backlog = int(backlog_row["n"]) if backlog_row else 0

        for agent in staff:
            person_id = str(agent["id"])
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
                chosen = self._decide(
                    report,
                    DecisionContext(
                        person_id=person_id,
                        role="support",
                        decision_seq=self._next_seq(person_id),
                        sim_time=report.sim_time,
                        kind="ticket.triage",
                        facts={
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
                        chosen["queue"],
                        chosen["severity"],
                        "rules",
                        untriaged["id"],
                    ),
                )
                self._emit(
                    report,
                    "ticket.triaged",
                    actor_id=person_id,
                    org_id="tallybird",
                    causes=(
                        [int(untriaged["opened_seq"])]
                        if untriaged["opened_seq"]
                        else []
                    ),
                    payload={
                        "ticket_id": int(untriaged["id"]),
                        "assignee_id": person_id,
                        "queue": chosen["queue"],
                        "severity": chosen["severity"],
                        "decided_by": "rules",
                    },
                )
                continue

            # Otherwise answer something already triaged.
            triaged = self._conn.execute(
                "SELECT id FROM tickets WHERE status = 'triaged' "
                "ORDER BY severity DESC, opened_sim LIMIT 1"
            ).fetchone()
            if triaged is None:
                continue
            chosen = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role="support",
                    decision_seq=self._next_seq(person_id),
                    sim_time=report.sim_time,
                    kind="ticket.answer",
                    facts={"backlog": backlog},
                    traits=traits,
                ),
            )
            if not chosen.get("answer_now"):
                continue
            self._conn.execute(
                "UPDATE tickets SET status = 'answered' WHERE id = %s", (triaged["id"],)
            )
            self._emit(
                report,
                "ticket.answered",
                actor_id=person_id,
                org_id="tallybird",
                payload={"ticket_id": int(triaged["id"]), "assignee_id": person_id},
            )

    # -- flow 3: month-end invoicing, blocked while Invoicing is down ------

    def _month_end(self, report: TickReport, payload: dict[str, Any]) -> None:
        seq = self._emit(
            report, "month.end", payload={"label": str(payload.get("label", ""))}
        )
        # Run in this same tick; a blocked run reschedules itself.
        for org_id in ("halloran", "ledgerline"):
            self._issue_invoices(report, org_id, cause=seq)

    def _issue_invoices(self, report: TickReport, org_id: str, *, cause: int) -> None:
        """The cascade's first link: no Invoicing module, no invoices."""

        if self._module_down("invoicing"):
            pending = self._conn.execute(
                "SELECT count(*) AS n FROM persons WHERE org_id = %s "
                "AND kind = 'counterparty'",
                (org_id,),
            ).fetchone()
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
            self._emit(
                report,
                "invoice.blocked",
                org_id=org_id,
                causes=causes,
                payload={
                    "from_org_id": org_id,
                    "module_id": "invoicing",
                    "pending": int(pending["n"]) if pending else 0,
                    "reason": "invoicing module is down",
                },
            )
            # Try again next tick; the block is recorded each time it bites.
            self._schedule(
                report.sim_time + TICK, "invoice.run", org_id, {"cause": cause}
            )
            self._conn.execute(
                "UPDATE invoices SET blocked_ticks = blocked_ticks + 1 "
                "WHERE from_org_id = %s AND paid_sim IS NULL",
                (org_id,),
            )
            return

        clients = self._conn.execute(
            "SELECT id, traits FROM persons "
            "WHERE org_id = %s AND kind = 'counterparty' "
            "ORDER BY id LIMIT 12",
            (org_id,),
        ).fetchall()
        rng = derive_rng(self._root, "invoice", org_id, report.tick_seq)
        for client in clients:
            amount = 80_000 + int(rng.random() * 540_000)
            invoice = self._conn.execute(
                "INSERT INTO invoices (from_org_id, to_person_id, issued_sim, "
                "due_sim, amount_cents, kind) VALUES (%s,%s,%s,%s,%s,'services') "
                "RETURNING id",
                (
                    org_id,
                    client["id"],
                    report.sim_time,
                    report.sim_time + 30 * DAY,
                    amount,
                ),
            ).fetchone()
            assert invoice is not None
            seq = self._emit(
                report,
                "invoice.issued",
                org_id=org_id,
                causes=[cause],
                payload={
                    "invoice_id": int(invoice["id"]),
                    "from_org_id": org_id,
                    "to": str(client["id"]),
                    "amount_cents": amount,
                    "invoice_kind": "services",
                },
            )
            self._post(
                report.sim_time,
                f"{org_id} invoices {client['id']}",
                [(f"{org_id}.receivable", amount), (f"{org_id}.revenue", -amount)],
                seq,
            )

    # -- flow 4: subscription invoices (automatic) -------------------------

    def _subscriptions(self, report: TickReport) -> None:
        rows = self._conn.execute(
            "SELECT org_id, person_id, module_id, monthly_cents FROM subscriptions "
            "WHERE active ORDER BY id"
        ).fetchall()
        total = 0
        for row in rows:
            amount = int(row["monthly_cents"])
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
            self._post(
                report.sim_time,
                "tallybird monthly subscriptions",
                [("tallybird.receivable", total), ("tallybird.revenue", -total)],
                seq,
            )
        # Monthly, so the next run is 28 days out.
        self._schedule(report.sim_time + 28 * DAY, "subscription.run", None, {})

    # -- flow 5: payments --------------------------------------------------

    def _payments(self, report: TickReport, now: SimTime) -> None:
        """Each org's bill-payer decides whether to settle what is due."""

        payers = self._conn.execute(
            "SELECT id, org_id, traits FROM persons "
            "WHERE role IN ('office_manager','client_admin','owner','founder') "
            "ORDER BY id"
        ).fetchall()
        for payer in payers:
            org_id = str(payer["org_id"])
            due = self._conn.execute(
                "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, "
                "  (SELECT seq FROM events e WHERE e.kind = 'invoice.issued' "
                "     AND (e.payload->>'invoice_id')::bigint = i.id "
                "   ORDER BY e.seq LIMIT 1) AS issued_seq "
                "FROM invoices i WHERE i.to_org_id = %s AND i.paid_sim IS NULL "
                "  AND i.due_sim <= %s ORDER BY i.due_sim, i.id LIMIT 1",
                (org_id, report.sim_time + DAY),
            ).fetchone()
            if due is None:
                continue

            cash_row = self._conn.execute(
                "SELECT COALESCE(sum(amount_cents),0) AS cents FROM ledger_entries "
                "WHERE account_id = %s",
                (f"{org_id}.cash",),
            ).fetchone()
            cash = int(cash_row["cents"]) if cash_row else 0
            amount = int(due["amount_cents"])
            days_until_due = (int(due["due_sim"]) - report.sim_time) // DAY
            person_id = str(payer["id"])

            chosen = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role=str(payer["id"]).split(".")[1],
                    decision_seq=self._next_seq(person_id),
                    sim_time=report.sim_time,
                    kind="payment.timing",
                    facts={
                        "days_until_due": days_until_due,
                        "can_afford": cash >= amount,
                        "runway_days": cash / max(1, amount) * 7,
                    },
                    traits=dict(payer["traits"] or {}),
                ),
            )
            causes = [int(due["issued_seq"])] if due["issued_seq"] else []
            days_late = max(0, -days_until_due)
            if not chosen.get("pay"):
                self._emit(
                    report,
                    "payment.deferred",
                    actor_id=person_id,
                    org_id=org_id,
                    causes=causes,
                    payload={
                        "invoice_id": int(due["id"]),
                        "days_late": days_late,
                        "reason": str(chosen.get("reason", "")),
                        "decided_by": "rules",
                    },
                )
                continue

            payee = str(due["from_org_id"])
            seq = self._emit(
                report,
                "payment.made",
                actor_id=person_id,
                org_id=org_id,
                causes=causes,
                payload={
                    "invoice_id": int(due["id"]),
                    "amount_cents": amount,
                    "days_late": days_late,
                    "decided_by": "rules",
                },
            )
            txn = self._post(
                report.sim_time,
                f"{org_id} pays {payee} invoice {due['id']}",
                [
                    (f"{org_id}.cash", -amount),
                    (f"{payee}.cash", amount),
                    (f"{payee}.receivable", -amount),
                    (f"{org_id}.expense", amount),
                ],
                seq,
            )
            self._conn.execute(
                "UPDATE invoices SET paid_sim = %s WHERE id = %s",
                (report.sim_time, due["id"]),
            )
            self._conn.execute(
                "INSERT INTO payments (invoice_id, paid_sim, amount_cents, txn_id, "
                "days_late) VALUES (%s,%s,%s,%s,%s)",
                (due["id"], report.sim_time, amount, txn, days_late),
            )

    def _client_payments(self, report: TickReport, now: SimTime) -> None:
        """Outside clients settling what the firms invoiced them.

        Without this the receivable side only ever grows: the firms issue at
        month-end and nothing comes back, so the credit chain in the scenario
        has no first link.
        """

        rng = derive_rng(self._root, "clientpay", report.tick_seq)
        due = self._conn.execute(
            "SELECT i.id, i.amount_cents, i.due_sim, i.from_org_id, i.to_person_id, "
            "  (SELECT seq FROM events e WHERE e.kind = 'invoice.issued' "
            "     AND (e.payload->>'invoice_id')::bigint = i.id "
            "   ORDER BY e.seq LIMIT 1) AS issued_seq "
            "FROM invoices i WHERE i.to_person_id IS NOT NULL "
            "  AND i.paid_sim IS NULL AND i.due_sim <= %s "
            "ORDER BY i.due_sim, i.id LIMIT 8",
            (report.sim_time,),
        ).fetchall()

        for invoice in due:
            person_id = str(invoice["to_person_id"])
            # A slice acts per tick; the rest are still thinking about it.
            if rng.random() > 0.25:
                continue
            traits = self._conn.execute(
                "SELECT traits FROM persons WHERE id = %s", (person_id,)
            ).fetchone()
            days_until_due = (int(invoice["due_sim"]) - report.sim_time) // DAY
            chosen = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role="client",
                    decision_seq=self._next_seq(person_id),
                    sim_time=report.sim_time,
                    kind="payment.timing",
                    facts={
                        "days_until_due": days_until_due,
                        "can_afford": True,
                        "runway_days": 60,
                    },
                    traits=dict((traits or {}).get("traits") or {}),
                ),
            )
            causes = _seq_of(invoice["issued_seq"])
            days_late = max(0, -days_until_due)
            payee = str(invoice["from_org_id"])
            amount = int(invoice["amount_cents"])
            if not chosen.get("pay"):
                self._emit(
                    report,
                    "payment.deferred",
                    actor_id=person_id,
                    org_id=payee,
                    causes=causes,
                    payload={
                        "invoice_id": int(invoice["id"]),
                        "days_late": days_late,
                        "reason": str(chosen.get("reason", "")),
                        "decided_by": "rules",
                    },
                )
                continue
            seq = self._emit(
                report,
                "payment.made",
                actor_id=person_id,
                org_id=payee,
                causes=causes,
                payload={
                    "invoice_id": int(invoice["id"]),
                    "amount_cents": amount,
                    "days_late": days_late,
                    "decided_by": "rules",
                },
            )
            txn = self._post(
                report.sim_time,
                f"{person_id} pays {payee} invoice {invoice['id']}",
                [
                    (f"{payee}.cash", amount),
                    (f"{payee}.receivable", -amount),
                ],
                seq,
            )
            self._conn.execute(
                "UPDATE invoices SET paid_sim = %s WHERE id = %s",
                (report.sim_time, invoice["id"]),
            )
            self._conn.execute(
                "INSERT INTO payments (invoice_id, paid_sim, amount_cents, txn_id, "
                "days_late) VALUES (%s,%s,%s,%s,%s)",
                (invoice["id"], report.sim_time, amount, txn, days_late),
            )

    # -- flow 6: the cafe --------------------------------------------------

    def _cafe(self, report: TickReport, now: SimTime) -> None:
        pos_down = self._module_down("pos")
        rng = derive_rng(self._root, "cafe", report.tick_seq)
        arrivals = CAFE_ARRIVALS_PER_TICK if now.in_office_hours else 2

        customers = self._conn.execute(
            "SELECT id, traits FROM persons WHERE org_id = 'thirdrail' "
            "AND kind = 'counterparty' ORDER BY id"
        ).fetchall()
        if not customers:
            return

        servers = 1.0 if pos_down else 2.0
        for arrival in range(arrivals):
            # What a customer actually waits behind: arrivals ahead of them,
            # less what the counter has served.
            queue_length = max(0, int(arrival - servers))
            row = customers[int(rng.random() * len(customers))]
            person_id = str(row["id"])
            chosen = self._decide(
                report,
                DecisionContext(
                    person_id=person_id,
                    role="customer",
                    decision_seq=self._next_seq(person_id),
                    sim_time=report.sim_time,
                    kind="cafe.purchase",
                    facts={"pos_down": pos_down, "queue_length": queue_length},
                    traits=dict(row["traits"] or {}),
                ),
            )
            if not chosen.get("buy"):
                self._emit(
                    report,
                    "cafe.walkout",
                    actor_id=person_id,
                    org_id="thirdrail",
                    payload={
                        "person_id": person_id,
                        "reason": str(chosen.get("reason", "queue")),
                    },
                )
                continue
            amount = int(chosen["amount_cents"])
            seq = self._emit(
                report,
                "cafe.sale",
                actor_id=person_id,
                org_id="thirdrail",
                payload={
                    "person_id": person_id,
                    "amount_cents": amount,
                    "pos_down": pos_down,
                },
            )
            txn = self._post(
                report.sim_time,
                "cafe sale",
                [("thirdrail.cash", amount), ("thirdrail.revenue", -amount)],
                seq,
            )
            self._conn.execute(
                "INSERT INTO cafe_sales (sim_time, person_id, amount_cents, txn_id, "
                "pos_down) VALUES (%s,%s,%s,%s,%s)",
                (report.sim_time, person_id, amount, txn, pos_down),
            )


def skip_to_next_open(conn: Connection[DictRow]) -> int:
    """Jump dead time (CORE-0003). Nothing calls a model overnight."""

    row = conn.execute("SELECT sim_time FROM sim_meta").fetchone()
    assert row is not None
    target = next_office_open(int(row["sim_time"]))
    conn.execute("UPDATE sim_meta SET sim_time = %s", (target,))
    conn.commit()
    return target
