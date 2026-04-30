"""Doc 2 §2.8 — `slowapi` token-bucket rate limiting for `/api/v2/`.

Four rate-limit classes per Doc 2:

  * `read`           — 60 requests/minute per user
  * `mutation`       — 10 requests/minute per user
  * `heavy_mutation` — 3 requests/minute per user (case execution, T2 runs,
    briefing generation, large file uploads)
  * `service_to_service` — 600 requests/minute per service identity

Each defines a `Rate` string (e.g. `"60/minute"`) plus a decorator factory
that endpoints attach to their handler:

```python
@router.get("/foo")
@read_limit
async def foo(...):
    ...
```

The keying function uses the authenticated user's `user_id` (read from
`request.state.user`, set by the auth dependency). For unauthenticated
endpoints the limiter falls back to remote IP per slowapi's default; this
is fine for `/auth/login` and `/auth/callback` where per-user keying isn't
yet possible.

Rate-limit-exceeded responses produce HTTP 429 with the standard
`Retry-After` header and an RFC 7807 problem body (handled by
`api_v2.errors.RateLimitError`). slowapi's default exception is wired
through `setup_rate_limiting` into our envelope handler.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from artha.api_v2.errors import (
    PROBLEM_CONTENT_TYPE,
    ProblemDetails,
    _request_id_from,
)

# Working defaults — configurable per deployment via env vars later.
DEFAULT_RATE_READ = "60/minute"
DEFAULT_RATE_MUTATION = "10/minute"
DEFAULT_RATE_HEAVY = "3/minute"
DEFAULT_RATE_SERVICE = "600/minute"


# ---------------------------------------------------------------------------
# Keying
# ---------------------------------------------------------------------------


def user_or_ip_key(request: Request) -> str:
    """Key by `user_id` if authenticated; else fall back to remote IP.

    The auth dependency sets `request.state.user` with a `UserContext`. If
    middleware has already validated the token (the normal case), this
    returns the user's id. If not (unauthenticated endpoints, or a request
    that bypasses auth), we fall back to the IP address.
    """
    user = getattr(request.state, "user", None)
    if user is not None:
        # Compose with firm_id so a malicious user can't hijack another
        # firm's quota by user_id collision.
        return f"user:{user.firm_id}:{user.user_id}"
    return f"ip:{get_remote_address(request)}"


# ---------------------------------------------------------------------------
# Limiter instance
# ---------------------------------------------------------------------------


_limiter: Limiter | None = None


def get_limiter() -> Limiter:
    """Lazy-initialised process-wide `Limiter`. Reset via `set_limiter`."""
    global _limiter
    if _limiter is None:
        _limiter = Limiter(key_func=user_or_ip_key, headers_enabled=True)
    return _limiter


def set_limiter(limiter: Limiter | None) -> None:
    """Test-only: replace the process-wide limiter (or reset to lazy default)."""
    global _limiter
    _limiter = limiter


# ---------------------------------------------------------------------------
# Per-class decorators
# ---------------------------------------------------------------------------


def read_limit(rate: str = DEFAULT_RATE_READ) -> Callable[..., Any]:
    """Decorator for read endpoints. Default: 60/min."""
    return get_limiter().limit(rate)


def mutation_limit(rate: str = DEFAULT_RATE_MUTATION) -> Callable[..., Any]:
    """Decorator for standard write endpoints. Default: 10/min."""
    return get_limiter().limit(rate)


def heavy_mutation_limit(rate: str = DEFAULT_RATE_HEAVY) -> Callable[..., Any]:
    """Decorator for expensive mutations (case run, T2 run, briefing gen). Default: 3/min."""
    return get_limiter().limit(rate)


def service_to_service_limit(rate: str = DEFAULT_RATE_SERVICE) -> Callable[..., Any]:
    """Decorator for cron / webhook ingress endpoints. Default: 600/min per service."""
    return get_limiter().limit(rate)


# ---------------------------------------------------------------------------
# Exception handler — RFC 7807 envelope
# ---------------------------------------------------------------------------


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Convert slowapi's `RateLimitExceeded` to RFC 7807 envelope."""
    retry_after = getattr(exc, "retry_after", None)
    if hasattr(exc, "detail"):
        detail_text = f"Rate limit exceeded: {exc.detail}"
    else:
        detail_text = "Rate limit exceeded."
    problem = ProblemDetails(
        type="https://samriddhi.ai/errors/rate-limit-exceeded",
        title="Rate limit exceeded",
        status=429,
        detail=detail_text,
        instance=request.url.path,
        request_id=_request_id_from(request),
        ex1_category="rate_limit_exceeded",
    )
    response = JSONResponse(
        content=problem.model_dump(mode="json", exclude_none=True),
        status_code=429,
        media_type=PROBLEM_CONTENT_TYPE,
    )
    if retry_after is not None:
        response.headers["Retry-After"] = str(int(retry_after))
    if problem.request_id:
        response.headers["X-Request-ID"] = problem.request_id
    return response


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_rate_limiting(app: FastAPI) -> Limiter:
    """Wire the limiter + the RFC 7807 429 handler onto a FastAPI app.

    Returns the `Limiter` instance so callers can attach further
    endpoint-specific limits if needed.
    """
    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    return limiter


__all__ = [
    "DEFAULT_RATE_HEAVY",
    "DEFAULT_RATE_MUTATION",
    "DEFAULT_RATE_READ",
    "DEFAULT_RATE_SERVICE",
    "get_limiter",
    "heavy_mutation_limit",
    "mutation_limit",
    "rate_limit_handler",
    "read_limit",
    "service_to_service_limit",
    "set_limiter",
    "setup_rate_limiting",
    "user_or_ip_key",
]
