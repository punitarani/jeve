"""The district, as data (CORE-0012).

Four firms were four string literals in about 140 places; the next eight would
have been thirty more. This is where a firm is described once — what it is
called, what it is, how a question set refers to it, who works there and on
which floor, what hours it keeps, what it subscribes to, who keeps its books,
who its landlord is, what it sells — and every other layer reads it from here.
Nothing outside this module, the seed's name overrides and the tests may name a
firm; `tests/test_orgs.py` walks the source to keep it so.

In `core` because every layer needs it and it depends on nothing: plain data.
Hours are whole hours of the day; money is integer cents; nothing here is a
rule, only what the rules are about.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- vocabulary ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hours:
    """When a firm is open: whole hours of the day, and whether it trades on
    Saturday. Nothing opens on Sunday."""

    open: int
    close: int
    saturday: bool = False


OFFICE = Hours(9, 17)
CAFE = Hours(7, 18, saturday=True)
SHOP = Hours(9, 18, saturday=True)
CLINIC = Hours(8, 17)
GYM = Hours(7, 20, saturday=True)
WAREHOUSE = Hours(7, 16)


@dataclass(frozen=True, slots=True)
class RoleSpec:
    words: str
    """How a question set names the role: what they do, never the title."""
    weekly_wage_cents: int


# Weekly wages by role, in cents. A rule, like every price in this world.
ROLES: dict[str, RoleSpec] = {
    # software
    "founder": RoleSpec("founder", 2_400_00),
    "exec": RoleSpec("executive", 2_200_00),
    "eng_lead": RoleSpec("engineering lead", 2_200_00),
    "engineer": RoleSpec("engineer", 1_900_00),
    "sre": RoleSpec("site reliability engineer", 2_000_00),
    "support_lead": RoleSpec("support lead", 1_500_00),
    "support": RoleSpec("support agent", 1_200_00),
    "account_manager": RoleSpec("account manager", 1_500_00),
    "sales": RoleSpec("salesperson", 1_400_00),
    "product": RoleSpec("product manager", 1_800_00),
    "designer": RoleSpec("designer", 1_600_00),
    "ops": RoleSpec("operations person", 1_000_00),
    # law
    "partner": RoleSpec("partner", 3_000_00),
    "senior_associate": RoleSpec("senior associate", 2_300_00),
    "junior_associate": RoleSpec("junior associate", 1_500_00),
    "paralegal": RoleSpec("paralegal", 1_100_00),
    "office_manager": RoleSpec("office manager", 1_200_00),
    "receptionist": RoleSpec("receptionist", 800_00),
    # accounting
    "principal": RoleSpec("principal", 2_400_00),
    "senior_accountant": RoleSpec("senior accountant", 1_800_00),
    "staff_accountant": RoleSpec("accountant", 1_300_00),
    "bookkeeper": RoleSpec("bookkeeper", 1_000_00),
    "payroll": RoleSpec("payroll clerk", 1_200_00),
    "client_admin": RoleSpec("client services administrator", 1_100_00),
    "it": RoleSpec("IT technician", 1_400_00),
    # cafe
    "owner": RoleSpec("owner", 900_00),
    "manager": RoleSpec("manager", 1_000_00),
    "barista": RoleSpec("barista", 600_00),
    "kitchen": RoleSpec("kitchen hand", 700_00),
    "baker": RoleSpec("baker", 700_00),
    # property
    "property_manager": RoleSpec("property manager", 1_800_00),
    "leasing_agent": RoleSpec("leasing agent", 1_200_00),
    "maintenance": RoleSpec("maintenance worker", 900_00),
    "admin": RoleSpec("administrator", 900_00),
    # supplier
    "warehouse_lead": RoleSpec("warehouse lead", 1_000_00),
    "picker": RoleSpec("warehouse picker", 650_00),
    "driver": RoleSpec("delivery driver", 750_00),
    # clinic
    "practice_manager": RoleSpec("practice manager", 1_400_00),
    "dentist": RoleSpec("dentist", 3_200_00),
    "hygienist": RoleSpec("dental hygienist", 1_500_00),
    "dental_assistant": RoleSpec("dental assistant", 900_00),
    # studio
    "studio_manager": RoleSpec("studio manager", 1_600_00),
    "principal_architect": RoleSpec("principal architect", 2_600_00),
    "architect": RoleSpec("architect", 1_800_00),
    "drafter": RoleSpec("draughtsperson", 1_200_00),
    "model_maker": RoleSpec("model maker", 1_100_00),
    # hardware
    "floor_lead": RoleSpec("shop floor lead", 900_00),
    "sales_assistant": RoleSpec("shop assistant", 650_00),
    "stock": RoleSpec("stockroom hand", 650_00),
    # bank
    "branch_manager": RoleSpec("branch manager", 2_200_00),
    "teller": RoleSpec("teller", 800_00),
    "member_services": RoleSpec("member services officer", 900_00),
    "lending_officer": RoleSpec("lending officer", 1_800_00),
    "analyst": RoleSpec("credit analyst", 1_500_00),
    # gym
    "front_desk": RoleSpec("front desk attendant", 650_00),
    "trainer": RoleSpec("personal trainer", 900_00),
    "instructor": RoleSpec("class instructor", 850_00),
    "physio": RoleSpec("physiotherapist", 1_400_00),
}


@dataclass(frozen=True, slots=True)
class TeamSpec:
    """A team, and the floor it works on. Order within `roles` is seating order."""

    id: str
    name: str
    floor: int
    layout: str
    """Which layout furnishes the floor: pods, offices, ranks, counter, rooms,
    shopfloor, warehouse, gym, branch (`world/map.py`)."""
    roles: dict[str, int]

    @property
    def headcount(self) -> int:
        return sum(self.roles.values())


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """A product a vendor sells. `category` is what it is *for*, which is what
    a customer's dependency is on: any invoicing module blocks month-end."""

    id: str
    name: str
    category: str
    monthly_cents: int
    """What an outside subscriber pays for it."""


