-- Tier 1's daily room (DECIDE-0005) counts yesterday's decisions by sim time,
-- once per batch that has a candidate for a second opinion — in production,
-- where tier 1 runs in shadow, most batches with a medium- or high-stakes set.
-- The only index on `decisions` was (person_id, decision_seq), so each count
-- scanned the whole table, which grows by every decision the world ever makes:
-- the failure class of the 2026-09-24 ledger fold (LLM-0010). A range on this.
CREATE INDEX decisions_time ON decisions (sim_time);
