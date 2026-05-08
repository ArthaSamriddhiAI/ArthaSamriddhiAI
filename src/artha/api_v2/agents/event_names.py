"""T1 event-name constants for cluster 7 real-LLM runtime.

Per FR Entry 20.3 §5 (cluster 7 chunk 7.1 spec). Each event captures a
real-agent runtime occurrence — cache hit/miss, cache invalidation,
per-agent retry, persistent agent unavailability.

Cluster 7.2 ships the cache persistence; cache_hit / cache_miss /
cache_invalidated_* events are reserved here for forward-compatibility.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cache lifecycle (chunk 7.1 spec §5)
# ---------------------------------------------------------------------------

CACHE_HIT = "cache_hit"
CACHE_MISS = "cache_miss"
CACHE_INVALIDATED_EARNINGS = "cache_invalidated_earnings"
CACHE_INVALIDATED_MANUAL = "cache_invalidated_manual"
CACHE_INVALIDATED_TTL = "cache_invalidated_ttl"

# ---------------------------------------------------------------------------
# Real-agent dispatch lifecycle (chunk 7.1 spec §3.4 + §10)
# ---------------------------------------------------------------------------

#: Successful real-agent dispatch — companion to the cluster-5
#: ``stub_dispatched`` event. Emitted by the pipeline orchestrator
#: once the real shim returns a verdict.
REAL_AGENT_DISPATCHED = "real_agent_dispatched"

#: Schema validation failure on an LLM-produced output. Caller retries
#: per the cluster-7 retry policy.
AGENT_SCHEMA_VIOLATION = "agent_schema_violation"

#: Single retry of a real-agent dispatch. Emitted before each retry on
#: timeout / 5xx / schema / semantic failure.
AGENT_DISPATCH_RETRY = "agent_dispatch_retry"

#: All retries exhausted — the real-agent dispatch is permanently failing
#: for this case. Caller routes the case to ``failed`` per the
#: case_arch08_b pattern.
AGENT_UNAVAILABLE_PERSISTENT = "agent_unavailable_persistent"

#: Per-agent semantic validation rule failed (e.g. E1 verdict=positive
#: with a high-severity risk_signal). Wraps as a schema-violation-style
#: failure for retry handling.
AGENT_SEMANTIC_VIOLATION = "agent_semantic_violation"


__all__ = [
    "AGENT_DISPATCH_RETRY",
    "AGENT_SCHEMA_VIOLATION",
    "AGENT_SEMANTIC_VIOLATION",
    "AGENT_UNAVAILABLE_PERSISTENT",
    "CACHE_HIT",
    "CACHE_INVALIDATED_EARNINGS",
    "CACHE_INVALIDATED_MANUAL",
    "CACHE_INVALIDATED_TTL",
    "CACHE_MISS",
    "REAL_AGENT_DISPATCHED",
]