MODULE_CATEGORIES = ("timetrack", "invoicing", "pos")


@dataclass(frozen=True, slots=True)
class Palette:
    """The firm's colours in the voxel town (WEB-0004)."""

    wall: str
    floor: str
    body: str
    accent: str


@dataclass(frozen=True, slots=True)
class Retail:
    """A firm that serves whoever walks in, one at a time, over a till."""

    arrivals_per_hour: dict[int, int]
    """Walk-ins per hour, by the hour of the day. Halved on a Saturday."""
    basket_cents: tuple[int, int]
    """What one visit comes to: drawn uniformly from this range."""
    till: str
    """The module category the till depends on: `pos`, or `invoicing` where a
    visit is billed rather than rung up."""
    servers: float = 2.0
    """How many people can be served in one tick when the till works."""


@dataclass(frozen=True, slots=True)
class Billing:
    """Month-end billing of outside clients."""

    kind: str
    """`monthly` for work billed by the month; `milestone` for project stages."""
    engaged_per_month: float
    """The chance a given client had work done in a given month."""
    amount_cents: tuple[int, int]
    terms_days: int = 30


@dataclass(frozen=True, slots=True)
class OrgSpec:
    id: str
    name: str
    kind: str
    """What kind of business: software, law, cafe, clinic… Never a rule key;
    words and looks hang off it."""
    words: str
    """How a question set names it: never the brand, always what it is."""
    place_words: str
    """How a question set names being there: "the neighbourhood cafe"."""
    archetype: str
    """What the rules do with it: vendor, professional_services, retail,
    landlord, supplier, bank."""
    lot: tuple[int, int]
    """(row, slot) on the district plan (`world/map.py`)."""
    hours: Hours
    palette: Palette
    teams: tuple[TeamSpec, ...]
    opening_cash_cents: int
    payer_roles: tuple[str, ...]
    """Who pays its bills and chases what it is owed, first match wins."""
    counterparty_role: str | None = None
    """What the outside people who deal with it are: clients, subscribers…"""
    counterparties: int = 0
    subscribes: tuple[tuple[str, int], ...] = ()
    """(module id, monthly cents) for each product the firm pays for."""
    modules: tuple[ModuleSpec, ...] = ()
    """What a vendor sells."""
    support_roles: tuple[str, ...] = ()
    buyer_roles: tuple[str, ...] = ()
    """Who orders lunch in, and supplies."""
    accountant: str | None = None
    """Who closes its books and runs its payroll. None: it does its own."""
    landlord: str | None = None
    rent_cents: int = 0
    supplier: str | None = None
    caterer: str | None = None
    billing: Billing | None = None
    close_fee_cents: int = 0
    """What its accountant charges for a monthly close."""
    retail: Retail | None = None
    social: bool = False
    """Somewhere the staff of other firms go: the cafe, the gym."""
    outside_income_cents: int = 0
    """Monthly income from beyond the district — subscribers in other towns,
    a loan book, other properties — booked weekly. The district is a slice of
    each firm's world, and a slice that had to pay every wage would go under
    in a fortnight."""

    @property
    def floors(self) -> int:
        return 1 + max(team.floor for team in self.teams)

    @property
    def headcount(self) -> int:
        return sum(team.headcount for team in self.teams)

    def teams_on(self, floor: int) -> tuple[TeamSpec, ...]:
        return tuple(team for team in self.teams if team.floor == floor)

    def staff_on(self, floor: int) -> int:
        return sum(team.headcount for team in self.teams_on(floor))

    def layout_on(self, floor: int) -> str:
        teams = self.teams_on(floor)
        if not teams:
            raise KeyError(f"{self.id} has no team on floor {floor}")
        return teams[0].layout

    @property
    def wages_per_week_cents(self) -> int:
        return sum(
            ROLES[role].weekly_wage_cents * n
            for team in self.teams
            for role, n in team.roles.items()
        )


