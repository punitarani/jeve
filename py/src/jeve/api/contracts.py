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
    "sofa",
    "stair",
    "whiteboard",
    "server_rack",
    "bookshelf",
    "conference",
    "reception",
    "filing",
    "partition",
    "kitchen",
    "kitchenette",
    "shelf",
    "rack",
    "equipment",
    "dental_chair",
    "teller",
    "plant",
    "planter",
    "lamp",
    "void",
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


class Palette(BaseModel):
    """A firm's colours (CORE-0012): what its building and its people are drawn
    in. Served rather than hardcoded so a thirteenth firm needs no client
    change."""

    wall: str
    floor: str
    body: str
    accent: str


class Org(BaseModel):
    id: str
    name: str
    kind: str = Field(description="what the firm is: software, law, cafe, gym...")
    archetype: str = Field(
        description="which flows it takes part in: vendor, professional_services, "
        "retail, landlord, supplier or bank (CORE-0012)"
    )
    palette: Palette
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
    team_id: str | None = Field(description="null for a counterparty")
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
    """One building's footprint. `door` is the walkable tile in its wall; the
    zone is the firm's id (WORLD-0006)."""

    zone: str
    org_id: str
    name: str
    kind: str
    archetype: str
    palette: Palette
    x0: int
    y0: int
    x1: int
    y1: int
    door: tuple[int, int]
    faces_south: bool = Field(
        description="the door is in the south wall; false means the north wall"
    )
    floors: int
    stair: tuple[int, int] = Field(
        description="the stair's tile, the same on every floor of the building"
    )


class Storey(BaseModel):
    """One upper floor of a building, furnished on its own: a local grid over
    the footprint, `tiles[y - y0][x - x0]`, walls on the edge and no door."""

    zone: str
    floor: int
    x0: int
    y0: int
    tiles: list[list[TileKindName]]


class Team(BaseModel):
    """A team is a floor (CORE-0012): who sits together, and how many of them
    are there now."""

    id: str
    org_id: str
    name: str
    floor: int
    layout: str
    headcount: int
    present: int = Field(description="how many of the team are on their floor now")


class TeamsResponse(BaseModel):
    """GET /teams — every team of every firm, with who is on their floor now."""

    teams: list[Team]


class TownMap(BaseModel):
    """GET /world/map — the whole town, as data. Static for a page's life."""

    width: int
    height: int
    tiles: list[list[TileKindName]]
    zones: list[list[str]]
    buildings: list[Building]
    storeys: list[Storey]
    crowd_spots: dict[str, list[tuple[int, int]]] = Field(
        description="where a sampled crowd may stand, by zone: every social "
        "firm's ground floor and the plaza"
    )
    seats: dict[str, list[tuple[int, int]]] = Field(
        description="the tiles somebody sits on, keyed `zone/floor`"
    )


class Agent(BaseModel):
    """One member of staff's position, as /world/agents serves it."""

    id: str
    name: str
    org_id: str
    team_id: str
    role: str
    zone: str
    floor: int
    # NULL while at home — present on the wire as null, not omitted.
    x: int | None
    y: int | None
    path: list[tuple[int, int, int]] = Field(
        description="(x, y, floor) nodes, this tick's walk, both ends included"
    )
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
    zone: str
    topic: str
    initiated: bool
    led_to: list[str]


class AgentDetail(BaseModel):
    """GET /world/agents/{id} — who they are, what they last decided, met."""

    id: str
    name: str
    org_id: str
    org_name: str
    team_id: str
    team_name: str
    role: str
    zone: str
    floor: int
    mood: int
    traits: dict[str, float]
    trait_words: dict[str, str]
    last_decision: DecisionBrief | None
    last_encounter: EncounterBrief | None


class OrgDetail(BaseModel):
    """GET /orgs/{id} — one firm's books, people, and what is going on."""

    id: str
    name: str
    kind: str
    archetype: str
    palette: Palette
    zone: str
    floors: int
    teams: list[Team]
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


# Emission order for the generated file: a schema is written only after the
# schemas it references, because `z.object({ x: Foo })` reads Foo at module
# load.
MODELS: list[type[BaseModel]] = [
    Clock,
    Palette,
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
    Storey,
    Team,
    TeamsResponse,
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
    Economics,
]
