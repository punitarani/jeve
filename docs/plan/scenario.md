# The scenario

Four small businesses on one street, coupled tightly enough that a bad Tuesday at one is a
bad Friday at another. Names are fictional.

Design rule inherited from 01: **emergence has to come from interaction structure** — cash
constraints, queues, deadlines, dependencies — because a closed action vocabulary cannot
invent a Valentine's party. So the structure is where the design effort goes.

## 1. Orgs and roles — 24 agents

| Org | Agents | Roles |
|---|---|---|
| **Tallybird Software** — sells *Tallybird*, a small-business suite with three modules: **TimeTrack**, **Invoicing**, **POS** | 8 | Founder/CEO · engineering lead · engineer ×2 · SRE / primary on-call · support lead · support agent · account manager |
| **Halloran & Pike LLP** — law firm; uses TimeTrack + Invoicing | 5 | Managing partner · senior associate · junior associate · paralegal · office manager / billing |
| **Ledgerline Accounting** — uses Invoicing | 5 | Principal CPA · senior accountant · staff accountant · payroll & bookkeeping specialist · client-services admin |
| **Third Rail Cafe** — uses POS + TimeTrack | 6 | Owner-operator · shift lead · barista ×2 · baker · weekend part-timer |

Tallybird is the largest because it carries the most internal structure — the tension between
roadmap, debt, and firefighting is where the outage dynamics are generated.

Each persona is a card plus a few **typed trait parameters** — diligence, conflict tolerance,
risk appetite, patience — rendered into `state` as words, never numbers (00 §1.6). Traits are
the only thing separating two people in the same role, which makes them the thing the
persona-flattening detector tests (02 §3.2).

### Everyone else is code

A closed four-firm loop only passes the same money round. Sources and sinks are seeded
stochastic processes, all booked through an `outside` account so stock-flow consistency is
checkable (02 §3.1):

- **Walk-in cafe customers** — arrivals by hour and weekday.
- **~12 outside clients** of the law and accounting firms — engagement arrivals, and payment
  behaviour with a realistic late share.
- **~40 outside Tallybird subscribers** — a revenue base, so three named customers are not
  all of Tallybird's income; and a churn process sensitive to incident history.
- **Sinks** — wages to households, rent, suppliers, tax.

## 2. Inter-org transactions

All typed. All money in a double-entry ledger. A model decides *whether* and *when*; code
decides what is possible and what it costs.

| Flow | From → to | Cadence | Blocked or degraded by |
|---|---|---|---|
| Subscription invoice | Tallybird → all three | Monthly, automatic | — |
| Support ticket | Any customer agent → Tallybird support | On a problem | — |
| Incident | A Tallybird module goes down | Hazard process in code, **modulated by engineering decisions** (debt level, rushed deploys) | — |
| Credit or goodwill discount | Tallybird account manager → customer | After incidents | — |
| Monthly close | Ledgerline → cafe, law firm, Tallybird | Monthly | Client's records: POS, TimeTrack, Invoicing exports |
| Payroll run | Ledgerline → cafe, law firm | Biweekly, hard deadline | **TimeTrack** timesheets |
| Quarterly review | Ledgerline → Tallybird | Quarterly | Tallybird's own books |
| Professional-services invoice | Ledgerline → clients; Halloran & Pike → clients | Month-end | **Invoicing**; for the law firm also time entries in **TimeTrack** |
| Legal engagement | Tallybird (contracts, terms), cafe (lease), Ledgerline (engagement letters) → Halloran & Pike | On a triggering event | — |
| Catering order | Any office → cafe | Meetings | **POS** (manual fallback is slower and error-prone) |
| Lunch and coffee | Any agent → cafe | Daily | **POS** (cash-only fallback) |
| Payment | Each org's bill-payer → payee | A decision around the due date | Cash on hand |
| Reminder, dispute, work stoppage | Payee → payer | A decision when a receivable ages | — |

Terms: net-30 for professional services, net-15 for catering, subscriptions due on receipt.

## 3. Each org's internal loop

**Tallybird.** Backlog of features, bugs, and debt → the engineering lead allocates the week
across *roadmap / debt / firefight* → deploys Tuesday and Thursday, with incident risk rising
in debt level and in whether the deploy was rushed → incidents → on-call response →
postmortem creates a debt item. Support triages (category and severity are J-type), responds,
and escalates to engineering. The account manager watches customer health, issues credits,
and handles renewals. The founder arbitrates between the roadmap and the fire.

**Halloran & Pike.** Intake → matter → tasks that consume hours → **time entries** →
month-end invoice → collection. Decisions: which matter to work; whether to log time now or
"later" (a diligence trait — later means leakage, unbilled hours); whether to accept a new
engagement at capacity; whether to remind, call, or pause work for a client who has not paid.

**Ledgerline.** Per client, a monthly close: a checklist with dependencies on the client's
data. Payroll runs on deadlines that do not move. Month-end invoicing and receivables
follow-up. Decisions: which client first; when a client's data is late — wait, nag, or
estimate and fix later; when to pay its own bills.

**Third Rail.** Open → serve → close → cash up. Service is a queue in code whose rate depends
on staff present and POS status. Weekly supplier order, staffing, catering. Decisions: cover
for an absent barista or run short; accept a catering order at capacity; pay the supplier,
Ledgerline, or Tallybird first when cash is thin.

## 4. Seed state

The sim starts at **08:00 on the Monday of a month-end week**, so week one contains a Tuesday
deploy, a Thursday payroll, and Friday month-end billing. None of what follows is scripted;
the calendar just guarantees things can collide.

