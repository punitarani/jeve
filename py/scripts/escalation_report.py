"""`make escalation-report`. The work is in `jeve.sim.escalations`, where a test
can reach it."""

from __future__ import annotations

import sys

from jeve.sim.escalations import main

if __name__ == "__main__":
    sys.exit(main())
