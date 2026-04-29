"""§11.7 — E6 PMS / AIF / SIF / MF Specialist agent.

E6 is the deepest sub-agent architecture in the system. The orchestrator
activates the relevant product-specific sub-agents based on case product
types, runs the structural-flag gate (deterministic), runs shared sub-agents
(fee normalisation, cascade engine, liquidity manager), and aggregates
everything into a final E6Verdict via RecommendationSynthesis.

Public surface:

  * `E6Orchestrator` — main service.
  * `E6Gate` — deterministic structural-flag gate (§11.7.1).
  * `E6ProductSubAgent` — base for product-specific sub-agents.
  * `compute_normalised_returns` / `compute_cascade_assessment` /
    `compute_liquidity_manager_output` — shared deterministic helpers.
"""

from artha.evidence.canonical_e6.gate import E6Gate, GateDecision
from artha.evidence.canonical_e6.orchestrator import (
    E6Orchestrator,
    E6OrchestratorInputs,
    RecommendationSynthesis,
)
from artha.evidence.canonical_e6.product_subagents import (
    PRODUCT_SUBAGENT_REGISTRY,
    AifCat1SubAgent,
    AifCat2SubAgent,
    AifCat3SubAgent,
    E6ProductSubAgent,
    MutualFundSubAgent,
    PmsSubAgent,
    SifSubAgent,
)
from artha.evidence.canonical_e6.shared_subagents import (
    compute_cascade_assessment,
    compute_liquidity_manager_output,
    compute_normalised_returns,
)

__all__ = [
    "AifCat1SubAgent",
    "AifCat2SubAgent",
    "AifCat3SubAgent",
    "E6Gate",
    "E6Orchestrator",
    "E6OrchestratorInputs",
    "E6ProductSubAgent",
    "GateDecision",
    "MutualFundSubAgent",
    "PRODUCT_SUBAGENT_REGISTRY",
    "PmsSubAgent",
    "RecommendationSynthesis",
    "SifSubAgent",
    "compute_cascade_assessment",
    "compute_liquidity_manager_output",
    "compute_normalised_returns",
]
