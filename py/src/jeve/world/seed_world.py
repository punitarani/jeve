"""The golden fixture: twelve firms, ~1,200 people, and a calendar that collides.

Deliberate shape, from the scenario:

  - Every org runs *warm*. A cascade needs finite slack; if backlogs sit at
    zero an outage cannot propagate and the sim is a screensaver.
  - Month-end lands on **day 3**, not Friday. With a Friday month-end and
    net-30 terms, the late invoices land after the window closes and nothing
    observable happens inside a five-day fixture.
  - Receivables are seeded so some fall due *inside* the window, which is what
    makes a payment decision fire at all.
  - One Invoicing outage is scheduled to run into day 4, across month-end.

Who exists comes from the roster (`jeve.core.orgs`, CORE-0012): every member of
staff a firm lists is made here, on the floor their team works on, with a name
drawn from a pool and traits drawn from their id. The twenty-four people the
town started with keep their names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.core.clock import DAY, DISTRICT_CLOSE, at
from jeve.core.names import person_name
from jeve.core.orgs import (
    MODULES,
    ORGS,
    counterparty_ids,
    module_owner,
    role_words,
    staff_ids,
    vendors,
)
from jeve.core.seed import derive_rng
from jeve.world.flows import daily_demand

ROOT_SEED = 20260920

HOUSEHOLD_OPENING_CENTS = 180_000_00
"""What the district's households have in the bank on day zero: a few days of
what they are collectively paid. Staff spend from it at the cafe and the gym,
and wages refill it (WORLD-0005)."""

# The people the town started with keep their names; everyone else is named
# from the pools in `jeve.core.names`.
NAMED: dict[str, str] = {
    "tallybird.leadership_ops.founder.0": "Dana Okonkwo",
    "tallybird.engineering.eng_lead.0": "Petra Halvorsen",
    "tallybird.engineering.engineer.0": "Mikel Andrade",
    "tallybird.engineering.engineer.1": "Sara Lindqvist",
    "tallybird.engineering.sre.0": "Tomas Brandt",
    "tallybird.support.support_lead.0": "Ruth Adeyemi",
    "tallybird.support.support.0": "Kwame Boateng",
    "tallybird.leadership_ops.account_manager.0": "Ingrid Solberg",
    "halloran.partners.partner.0": "Maeve Halloran",
    "halloran.associates.senior_associate.0": "Julian Pike",
    "halloran.associates.junior_associate.0": "Nadia Farrow",
    "halloran.front_office.paralegal.0": "Owen Castellanos",
    "halloran.front_office.office_manager.0": "Priya Raghunathan",
    "ledgerline.accountants.principal.0": "Grace Ledger",
    "ledgerline.accountants.senior_accountant.0": "Hugo Marchetti",
    "ledgerline.accountants.staff_accountant.0": "Amara Diallo",
    "ledgerline.client_services.payroll.0": "Bjorn Aaltonen",
    "ledgerline.client_services.client_admin.0": "Cleo Vanterpool",
    "thirdrail.front_of_house.owner.0": "Rosa Etxeberria",
    "thirdrail.front_of_house.manager.0": "Denny Kowalczyk",
    "thirdrail.front_of_house.barista.0": "Yusuf Kaplan",
    "thirdrail.front_of_house.barista.1": "Lila Mbeki",
    "thirdrail.kitchen.baker.0": "Anton Reyes",
    "thirdrail.kitchen.kitchen.0": "Fiona Trethewey",
}

OPEN_TICKETS = 9
"""Open tickets at the first vendor on day zero, so support starts warm rather
than idle; a third as many at the second."""


@dataclass(frozen=True, slots=True)
class SeedSummary:
    orgs: int
    teams: int
    staff: int
    counterparties: int
    invoices: int
    tickets: int
    scheduled: int

    @property
    def persons(self) -> int:
        return self.staff + self.counterparties


def _traits(rng: object, role: str) -> dict[str, float]:
    """Per-person parameters. The only thing separating two people in the same
    role, and therefore what the persona-flattening detector tests."""

    draw = rng.random  # type: ignore[attr-defined]
    return {
        "diligence": round(0.35 + 0.5 * draw(), 3),
        "promptness": round(0.30 + 0.55 * draw(), 3),
        "patience": round(0.30 + 0.6 * draw(), 3),
        "vocality": round(0.15 + 0.6 * draw(), 3),
        "risk_appetite": round(0.15 + 0.6 * draw(), 3),
        # Drawn last: adding a trait must not re-roll the ones before it.
        "sociability": round(0.15 + 0.7 * draw(), 3),
    }


def _unique_name(root_seed: int, person_id: str, taken: set[str]) -> str:
    """A name nobody else at the firm has. Drawn from the person's id, and
    from their id again with a suffix when the first draw is taken, so the
    result depends on nobody else's id."""

    name = NAMED.get(person_id) or person_name(root_seed, person_id)
    attempt = 1
    while name in taken:
        name = person_name(root_seed, f"{person_id}#{attempt}")
        attempt += 1
    taken.add(name)
    return name


