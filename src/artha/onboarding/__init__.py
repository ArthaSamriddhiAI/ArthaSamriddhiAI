"""§10.3 — three onboarding paths (FORM / C0 / API).

Public surface:
  * `FormOnboardingHandler` — deterministic structured-form intake.
  * `C0OnboardingHandler` — LLM-backed conversational extraction with checkpoints.
  * `ApiOnboardingHandler` — bulk-API intake with MUST_RESPOND N0 confirmation.
  * `build_canonical_objects` — shared profile + mandate builder.
  * `OnboardingError` family — handler-specific exceptions.
"""

from artha.onboarding.canonical_api import (
    ApiOnboardingHandler,
    ApiSchemaValidationError,
    PendingApiConfirmation,
)
from artha.onboarding.canonical_c0 import (
    C0CheckpointNotConfirmedError,
    C0OnboardingHandler,
    C0OnboardingLLMUnavailableError,
)
from artha.onboarding.canonical_common import (
    OnboardingError,
    build_canonical_objects,
    emit_activation_event,
)
from artha.onboarding.canonical_form import (
    FormOnboardingHandler,
    StructuralFlagsNotConfirmedError,
)

__all__ = [
    "ApiOnboardingHandler",
    "ApiSchemaValidationError",
    "C0CheckpointNotConfirmedError",
    "C0OnboardingHandler",
    "C0OnboardingLLMUnavailableError",
    "FormOnboardingHandler",
    "OnboardingError",
    "PendingApiConfirmation",
    "StructuralFlagsNotConfirmedError",
    "build_canonical_objects",
    "emit_activation_event",
]
