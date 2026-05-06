"""Cluster 5 chunk 5.1 — decision-artifact hash service tests.

Pins FR Entry 20.1 §4.3 + FR 20.4 §3 hash spec:

- Canonical-JSON deterministic encoding.
- Six hashes (or subset) for the decision artifact.
- Re-computing hashes from persisted records produces identical values
  (replayability — the audit-replay anchor).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from artha.api_v2.cases.hashing import (
    canonical_json_bytes,
    compute_decision_hashes,
    hash_a1,
    hash_evidence_packet,
    hash_governance_packet,
    hash_ic1,
    hash_portfolio_risk,
    hash_synthesis,
    hash_value,
    sha256_hex,
)


class TestCanonicalJSON:
    def test_keys_are_sorted(self):
        a = canonical_json_bytes({"b": 1, "a": 2})
        b = canonical_json_bytes({"a": 2, "b": 1})
        assert a == b

    def test_no_whitespace(self):
        out = canonical_json_bytes({"a": 1, "b": [1, 2, 3]})
        assert b" " not in out
        assert b"\n" not in out

    def test_datetime_falls_back_to_str(self):
        ts = datetime(2026, 5, 6, 10, 0, 0, tzinfo=timezone.utc)
        out = canonical_json_bytes({"at": ts})
        assert b"2026-05-06" in out

    def test_decimal_falls_back_to_str(self):
        out = canonical_json_bytes({"amount": Decimal("12345.67")})
        assert b"12345.67" in out


class TestHashStability:
    def test_same_value_same_hash(self):
        a = hash_value({"a": 1, "b": 2})
        b = hash_value({"b": 2, "a": 1})
        assert a == b

    def test_different_values_different_hashes(self):
        a = hash_value({"a": 1})
        b = hash_value({"a": 2})
        assert a != b

    def test_sha256_hex_format(self):
        h = sha256_hex(b"hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestStageHashes:
    def test_evidence_packet_hash_is_order_dependent(self):
        # Caller is responsible for ordering by (agent_id, produced_at).
        ordered = [{"agent_id": "e1"}, {"agent_id": "e2"}]
        reversed_order = list(reversed(ordered))
        assert hash_evidence_packet(ordered) != hash_evidence_packet(reversed_order)

    def test_synthesis_none_returns_none(self):
        assert hash_synthesis(None) is None

    def test_governance_packet_hashed(self):
        rows = [
            {"gate": "g1_mandate", "outcome": "approved"},
            {"gate": "g2_sebi_regulatory", "outcome": "approved"},
        ]
        assert len(hash_governance_packet(rows)) == 64

    def test_portfolio_risk_optional(self):
        assert hash_portfolio_risk(None) is None
        assert len(hash_portfolio_risk({"overall": "low"})) == 64

    def test_ic1_optional(self):
        assert hash_ic1(None) is None
        assert len(hash_ic1({"recommendation": "proceed"})) == 64

    def test_a1_optional(self):
        assert hash_a1(None) is None
        assert len(hash_a1({"counter_arguments": []})) == 64


class TestComputeDecisionHashes:
    def test_full_bundle(self):
        bundle = compute_decision_hashes(
            evidence_rows=[{"agent_id": "e1", "verdict": "ok"}],
            synthesis_row={"recommendation": "proceed"},
            governance_rows=[
                {"gate": "g1_mandate", "outcome": "approved"},
            ],
            portfolio_risk_row={"overall": "low"},
            ic1_row={"recommendation": "proceed"},
            a1_row={"counter_arguments": []},
        )
        assert all(
            len(h) == 64
            for h in (
                bundle.evidence_packet_hash,
                bundle.synthesis_hash,
                bundle.governance_packet_hash,
                bundle.portfolio_risk_hash,
                bundle.ic1_hash,
                bundle.a1_hash,
            )
        )

    def test_non_material_omits_ic1(self):
        bundle = compute_decision_hashes(
            evidence_rows=[{"agent_id": "e1"}],
            synthesis_row={"recommendation": "proceed"},
            governance_rows=[{"gate": "g1_mandate", "outcome": "approved"}],
            portfolio_risk_row={"overall": "low"},
            ic1_row=None,
            a1_row={"counter_arguments": []},
        )
        assert bundle.ic1_hash is None
        assert bundle.a1_hash is not None

    def test_replay_stability(self):
        # Re-computing from the same inputs produces the same hashes.
        kwargs = dict(
            evidence_rows=[{"agent_id": "e1", "verdict": "ok"}],
            synthesis_row={"recommendation": "proceed"},
            governance_rows=[{"gate": "g1_mandate", "outcome": "approved"}],
        )
        h1 = compute_decision_hashes(**kwargs)
        h2 = compute_decision_hashes(**kwargs)
        assert h1 == h2

    def test_tampering_changes_hash(self):
        original = compute_decision_hashes(
            evidence_rows=[{"agent_id": "e1", "verdict": "ok"}],
            synthesis_row={"recommendation": "proceed"},
            governance_rows=[{"gate": "g1_mandate", "outcome": "approved"}],
        )
        tampered = compute_decision_hashes(
            evidence_rows=[{"agent_id": "e1", "verdict": "tampered"}],
            synthesis_row={"recommendation": "proceed"},
            governance_rows=[{"gate": "g1_mandate", "outcome": "approved"}],
        )
        assert original.evidence_packet_hash != tampered.evidence_packet_hash
        # synthesis + governance are unchanged → those hashes match.
        assert original.synthesis_hash == tampered.synthesis_hash
        assert original.governance_packet_hash == tampered.governance_packet_hash
