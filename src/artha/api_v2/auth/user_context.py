"""Authenticated user context.

Per FR Entry 17.0 §3.1 (application JWT claims) and FR Entry 17.2 §2 (the four
roles). The :class:`UserContext` is what every authenticated FastAPI route
receives via the :func:`get_current_user` dependency: a small immutable
object capturing user identity, firm membership, role, and session linkage.

Construction goes through :meth:`UserContext.from_jwt_claims` so that the
parsing rules live in one place. JWT signature validation happens upstream
(in :mod:`artha.api_v2.auth.jwt_signing`); this module trusts the claims it
receives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Role(str, Enum):
    """The four roles per FR Entry 17.2 §2.

    The values must match the strings used in IdP claims (or, for demo stage,
    the strings in ``dev/test_users.yaml``). Future role additions are additive.
    """

    ADVISOR = "advisor"
    CIO = "cio"
    COMPLIANCE = "compliance"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class UserContext:
    """The authenticated principal for a request.

    All fields originate from validated JWT claims (FR 17.0 §3.1); this object
    is constructed only after signature verification. Frozen to discourage
    mutation between dependency resolution and route handler execution.
    """

    user_id: str
    firm_id: str
    role: Role
    email: str
    name: str
    session_id: str

    @classmethod
    def from_jwt_claims(cls, claims: dict[str, Any]) -> "UserContext":
        """Parse a verified JWT claims dict into a :class:`UserContext`.

        Raises :class:`ValueError` if required claims are missing or the role
        value is not in the known :class:`Role` set. Callers (typically the
        :func:`get_current_user` dependency) translate this into HTTP 401.
        """
        try:
            user_id = claims["sub"]
            firm_id = claims["firm_id"]
            role_str = claims["role"]
            email = claims["email"]
            session_id = claims["session_id"]
        except KeyError as exc:
            raise ValueError(f"JWT missing required claim: {exc.args[0]}") from exc

        # Name falls back to email per FR 17.0 §2.2.
        name = claims.get("name") or email

        try:
            role = Role(role_str)
        except ValueError as exc:
            raise ValueError(f"JWT carries unknown role: {role_str!r}") from exc

        return cls(
            user_id=user_id,
            firm_id=firm_id,
            role=role,
            email=email,
            name=name,
            session_id=session_id,
        )