def _team(id: str, name: str, floor: int, layout: str, **roles: int) -> TeamSpec:
    return TeamSpec(id, name, floor, layout, dict(roles))


# The cafe's day: a rush before work, a bigger one at lunch.
_CAFE_ARRIVALS = {
    7: 10, 8: 30, 9: 25, 10: 19, 11: 22, 12: 41,
    13: 31, 14: 19, 15: 19, 16: 16, 17: 10,
}  # fmt: skip
_SHOP_ARRIVALS = {9: 6, 10: 8, 11: 8, 12: 7, 13: 7, 14: 8, 15: 8, 16: 7, 17: 5}
_CLINIC_ARRIVALS = {8: 3, 9: 3, 10: 3, 11: 3, 12: 1, 13: 3, 14: 3, 15: 3, 16: 2}
_GYM_ARRIVALS = {
    7: 8, 8: 6, 9: 4, 10: 3, 11: 3, 12: 6, 13: 4,
    14: 3, 15: 3, 16: 5, 17: 9, 18: 10, 19: 6,
}  # fmt: skip

# -- the roster ----------------------------------------------------------------

ORGS: tuple[OrgSpec, ...] = (
    OrgSpec(
        id="tallybird",
        name="Tallybird Software",
        kind="software",
        words="the software company",
        place_words="the software company's office",
        archetype="vendor",
        lot=(0, 0),
        hours=OFFICE,
        palette=Palette("#5b78d6", "#c9d4f5", "#7c9cff", "#2b3f8c"),
        teams=(
            _team(
                "leadership_ops",
                "Leadership, sales and ops",
                0,
                "pods",
                founder=1,
                exec=1,
                ops=3,
                account_manager=2,
                sales=3,
                product=2,
                designer=2,
            ),
            _team("support", "Support", 1, "pods", support_lead=1, support=7),
            _team(
                "engineering", "Engineering", 2, "pods", eng_lead=2, engineer=16, sre=2
            ),
        ),
        opening_cash_cents=420_000_00,
        payer_roles=("founder", "ops"),
        counterparty_role="subscriber",
        counterparties=100,
        modules=(
            ModuleSpec("timetrack", "TimeTrack", "timetrack", 49_00),
            ModuleSpec("invoicing", "Invoicing", "invoicing", 49_00),
            ModuleSpec("pos", "POS", "pos", 49_00),
        ),
        support_roles=("support", "support_lead"),
        buyer_roles=("ops", "founder"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=9_000_00,
        caterer="thirdrail",
        close_fee_cents=900_00,
        outside_income_cents=300_000_00,
    ),
    OrgSpec(
        id="halloran",
        name="Halloran & Pike LLP",
        kind="law",
        words="the law firm",
        place_words="the law firm's office",
        archetype="professional_services",
        lot=(0, 1),
        hours=OFFICE,
        palette=Palette("#a8871f", "#efe3b8", "#c9a227", "#5e4a0c"),
        teams=(
            _team(
                "front_office",
                "Front office",
                0,
                "offices",
                receptionist=2,
                office_manager=1,
                ops=1,
                paralegal=4,
            ),
            _team(
                "associates",
                "Associates",
                1,
                "offices",
                senior_associate=3,
                junior_associate=5,
                paralegal=2,
            ),
            _team("partners", "Partners", 2, "offices", partner=4, paralegal=2),
        ),
        opening_cash_cents=240_000_00,
        payer_roles=("office_manager", "ops"),
        counterparty_role="client",
        counterparties=80,
        subscribes=(("timetrack", 240_00), ("invoicing", 180_00)),
        buyer_roles=("office_manager", "receptionist"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=7_500_00,
        caterer="thirdrail",
        billing=Billing("monthly", 0.30, (300_000, 1_360_000)),
        close_fee_cents=1_200_00,
    ),
    OrgSpec(
        id="ledgerline",
        name="Ledgerline Accounting",
        kind="accounting",
        words="the accounting firm",
        place_words="the accounting firm's office",
        archetype="professional_services",
        lot=(0, 2),
        hours=OFFICE,
        palette=Palette("#3f9470", "#cdebdc", "#5bb98c", "#1f4d3a"),
        teams=(
            _team(
                "client_services",
                "Client services",
                0,
                "ranks",
                client_admin=2,
                it=1,
                payroll=2,
                bookkeeper=5,
            ),
            _team(
                "accountants",
                "Accountants",
                1,
                "ranks",
                principal=3,
                senior_accountant=3,
                staff_accountant=4,
            ),
        ),
        opening_cash_cents=170_000_00,
        payer_roles=("client_admin", "principal"),
        counterparty_role="client",
        counterparties=80,
        subscribes=(("invoicing", 180_00),),
        buyer_roles=("client_admin", "principal"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=5_500_00,
        caterer="thirdrail",
        billing=Billing("monthly", 0.30, (200_000, 800_000)),
    ),
    OrgSpec(
        id="keystone",
        name="Keystone Property",
        kind="property",
        words="the property company",
        place_words="the property company's office",
        archetype="landlord",
        lot=(0, 3),
        hours=OFFICE,
        palette=Palette("#8a6a4a", "#e8dccb", "#b58a5c", "#4a3520"),
        teams=(
            _team(
                "maintenance",
                "Maintenance and front desk",
                0,
                "ranks",
                receptionist=1,
                maintenance=5,
            ),
            _team(
                "management",
                "Management",
                1,
                "offices",
                property_manager=1,
                leasing_agent=2,
                admin=1,
                ops=1,
            ),
        ),
        opening_cash_cents=120_000_00,
        payer_roles=("admin", "property_manager"),
        subscribes=(("invoicing", 180_00),),
        buyer_roles=("admin", "property_manager"),
        accountant="ledgerline",
        caterer="thirdrail",
        close_fee_cents=600_00,
        outside_income_cents=15_000_00,
    ),
    OrgSpec(
        id="thirdrail",
        name="Third Rail Cafe",
        kind="cafe",
        words="the cafe",
        place_words="the neighbourhood cafe",
        archetype="retail",
        lot=(1, 0),
        hours=CAFE,
        palette=Palette("#b9555c", "#f6d3d5", "#e0757c", "#6b2227"),
        teams=(
            _team(
                "front_of_house",
                "Front of house",
                0,
                "counter",
                owner=1,
                manager=2,
                barista=10,
            ),
            _team("kitchen", "Kitchen", 0, "counter", kitchen=3, baker=1),
        ),
        opening_cash_cents=30_000_00,
        payer_roles=("owner", "manager"),
        counterparty_role="customer",
        counterparties=200,
        subscribes=(("pos", 120_00), ("timetrack", 90_00)),
        buyer_roles=("owner", "manager"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=3_200_00,
        supplier="northfield",
        close_fee_cents=450_00,
        retail=Retail(_CAFE_ARRIVALS, (350, 950), "pos"),
        social=True,
    ),
    OrgSpec(
        id="brightwater",
        name="Brightwater Dental",
        kind="clinic",
        words="the dental clinic",
        place_words="the dental clinic",
        archetype="retail",
        lot=(1, 1),
        hours=CLINIC,
        palette=Palette("#4f9fb8", "#d6ecf3", "#6fc0d8", "#1f4c5c"),
        teams=(
            _team(
                "reception",
                "Reception",
                0,
                "branch",
                receptionist=2,
                practice_manager=1,
                admin=1,
            ),
            _team(
                "clinical",
                "Clinical",
                1,
                "clinic",
                dentist=3,
                hygienist=4,
                dental_assistant=3,
            ),
        ),
        opening_cash_cents=90_000_00,
        payer_roles=("practice_manager", "admin"),
        counterparty_role="patient",
        counterparties=120,
        subscribes=(("invoicing", 180_00),),
        buyer_roles=("practice_manager", "admin"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=4_800_00,
        caterer="thirdrail",
        close_fee_cents=700_00,
        retail=Retail(_CLINIC_ARRIVALS, (120_00, 260_00), "invoicing", servers=3.0),
    ),
    OrgSpec(
        id="meridian",
        name="Meridian Studio Architects",
        kind="studio",
        words="the architecture studio",
        place_words="the architecture studio",
        archetype="professional_services",
        lot=(1, 2),
        hours=OFFICE,
        palette=Palette("#6c5fa8", "#e0dcf2", "#9a8ee0", "#3a2f6b"),
        teams=(
            _team(
                "front_admin",
                "Front desk and admin",
                0,
                "offices",
                studio_manager=1,
                admin=2,
                receptionist=1,
            ),
            _team(
                "studio_a",
                "Studio A",
                1,
                "rooms",
                principal_architect=1,
                architect=5,
                drafter=3,
            ),
            _team(
                "studio_b",
                "Studio B",
                2,
                "rooms",
                principal_architect=1,
                architect=3,
                drafter=2,
                model_maker=1,
            ),
        ),
        opening_cash_cents=120_000_00,
        payer_roles=("studio_manager", "admin"),
        counterparty_role="client",
        counterparties=30,
        subscribes=(("quill_timetrack", 240_00), ("quill_invoicing", 180_00)),
        buyer_roles=("studio_manager", "admin"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=5_500_00,
        caterer="thirdrail",
        billing=Billing("milestone", 0.25, (1_500_000, 4_500_000)),
        close_fee_cents=900_00,
    ),
    OrgSpec(
        id="commonwealth",
        name="Commonwealth Credit Union",
        kind="bank",
        words="the credit union",
        place_words="the credit union's branch",
        archetype="bank",
        lot=(1, 3),
        hours=OFFICE,
        palette=Palette("#2f6b8a", "#cfe0ea", "#5a93b3", "#173a4d"),
        teams=(
            _team(
                "branch",
                "Branch",
                0,
                "branch",
                branch_manager=1,
                teller=6,
                member_services=2,
            ),
            _team(
                "lending", "Lending", 1, "offices", lending_officer=3, analyst=2, ops=2
            ),
        ),
        opening_cash_cents=900_000_00,
        payer_roles=("ops", "branch_manager"),
        buyer_roles=("ops", "branch_manager"),
        landlord="keystone",
        rent_cents=6_000_00,
        caterer="thirdrail",
        outside_income_cents=95_000_00,
    ),
    OrgSpec(
        id="pemberton",
        name="Pemberton Hardware",
        kind="hardware",
        words="the hardware store",
        place_words="the hardware store",
        archetype="retail",
        lot=(2, 0),
        hours=SHOP,
        palette=Palette("#b8762f", "#f2dfc4", "#d9944a", "#5c3a12"),
        teams=(
            _team(
                "shop_floor",
                "Shop floor",
                0,
                "shopfloor",
                owner=1,
                floor_lead=1,
                sales_assistant=7,
            ),
            _team(
                "stock_office",
                "Stockroom and office",
                1,
                "warehouse",
                stock=3,
                bookkeeper=1,
            ),
        ),
        opening_cash_cents=40_000_00,
        payer_roles=("bookkeeper", "owner"),
        counterparty_role="customer",
        counterparties=150,
        subscribes=(("pos", 120_00), ("invoicing", 180_00)),
        buyer_roles=("owner", "floor_lead"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=3_600_00,
        supplier="northfield",
        close_fee_cents=500_00,
        retail=Retail(_SHOP_ARRIVALS, (12_00, 65_00), "pos"),
    ),
    OrgSpec(
        id="quill",
        name="Quill Systems",
        kind="software",
        words="the other software company",
        place_words="the other software company's office",
        archetype="vendor",
        lot=(2, 1),
        hours=OFFICE,
        palette=Palette("#3f8a8c", "#cfe9e9", "#5fb3b5", "#1d4748"),
        teams=(
            _team(
                "sales_ops",
                "Sales and ops",
                0,
                "pods",
                founder=1,
                sales=2,
                ops=1,
                account_manager=1,
            ),
            _team("support", "Support", 1, "pods", support_lead=1, support=4),
            _team(
                "engineering", "Engineering", 2, "pods", eng_lead=1, engineer=10, sre=1
            ),
        ),
        opening_cash_cents=200_000_00,
        payer_roles=("founder", "ops"),
        counterparty_role="subscriber",
        counterparties=60,
        modules=(
            ModuleSpec("quill_timetrack", "Quill Hours", "timetrack", 45_00),
            ModuleSpec("quill_invoicing", "Quill Billing", "invoicing", 45_00),
            ModuleSpec("quill_pos", "Quill Register", "pos", 45_00),
        ),
        support_roles=("support", "support_lead"),
        buyer_roles=("ops", "founder"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=6_000_00,
        caterer="thirdrail",
        close_fee_cents=800_00,
        outside_income_cents=150_000_00,
    ),
    OrgSpec(
        id="ironworks",
        name="Ironworks Gym",
        kind="gym",
        words="the gym",
        place_words="the gym",
        archetype="retail",
        lot=(2, 2),
        hours=GYM,
        palette=Palette("#585e66", "#d9dbdf", "#8b939c", "#23272d"),
        teams=(
            _team("gym_floor", "Gym floor", 0, "gym", owner=1, front_desk=2, trainer=6),
            _team("studio", "Studio", 1, "gym", instructor=3, physio=1),
        ),
        opening_cash_cents=28_000_00,
        payer_roles=("owner", "front_desk"),
        counterparty_role="member",
        counterparties=150,
        subscribes=(("quill_pos", 120_00), ("quill_timetrack", 90_00)),
        buyer_roles=("owner", "front_desk"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=4_200_00,
        close_fee_cents=450_00,
        retail=Retail(_GYM_ARRIVALS, (8_00, 18_00), "pos"),
        social=True,
        outside_income_cents=25_000_00,
    ),
    OrgSpec(
        id="northfield",
        name="Northfield Provisions",
        kind="supplier",
        words="the provisions supplier",
        place_words="the provisions supplier's yard",
        archetype="supplier",
        lot=(2, 3),
        hours=WAREHOUSE,
        palette=Palette("#6f8f3f", "#dfe9c8", "#93b55a", "#34481b"),
        teams=(
            _team(
                "warehouse",
                "Warehouse",
                0,
                "warehouse",
                warehouse_lead=1,
                picker=5,
                driver=3,
            ),
            _team("office", "Office", 1, "ranks", owner=1, sales=2, admin=1),
        ),
        opening_cash_cents=45_000_00,
        payer_roles=("admin", "owner"),
        subscribes=(("quill_invoicing", 180_00),),
        buyer_roles=("admin", "owner"),
        accountant="ledgerline",
        landlord="keystone",
        rent_cents=3_800_00,
        close_fee_cents=600_00,
        outside_income_cents=40_000_00,
    ),
)

BY_ID: dict[str, OrgSpec] = {org.id: org for org in ORGS}

MODULES: dict[str, ModuleSpec] = {
    module.id: module for org in ORGS for module in org.modules
}
_OWNER: dict[str, str] = {module.id: org.id for org in ORGS for module in org.modules}


def module_owner(module_id: str) -> str:
    """The vendor that sells a module."""

    return _OWNER[module_id]


def vendors() -> tuple[OrgSpec, ...]:
    return tuple(org for org in ORGS if org.archetype == "vendor")


def modules_of(org_id: str, category: str | None = None) -> tuple[str, ...]:
    """The module ids a firm pays for, optionally only those of one category.
    A vendor is on its own products."""

    org = BY_ID[org_id]
    own = [m.id for m in org.modules]
    paid = [module_id for module_id, _ in org.subscribes]
    return tuple(
        module_id
        for module_id in (*own, *paid)
        if category is None or MODULES[module_id].category == category
    )


def uses(org_id: str) -> frozenset[str]:
    return frozenset(modules_of(org_id))


def clients_of(accountant_id: str) -> tuple[OrgSpec, ...]:
    """Whose books an accounting firm closes: its clients, itself excluded."""

    return tuple(
        org
        for org in ORGS
        if org.accountant == accountant_id and org.id != accountant_id
    )


def tenants_of(landlord_id: str) -> tuple[OrgSpec, ...]:
    return tuple(org for org in ORGS if org.landlord == landlord_id)


def social_places() -> tuple[OrgSpec, ...]:
    """Where the staff of other firms go on their own time, in roster order."""

    return tuple(org for org in ORGS if org.social)


def retailers() -> tuple[OrgSpec, ...]:
    return tuple(org for org in ORGS if org.retail is not None)


def role_words(role: str) -> str:
    spec = ROLES.get(role)
    return spec.words if spec is not None else role.replace("_", " ")


def wage(role: str) -> int:
    spec = ROLES.get(role)
    return spec.weekly_wage_cents if spec is not None else 1_000_00


def staff_ids(org_id: str) -> tuple[str, ...]:
    """Every member of staff's id, in seating order: team, role, number."""

    org = BY_ID[org_id]
    return tuple(
        f"{org.id}.{team.id}.{role}.{n}"
        for team in org.teams
        for role, count in team.roles.items()
        for n in range(count)
    )


def counterparty_ids(org_id: str) -> tuple[str, ...]:
    org = BY_ID[org_id]
    if org.counterparty_role is None:
        return ()
    return tuple(
        f"{org.id}.{org.counterparty_role}.{n}" for n in range(org.counterparties)
    )


HEADCOUNT = sum(org.headcount for org in ORGS)
