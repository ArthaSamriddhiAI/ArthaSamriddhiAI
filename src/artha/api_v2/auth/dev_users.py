"""YAML-backed test user catalogue for the demo-stage stub auth.

Per Cluster 0 Dev-Mode Addendum §3.1. The YAML lives at the path configured
by :data:`settings.dev_test_users_path` (defaults to ``dev/test_users.yaml``).
Production-readiness phase removes this module along with the dev-login
endpoint; the YAML is replaced by the firm's real OIDC IdP.

The loader is module-level cached: the YAML is read once on first access. In
demo stage the file changes infrequently (when adding/renaming test users),
so the cache is acceptable. Tests that mutate the catalogue can call
:func:`reload` to flush.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from artha.api_v2.auth.user_context import Role
from artha.config import settings


@dataclass(frozen=True, slots=True)
class DemoFirm:
    """Static firm config for demo stage. Only one firm exists in this mode."""

    firm_id: str
    firm_name: str
    firm_display_name: str
    primary_color: str
    accent_color: str
    logo_url: str
    regulatory_jurisdiction: str


@dataclass(frozen=True, slots=True)
class DemoUser:
    """One test user from the YAML."""

    user_id: str
    email: str
    name: str
    role: Role


@dataclass(frozen=True, slots=True)
class DemoCatalogue:
    """Combined firm + users payload."""

    firm: DemoFirm
    users: tuple[DemoUser, ...]

    def find_user(self, user_id: str) -> DemoUser | None:
        for u in self.users:
            if u.user_id == user_id:
                return u
        return None


_cache: DemoCatalogue | None = None


def _load_from_disk() -> DemoCatalogue:
    path = Path(settings.dev_test_users_path)
    if not path.exists():
        raise FileNotFoundError(
            f"dev_test_users_path does not exist: {path.resolve()}. "
            "Cluster 0 stub auth requires this YAML; see Dev-Mode Addendum §3.1."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    firm_raw = raw["firm"]
    firm = DemoFirm(
        firm_id=firm_raw["firm_id"],
        firm_name=firm_raw["firm_name"],
        firm_display_name=firm_raw["firm_display_name"],
        primary_color=firm_raw["primary_color"],
        accent_color=firm_raw["accent_color"],
        logo_url=firm_raw["logo_url"],
        regulatory_jurisdiction=firm_raw["regulatory_jurisdiction"],
    )
    users = tuple(
        DemoUser(
            user_id=u["user_id"],
            email=u["email"],
            name=u["name"],
            role=Role(u["role"]),
        )
        for u in raw.get("users", [])
    )
    return DemoCatalogue(firm=firm, users=users)


def get_catalogue() -> DemoCatalogue:
    """Return the cached YAML catalogue, loading it lazily on first call."""
    global _cache
    if _cache is None:
        _cache = _load_from_disk()
    return _cache


def reload() -> DemoCatalogue:
    """Re-read the YAML from disk, replacing the cache. Test helper."""
    global _cache
    _cache = _load_from_disk()
    return _cache
