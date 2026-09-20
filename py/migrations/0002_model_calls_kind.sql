-- DECIDE-0003: which question set a recorded call belongs to.
--
-- The hash says *what* was asked; it cannot say why. Without the kind, the
-- economics report can total spend but not attribute it, and a replay miss can
-- only print a hash nobody can read.
ALTER TABLE model_calls ADD COLUMN kind text NOT NULL DEFAULT '';
CREATE INDEX model_calls_kind ON model_calls (kind);
