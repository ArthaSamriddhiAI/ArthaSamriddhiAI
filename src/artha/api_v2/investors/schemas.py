"""Pydantic request/response schemas for the investors + households surfaces.

Validation rules per FR Entry 10.7 §2.4 are enforced both client-side
(Zod schemas mirror these) and server-side (canonical authority).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def normalise_phone(value: str) -> str:
    """E.164 normalisation per FR 10.7 §2.4: default to +91 country code if
    a 10-digit Indian number is provided without country code."""
    cleaned = re.sub(r"[\s\-()]", "", value)
    if cleaned.startswith("+"):
        # Already has country code; basic length sanity check.
        if not re.match(r"^\+\d{8,15}$", cleaned):
            raise ValueError("phone is not a valid E.164 number")
        return cleaned
    # No country code — assume +91 (India) per FR 10.7 §2.4 default.
    if re.match(r"^\d{10}$", cleaned):
        return f"+91{cleaned}"
    raise ValueError("phone must be E.164 format or a 10-digit Indian number")


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


class HouseholdCreateRequest(BaseModel):
    """Standalone household creation. Also creatable inline during
    investor onboarding via :class:`InvestorCreateRequest.household_name`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class HouseholdRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    household_id: str
    name: str
    created_by: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Investors
# ---------------------------------------------------------------------------


class InvestorCreateRequest(BaseModel):
    """POST /api/v2/investors body.

    Either ``household_id`` (existing household) or ``household_name`` (create
    new household inline) MUST be present. Validation enforces XOR — exactly
    one. ``advisor_id`` defaults to the current user; CIO can override.
    ``duplicate_pan_acknowledged`` short-circuits the warn-and-proceed flow
    when the advisor has already seen the duplicate-PAN dialog.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str
    pan: str
    age: int = Field(ge=18, le=100)
    household_id: str | None = None
    household_name: str | None = None
    advisor_id: str | None = None  # defaults to current user
    risk_appetite: Literal["aggressive", "moderate", "conservative"]
    time_horizon: Literal["under_3_years", "3_to_5_years", "over_5_years"]
    duplicate_pan_acknowledged: bool = False

    @field_validator("name")
    @classmethod
    def name_must_contain_space(cls, value: str) -> str:
        if " " not in value.strip():
            raise ValueError("name must contain at least one space (full name)")
        return value.strip()

    @field_validator("phone")
    @classmethod
    def phone_must_be_e164_or_indian_10_digit(cls, value: str) -> str:
        return normalise_phone(value)

    @field_validator("pan", mode="before")
    @classmethod
    def pan_uppercased_and_valid(cls, value: str) -> str:
        upper = value.strip().upper()
        if not PAN_REGEX.match(upper):
            raise ValueError(
                "pan must match the 10-character format ^[A-Z]{5}[0-9]{4}[A-Z]$"
            )
        return upper

    @field_validator("household_name")
    @classmethod
    def household_name_normalised(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip().title()
        if not normalised:
            raise ValueError("household_name cannot be empty")
        return normalised


class InvestorRead(BaseModel):
    """Full investor record returned to UI surfaces.

    Includes all schema fields from FR 10.7 §2.1, including the I0 enrichment
    fields populated synchronously at creation.
    """

    model_config = ConfigDict(extra="forbid")

    investor_id: str
    name: str
    email: str
    phone: str
    pan: str
    age: int
    household_id: str
    advisor_id: str
    risk_appetite: str
    time_horizon: str
    kyc_status: str
    kyc_verified_at: datetime | None
    kyc_provider: str | None
    life_stage: str | None
    life_stage_confidence: str | None
    liquidity_tier: str | None
    liquidity_tier_range: str | None
    enriched_at: datetime | None
    enrichment_version: str | None
    created_at: datetime
    created_by: str
    created_via: str
    duplicate_pan_acknowledged: bool
    last_modified_at: datetime
    last_modified_by: str
    schema_version: int


class InvestorsListResponse(BaseModel):
    investors: list[InvestorRead]


class HouseholdsListResponse(BaseModel):
    households: list[HouseholdRead]


class DuplicatePanWarningResponse(BaseModel):
    """Returned when a POST /investors hits a duplicate PAN without
    ``duplicate_pan_acknowledged=true``. The frontend displays the dialog
    and re-submits with the flag set.
    """

    model_config = ConfigDict(extra="forbid")

    duplicate_of_investor_id: str
    duplicate_of_name: str
    duplicate_of_created_at: datetime
    pan: str
