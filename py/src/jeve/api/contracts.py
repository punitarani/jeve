"""The API contract, as pydantic models — the one source of truth.

These describe what `app.py` actually puts on the wire. They are not attached
to the endpoints as `response_model` (FastAPI would then *strip* any field it
did not know, hiding additions instead of surfacing them); they are enforced
two ways instead:

* `tools/contract-gen/generate_zod.py` renders the zod schemas the browser
  parses every response with — drift fails loudly at the client boundary.
* `test_api.py` validates real endpoint responses against these models — a
  shape the model forgot is a failing test, not a runtime surprise.

Field descriptions become comments in the generated TypeScript.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from jeve.world.map import Zone

# sim_meta.status's CHECK constraint is the vocabulary — every status the
# daemon can write, on the wire verbatim.
SimStatus = Literal[
    "running",
    "paused",
    "paused_budget",
    "waiting_on_model",
    "waiting_on_budget",
    "halted",
]
OrgKind = Literal["software", "law", "accounting", "cafe"]
# The tile vocabulary lives in world/map.py's layout code, not in an enum —
# the wire test over /world/map is what keeps this list honest.
TileKindName = Literal[
    "grass",
    "plaza",
    "path",
    "wall",
    "floor",
    "door",
    "desk",
    "counter",
    "table",
    "tree",
    "fountain",
    "chair",
    "bench",
    "whiteboard",
    "server_rack",
    "bookshelf",
    "conference",
    "reception",
    "filing",
    "partition",
    "kitchen",
    "plant",
    "planter",
    "lamp",
]


class Clock(BaseModel):
    sim_time: int
    label: str
    day: int
    weekday: int
    in_office_hours: bool
    tick_seq: int
    status: SimStatus = Field(
        description="Every value the database's CHECK allows. `paused_budget` "
        "was missing, so the day the governor paused the world the page would "
        "have failed to parse."
    )
    speed: float
    run_id: str


class Org(BaseModel):
    id: str
    name: str
    kind: OrgKind
    cash_cents: int
    receivable_cents: int


class Module(BaseModel):
    id: str
    name: str
    status: Literal["up", "down"]


class Health(BaseModel):
    """Is anybody driving? `clock.status` is the daemon's word; this is the
    evidence (SIM-0002)."""

    heartbeat_age_s: float | None = Field(
        description="Seconds since the daemon last proved it was alive. "
        "Null before its first beat."
    )
    lag_s: float = Field(description="How far the last tick ran over its pacing.")
    last_error: str | None
    stale: bool = Field(
        description="The status says a process should be alive and the "
        "heartbeat says none is."
    )
    tracing: bool = Field(
        description="Whether this deployment carries a BRAINTRUST_API_KEY "
        "(LLM-0008). False means nothing is traced, silently and by design. "
        "True means the key is present, not that Braintrust is accepting the "
        "spans — the SDK reports a rejected key or project only on the "
        "daemon's stderr."
    )


class TicketCounts(BaseModel):
    untriaged: int
    open: int


class UnpaidInvoices(BaseModel):
    n: int
    cents: int


class WorldState(BaseModel):
    seq: int
    clock: Clock
    health: Health
    orgs: list[Org]
    modules: list[Module]
    tickets: TicketCounts
    unpaid_invoices: UnpaidInvoices
    persons: dict[str, int]


class SimEvent(BaseModel):
    seq: int
    sim_time: int
    # /causal walks a CTE that does not select tick_seq — absent, not null.
    tick_seq: int | None = None
    kind: str
    actor_id: str | None
    org_id: str | None
    payload: dict[str, Any]
    causes: list[int]
    label: str
    depth: int | None = None


class EventPage(BaseModel):
    events: list[SimEvent]
    seq: int = Field(description="the newest seq in this page: the cursor for `after`")
    oldest: int = Field(
        description="the oldest seq in this page: the cursor for `before`; 0 when empty"
    )
    more: bool = Field(
        description="whether another page exists in the direction this one travelled"
    )


class CausalChain(BaseModel):
    root: int
    direction: Literal["up", "down"]
    events: list[SimEvent]


class Person(BaseModel):
    id: str
    org_id: str | None
    name: str
    role: str
    kind: Literal["staff", "counterparty"]
    traits: dict[str, float]
    # /persons/{id}/decisions does not select these — absent, not null.
    decision_seq: int | None = None
    status: str | None = None


class Decision(BaseModel):
    id: int
    decision_seq: int
    sim_time: int
    tick_seq: int
    label: str
    question_set: str
    source: Literal["rules", "jev", "llm"] = Field(
        description="Which kind of decider answered — the research question, per row."
    )
    distributions: dict[str, dict[str, float]] = Field(
        description="Empty for a rules decision; the full distribution when a "
        "model answered."
    )
    prng_path: str
    draws: dict[str, float]
    chosen: dict[str, Any]
    model_call: str | None


class PersonsResponse(BaseModel):
    persons: list[Person]


class PersonDecisions(BaseModel):
    person: Person
    decisions: list[Decision]


class PerSimDay(BaseModel):
    usd: float
    usd_per_100_persons: float
    usd_per_10_orgs: float
    usd_per_1000_events: float


class SpendWithoutDedup(BaseModel):
    spend_usd: float
    per_sim_day: PerSimDay


class DecisionsByModel(BaseModel):
    model: str
    decisions: int
    calls: int


class DecisionsByKind(BaseModel):
    kind: str
    source: str
    decisions: int
    calls: int
    usd: float


# -- the spatial world (WORLD-0003, WEB-0002) -------------------------------


class Building(BaseModel):
    """One building's footprint. `door` is the walkable tile in its wall."""

    zone: Zone
    org_id: str
    name: str
    x0: int
    y0: int
    x1: int
    y1: int
    door: tuple[int, int]


