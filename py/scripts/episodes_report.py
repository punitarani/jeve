"""`make episodes`. The work is in `jeve.sim.episode_study`, where a test can
reach it."""

from __future__ import annotations

import sys

from jeve.sim.episode_study import main

if __name__ == "__main__":
    sys.exit(main())
