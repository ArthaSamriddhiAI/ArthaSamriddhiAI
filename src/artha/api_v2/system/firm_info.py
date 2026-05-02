"""``GET /api/v2/system/firm-info`` — per-firm runtime configuration.

Per Cluster 0 chunk plan §scope_in and Dev-Mode Addendum §3.5.

Returns the firm's identity + branding + feature flags + regulatory
jurisdiction, sourced from the YAML demo catalogue in cluster 0. Production
deployment swaps the source for per-deployment env config; the response shape
is unchanged so the React app's CSS-variable wiring (`--color-primary` etc.)
keeps working without code changes.

Defence-in-depth firm-id check: per addendum §3.5, a JWT carrying a
``firm_id`` that doesn't match the deployment's configured firm is rejected
with 403. With stub auth this can never happen (only one firm exists), but
the validation is preserved here so the production integration inherits it
for free.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from artha.api_v2.auth.dev_users import get_catalogue
from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext

router = APIRouter(prefix="/api/v2/system", tags=["system"])


class BrandingInfo(BaseModel):
    """Firm-level branding written into CSS variables on auth completion."""

    model_config = ConfigDict(extra="forbid")

    primary_color: str
    accent_color: str
    logo_url: str


class FirmInfo(BaseModel):
    """Public firm configuration returned to the authenticated SPA."""

    model_config = ConfigDict(extra="forbid")

    firm_id: str
    firm_name: str
    firm_display_name: str
    branding: BrandingInfo
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    regulatory_jurisdiction: str


@router.get(
    "/firm-info",
    response_model=FirmInfo,
    summary="Per-firm runtime configuration for the authenticated SPA",
)
async def firm_info(
    user: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_FIRM_INFO_READ)),
    ],
) -> FirmInfo:
    """Return the firm config for the authenticated user's deployment.

    Validates that the user's JWT ``firm_id`` matches the deployment's
    configured firm; mismatches return 403 (defence-in-depth — stub auth
    can't trigger this, but the production OIDC path inherits the check).
    """
    catalogue = get_catalogue()
    if user.firm_id != catalogue.firm.firm_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"JWT firm_id={user.firm_id!r} does not match "
                f"deployment firm_id={catalogue.firm.firm_id!r}."
            ),
        )

    firm = catalogue.firm
    return FirmInfo(
        firm_id=firm.firm_id,
        firm_name=firm.firm_name,
        firm_display_name=firm.firm_display_name,
        branding=BrandingInfo(
            primary_color=firm.primary_color,
            accent_color=firm.accent_color,
            logo_url=firm.logo_url,
        ),
        feature_flags={},  # Cluster 0 placeholder per chunk plan.
        regulatory_jurisdiction=firm.regulatory_jurisdiction,
    )
