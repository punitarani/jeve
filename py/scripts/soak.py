"""`make soak`. The work is in `jeve.sim.soak`, where a test can reach it."""

from __future__ import annotations

import sys

from jeve.sim.soak import main

if __name__ == "__main__":
    sys.exit(main())
