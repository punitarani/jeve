"""The roster is one spec, and nothing else names a firm (CORE-0012).

Four firms were four string literals in about 140 places. The spec in
`jeve.core.orgs` is where a firm is described once; these tests keep it
whole — every reference resolves, every floor has a layout, every team has
people — and walk the source to keep a firm's id out of the code that computes
the world.
"""

from __future__ import annotations

import re
from pathlib import Path

from jeve.core import orgs
from jeve.core.orgs import (
    BY_ID,
    HEADCOUNT,
    MODULE_CATEGORIES,
    MODULES,
    ORGS,
    ROLES,
    clients_of,
    counterparty_ids,
    module_owner,
    modules_of,
    retailers,
    social_places,
    staff_ids,
    tenants_of,
    uses,
    vendors,
)
from jeve.world.map import LAYOUTS

SRC = Path(orgs.__file__).resolve().parents[1]


def test_every_id_is_unique_and_every_reference_resolves() -> None:
    ids = [org.id for org in ORGS]
    assert len(ids) == len(set(ids))
    assert set(BY_ID) == set(ids)
    assert len(set(MODULES)) == len(MODULES)
    for org in ORGS:
        for module_id, cents in org.subscribes:
            assert module_id in MODULES, (org.id, module_id)
            assert cents > 0
            assert module_owner(module_id) != org.id, "nobody subscribes to their own"
        for module in org.modules:
            assert module.category in MODULE_CATEGORIES
            assert module_owner(module.id) == org.id
        for other in (org.accountant, org.landlord, org.supplier, org.caterer):
            assert other is None or other in BY_ID, (org.id, other)
        for role in (*org.payer_roles, *org.support_roles, *org.buyer_roles):
            assert role in ROLES, (org.id, role)
            assert any(role in team.roles for team in org.teams), (org.id, role)
        # Counterparties are demand, not payroll: their role has words but no wage.
        if org.counterparties:
            assert org.counterparty_role and org.counterparty_role not in ROLES
        else:
            assert org.counterparty_role is None
        if org.retail is not None:
            # A till is a category — whoever sells the product, it must be up.
            assert org.retail.till in MODULE_CATEGORIES, (org.id, org.retail.till)
            assert modules_of(org.id, org.retail.till), (org.id, org.retail.till)
            assert org.counterparties > 0


def test_teams_are_floors_from_the_ground_up() -> None:
    for org in ORGS:
        assert org.teams, org.id
        floors = sorted({team.floor for team in org.teams})
        assert floors == list(range(org.floors)), (org.id, floors)
        for team in org.teams:
            assert team.roles and all(n > 0 for n in team.roles.values())
            assert all(role in ROLES for role in team.roles), (org.id, team.id)
            assert team.layout in LAYOUTS, (org.id, team.layout)
        # One layout per floor: two teams that share a floor share its style.
        for floor in floors:
            styles = {team.layout for team in org.teams_on(floor)}
            assert len(styles) == 1, (org.id, floor, styles)
        assert org.headcount == sum(team.headcount for team in org.teams)
        assert org.payer_roles, f"{org.id} has nobody to pay its bills"
        assert org.opening_cash_cents > 0 and org.wages_per_week_cents > 0


def test_the_district_has_twelve_firms_and_the_headcount_it_was_designed_for() -> None:
    assert len(ORGS) == 12
    assert HEADCOUNT == 225
    assert sum(org.counterparties for org in ORGS) == 970
    assert {org.archetype for org in ORGS} == {
        "vendor",
        "professional_services",
        "retail",
        "landlord",
        "supplier",
        "bank",
    }
    assert len(vendors()) == 2
    assert {org.id for org in retailers()} >= {org.id for org in social_places()}
    # Every lot is taken once: three rows of four.
    lots = sorted(org.lot for org in ORGS)
    assert lots == [(row, slot) for row in range(3) for slot in range(4)]


def test_who_depends_on_whom_is_derived_not_declared_twice() -> None:
    for vendor in vendors():
        assert vendor.modules and vendor.support_roles
        for module in vendor.modules:
            assert module.id in uses(vendor.id), "a vendor runs on its own product"
    for org in ORGS:
        if org.accountant is not None and org.accountant != org.id:
            assert org in clients_of(org.accountant)
        elif org.accountant == org.id:
            # A firm that keeps its own books is nobody's client.
            assert org not in clients_of(org.id) and org.close_fee_cents == 0
        if org.landlord is not None:
            assert org in tenants_of(org.landlord)
            assert org.rent_cents > 0
        for category in MODULE_CATEGORIES:
            had = modules_of(org.id, category)
            assert len(had) <= 1, f"{org.id} uses two {category} products"
            for module_id in had:
                assert module_id in uses(org.id)


def test_people_are_named_by_org_team_role_and_number() -> None:
    seen: set[str] = set()
    for org in ORGS:
        ids = staff_ids(org.id)
        assert len(ids) == org.headcount
        for pid in ids:
            head, team, role, n = pid.split(".")
            assert head == org.id and role in ROLES and n.isdigit()
            assert any(t.id == team and role in t.roles for t in org.teams), pid
        seen.update(ids)
        cps = counterparty_ids(org.id)
        assert len(cps) == org.counterparties
        assert all(cp.startswith(f"{org.id}.{org.counterparty_role}.") for cp in cps)
        seen.update(cps)
    assert len(seen) == HEADCOUNT + sum(org.counterparties for org in ORGS)


LITERAL = re.compile(
    "['\"](?:" + "|".join(re.escape(org.id) for org in ORGS) + ")[.'\"]"
)
ALLOWED = {
    # The spec itself, and the names the story keeps for the people it began with.
    SRC / "core" / "orgs.py",
    SRC / "world" / "seed_world.py",
}


def test_no_firm_is_named_outside_the_roster() -> None:
    """A firm's id in the code that computes the world is the four-firm street
    coming back. The seed keeps its `NAMED` overrides; everything else asks
    the spec who does what."""

    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path in ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if LITERAL.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{number}: {line.strip()}")
    assert offenders == []