def seed(conn: Connection[DictRow], *, root_seed: int = ROOT_SEED) -> SeedSummary:
    """Populate an empty, migrated database. Idempotent by truncation."""

    # Deferred constraint triggers left pending by a previous transaction make
    # TRUNCATE fail with ObjectInUse, so start from a clean slate.
    conn.commit()

    # Resetting a world that a daemon is writing to destroys it mid-tick. The
    # lock is re-entrant, so a daemon seeding its own world passes straight
    # through; a test run against a live daemon's database fails here, loudly,
    # instead of truncating underneath it.
    db.take_writer_lock(conn)

    with conn.transaction():
        conn.execute(
            """
            TRUNCATE sim_meta, scheduled, events, orgs, teams, persons, accounts,
                     ledger_txns, ledger_entries, modules, incidents,
                     subscriptions, tickets, invoices, payments, retail_sales,
                     decisions, positions, outage_notices, loans, beliefs,
                     relationships
                     RESTART IDENTITY CASCADE
            """
        )
        conn.execute(
            "INSERT INTO sim_meta (run_id, root_seed, sim_time, status) "
            "VALUES (%s, %s, %s, 'paused')",
            (f"golden-{root_seed}", root_seed, at(0, 7)),
        )
        db.executemany(
            conn,
            "INSERT INTO orgs (id, name, kind, archetype, policy) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(org.id, org.name, org.kind, org.archetype, "{}") for org in ORGS],
        )
        db.executemany(
            conn,
            "INSERT INTO modules (id, name, org_id, category) VALUES (%s, %s, %s, %s)",
            [
                (module.id, module.name, org.id, module.category)
                for org in vendors()
                for module in org.modules
            ],
        )
        teams = [
            (f"{org.id}.{team.id}", org.id, team.name, team.floor, team.layout, ord_)
            for org in ORGS
            for ord_, team in enumerate(org.teams)
        ]
        db.executemany(
            conn,
            "INSERT INTO teams (id, org_id, name, floor, layout, ord) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            teams,
        )

        # Accounts. `external` is the outside world: having it as a real
        # account is what makes total cash checkable end to end.
        accounts: list[tuple[str, str | None, str, str]] = [
            ("external", None, "Outside world", "external")
        ]
        for org in ORGS:
            for kind in ("cash", "receivable", "payable", "revenue", "expense"):
                accounts.append((f"{org.id}.{kind}", org.id, kind.title(), kind))
        # The people who work in the district, as one purse. No org: they are
        # not a firm, and the dashboard's per-firm cash must not count them.
        accounts += [
            ("households.cash", None, "Households: cash", "cash"),
            ("households.income", None, "Households: wages received", "revenue"),
            ("households.spending", None, "Households: spending", "expense"),
        ]
        db.executemany(
            conn,
            "INSERT INTO accounts (id, org_id, name, kind) VALUES (%s, %s, %s, %s)",
            accounts,
        )

        # Opening cash, chosen for runway: the cafe is thin, the bank is fat.
        opening = {org.id: org.opening_cash_cents for org in ORGS}
        txn = conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'opening balances') "
            "RETURNING id"
        ).fetchone()
        assert txn is not None
        entries = [(txn["id"], f"{org}.cash", cents) for org, cents in opening.items()]
        entries.append((txn["id"], "households.cash", HOUSEHOLD_OPENING_CENTS))
        entries.append(
            (txn["id"], "external", -sum(opening.values()) - HOUSEHOLD_OPENING_CENTS)
        )
        db.executemany(
            conn,
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, %s, %s)",
            entries,
        )

        # People. Staff from the roster, on the floor their team works on.
        persons: list[tuple[str, str, str | None, str, str, str, str]] = []
        staff = 0
        for org in ORGS:
            taken: set[str] = set()
            for pid in staff_ids(org.id):
                _, team, role, _ = pid.split(".")
                # CORE-0009: about this person, not about their place in a list.
                rng = derive_rng(root_seed, "traits", pid)
                persons.append(
                    (
                        pid,
                        org.id,
                        f"{org.id}.{team}",
                        _unique_name(root_seed, pid, taken),
                        role,
                        "staff",
                        json.dumps(_traits(rng, role)),
                    )
                )
                staff += 1

        counterparties = 0
        for org in ORGS:
            if org.counterparty_role is None:
                continue
            role = org.counterparty_role
            for index, pid in enumerate(counterparty_ids(org.id)):
                rng = derive_rng(root_seed, "cp", org.id, index)
                persons.append(
                    (
                        pid,
                        # A counterparty deals *with* the org but is not staff;
                        # org_id records the relationship.
                        org.id,
                        None,
                        f"{role_words(role).title()} {index:03d}",
                        role,
                        "counterparty",
                        json.dumps(_traits(rng, role)),
                    )
                )
                counterparties += 1
        db.executemany(
            conn,
            "INSERT INTO persons (id, org_id, team_id, name, role, kind, traits) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            persons,
        )

        # Everyone starts the run at home; the first open tick brings them in.
        db.executemany(
            conn,
            "INSERT INTO positions (person_id, zone) VALUES (%s, 'home')",
            [(row[0],) for row in persons if row[5] == "staff"],
        )

        # Subscriptions: what each firm pays for, and each vendor's outside
        # subscribers spread over its products — invoicing most of all, so a
        # person notices an outage of what they use.
        subs: list[tuple[str | None, str | None, str, int]] = []
        for org in ORGS:
            for module_id, cents in org.subscribes:
                subs.append((org.id, None, module_id, cents))
        for vendor in vendors():
            spread = [
                m
                for m in vendor.modules
                for _ in (range(2) if m.category == "invoicing" else range(1))
            ]
            for index, pid in enumerate(counterparty_ids(vendor.id)):
                module = spread[index % len(spread)]
                subs.append((None, pid, module.id, module.monthly_cents))
        db.executemany(
            conn,
            "INSERT INTO subscriptions (org_id, person_id, module_id, monthly_cents) "
            "VALUES (%s, %s, %s, %s)",
            subs,
        )

        # Receivables already in flight, some falling due inside the window.
        invoices: list[tuple[str, str | None, str | None, int, int, int, str]] = []
        # Last month's subscriptions, a couple of days past due: the first thing
        # every payer is asked about.
        for org in ORGS:
            for module_id, cents in org.subscribes:
                invoices.append(
                    (
                        module_owner(module_id),
                        org.id,
                        None,
                        at(-16),
                        at(-2),
                        cents,
                        "subscription",
                    )
                )
        # Last month's close fees, each at a date of its own: some overdue on
        # day zero, some not yet due.
        for org in ORGS:
            if org.accountant is None or org.accountant == org.id:
                continue
            rng = derive_rng(root_seed, "closefee", org.accountant, org.id)
            issued = at(-24 + int(rng.random() * 20))
            invoices.append(
                (
                    org.accountant,
                    org.id,
                    None,
                    issued,
                    issued + 14 * DAY,
                    org.close_fee_cents,
                    "services",
                )
            )
        # The books open mid-story (WORLD-0005): last month's client work was
        # billed four weeks ago on the firm's terms, so it falls due across the
        # first week. Same draw as the engine's month-end uses, for month -1.
        # Initial conditions: without them nothing is collectable inside ten days.
        for org in ORGS:
            if org.billing is None:
                continue
            low, high = org.billing.amount_cents
            for client in counterparty_ids(org.id):
                rng = derive_rng(root_seed, "engagement", org.id, client, -1)
                if rng.random() >= org.billing.engaged_per_month:
                    continue
                amount = low + int(rng.random() * (high - low))
                spread_rng = derive_rng(root_seed, "aged", org.id, client)
                issued = at(-27) + int(spread_rng.random() * 5 * DAY)
                invoices.append(
                    (
                        org.id,
                        None,
                        client,
                        issued,
                        issued + org.billing.terms_days * DAY,
                        amount,
                        "services",
                    )
                )

        db.executemany(
            conn,
            "INSERT INTO invoices "
            "(from_org_id, to_org_id, to_person_id, issued_sim, due_sim, "
            " amount_cents, kind) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            invoices,
        )

        # Every open invoice is a receivable the issuer already earned. Without
        # this, collecting one drives the receivable account negative — money
        # arriving that was never owed — and the balance sheet lies even though
        # the ledger still sums to zero.
        opening_txn = conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo) "
            "VALUES (0, 'opening receivables') RETURNING id"
        ).fetchone()
        assert opening_txn is not None
        receivable_legs: list[tuple[int, str, int]] = []
        for from_org, _to_org, _to_person, _issued, _due, cents, _kind in invoices:
            receivable_legs.append((opening_txn["id"], f"{from_org}.receivable", cents))
            receivable_legs.append((opening_txn["id"], f"{from_org}.revenue", -cents))
        db.executemany(
            conn,
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, %s, %s)",
            receivable_legs,
        )

        # Open tickets, so support starts warm rather than idle.
        tickets: list[tuple[int, str, str, str]] = []
        for vendor_index, vendor in enumerate(vendors()):
            count = OPEN_TICKETS if vendor_index == 0 else OPEN_TICKETS // 3
            modules = [m.id for m in vendor.modules]
            for index, reporter in enumerate(counterparty_ids(vendor.id)[:count]):
                module_id = modules[index % len(modules)]
                tickets.append(
                    (
                        at(-1, 14),
                        reporter,
                        module_id,
                        f"Export is slow on large accounts ({index})",
                    )
                )
        db.executemany(
            conn,
            "INSERT INTO tickets (opened_sim, reporter_id, module_id, subject) "
            "VALUES (%s, %s, %s, %s)",
            tickets,
        )

        # The calendar. Month-end on day 3; the outage starts day 3 morning and
        # runs into day 4, so invoicing is blocked exactly when it matters.
        schedule: list[tuple[int, int, str, str | None, str]] = [
            (at(3, 9, 30), 0, "month.end", None, '{"label": "month 1", "month": 0}'),
            (
                at(3, 8, 45),
                0,
                "incident.start",
                "invoicing",
                '{"severity": 2, "expected_minutes": 1500}',
            ),
        ]
        schedule += [
            (at(0, 9), 0, "subscription.run", vendor.id, "{}") for vendor in vendors()
        ]
        # Income from beyond the district lands on Monday mornings.
        schedule += [
            (at(0, 9, 15), 0, "income.outside", org.id, "{}")
            for org in ORGS
            if org.outside_income_cents
        ]
        # Payday is Friday at ten, for every firm.
        payday = at(4, 10)
        schedule += [
            (payday, 0, "payroll.run", org.id, json.dumps({"due": payday}))
            for org in ORGS
        ]
        # An accountant closes its clients' books the working day after month-end.
        closing = at(4, 9)
        schedule += [
            (closing, 0, "close.run", org.id, json.dumps({"due": closing}))
            for org in ORGS
            if org.accountant is not None and org.accountant != org.id
        ]
        # Lunch in from the cafe is thought about on Tuesdays and Thursdays.
        schedule += [
            (at(1, 10), 0, "catering.consider", org.id, "{}")
            for org in ORGS
            if org.caterer is not None
        ]
        # Rent goes out on the first working day of the month; supplies are
        # ordered on Monday mornings; the supplier puts its prices up in the
        # second week, which is the story's second shock (WORLD-0008).
        landlords = sorted({org.landlord for org in ORGS if org.landlord is not None})
        schedule += [
            (at(1, 9, 30), 0, "rent.run", landlord, '{"month": 0}')
            for landlord in landlords
        ]
        schedule += [
            (at(0, 9, 30), 0, "supply.order", org.id, "{}")
            for org in ORGS
            if org.supplier is not None
        ]
        suppliers = sorted({org.supplier for org in ORGS if org.supplier is not None})
        schedule += [
            (at(9, 9), 0, "supply.reprice", supplier, "{}") for supplier in suppliers
        ]
        # Every night, what fades fades (MEM-0002).
        schedule.append((at(0) + DISTRICT_CLOSE, 0, "day.end", None, "{}"))
        # A good week's stock on the shelves to begin with.
        for org in ORGS:
            if org.supplier is not None:
                conn.execute(
                    "UPDATE orgs SET stock_units = %s WHERE id = %s",
                    (9 * daily_demand(org.id), org.id),
                )
        db.executemany(
            conn,
            "INSERT INTO scheduled (due_sim_time, ord, kind, subject_id, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            schedule,
        )

    assert MODULES  # the roster names at least one vendor
    return SeedSummary(
        orgs=len(ORGS),
        teams=len(teams),
        staff=staff,
        counterparties=counterparties,
        invoices=len(invoices),
        tickets=len(tickets),
        scheduled=len(schedule),
    )
