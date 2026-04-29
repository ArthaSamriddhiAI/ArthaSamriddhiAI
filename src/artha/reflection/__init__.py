"""§13.8 — T2 reflection engine.

Public surface:
  * `ReflectionEngine` — monthly + event-triggered reflection runs.
"""

from artha.reflection.canonical_t2 import (
    CalibrationSample,
    ReflectionEngine,
    ReflectionScope,
    T2LLMUnavailableError,
)

__all__ = [
    "CalibrationSample",
    "ReflectionEngine",
    "ReflectionScope",
    "T2LLMUnavailableError",
]
