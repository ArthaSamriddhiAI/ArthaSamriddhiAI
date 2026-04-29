"""§12 — synthesis layer: S1 (master synthesis) + IC1 (investment committee).

S1 reads E1–E6 evidence verdicts and produces a unified `S1Synthesis`.
IC1 then reads case + S1 to produce `IC1Deliberation` (materiality gate +
four LLM-backed sub-roles).

Public surface:

  * `S1SynthesisAgent` — master synthesis (§12.2).
  * `IC1Agent` — investment committee deliberation (§12.3).
  * `IC1MaterialityGate` — deterministic materiality gate (§12.3.2).
"""

from artha.synthesis.canonical_ic1 import (
    IC1Agent,
    IC1MaterialityGate,
    MaterialityInputs,
)
from artha.synthesis.canonical_s1 import S1SynthesisAgent

__all__ = [
    "IC1Agent",
    "IC1MaterialityGate",
    "MaterialityInputs",
    "S1SynthesisAgent",
]