- Every org runs **warm**: utilisation 0.75–0.9. Cascades need finite slack — if backlogs sit
  at zero an outage cannot propagate (02 §3.2).
- **Cash runway:** cafe ≈ 3 weeks, Ledgerline ≈ 6, Halloran & Pike ≈ 8, Tallybird ≈ 5 months.
- **One receivable already aged:** the cafe owes Ledgerline, 12 days overdue.
- **Tallybird's debt level: elevated.** A risky deploy is queued for Tuesday.
- Open matters at the law firm; Ledgerline mid-close for two clients; nine open tickets.
- One fact known to a single agent — a Tallybird engineer knows a price rise is planned —
  seeds the diffusion measure.

**Shock deck** — a seeded exogenous process in code: a module outage, a key person out sick,
an unusually large catering order, a supplier price rise, an outside client disputing a bill,
an audit notice, a rumour. Poisson, mean 1.5 per sim-week. The live MVP additionally
guarantees at least one per sim-week so there is always something to watch.
**That guarantee is a watchability hack and is switched off for every validation run.** The
shocks are environment; what is emergent is the response and the propagation.

## 5. What a viewer should see within one sim-week

Each has an observable, a causal path visible in the timeline (ADR-010), and a way to be
falsified (02 §3.3).

| # | Behaviour | Path | Observable |
|---|---|---|---|
| 1 | **Outage → missed billing → cash trough.** Your example, and the MVP's pre-registered interventional test. | Invoicing down at month-end → Ledgerline and the law firm issue late → clients pay later → cash dips → the bill-payer delays their *own* payables | Invoice issue dates past month-end; DSO up; cash minimum; count of deferred payables |
| 2 | **Payroll squeeze.** | TimeTrack down near Thursday → Ledgerline runs payroll late or on estimates → cafe staff morale belief falls → call-outs → slower service → lost sales | Payroll timeliness; morale slots; absences; cafe queue length; revenue against the same weekday |
| 3 | **Credit chain.** | One late payer → the payee's receivables age → the payee pays *its* supplier late → reminders, disputes, a work stoppage | Payment delays correlated along the org graph at a lag; reminders and stoppages in the timeline |
| 4 | **Firefighting trap.** | Ticket surge → engineering lead shifts allocation to firefight → debt deferred → hazard rises → more incidents | Weekly allocation shares; hazard multiplier series; whether and when someone chooses to pay down debt |
| 5 | **Workaround divergence.** The most direct test of the research question. | Same outage, different people: one waits, one does it by hand, one files a ticket, one calls the account manager. Manual work later fails reconciliation. | Response mix by persona under an identical stimulus; rework tickets at the next close |
| 6 | **Diffusion through the cafe.** | Co-presence at lunch → "does A mention T to B?" (a noul per salient topic) → B now knows → B's beliefs shift | Share of agents who know the seeded fact over time — Smallville's measure, with no prose involved. It matters causally: knowing "Tallybird lost data" moves churn consideration at firms the incident never touched. |
| 7 | **Churn bargaining.** | Repeated incidents → a customer's `considering_alternatives` climbs → the account manager perceives risk → offers credit → consideration falls, or does not | Belief trajectories; credits issued; Tallybird MRR |

**If the sim cannot produce at least #1, #3 and #5, it is a screensaver.** #1 and #3 can in
principle arise from rules alone, which is exactly why the rule-based twin (02 §3.4, N1)
exists: the claim worth making is how agent decisions *change* those cascades. #5 cannot come
from rules. If #5 is absent, Jev is ignoring persona and the thesis has failed at the point
that matters.

## 6. Degenerate failure modes expected here

General detectors and thresholds are in 02 §3.2 and §3.8. What they look like in this world:

| Failure | How it would appear | Caught by |
|---|---|---|
| **Everyone idles** | The safest verb always wins; backlogs grow beside idle people | Idle-with-backlog; action entropy |
| **Everyone pays on the due date** | No variance in payment timing, so #3 can never occur | Negative-event rate; payment-delay distribution degenerate at zero |
| **Runaway politeness** | Every catering order accepted, every credit granted, nothing ever disputed | Inter-org acceptance rate > 95% |
| **Reminder ping-pong** | Remind → acknowledge → remind, no payment, no state change | Dyadic no-progress cycle. workbench has met this one: 200+ acknowledgment-only emails, fixed with reply-depth caps (00 §6.5) — lifted as defaults |
| **Ticket tennis** | Support ⇄ engineering reassignments with no work done | Same detector |
| **Tallybird death spiral** | Behaviour #4 with no damping: incidents → churn → no revenue → collapse | Hazard multiplier and MRR bounds; bankruptcy as an absorbing state; Kaplan–Meier across replicas |
| **Frozen economy** | Everyone conserves cash, nobody pays, velocity → 0 | Money velocity; ρ < 0.1 |
| **The cafe does not matter** | Its links are too small to transmit anything | Path-blocking: removing the cafe changes nothing downstream |
| **Persona flattening** | Two baristas, or two engineers, are interchangeable | Within-role JSD against the shuffled-persona null; persona classifier near chance |
| **Rare-event inflation** | Resignations and churn far too frequent | Rates that scale with wake frequency — the hazard-rate rule's failure signature (ADR-004) |
| **Lunch monoculture** | Everyone orders the same thing forever | Entropy of a trivially observable choice; the cheapest canary for argmax-instead-of-sample bugs |
| **Phantom events** | Agents act on something that never happened | Every event's `causes` must resolve; engine faults never enter agent memory (00 §6.5) |

Tuning the seed so the economy is neither frozen nor exploding is real work and will take
iteration. It is done against the **rule-based twin first**, where a 60-sim-day run costs
nothing.
