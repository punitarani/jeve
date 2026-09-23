"""What an agent carries forward, and what travels between them.

Two things live here, and they answer different questions:

* `store` — what persists between meetings: a fact that can travel, who holds
  it, and a promise that was made. `jeve.world` writes through it so that
  "what a meeting changed" is one vocabulary rather than SQL scattered across
  flows.
* `beliefs` — what a person has come to think: four typed slots with four
  described levels each, revised by a score asked inside a request that is
  being made anyway, plus the relationships that decide who they talk to.

Neither generates anything. A fact is a row and a belief is a level; the
words attached to them are fixed sentences, chosen by a number.
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
]
