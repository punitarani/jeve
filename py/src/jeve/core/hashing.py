"""Canonical JSON and content hashes (CORE-0005).

The hash of a model request is its cache key, so it must not depend on dict
ordering or on how a float was spelled. Adapted from workbench's
`core/hashing.py`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

_DOMAIN = b"jeve.hash.v1"


def canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    digest = hashlib.blake2b(_DOMAIN, digest_size=32)
    digest.update(canonical_json(value))
    return digest.hexdigest()
