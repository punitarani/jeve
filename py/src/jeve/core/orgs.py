"""The firms, as data (the first seam of orgs-as-data; see CORE records).

Four firms were four string literals in about 140 places. This is where a firm
is described once: what it is called, what it is, how a question set refers to
it, where it lives, who deals with it from outside, and who works there. Code
that needs one of those facts should read it from here; code written before this
existed still has literals, and is moved over when it is next touched.

In `core` because every layer needs it and it depends on nothing: plain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OrgSpec:
    id: str
    name: str
    kind: str
    words: str
    """How a question set names it: never the brand, always what it is."""
    zone: str
    counterparty_role: str
    """What the outside people who deal with it are: clients, subscribers…"""
    bills_clients_monthly: bool = False
    """Runs a month-end billing cycle for outside clients."""
    payer_roles: tuple[str, ...] = ()
    """Who pays its bills and chases what it is owed, first match wins."""
    opening_cash_cents: int = 0
    headcount: dict[str, int] = field(default_factory=dict)
    """Role -> how many, for the full town (104). Order is seating order."""


ORGS: tuple[OrgSpec, ...] = (
    OrgSpec(
        id="tallybird",
        name="Tallybird Software",
        kind="software",
        words="the software company",
        zone="software_office",
        counterparty_role="subscriber",
        payer_roles=("founder", "ops"),
        opening_cash_cents=48_000_00,
        headcount={
            "founder": 1,
            "exec": 1,
            "eng_lead": 2,
            "engineer": 18,
            "sre": 2,
            "support_lead": 1,
            "support": 7,
            "account_manager": 2,
            "sales": 3,
            "product": 2,
            "designer": 2,
            "ops": 3,
        },
    ),
    OrgSpec(
        id="halloran",
        name="Halloran & Pike LLP",
        kind="law",
        words="the law firm",
        zone="law_office",
        counterparty_role="client",
        bills_clients_monthly=True,
        payer_roles=("office_manager", "ops"),
        opening_cash_cents=96_000_00,
        headcount={
            "partner": 4,
            "senior_associate": 3,
            "junior_associate": 5,
            "paralegal": 6,
            "office_manager": 1,
            "receptionist": 3,
            "ops": 2,
        },
    ),
    OrgSpec(
        id="ledgerline",
        name="Ledgerline Accounting",
        kind="accounting",
        words="the accounting firm",
        zone="accounting_office",
        counterparty_role="client",
        bills_clients_monthly=True,
        payer_roles=("client_admin", "principal"),
        opening_cash_cents=50_000_00,
        headcount={
            "principal": 3,
            "senior_accountant": 3,
            "staff_accountant": 4,
            "bookkeeper": 6,
            "payroll": 1,
            "client_admin": 2,
            "it": 1,
        },
    ),
    OrgSpec(
        id="thirdrail",
        name="Third Rail Cafe",
        kind="cafe",
        words="the cafe",
        zone="cafe",
        counterparty_role="customer",
        payer_roles=("owner", "manager"),
        opening_cash_cents=18_000_00,
        headcount={
            "owner": 1,
            "manager": 2,
            "barista": 10,
            "kitchen": 3,
        },
    ),
)

BY_ID: dict[str, OrgSpec] = {org.id: org for org in ORGS}


@dataclass(frozen=True, slots=True)
class Shift:
    """When one job is done: which weekdays (0 = Monday), from and to when, in
    seconds after midnight."""

    days: tuple[int, ...]
    start: int
    end: int

    def covers(self, weekday: int, time_of_day: int) -> bool:
        return weekday in self.days and self.start <= time_of_day < self.end


_HOUR = 3600
_WEEKDAYS = (0, 1, 2, 3, 4)
OFFICE_HOURS = Shift(_WEEKDAYS, 9 * _HOUR, 17 * _HOUR)

SHIFTS: dict[tuple[str, str], tuple[Shift, ...]] = {
    # The cafe opens at seven, six days a week, and nobody works all of it.
    # Hours used to belong to the firm, so every member of cafe staff worked
    # every open hour and the weekend part-timer worked six days (field
    # report, defect 5). Two baristas split the day between them; the
    # n-th person in a role takes the n-th shift, round the list.
    ("thirdrail", "owner"): (Shift(_WEEKDAYS, 8 * _HOUR, 16 * _HOUR),),
    ("thirdrail", "manager"): (Shift((1, 2, 3, 4, 5), 10 * _HOUR, 18 * _HOUR),),
    ("thirdrail", "shift_lead"): (Shift(_WEEKDAYS, 7 * _HOUR, 15 * _HOUR),),
    ("thirdrail", "barista"): (
        Shift(_WEEKDAYS, 7 * _HOUR, 13 * _HOUR),
        Shift(_WEEKDAYS, 12 * _HOUR, 18 * _HOUR),
    ),
    ("thirdrail", "baker"): (Shift((0, 1, 2, 3, 4, 5), 7 * _HOUR, 12 * _HOUR),),
    ("thirdrail", "kitchen"): (Shift((0, 1, 2, 3, 4, 5), 10 * _HOUR, 16 * _HOUR),),
    ("thirdrail", "weekend"): (Shift((5,), 7 * _HOUR, 18 * _HOUR),),
}


def shift_for(org: str, role: str, nth: int = 0) -> Shift:
    """The hours the `nth` person in this role at this firm keeps."""

    shifts = SHIFTS.get((org, role))
    if not shifts:
        return OFFICE_HOURS
    return shifts[nth % len(shifts)]


assert sum(sum(o.headcount.values()) for o in ORGS) == 104
assert [sum(o.headcount.values()) for o in ORGS] == [44, 24, 20, 16]
