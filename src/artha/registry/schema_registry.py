"""§15.13 — canonical schema registry.

Every T1-persisted payload carries a `schema_version` (via `VersionPins`)
captured at write time. To replay correctly across schema evolution the
replay path needs to deserialize that payload against the historical
Pydantic class — not the current one. The schema registry is the lookup
table that makes this possible.

Design (§15.13.3):

  * Each schema has a stable `name` (e.g. `"T1Event"`, `"N0Alert"`,
    `"LibrarianSession"`, `"E6Verdict"`).
  * Multiple semver-tagged Pydantic classes can be registered under the
    same name. `register(name, version, cls)` is additive and idempotent
    on the (name, version) tuple.
  * `lookup(name, version)` returns the registered class.
  * `validate(name, version, payload)` deserializes a dict into the
    correct historical schema and raises `SchemaNotRegisteredError` when
    no class matches.
  * `register_default()` populates the registry with the canonical
    classes shipped today; downstream registry consumers add their own
    historical classes via additional `register()` calls.

§15.13.6 replay correctness: the registry is the bridge between the
`schema_version` stored on a T1 event and the Pydantic class needed to
reconstruct it.

Backward-compatibility (§15.13.2): minor/patch versions are
backward-compatible. Major bumps register a new class under the same
schema name. `lookup_compatible(name, requested_version)` honors semver
fallback (find newest registered class with same major version) when
the exact (name, version) tuple isn't registered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from artha.common.errors import ArthaError

T = TypeVar("T", bound=BaseModel)


_SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class SchemaNotRegisteredError(ArthaError):
    """Raised when a (name, version) lookup misses the registry."""


class SchemaValidationError(ArthaError):
    """Raised when payload doesn't validate against the resolved schema class."""


class SchemaVersionFormatError(ArthaError):
    """Raised when a registered version isn't a valid semver triple."""


@dataclass(frozen=True)
class _RegistryKey:
    name: str
    version: str  # semver "major.minor.patch"


@dataclass(frozen=True)
class RegistryEntry:
    """One registered (name, version) → Pydantic class binding."""

    name: str
    version: str
    model_cls: type[BaseModel]


