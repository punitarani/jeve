-- SIM-0003: waiting_on_budget is a daemon status, set when OpenRouter
-- answers 402 (the account cap is spent). It is not model weather — a
-- two-minute backoff refills nothing — and not a halt, because the cap
-- resets on its billing window and the world resumes by itself. SIM-0001
-- pinned this CHECK as the place where what an operator sees lives.
ALTER TABLE sim_meta DROP CONSTRAINT sim_meta_status_check;
ALTER TABLE sim_meta ADD CONSTRAINT sim_meta_status_check
    CHECK (status IN (
        'running', 'paused', 'paused_budget',
        'waiting_on_model', 'waiting_on_budget', 'halted'
    ));
