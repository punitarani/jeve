-- LLM-0010: the fold over spend_entries ran four times per model call and was
-- 80% of the production database's time at 86k rows on a 1/8 vCPU
-- (2026-09-24, CPU pinned at 100%). The ledger stays append-only (LLM-0007);
-- this is its running total, moved by every append under the ledger lock and
-- read by every spend check. Seeded here by the same fold
-- `SpendLedger.rebuild()` runs, so the row is right the moment this commits.
-- A ledger that opens against a total behind the ledger's head — the old
-- daemon appending between this migration and its own restart — folds the
-- rest in itself.
CREATE TABLE spend_totals (
    one             boolean PRIMARY KEY DEFAULT true CHECK (one),
    as_of_seq       bigint NOT NULL,
    settled_usd     double precision NOT NULL,
    calls           bigint NOT NULL,
    estimated_calls bigint NOT NULL,
    reserved_usd    double precision NOT NULL,
    baseline_usd    double precision,
    remote_usd      double precision,
    remote_at       timestamptz
);

INSERT INTO spend_totals (
    one, as_of_seq, settled_usd, calls, estimated_calls, reserved_usd,
    baseline_usd, remote_usd, remote_at
)
SELECT
  true,
  COALESCE(max(seq), 0),
  COALESCE(sum(amount_usd) FILTER (WHERE kind = 'settle'), 0),
  count(*) FILTER (WHERE kind = 'settle'),
  count(*) FILTER (WHERE kind = 'settle' AND (detail->>'estimated')::boolean),
  (SELECT COALESCE(sum(r.amount_usd), 0) FROM spend_entries r
    WHERE r.kind = 'reserve' AND NOT EXISTS (
      SELECT 1 FROM spend_entries s
      WHERE s.call_id = r.call_id AND s.kind IN ('settle', 'release'))),
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'baseline' ORDER BY seq LIMIT 1),
  (SELECT amount_usd FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1),
  (SELECT ts FROM spend_entries
    WHERE kind = 'remote' ORDER BY seq DESC LIMIT 1)
FROM spend_entries;

-- GET /world/agents counts the last tick's cafe crowd every five seconds per
-- open page. With only (kind, seq) to go on that was a bitmap scan over every
-- cafe event ever written, twice per call: 11% of the database's time and
-- 200 ms a call at 34k cafe events. (kind, tick_seq) makes both the max and
-- the count a short index range.
CREATE INDEX events_kind_tick ON events (kind, tick_seq);

-- Balances are sums over ledger_entries (WORLD-0005): GET /state sums every
-- org's cash and receivables every five seconds per open dashboard, and the
-- engine's cash_of() sums an account before every payment. Carrying the
-- amount in the account index makes those index-only rather than a heap fetch
-- per entry. Same name, same leading columns, so nothing that ordered by it
-- changes. Built before the old one is dropped, and last in the file: the
-- build takes seconds and only blocks writes, while DROP's exclusive lock —
-- which blocks /state's reads too — is held from here to the commit.
CREATE INDEX ledger_entries_account_new
    ON ledger_entries (account_id, id) INCLUDE (amount_cents);
DROP INDEX ledger_entries_account;
ALTER INDEX ledger_entries_account_new RENAME TO ledger_entries_account;
