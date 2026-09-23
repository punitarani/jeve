"""Typed events: the closed vocabulary of things that can happen.

A discriminated union, validated at the boundary. Every event carries the seqs
of the events that caused it, which is what makes a cascade a query rather
than an inference (CORE-0007).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IncidentStarted(_Event):
    kind: Literal["incident.started"] = "incident.started"
    module_id: str
    severity: int
    expected_minutes: int


class IncidentEnded(_Event):
    kind: Literal["incident.ended"] = "incident.ended"
    module_id: str
    incident_id: int
    minutes: int


class TicketOpened(_Event):
    kind: Literal["ticket.opened"] = "ticket.opened"
    ticket_id: int
    reporter_id: str
    module_id: str | None = None
    subject: str


class TicketTriaged(_Event):
    kind: Literal["ticket.triaged"] = "ticket.triaged"
    ticket_id: int
    assignee_id: str
    queue: str
    severity: float
    decided_by: str


class TicketAnswered(_Event):
    kind: Literal["ticket.answered"] = "ticket.answered"
    ticket_id: int
    assignee_id: str


class InvoiceIssued(_Event):
    kind: Literal["invoice.issued"] = "invoice.issued"
    invoice_id: int
    from_org_id: str
    to: str
    amount_cents: int
    invoice_kind: str
    blocked_ticks: int = 0


class InvoiceBlocked(_Event):
    kind: Literal["invoice.blocked"] = "invoice.blocked"
    from_org_id: str
    module_id: str
    pending: int
    reason: str


class PaymentMade(_Event):
    kind: Literal["payment.made"] = "payment.made"
    invoice_id: int
    amount_cents: int
    days_late: int
    decided_by: str


class PaymentDeferred(_Event):
    kind: Literal["payment.deferred"] = "payment.deferred"
    invoice_id: int
    days_late: int
    reason: str
    decided_by: str


class RetailSale(_Event):
    """At any firm with a till; the retailer is the event's `org_id`."""

    kind: Literal["retail.sale"] = "retail.sale"
    person_id: str | None
    amount_cents: int
    till_down: bool


class RetailWalkout(_Event):
    kind: Literal["retail.walkout"] = "retail.walkout"
    person_id: str | None
    reason: str


class MonthEnd(_Event):
    kind: Literal["month.end"] = "month.end"
    label: str


class EngineChanged(_Event):
    """A code-version seam, recorded rather than refused (CORE-0005)."""

    kind: Literal["sim.engine.changed"] = "sim.engine.changed"
    from_sha: str
    to_sha: str


type EventPayload = Annotated[
    IncidentStarted
    | IncidentEnded
    | TicketOpened
    | TicketTriaged
    | TicketAnswered
    | InvoiceIssued
    | InvoiceBlocked
    | PaymentMade
    | PaymentDeferred
    | RetailSale
    | RetailWalkout
    | MonthEnd
    | EngineChanged,
    Field(discriminator="kind"),
]


class EventEnvelope(BaseModel):
    """An event as stored. `seq` is assigned by the database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    sim_time: int
    tick_seq: int
    kind: str
    actor_id: str | None
    org_id: str | None
    payload: dict[str, object]
    causes: list[int]
    decision_id: int | None = None
