"""Decision-artifact hash service (FR Entry 20.4 §3 / FR 20.1 §4.3).

When the CIO records a decision, six hashes (or fewer per case mode)
are computed deterministically over the case's evidence + synthesis +
governance + portfolio-risk + IC1 + A1 packets. The hashes are
persisted on the ``decision_artifacts`` row and surface in the
``case_decided`` T1 event payload, anchoring audit replay.

Algorithm (FR 20.1 §4.3):

1. ``evidence_packet_hash`` — SHA-256 over canonical-JSON of the
   evidence_verdict rows ordered by ``(agent_id, produced_at)``.
2. ``synthesis_hash`` — SHA-256 of the synthesis_output row.
3. ``governance_packet_hash`` — SHA-256 over governance_results ordered
   by ``gate``.
4. ``portfolio_risk_hash`` — SHA-256 of the portfolio_risk_analytics
   row (None when missing).
5. ``ic1_hash`` — SHA-256 of the ic1_deliberation row (None for
   non-material cases).
6. ``a1_hash`` — SHA-256 of the a1_challenge row (None for diagnostic /
   briefing modes; cluster-5 decision_artifacts only ever exist for
   case modes).

Canonical-JSON format (cluster 5 working answer; spec doesn't pin
RFC 8785): ``json.dumps(obj, sort_keys=True, separators=(",", ":"),
default=str)``. Same format on both write and verify so re-computing
hashes from persisted rows produces identical bytes.

Re-computation produces identical hashes iff the underlying records
weren't tampered with. Mismatches surface
:data:`DECISION_ARTIFACT_HASH_MISMATCH` T1 events on audit replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Canonical encoding
# ---------------------------------------------------------------------------


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 byte encoding for hashing.

    Keys sorted, no whitespace, ``default=str`` so datetime / Decimal
    / UUID fall back to ``str()`` representation. Matches the cluster 3
    staging convention so the wider audit-replay machinery uses the
    same canonical form.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_value(value: Any) -> str:
    """Hash an arbitrary JSON-serialisable value via the canonical path."""
    return sha256_hex(canonical_json_bytes(value))


# ---------------------------------------------------------------------------
# Per-stage helpers
# ---------------------------------------------------------------------------


def hash_evidence_packet(rows: list[dict[str, Any]]) -> str:
    """Hash a list of evidence_verdict dicts.

    Caller orders by ``(agent_id, produced_at)`` per FR 20.1 §4.3 — we
    do NOT re-sort here so caller controls the canonical sequence
    (e.g. reading from DB ``ORDER BY agent_id, produced_at``).
    """
    return sha256_hex(canonical_json_bytes(rows))


def hash_synthesis(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return sha256_hex(canonical_json_bytes(row))


def hash_governance_packet(rows: list[dict[str, Any]]) -> str:
    """Hash a list of governance_result dicts ordered by ``gate``."""
    return sha256_hex(canonical_json_bytes(rows))


def hash_portfolio_risk(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return sha256_hex(canonical_json_bytes(row))


def hash_ic1(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return sha256_hex(canonical_json_bytes(row))


def hash_a1(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return sha256_hex(canonical_json_bytes(row))


# ---------------------------------------------------------------------------
# Bundle helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionHashBundle:
    """The six hashes (or subset) that anchor a decision_artifact row.

    ``portfolio_risk_hash`` / ``ic1_hash`` / ``a1_hash`` are nullable
    per FR 20.1 §4.3 (e.g. non-material cases have no IC1 hash).
    """

    evidence_packet_hash: str
    synthesis_hash: str
    governance_packet_hash: str
    portfolio_risk_hash: str | None
    ic1_hash: str | None
    a1_hash: str | None


def compute_decision_hashes(
    *,
    evidence_rows: list[dict[str, Any]],
    synthesis_row: dict[str, Any],
    governance_rows: list[dict[str, Any]],
    portfolio_risk_row: dict[str, Any] | None = None,
    ic1_row: dict[str, Any] | None = None,
    a1_row: dict[str, Any] | None = None,
) -> DecisionHashBundle:
    """Single-call wrapper that produces the full :class:`DecisionHashBundle`."""
    return DecisionHashBundle(
        evidence_packet_hash=hash_evidence_packet(evidence_rows),
        synthesis_hash=sha256_hex(canonical_json_bytes(synthesis_row)),
        governance_packet_hash=hash_governance_packet(governance_rows),
        portfolio_risk_hash=hash_portfolio_risk(portfolio_risk_row),
        ic1_hash=hash_ic1(ic1_row),
        a1_hash=hash_a1(a1_row),
    )


__all__ = [
    "DecisionHashBundle",
    "canonical_json_bytes",
    "compute_decision_hashes",
    "hash_a1",
    "hash_evidence_packet",
    "hash_governance_packet",
    "hash_ic1",
    "hash_portfolio_risk",
    "hash_synthesis",
    "hash_value",
    "sha256_hex",
]
