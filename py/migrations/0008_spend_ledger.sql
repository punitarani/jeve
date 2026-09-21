-- LLM-0007: the spend ledger is a table, not a file. A JSONL at
-- ops/ledger.jsonl was invisible to the API container and died with the
-- daemon's filesystem; spend accounting is exactly the state that must
-- survive both. Append-only, one row per event — reserve, settle, release,
-- baseline, remote — folded by the reader exactly as the file was.
CREATE TABLE spend_entries (
    seq        bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    pid        bigint NOT NULL,
    kind       text NOT NULL
               CHECK (kind IN ('reserve', 'settle', 'release',
                               'baseline', 'remote')),
    -- The reservation this entry settles or releases, for those kinds.
    call_id    text,
    amount_usd double precision,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Settles and releases find their reserve by call_id on every read.
CREATE INDEX spend_entries_call ON spend_entries (call_id)
    WHERE call_id IS NOT NULL;
