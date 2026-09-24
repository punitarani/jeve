"""The golden fixture: four orgs, ~424 people, and a calendar that collides.

Deliberate shape, from the scenario:

  - Every org runs *warm*. A cascade needs finite slack; if backlogs sit at
    zero an outage cannot propagate and the sim is a screensaver.
  - Month-end lands on **day 3**, not Friday. With a Friday month-end and
    net-30 terms, the late invoices land after the window closes and nothing
    observable happens inside a five-day fixture.
  - Receivables are seeded so some fall due *inside* the window, which is what
    makes a payment decision fire at all.
  - One Invoicing outage is scheduled to run into day 4, across month-end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db, memory
from jeve.core.clock import DAY, at
from jeve.core.orgs import ORGS as ORG_SPECS
from jeve.core.seed import derive_rng
from jeve.world.economy import (
    SEAT_PRICE_CENTS,
    household,
    household_accounts,
    recurring,
    seats_for,
)
from jeve.world.flows import WEEKLY_WAGE_CENTS

ROOT_SEED = 20260920

MODULES = (("timetrack", "TimeTrack"), ("invoicing", "Invoicing"), ("pos", "POS"))

ORGS = tuple((org.id, org.name, org.kind) for org in ORG_SPECS)

HOUSEHOLD_OPENING_WEEKS = 1.5
"""What each firm's households have in the bank on day zero, in weeks of that
firm's wages. One purse per employer (WORLD-0010): the town used to share one,
so an unpaid engineer's coffee came out of a lawyer's wages."""

# Staff with a full decision surface. Counterparties are generated below.
STAFF: tuple[tuple[str, str, str], ...] = (
    ("tallybird", "founder", "Dana Okonkwo"),
    ("tallybird", "eng_lead", "Petra Halvorsen"),
    ("tallybird", "engineer", "Mikel Andrade"),
    ("tallybird", "engineer", "Sara Lindqvist"),
    ("tallybird", "sre", "Tomas Brandt"),
    ("tallybird", "support_lead", "Ruth Adeyemi"),
    ("tallybird", "support", "Kwame Boateng"),
    ("tallybird", "account_manager", "Ingrid Solberg"),
    ("halloran", "partner", "Maeve Halloran"),
    ("halloran", "senior_associate", "Julian Pike"),
    ("halloran", "junior_associate", "Nadia Farrow"),
    ("halloran", "paralegal", "Owen Castellanos"),
    ("halloran", "office_manager", "Priya Raghunathan"),
    ("ledgerline", "principal", "Grace Ledger"),
    ("ledgerline", "senior_accountant", "Hugo Marchetti"),
    ("ledgerline", "staff_accountant", "Amara Diallo"),
    ("ledgerline", "payroll", "Bjorn Aaltonen"),
    ("ledgerline", "client_admin", "Cleo Vanterpool"),
    ("thirdrail", "owner", "Rosa Etxeberria"),
    ("thirdrail", "shift_lead", "Denny Kowalczyk"),
    ("thirdrail", "barista", "Yusuf Kaplan"),
    ("thirdrail", "barista", "Lila Mbeki"),
    ("thirdrail", "baker", "Anton Reyes"),
    ("thirdrail", "weekend", "Fiona Trethewey"),
)

COUNTERPARTIES_PER_ORG = 100


@dataclass(frozen=True, slots=True)
class SeedSummary:
    orgs: int
    staff: int
    counterparties: int
    invoices: int
    tickets: int
    scheduled: int

    @property
    def persons(self) -> int:
        return self.staff + self.counterparties


def traits_for(rng: object) -> dict[str, float]:
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
            TRUNCATE sim_meta, scheduled, events, orgs, persons, accounts,
                     ledger_txns, ledger_entries, modules, incidents,
                     subscriptions, tickets, invoices, payments, cafe_sales,
                     decisions, positions, outage_notices,
                     facts, knowledge, episodes, episode_participants,
                     commitments, timesheets, rota, escalations
                     RESTART IDENTITY CASCADE
            """
        )
        conn.execute(
            "INSERT INTO sim_meta (run_id, root_seed, sim_time, status) "
            "VALUES (%s, %s, %s, 'paused')",
            (f"golden-{root_seed}", root_seed, at(0, 7)),
        )
        db.executemany(
            conn, "INSERT INTO modules (id, name) VALUES (%s, %s)", list(MODULES)
        )
        # What each firm has decided lives in `policy` (WORLD-0010). A world
        # seeded here is under this economy from its first second; a world
        # that predates it counts missed paydays from its upgrade.
        db.executemany(
            conn,
            "INSERT INTO orgs (id, name, kind, policy) VALUES (%s, %s, %s, %s)",
            [
                (
                    oid,
                    name,
                    kind,
                    json.dumps(
                        {"economy_since": 0}
                        | ({"seats_priced": True} if oid == "tallybird" else {})
                    ),
                )
                for oid, name, kind in ORGS
            ],
        )

        # Accounts. `external` is the outside world: having it as a real
        # account is what makes total cash checkable end to end.
        accounts: list[tuple[str, str | None, str, str]] = [
            ("external", None, "Outside world", "external")
        ]
        for org_id, _, _ in ORGS:
            for kind in ("cash", "receivable", "payable", "revenue", "expense"):
                accounts.append((f"{org_id}.{kind}", org_id, kind.title(), kind))
        # The people who work in the town, one purse per employer.
        accounts += household_accounts()
        db.executemany(
            conn,
            "INSERT INTO accounts (id, org_id, name, kind) VALUES (%s, %s, %s, %s)",
            accounts,
        )

        # Opening cash, chosen for runway: the cafe is thin, Tallybird is fat.
        opening = {org.id: org.opening_cash_cents for org in ORG_SPECS}
        txn = conn.execute(
            "INSERT INTO ledger_txns (sim_time, memo) VALUES (0, 'opening balances') "
            "RETURNING id"
        ).fetchone()
        assert txn is not None
        entries = [(txn["id"], f"{org}.cash", cents) for org, cents in opening.items()]
        savings = {
            org: int(
                HOUSEHOLD_OPENING_WEEKS
                * sum(
                    WEEKLY_WAGE_CENTS.get(role, 1_000_00)
                    for staff_org, role, _ in STAFF
                    if staff_org == org
                )
            )
            for org in opening
        }
        entries += [(txn["id"], household(org), c) for org, c in savings.items()]
        entries.append(
            (txn["id"], "external", -sum(opening.values()) - sum(savings.values()))
        )
        db.executemany(
            conn,
            "INSERT INTO ledger_entries (txn_id, account_id, amount_cents) "
            "VALUES (%s, %s, %s)",
            entries,
        )

        # People.
        persons: list[tuple[str, str, str, str, str, str]] = []

        for index, (org_id, role, name) in enumerate(STAFF):
            rng = derive_rng(root_seed, "staff", index)
            pid = f"{org_id}.{role}.{index}"
            persons.append(
                (pid, org_id, name, role, "staff", json.dumps(traits_for(rng)))
            )

        counterparties = 0
        for org_id, _, kind in ORGS:
            role = {
                "software": "subscriber",
                "law": "client",
                "accounting": "client",
                "cafe": "customer",
            }[kind]
            for index in range(COUNTERPARTIES_PER_ORG):
                rng = derive_rng(root_seed, "cp", org_id, index)
                pid = f"{org_id}.{role}.{index}"
                persons.append(
                    (
                        pid,
                        # A counterparty deals *with* the org but is not staff;
                        # org_id records the relationship.
                        org_id,
                        f"{role.title()} {index:03d}",
                        role,
                        "counterparty",
                        json.dumps(traits_for(rng)),
                    )
                )
                counterparties += 1
        db.executemany(
            conn,
            "INSERT INTO persons (id, org_id, name, role, kind, traits) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            persons,
        )

        # Everyone starts the run at home; the first open tick brings them in.
        db.executemany(
            conn,
            "INSERT INTO positions (person_id, zone) VALUES (%s, 'home')",
            [(row[0],) for row in persons if row[4] == "staff"],
        )

        # Subscriptions: the three firms use Tallybird, plus outside subscribers.
        subs: list[tuple[str | None, str | None, str, int]] = [
            ("halloran", None, "timetrack", 240_00),
            ("halloran", None, "invoicing", 180_00),
            ("ledgerline", None, "invoicing", 180_00),
            ("thirdrail", None, "pos", 120_00),
            ("thirdrail", None, "timetrack", 90_00),
        ]
        # Outside subscribers, spread over the three products. They all used to
        # be on Invoicing, while any of the first forty could report an outage
        # of anything; now a person notices an outage of what they use.
        for index in range(COUNTERPARTIES_PER_ORG):
            module = ("invoicing", "timetrack", "invoicing", "pos", "invoicing")[
                index % 5
            ]
            person = f"tallybird.subscriber.{index}"
            # Small firms, paying per seat (WORLD-0010): a hundred at $49 a
            # month each was a tenth of Tallybird's wage bill.
            price = SEAT_PRICE_CENTS * seats_for(root_seed, person)
            subs.append((None, person, module, price))
        db.executemany(
            conn,
            "INSERT INTO subscriptions (org_id, person_id, module_id, monthly_cents) "
            "VALUES (%s, %s, %s, %s)",
            subs,
        )

        # One thing known to exactly one person on day zero (MEM-0002). The
        # scenario calls for it: the share of the town holding it over time is
        # the diffusion measure, and it means something only because nobody
        # else starts with it. An engineer, not the founder — the founder talks
        # to everyone, which would make the measure about their diary.
        rise = memory.Fact.price_rise("tallybird")
        memory.record_fact(conn, rise, sim_time=0)
        memory.learn(conn, "tallybird.engineer.2", rise.id, sim_time=0)

        # Receivables already in flight, some falling due inside the window.
        invoices: list[tuple[str, str | None, str | None, int, int, int, str]] = [
            # The cafe is 12 days late to Ledgerline before the run starts.
            (
                "ledgerline",
                "thirdrail",
                None,
                at(-12),
                at(-12 + 30),
                1_850_00,
                "services",
            ),
            (
                "halloran",
                None,
                "halloran.client.3",
                at(-25),
                at(2, 12),
                6_400_00,
                "services",
            ),
            (
                "halloran",
                None,
                "halloran.client.7",
                at(-28),
                at(1, 12),
                3_200_00,
                "services",
            ),
            (
                "ledgerline",
                None,
                "ledgerline.client.2",
                at(-26),
                at(3, 12),
                2_100_00,
                "services",
            ),
            (
                "ledgerline",
                None,
                "ledgerline.client.9",
                at(-31),
                at(0, 12),
                1_450_00,
                "services",
            ),
            ("tallybird", "halloran", None, at(-30), at(2, 9), 420_00, "subscription"),
            (
                "tallybird",
                "ledgerline",
                None,
                at(-30),
                at(4, 9),
                180_00,
                "subscription",
            ),
        ]
        # The books open mid-story (WORLD-0005): last month's client work was
        # billed four weeks ago on thirty-day terms, so it falls due across the
        # first week. Same draw as the engine's month-end uses, for month -1.
        # Initial conditions: without them nothing is collectable inside ten days.
        from jeve.world.engine import CLIENT_ENGAGED_PER_MONTH

        for org in ORG_SPECS:
            if not org.bills_clients_monthly:
                continue
            for index in range(COUNTERPARTIES_PER_ORG):
                client = f"{org.id}.{org.counterparty_role}.{index}"
                rng = derive_rng(root_seed, "engagement", org.id, client, -1)
                if rng.random() >= CLIENT_ENGAGED_PER_MONTH:
                    continue
                amount = 80_000 + int(rng.random() * 540_000)
                spread = derive_rng(root_seed, "aged", org.id, client)
                issued = at(-27) + int(spread.random() * 5 * DAY)
                invoices.append(
                    (
                        org.id,
                        None,
                        client,
                        issued,
                        issued + 30 * DAY,
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

        # Nine open tickets, so support starts warm rather than idle.
        tickets = [
            (
                at(-1, 14),
                f"tallybird.subscriber.{index}",
                "invoicing" if index % 2 else "timetrack",
                f"Export is slow on large accounts ({index})",
            )
            for index in range(9)
        ]
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
            (at(0, 9), 0, "subscription.run", None, "{}"),
        ]
        # Payday is Friday at ten, for every firm, run by Ledgerline.
        payday = at(4, 10)
        schedule += [
            (payday, 0, "payroll.run", org_id, json.dumps({"due": payday}))
            for org_id, _, _ in ORGS
        ]
        # Ledgerline closes its clients' books the working day after month-end.
        closing = at(4, 9)
        schedule += [
            (closing, 0, "close.run", org_id, json.dumps({"due": closing}))
            for org_id in ("halloran", "tallybird", "thirdrail")
        ]
        # And a quarter of an hour before, which of the three waits a day.
        schedule.append((closing - 15 * 60, 0, "close.plan", "ledgerline", "{}"))
        # Lunch in from the cafe is thought about on Tuesdays and Thursdays.
        schedule += [
            (at(1, 10), 0, "catering.consider", org_id, "{}")
            for org_id in ("halloran", "ledgerline", "tallybird")
        ]
        # Rent, stock, tax, households, loans, reviews and hiring (WORLD-0010).
        schedule += [
            (due, 0, kind, subject, json.dumps(payload))
            for due, kind, subject, payload in recurring(at(0, 7))
        ]
        db.executemany(
            conn,
            "INSERT INTO scheduled (due_sim_time, ord, kind, subject_id, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            schedule,
        )

    return SeedSummary(
        orgs=len(ORGS),
        staff=len(STAFF),
        counterparties=counterparties,
        invoices=len(invoices),
        tickets=len(tickets),
        scheduled=len(schedule),
    )
