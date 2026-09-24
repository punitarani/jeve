"""`make judge-panel`. The work is in `jeve.sim.panel`, where a test can reach
it."""

from __future__ import annotations

import sys

from jeve.sim.panel import main

if __name__ == "__main__":
    sys.exit(main())
