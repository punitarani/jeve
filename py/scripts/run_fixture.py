"""Run the golden fixture end to end and report what happened.

    make fixture                       # Jev, replayed from the cassette: free
    make fixture POLICY=rules          # null model N1, no model at all
    make fixture CALLS=record          # live: hit-or-call, appends to the cassette

The fixture is the daemon with the clock off and a horizon (SIM-0001): there is
one run loop, so what passes here is what `make sim` runs.
"""

from __future__ import annotations

import sys

from jeve.sim.daemon import main

if __name__ == "__main__":
    args = sys.argv[1:]
    days = "5"
    if "--days" in args:
        at = args.index("--days")
        days = args[at + 1]
        del args[at : at + 2]
    sys.exit(
        main(
            [
                "--seed-world",
                *("--until-day", days),
                *("--day-minutes", "0"),
                "--verbose",
                *args,
            ]
        )
    )
