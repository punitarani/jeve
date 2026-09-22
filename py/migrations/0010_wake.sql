-- WORLD-0007: movement is decided at decision points, not every tick.
--
-- When somebody next decides where to go, and when they last did. A dwell is
-- drawn in code when a decision is made; an outage, a relevant arrival or the
-- lunch hour can wake a person sooner. Zero means "due now", which is what a
-- fresh seed and everyone arriving from home want.
ALTER TABLE positions ADD COLUMN next_decision_sim bigint NOT NULL DEFAULT 0;
ALTER TABLE positions ADD COLUMN last_decision_sim bigint NOT NULL DEFAULT 0;
