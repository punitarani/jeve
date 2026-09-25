"""`make evals`. The work is in `jeve.evals`, where a test can reach it."""

from __future__ import annotations

import sys

from jeve.evals.cli import main

if __name__ == "__main__":
    sys.exit(main())
