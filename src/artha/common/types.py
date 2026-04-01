"""Domain-specific type aliases for identifiers used across the system.

All IDs are strings (UUIDs) for database portability and human readability.
"""

from __future__ import annotations

from typing import NewType

DecisionID = NewType("DecisionID", str)
ArtifactID = NewType("ArtifactID", str)
TraceNodeID = NewType("TraceNodeID", str)
RuleID = NewType("RuleID", str)
RuleSetVersionID = NewType("RuleSetVersionID", str)
AgentID = NewType("AgentID", str)
SnapshotID = NewType("SnapshotID", str)
IntentID = NewType("IntentID", str)
OrderID = NewType("OrderID", str)
ApprovalID = NewType("ApprovalID", str)
