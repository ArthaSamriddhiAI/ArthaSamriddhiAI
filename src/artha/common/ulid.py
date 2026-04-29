"""ULID generator — Crockford base32, 48-bit ms timestamp + 80-bit randomness.

Per Section 15.11.1 of the consolidation spec, T1 event_id is a ULID. ULIDs are
time-sortable (the leading 10 chars encode the millisecond timestamp), which makes
chronological scans of the T1 ledger cheap without a separate index.

This is a minimal stdlib-only implementation. We avoid an external dep because
the surface is tiny and the spec only requires the string shape, not crate-level
compatibility with any specific ULID library.
"""

from __future__ import annotations

import os
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now_ms: int | None = None) -> str:
    """Return a 26-character Crockford base32 ULID.

    `now_ms` lets tests inject a deterministic timestamp without monkeypatching `time`.
    """
    ts = now_ms if now_ms is not None else int(time.time() * 1000)
    if ts < 0 or ts >= (1 << 48):
        raise ValueError(f"timestamp out of 48-bit range: {ts}")
    raw = ts.to_bytes(6, "big") + os.urandom(10)
    n = int.from_bytes(raw, "big")
    out = [""] * 26
    for i in range(25, -1, -1):
        out[i] = _CROCKFORD_ALPHABET[n & 0x1F]
        n >>= 5
    return "".join(out)


def is_ulid(s: str) -> bool:
    """Cheap shape check — 26 chars, all in the Crockford alphabet."""
    return len(s) == 26 and all(c in _CROCKFORD_ALPHABET for c in s)
