"""What persists between meetings (MEM-0002).

A fact that can travel, a record of who holds it, and a promise that was made.
Three tables and the queries over them — no generation anywhere, and nothing
here knows what an episode is. `jeve.world` writes through this module so that
"what a meeting changed" is one vocabulary rather than SQL scattered across
flows.
"""

from __future__ import annotations

from jeve.memory.store import (
    Commitment,
    Fact,
    Tellable,
    close_commitments_for,
    facts_known_by,
    holders_of,
    learn,
    make_stale,
    most_tellable,
    open_commitment,
    promise,
    reach_of,
    record_fact,
    revive,
)

__all__ = [
    "Commitment",
    "Fact",
    "Tellable",
    "close_commitments_for",
    "facts_known_by",
    "holders_of",
    "learn",
    "make_stale",
    "most_tellable",
    "open_commitment",
    "promise",
    "reach_of",
    "record_fact",
    "revive",
]