class TownMap(BaseModel):
    """GET /world/map — the whole town, as data. Static for a page's life."""

    width: int
    height: int
    tiles: list[list[TileKindName]]
    zones: list[list[Zone]]
    buildings: list[Building]
    crowd_spots: dict[str, list[tuple[int, int]]]
    seats: dict[str, list[tuple[int, int]]]


class Agent(BaseModel):
    """One member of staff's position, as /world/agents serves it."""

    id: str
    name: str
    org_id: str
    role: str
    zone: Zone
    # NULL while at home — present on the wire as null, not omitted.
    x: int | None
    y: int | None
    path: list[tuple[int, int]]
    moved_tick: int
    mood: int


class AgentsFrame(BaseModel):
    """GET /world/agents — the current frame: staff, the crowd, what is down."""

    seq: int
    tick_seq: int
    sim_time: int
    label: str
    status: SimStatus
    agents: list[Agent]
    crowd: dict[str, int]
    down_modules: list[str]


class DecisionBrief(BaseModel):
    """A person's last decision: the distribution Jev returned and the draw."""

    id: int
    sim_time: int
    label: str
    question_set: str
    source: Literal["rules", "jev", "llm"]
    model: str | None
    chosen: dict[str, Any]
    distributions: dict[str, dict[str, float]]
    draws: dict[str, float]


class EncounterBrief(BaseModel):
    """Whom a person last met, and what the meeting led to."""

    seq: int
    label: str
    with_id: str
    with_name: str
    zone: Zone
    topic: str
    initiated: bool
    led_to: list[str]


class AgentDetail(BaseModel):
    """GET /world/agents/{id} — who they are, what they last decided, met."""

    id: str
    name: str
    org_id: str
    org_name: str
    role: str
    zone: Zone
    mood: int
    traits: dict[str, float]
    trait_words: dict[str, str]
    last_decision: DecisionBrief | None
    last_encounter: EncounterBrief | None


class OrgDetail(BaseModel):
    """GET /orgs/{id} — one firm's books, people, and what is going on."""

    id: str
    name: str
    kind: OrgKind
    zone: Zone
    cash_cents: int
    receivable_cents: int
    staff_present: int
    staff_total: int
    open_tickets: int
    unpaid_invoices: int
    active: list[str]


class DialogueLine(BaseModel):
    speaker: str
    text: str


class EncounterTyped(BaseModel):
    """The typed record of one encounter — this, not the prose, is what
    happened (GEN-0001)."""

    seq: int
    between: tuple[str, str]
    zone: str
    topic: str
    mood: str
    escalated: bool


class EncounterProse(BaseModel):
    """A rendering of the typed record. `skipped` is sent only by a fresh
    render — cached prose has none — so the wire omits it rather than
    sending null."""

    lines: list[DialogueLine]
    model: str
    cost_usd: float
    cached: bool
    skipped: list[str] = []


class EncounterDialogue(BaseModel):
    """GET /encounters/{seq}/dialogue — the record always; prose if held."""

    typed: EncounterTyped
    prose: EncounterProse | None
    reason: str | None