def _parse_semver(version: str) -> tuple[int, int, int]:
    match = _SEMVER_PATTERN.match(version)
    if match is None:
        raise SchemaVersionFormatError(
            f"version {version!r} is not a valid semver triple"
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


class SchemaRegistry:
    """§15.13 canonical schema registry.

    Use the module-level `DEFAULT_REGISTRY` for the canonical bindings;
    pass an instance explicitly when tests need isolation.
    """

    def __init__(self) -> None:
        self._entries: dict[_RegistryKey, type[BaseModel]] = {}

    # --------------------- Registration -----------------------------

    def register(
        self,
        *,
        name: str,
        version: str,
        model_cls: type[BaseModel],
        replace: bool = False,
    ) -> None:
        """Register a (name, version) → Pydantic class binding.

        `replace=False` (default) raises on collision so callers can't
        silently shadow an existing registration. Passing `replace=True`
        is meant for tests; production registrations should be additive.
        """
        _parse_semver(version)
        key = _RegistryKey(name=name, version=version)
        if not replace and key in self._entries:
            raise SchemaNotRegisteredError(
                f"schema ({name}, {version}) already registered; "
                "pass replace=True to override"
            )
        self._entries[key] = model_cls

    def register_default(self) -> None:
        """Populate with canonical schemas current at Pass 19.

        Called once on startup; subsequent passes wire historical schemas
        when breaking changes ship.
        """
        from artha.accountability.t1.models import T1Event
        from artha.canonical.cascade import (
            BucketRemappingEvent,
            L4CascadeRun,
            MandateAmendmentResult,
        )
        from artha.canonical.case import CaseObject
        from artha.canonical.channels import (
            C0ParseOutput,
            LibrarianSession,
        )
        from artha.canonical.construction import (
            BucketConstructionProposal,
            ConstructionRun,
        )
        from artha.canonical.evidence_verdict import (
            E1Verdict,
            E2Verdict,
            E3Verdict,
            E4Verdict,
            E5Verdict,
            E6Verdict,
            StandardEvidenceVerdict,
        )
        from artha.canonical.investor import InvestorContextProfile
        from artha.canonical.mandate import MandateAmendmentRequest, MandateObject
        from artha.canonical.model_portfolio import ModelPortfolioObject
        from artha.canonical.monitoring import (
            EX1Event,
            M1DriftReport,
            N0Alert,
            PM1Event,
            T2ReflectionRun,
        )
        from artha.canonical.onboarding import OnboardingResult
        from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
        from artha.canonical.views import (
            AdvisorCaseDetailView,
            AdvisorPerClientView,
            CIOConstructionApprovalView,
            CIOFirmDriftDashboard,
            ComplianceCaseReasoningTrail,
            ComplianceOverrideHistoryView,
        )

        defaults: list[tuple[str, type[BaseModel]]] = [
            # Core ledger
            ("T1Event", T1Event),
            # Investor + mandate + model portfolio
            ("InvestorContextProfile", InvestorContextProfile),
            ("MandateObject", MandateObject),
            ("MandateAmendmentRequest", MandateAmendmentRequest),
            ("ModelPortfolioObject", ModelPortfolioObject),
            # Case
            ("CaseObject", CaseObject),
            # Evidence verdicts
            ("StandardEvidenceVerdict", StandardEvidenceVerdict),
            ("E1Verdict", E1Verdict),
            ("E2Verdict", E2Verdict),
            ("E3Verdict", E3Verdict),
            ("E4Verdict", E4Verdict),
            ("E5Verdict", E5Verdict),
            ("E6Verdict", E6Verdict),
            # Synthesis + deliberation
            ("S1Synthesis", S1Synthesis),
            ("IC1Deliberation", IC1Deliberation),
            # Monitoring + reflection
            ("PM1Event", PM1Event),
            ("M1DriftReport", M1DriftReport),
            ("EX1Event", EX1Event),
            ("T2ReflectionRun", T2ReflectionRun),
            ("N0Alert", N0Alert),
            # Channels
            ("C0ParseOutput", C0ParseOutput),
            ("LibrarianSession", LibrarianSession),
            # Onboarding
            ("OnboardingResult", OnboardingResult),
            # Construction
            ("ConstructionRun", ConstructionRun),
            ("BucketConstructionProposal", BucketConstructionProposal),
            # Cascade
            ("L4CascadeRun", L4CascadeRun),
            ("MandateAmendmentResult", MandateAmendmentResult),
            ("BucketRemappingEvent", BucketRemappingEvent),
            # Views (Pass 18)
            ("AdvisorPerClientView", AdvisorPerClientView),
            ("AdvisorCaseDetailView", AdvisorCaseDetailView),
            ("CIOConstructionApprovalView", CIOConstructionApprovalView),
            ("CIOFirmDriftDashboard", CIOFirmDriftDashboard),
            ("ComplianceCaseReasoningTrail", ComplianceCaseReasoningTrail),
            ("ComplianceOverrideHistoryView", ComplianceOverrideHistoryView),
        ]
        for name, cls in defaults:
            self.register(name=name, version=DEFAULT_SCHEMA_VERSION, model_cls=cls)

    # --------------------- Lookup -----------------------------------

    def lookup(self, *, name: str, version: str) -> type[BaseModel]:
        """Strict lookup: exact (name, version) match required."""
        key = _RegistryKey(name=name, version=version)
        cls = self._entries.get(key)
        if cls is None:
            raise SchemaNotRegisteredError(
                f"no schema registered for ({name!r}, {version!r}); "
                f"available versions: {sorted(self.versions_for(name))}"
            )
        return cls

    def lookup_compatible(self, *, name: str, version: str) -> type[BaseModel]:
        """Semver-compatible lookup.

        Returns the exact match if present; else the newest registered
        version with the same major number; else raises.
        """
        try:
            return self.lookup(name=name, version=version)
        except SchemaNotRegisteredError:
            pass
        major, _, _ = _parse_semver(version)
        candidates = [
            (v, cls)
            for k, cls in self._entries.items()
            if k.name == name
            and (v := _parse_semver(k.version))[0] == major
        ]
        if not candidates:
            raise SchemaNotRegisteredError(
                f"no compatible schema for ({name!r}, {version!r}); "
                f"requested major={major} not present"
            )
        # Pick newest by tuple comparison
        _, cls = max(candidates, key=lambda pair: pair[0])
        return cls

    def versions_for(self, name: str) -> list[str]:
        """Return registered versions of a given schema name."""
        return [k.version for k in self._entries.keys() if k.name == name]

    def names(self) -> list[str]:
        """Return all registered schema names (deduplicated)."""
        return sorted({k.name for k in self._entries.keys()})

    def is_registered(self, *, name: str, version: str) -> bool:
        return _RegistryKey(name=name, version=version) in self._entries

    def all_entries(self) -> list[RegistryEntry]:
        """Return every registered binding (sorted by name then version)."""
        rows = [
            RegistryEntry(name=k.name, version=k.version, model_cls=cls)
            for k, cls in self._entries.items()
        ]
        return sorted(rows, key=lambda r: (r.name, _parse_semver(r.version)))

    # --------------------- Validation -------------------------------

    def validate(
        self,
        *,
        name: str,
        version: str,
        payload: dict[str, Any],
    ) -> BaseModel:
        """Deserialize `payload` against the registered (name, version) schema.

        Uses strict lookup first; callers wanting compatibility-window
        behaviour should call `lookup_compatible` themselves and pass the
        returned class to `model_validate` directly.
        """
        cls = self.lookup(name=name, version=version)
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise SchemaValidationError(
                f"payload failed validation against ({name}, {version}): {exc}"
            ) from exc


# Default version pin used by `register_default` — every canonical Pydantic
# class as it stands at Pass 19. Future passes that change a schema's wire
# shape register a new version under the same name.
DEFAULT_SCHEMA_VERSION = "1.0.0"


# Process-wide default registry. Tests should construct their own
# `SchemaRegistry()` to keep state isolated.
DEFAULT_REGISTRY = SchemaRegistry()


def populate_default_registry() -> SchemaRegistry:
    """Populate `DEFAULT_REGISTRY` with the canonical schemas. Idempotent.

    Call once on startup; subsequent calls re-register with `replace=True`
    so deployment hot-reload paths don't crash.
    """
    if not DEFAULT_REGISTRY._entries:
        DEFAULT_REGISTRY.register_default()
    return DEFAULT_REGISTRY


__all__ = [
    "DEFAULT_REGISTRY",
    "DEFAULT_SCHEMA_VERSION",
    "RegistryEntry",
    "SchemaNotRegisteredError",
    "SchemaRegistry",
    "SchemaValidationError",
    "SchemaVersionFormatError",
    "populate_default_registry",
]
