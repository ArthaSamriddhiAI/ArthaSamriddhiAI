"""Pydantic request/response schemas for the M1 mandate surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from artha.api_v2.m1.i0_defaults import MandateDefaults

CreatedVia = Literal["form", "conversational", "api", "pdf"]
MandateStatus = Literal[
    "draft", "pending_approval", "active", "archived", "rejected"
]


# ---------------------------------------------------------------------------
# Constraint-input mixin (per-field range checks)
# ---------------------------------------------------------------------------


class MandateConstraintInput(BaseModel):
    """The five constraint families on the wire from advisor → server.

    Per-field range / type checks live here; cross-constraint rules
    (sum-of-mins, max>=min) live in :mod:`artha.api_v2.m1.validation`
    because they span multiple fields.
    """

    model_config = ConfigDict(extra="forbid")

    # Asset allocation bands (FR 12.1 §2.2)
    equity_min_pct: int = Field(ge=0, le=100)
    equity_max_pct: int = Field(ge=0, le=100)
    debt_min_pct: int = Field(ge=0, le=100)
    debt_max_pct: int = Field(ge=0, le=100)
    alternatives_min_pct: int = Field(ge=0, le=100)
    alternatives_max_pct: int = Field(ge=0, le=100)

    # Single-position concentration (FR 12.1 §3.2)
    single_position_max_pct: int = Field(ge=0, le=100)

    # Liquidity floor (FR 12.1 §4.2)
    liquidity_floor_pct: int = Field(ge=0, le=100)

    # Sector cap (FR 12.1 §5.2)
    sector_max_pct: int = Field(ge=0, le=100)

    # Prohibited list (FR 12.1 §6.2 — max 50 strings, each 1-200 chars)
    prohibited_instruments: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("prohibited_instruments")
    @classmethod
    def _strip_and_check_each_item(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            stripped = item.strip()
            if not stripped:
                continue
            if len(stripped) > 200:
                raise ValueError(
                    "prohibited_instruments items must be 1-200 characters"
                )
            cleaned.append(stripped)
        return cleaned


# ---------------------------------------------------------------------------
# Create / read shapes
# ---------------------------------------------------------------------------


class MandateCreateRequest(MandateConstraintInput):
    """``POST /api/v2/investors/{investor_id}/mandate`` body."""


class MandateVersionRead(BaseModel):
    """Read shape for a single :class:`MandateVersion` row."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    mandate_id: str
    version_number: int
    status: MandateStatus

    # Constraint families
    equity_min_pct: int
    equity_max_pct: int
    debt_min_pct: int
    debt_max_pct: int
    alternatives_min_pct: int
    alternatives_max_pct: int
    single_position_max_pct: int
    liquidity_floor_pct: int
    sector_max_pct: int
    prohibited_instruments: list[str]

    # Provenance
    created_at: datetime
    created_by: str
    created_via: CreatedVia
    parent_version_id: str | None

    # Approval workflow (lazily populated)
    proposed_at: datetime | None
    proposed_by: str | None
    approved_at: datetime | None
    approved_by: str | None
    rejected_at: datetime | None
    rejected_by: str | None
    rejection_reason: str | None
    approval_comments: str | None
    changes_requested_at: datetime | None
    changes_requested_by: str | None
    changes_requested_comments: str | None

    # Activation
    activated_at: datetime | None
    archived_at: datetime | None


class MandateRead(BaseModel):
    """Read shape for a :class:`Mandate` row + its active version."""

    model_config = ConfigDict(extra="forbid")

    mandate_id: str
    investor_id: str
    active_version_id: str | None
    active_version: MandateVersionRead | None
    created_at: datetime
    created_by: str
    schema_version: int


class MandateVersionsListResponse(BaseModel):
    """Read shape for ``GET .../mandate/versions``."""

    versions: list[MandateVersionRead]


# ---------------------------------------------------------------------------
# Soft warnings (returned alongside successful creates / on dry-run validation)
# ---------------------------------------------------------------------------


class SoftWarningRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    code: str
    message: str


class MandateCreateResponse(BaseModel):
    """``POST .../mandate`` 201 envelope: the active mandate + any soft warnings."""

    model_config = ConfigDict(extra="forbid")

    mandate: MandateRead
    warnings: list[SoftWarningRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Defaults endpoint (form-path pre-population)
# ---------------------------------------------------------------------------


class MandateDefaultsRead(BaseModel):
    """Read shape for ``GET .../mandate/defaults``.

    ``sources`` parallels each constraint field with the I0 / industry-
    standard provenance string the UI shows alongside the input.
    """

    model_config = ConfigDict(extra="forbid")

    equity_min_pct: int
    equity_max_pct: int
    debt_min_pct: int
    debt_max_pct: int
    alternatives_min_pct: int
    alternatives_max_pct: int
    single_position_max_pct: int
    liquidity_floor_pct: int
    sector_max_pct: int
    prohibited_instruments: list[str]
    sources: dict[str, str]
    risk_appetite: str | None
    liquidity_tier: str | None

    @classmethod
    def from_defaults(
        cls,
        defaults: MandateDefaults,
        *,
        risk_appetite: str | None,
        liquidity_tier: str | None,
    ) -> MandateDefaultsRead:
        return cls(
            equity_min_pct=defaults.equity_min_pct,
            equity_max_pct=defaults.equity_max_pct,
            debt_min_pct=defaults.debt_min_pct,
            debt_max_pct=defaults.debt_max_pct,
            alternatives_min_pct=defaults.alternatives_min_pct,
            alternatives_max_pct=defaults.alternatives_max_pct,
            single_position_max_pct=defaults.single_position_max_pct,
            liquidity_floor_pct=defaults.liquidity_floor_pct,
            sector_max_pct=defaults.sector_max_pct,
            prohibited_instruments=list(defaults.prohibited_instruments),
            sources=dict(defaults.sources),
            risk_appetite=risk_appetite,
            liquidity_tier=liquidity_tier,
        )