# -- episodes (WORLD-0006) --------------------------------------------------


class EpisodeParticipant(BaseModel):
    """One person at the table. `seat` is speaking order, drawn when the
    episode opened; `left_round` is set if they walked away early."""

    person_id: str
    name: str
    org_id: str | None
    role: str
    seat: int
    left_round: int | None
    role_in_stake: Literal["holder", "asker", "bystander"] = Field(
        description="Whether they could settle the matter, wanted it settled, "
        "or were only in the room. Derived from the acts they were offered."
    )


class EpisodeAct(BaseModel):
    """What one person did in one round — the typed record, not a line of
    dialogue. There is no prose here to render."""

    person_id: str
    act: str
    seat: int


class EpisodeRound(BaseModel):
    round: int
    acts: list[EpisodeAct]
    left: list[str]
    tension: int
    decided_by: Literal["rules", "jev", "llm", "episode"]


class EpisodeOutcome(BaseModel):
    """What the episode changed. Every field here reached the world through an
    event that cites the episode's closing event, never through this record."""

    pressed: bool
    promised: bool
    refused: bool
    tension: int
    facts_passed: int
    ontology_gaps: int = Field(
        description="Acts that landed on `other`: the share of a decision "
        "surface the typed vocabulary did not cover, which is the project's "
        "primary research measurement (DECIDE-0001)."
    )


class Episode(BaseModel):
    """GET /episodes/{id} — a meeting that got more than one round."""

    id: int
    zone: Zone
    stake: Literal["outage", "invoice", "news"]
    stake_ref: str
    depth: int
    parent_id: int | None
    opened_sim: int
    opened_label: str
    opened_seq: int
    closed_sim: int | None
    closed_seq: int | None
    rounds: int
    exit_reason: Literal["settled", "emptied", "rounds"] | None
    outcome: EpisodeOutcome
    participants: list[EpisodeParticipant]
    round_log: list[EpisodeRound]
    led_to: list[SimEvent] = Field(
        description="What the episode caused, by following `causes` from its "
        "closing event — an escalation, a fact passed on, a promise."
    )


class EpisodePage(BaseModel):
    episodes: list[Episode]
    more: bool


class Economics(BaseModel):
    spend_usd: float
    spend_is_estimated_calls: int
    model_calls: int
    input_tokens: int
    sim_days: float
    counts: dict[str, int]
    per_sim_day: PerSimDay
    without_dedup: SpendWithoutDedup
    dedup_rate: float
    unpriced_decisions: int
    decisions_by_model: list[DecisionsByModel]
    by_kind: list[DecisionsByKind]
    note: str


# -- the field report (GET /report) -----------------------------------------


class ReportVitals(BaseModel):
    sim_days: int
    events: int
    decisions: int
    modelled: int = Field(description="Decisions a model call answered.")
    distinct_calls: int
    cache_hit_rate: float = Field(
        description="1 - distinct_calls / modelled: the share of modelled "
        "decisions answered by a call made before."
    )
    spend_usd: float = Field(
        description="Priced as /economics prices it: each call this run used, "
        "once, at what it cost when first made."
    )
    ledger_entries: int
    ledger_imbalance_cents: int = Field(
        description="Sum of every ledger entry. Zero, or the books are wrong."
    )
    incidents: int
    incidents_escalated: int
    escalations: int
    escalations_in_cafe: int
    persons: dict[str, int]


class ReportCashSeries(BaseModel):
    account_id: str
    org_id: str | None = Field(description="Null for the household sector.")
    name: str
    values: list[int] = Field(
        description="Cents at the end of each sim-day, from `first_day`."
    )


class ReportCash(BaseModel):
    first_day: int
    series: list[ReportCashSeries]


class ReportCacheDay(BaseModel):
    day: int
    decisions: int = Field(description="Modelled decisions that sim-day.")
    new_calls: int = Field(description="Of those, calls never made before.")


class ReportCallSet(BaseModel):
    question_set: str
    decisions: int
    gated: int = Field(description="Settled by a gate, with no model call.")
    calls: int
    usd: float


class ReportPerson(BaseModel):
    id: str
    name: str
    org_id: str
    role: str
    decisions: int = Field(description="agent.tick decisions.")
    mood: float | None = Field(description="Mean chosen mood, 0-3.")
    talk_share: float = Field(description="Share of ticks they chose to talk.")
    cafe_share: float = Field(
        description="Share of their time on the map spent at the cafe, walked "
        "from agent.moved."
    )
    raised: int = Field(description="Outages they escalated in person.")
    received: int = Field(description="Escalations raised with them.")
    sociability: float
    diligence: float


