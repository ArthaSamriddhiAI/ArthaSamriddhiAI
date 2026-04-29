"""Canonical JSON hashing for replay-stable payload identity.

Per Section 15.11.1, T1 events carry a `payload_hash` (SHA-256 of the payload).
For replay correctness, two payloads that are semantically identical must produce
the same hash regardless of dict key ordering or insignificant whitespace. We
canonicalise via `json.dumps(..., sort_keys=True, separators=(",", ":"))`.

Datetimes, enums, and Decimals are coerced to deterministic string forms.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"not JSON-serialisable for hashing: {type(obj).__name__}")


def canonical_json(payload: Any) -> str:
    """Deterministic JSON serialisation suitable for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)


def payload_hash(payload: Any) -> str:
    """SHA-256 hex digest of the canonical JSON of `payload`."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
