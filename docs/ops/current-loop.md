# Current loop — execution state

Working checklist for the autonomous completion loop. Updated as work lands.

## Repo state

- `main` @ `e7df311` — deployment-audit remediation committed, not pushed.
- `make check` green: ruff, mypy --strict (61 files), 257 tests, 38 decision
  records, markdownlint.
- `make e2e` green: replay world, pooled API, static export, 14/14 Playwright,
  economics MET.
- `make soak` green: 35 sim-days on rules, all invariants, ledger balances.
- Docker: `Dockerfile.{api,sim,web}` all build.
- Postgres: local container at 127.0.0.1:55432; `spend_entries` is the meter.

## Audit-flagged items — status from code

| Item | Status |
|---|---|
| Tickets never closing | resolved — `ticket.closed`/`answered`/`escalated` flow in `engine._support`/`_close`; soak shows 23 closed in 35d |
| Receivables never collected | resolved — `_payments`/`_client_payments`/`_chase`/`_write_off`; `payment.made` events |
| Month-end once only | resolved — soak: 2 month-ends in 35d, 6 monthly closes |
| Cash identical across arms | resolved — `soak --counterfactual` asserts `cash differs across arms: yes` |
| Spatial one-condition | resolved — encounters carry topic/mood/can_raise/raise_outage |
| Activity winding down | resolved — soak sustains to d35 |
| 104-agent seed | exceeded — 424 persons (24 staff + 400 counterparties) |
| Encounter blow-up | bounded by design — only staff are `present`, one `with` per agent per tick (~24 decisions/tick max) |
| Screenshots gitignored | resolved — `tools/` tracked; `.next-shots/` (output) ignored |
| UI postponed | resolved — hero + /world explorer + dashboard, e2e-covered |

## Working / broken / missing

- **Working**: sim loop, Jev policy with cassette replay, Postgres ledger,
  pooled API + shared stream hub, static frontend, CI/CD, docker images.
- **Broken**: nothing known.
- **Missing**: `HANDOFF.md`; live smoke since the gateway rewrite;
  production secrets not yet set (deploy-blocked by choice).

## Budget

Ledger `spend_entries` (LLM-0007) is the meter: baseline $0.30 / 2 calls at
loop start. `$20` cap is the *development* envelope; production ceilings are
env-tunable and set high, OpenRouter's own cap is the real stop. All work this
loop prefers replay; live calls only for `make smoke` (<$0.01).

## Queue (impact order)

1. `make smoke` — prove the real OpenRouter path post-rewrite (402 handling,
   rate-limit headers, ledger settlement). <$0.01.
2. Screenshot pass on the static build — visual regression check.
3. `HANDOFF.md` — required artifact.
4. Soak with `--counterfactual` live output check (already covered by
   test_soak; confirm report text).
5. Deployment prerequisites documentation sweep (done; verify env table
   matches code once more).

## Validation so far

- 2026-09-21: `make check`/`e2e`/`soak` all green; 3 docker images build;
  committed as `e7df311`.