class ReportHourShare(BaseModel):
    hour: int
    share: float


class ReportCafeHour(BaseModel):
    hour: int
    sales: int
    walkouts: int


class ReportMood(BaseModel):
    mind: str = Field(
        description="`ordinary`, the id of the module the prompt said was down, "
        "or `other`."
    )
    decisions: int
    mood: float


class ReportPayroll(BaseModel):
    org_id: str
    name: str
    paid: int
    held: int
    last_paid_day: int | None
    insolvency_warnings: int


class ReportCollections(BaseModel):
    paid: int
    mean_days_late: float | None
    max_days_late: int | None
    open: int
    overdue: int
    written_off: int


class ReportHouseholds(BaseModel):
    wages_cents: int
    spending_cents: int


class ReportOutage(BaseModel):
    module_id: str
    name: str
    incidents: int
    escalated: int
    minutes_to_escalate: float | None
    minutes_escalated: float | None = Field(
        description="Mean outage length when someone escalated it."
    )
    minutes_not_escalated: float | None
    tickets: int


class ReportTopic(BaseModel):
    topic: str
    n: int


class ReportKnowledge(BaseModel):
    first_hand: int
    relayed: int
    encounters: int


class ReportAnswer(BaseModel):
    """One distinct model call: the state it was asked about and its answer."""

    uses: int
    state: dict[str, Any]
    ans: dict[str, Any] = Field(
        description="Per question: P(yes) for a yes/no question, otherwise "
        "the distribution."
    )


class CastMember(BaseModel):
    """Who the town replay draws: their seat and their walk to the cafe."""

    id: str
    name: str
    org_id: str
    role: str
    seat: tuple[int, int]
    spot: tuple[int, int]
    path: list[tuple[int, int]]


class FieldReport(BaseModel):
    """GET /report — the field report, recomputed at most once per tick."""

    seq: int
    as_of: str = Field(
        description="The database's clock when this was served, ISO-8601 UTC."
    )
    clock: Clock
    health: Health
    model: str | None = Field(
        description="The build that answered the latest modelled decision."
    )
    vitals: ReportVitals
    cash: ReportCash
    cache_by_day: list[ReportCacheDay]
    calls: list[ReportCallSet]
    people: list[ReportPerson]
    office_at_cafe: list[ReportHourShare]
    cafe_by_hour: list[ReportCafeHour]
    mood_by_mind: list[ReportMood]
    payroll: list[ReportPayroll]
    collections: ReportCollections
    households: ReportHouseholds
    outages: list[ReportOutage]
    topics: list[ReportTopic]
    knowledge: ReportKnowledge
    answers: dict[str, list[ReportAnswer]]
    cast: list[CastMember]
    queue: list[tuple[int, int]]


# Emission order for the generated file: a schema is written only after the
# schemas it references, because `z.object({ x: Foo })` reads Foo at module
# load.
MODELS: list[type[BaseModel]] = [
    Clock,
    Org,
    Module,
    Health,
    TicketCounts,
    UnpaidInvoices,
    WorldState,
    SimEvent,
    EventPage,
    CausalChain,
    Person,
    Decision,
    PersonsResponse,
    PersonDecisions,
    PerSimDay,
    SpendWithoutDedup,
    DecisionsByModel,
    DecisionsByKind,
    Building,
    TownMap,
    Agent,
    AgentsFrame,
    DecisionBrief,
    EncounterBrief,
    AgentDetail,
    OrgDetail,
    DialogueLine,
    EncounterTyped,
    EncounterProse,
    EncounterDialogue,
    EpisodeParticipant,
    EpisodeAct,
    EpisodeRound,
    EpisodeOutcome,
    Episode,
    EpisodePage,
    Economics,
    ReportVitals,
    ReportCashSeries,
    ReportCash,
    ReportCacheDay,
    ReportCallSet,
    ReportPerson,
    ReportHourShare,
    ReportCafeHour,
    ReportMood,
    ReportPayroll,
    ReportCollections,
    ReportHouseholds,
    ReportOutage,
    ReportTopic,
    ReportKnowledge,
    ReportAnswer,
    CastMember,
    FieldReport,
]
