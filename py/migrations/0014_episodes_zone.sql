-- WORLD-0008: an episode's zone is a firm's id.
--
-- 0009 gave `episodes.zone` a CHECK listing the four-firm town's six zone
-- names. The district has twelve firms and the roster is the only place they
-- are written (CORE-0012), so the column keeps the emptiness check
-- `positions.zone` has and nothing else.
--
-- On its own rather than inside 0010 because the upgrade test rebuilds a
-- pre-episodes world by dropping 0009's tables and re-applying it: anything
-- that alters those tables has to be re-appliable on its own too, and 0010
-- does far more than this.

ALTER TABLE episodes DROP CONSTRAINT IF EXISTS episodes_zone_check;
ALTER TABLE episodes ADD CONSTRAINT episodes_zone_check CHECK (zone <> '');
