-- SIM-0002: a reader must be able to tell a world asleep for the night from a
-- process that has died, and a slow model from a broken one.
--
-- heartbeat_at is wall-clock and written by the daemon between ticks and from
-- its sleep loop. Nothing in the simulation reads it.
ALTER TABLE sim_meta ADD COLUMN heartbeat_at timestamptz;
ALTER TABLE sim_meta ADD COLUMN lag_s double precision NOT NULL DEFAULT 0;
ALTER TABLE sim_meta ADD COLUMN last_error text;
