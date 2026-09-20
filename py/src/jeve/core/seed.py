"""Path-derived randomness (CORE-0005).

Every draw is a pure function of a root seed and a path, so there is no RNG
state to checkpoint and a crash cannot desynchronise a stream. Keying by a
per-person decision counter rather than by tick means a scheduler change does
not reshuffle everyone's luck — which is also what lets a control and a
treatment branch share draws for decisions the intervention never touched.

Adapted from workbench's `core/seed.py`, which earned it over a 140-day run.
"""

from __future__ import annotations

import hashlib
import random

_DOMAIN = b"jeve.seed.v1"


def derive_seed(root: int, *path: str | int) -> int:
    """A stable 64-bit seed for this point in the run.

    Stable across processes and platforms: blake2b rather than the builtin
    `hash()`, which is salted per process and would quietly break replay.
    """

    digest = hashlib.blake2b(_DOMAIN, digest_size=8)
    digest.update(root.to_bytes(8, "big", signed=False))
    for part in path:
        encoded = str(part).encode("utf-8")
        # Length-prefixed, so ("a", "bc") and ("ab", "c") differ.
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return int.from_bytes(digest.digest(), "big")


def derive_rng(root: int, *path: str | int) -> random.Random:
    return random.Random(derive_seed(root, *path))


def path_of(*path: str | int) -> str:
    """The human-readable form, stored on every decision row."""

    return "/".join(str(part) for part in path)
