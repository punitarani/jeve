"""Pydantic models for contract generation.

These models correspond to the zod schemas in packages/contracts/src/index.ts.
They serve as the single source of truth for API contracts.
"""

from pydantic import BaseModel, Field
from typing import Literal, Dict, List, Optional, Any


class Clock(BaseModel):
    sim_time: int
    label: str
    day: int
    weekday: int
    in_office_hours: bool
    tick_seq: int
    status: Literal["running", "paused", "paused_budget", "waiting_on_model", "halted"]
    speed: float
    run_id: str


class Org(BaseModel):
    id: str
    name: str
    kind: Literal["software", "law", "accounting", "cafe"]
    cash_cents: int
    receivable_cents: int


class Module(BaseModel):
    id: str
    name: str
    status: Literal["up", "down"]


class Health(BaseModel):
    heartbeat_age_s: Optional[float]
    lag_s: float
    last_error: Optional[str]
    stale: bool


class WorldState(BaseModel):
    seq: int
    clock: Clock
    health: Health
    orgs: List[Org]
    modules: List[Module]
    tickets: Dict[str, int]
    unpaid_invoices: Dict[str, int]
    persons: Dict[str, int]


class SimEvent(BaseModel):
    seq: int
    sim_time: int
    tick_seq: Optional[int] = None
    kind: str
    actor_id: Optional[str]
    org_id: Optional[str]
    payload: Dict[str, Any]
    causes: List[int]
    label: Optional[str] = None
    depth: Optional[int] = None


class EventPage(BaseModel):
    events: List[SimEvent]
    seq: int


class CausalChain(BaseModel):
    root: int
    direction: Literal["up", "down"]
    events: List[SimEvent]


class Person(BaseModel):
    id: str
    org_id: Optional[str]
    name: str
    role: str
    kind: Literal["staff", "counterparty"]
    traits: Optional[Dict[str, float]]
    decision_seq: Optional[int] = None
    status: Optional[str] = None


class Decision(BaseModel):
    id: int
    decision_seq: int
    sim_time: int
    label: Optional[str] = None
    question_set: str
    source: Literal["rules", "jev", "llm"]
    distributions: Dict[str, Dict[str, float]]
    prng_path: str
    draws: Dict[str, float]
    chosen: Dict[str, Any]
    model_call: Optional[str]


class PersonDecisions(BaseModel):
    person: Person
    decisions: List[Decision]


class PerSimDay(BaseModel):
    usd: float
    usd_per_100_persons: float
    usd_per_10_orgs: float
    usd_per_1000_events: float


class Economics(BaseModel):
    spend_usd: float
    spend_is_estimated_calls: int
    model_calls: int
    input_tokens: int
    sim_days: float
    counts: Dict[str, int]
    per_sim_day: PerSimDay
    without_dedup: Dict[str, Any]
    dedup_rate: float
    unpriced_decisions: int
    decisions_by_model: List[Dict[str, Any]]
    by_kind: List[Dict[str, Any]]
    note: str


class ORG_COLORS:
    tallybird: str = "#7c9cff"
    halloran: str = "#c9a227"
    ledgerline: str = "#5bb98c"
    thirdrail: str = "#e0757c"
