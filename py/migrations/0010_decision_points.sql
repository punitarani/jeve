-- WORLD-0008: somebody is asked `agent.tick` at a decision point, not every tick.
--
-- `mind` is what was on their mind the last time they were asked, as a typed
-- key (`nothing`, `unpaid`, `outage:invoicing`, ...). A change to it is one of
-- the things that makes a moment a decision point; without it being written
-- down, "their situation changed" could not be told from "it is still the
-- same bad day".
ALTER TABLE positions ADD COLUMN mind text NOT NULL DEFAULT '';
