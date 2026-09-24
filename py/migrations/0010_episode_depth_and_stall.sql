-- WORLD-0008: an episode can be two levels below the meeting that started it,
-- and a conversation can end by going round in circles.
--
-- Depth was capped at one in the schema as well as in code (WORLD-0006). The cap
-- stays in both places; it moves to two because a child now opens only where
-- the parent left a subset of its people with a stake of their own, and the
-- recursion research pre-registered exactly that bound.
ALTER TABLE episodes DROP CONSTRAINT episodes_depth_check;
ALTER TABLE episodes ADD CONSTRAINT episodes_depth_check CHECK (depth BETWEEN 0 AND 2);

-- `stalled`: a round in which everybody did what they did the round before.
-- In production, with live answers, 7 of the first 8 episodes ended on the round
-- cap and none as settled, because nothing stopped the same question being
-- asked again. Circling is a different finding from agreeing or running out of
-- rounds, so it gets its own name.
ALTER TABLE episodes DROP CONSTRAINT episodes_exit_reason_check;
ALTER TABLE episodes ADD CONSTRAINT episodes_exit_reason_check
    CHECK (exit_reason IN ('settled', 'emptied', 'rounds', 'stalled'));
