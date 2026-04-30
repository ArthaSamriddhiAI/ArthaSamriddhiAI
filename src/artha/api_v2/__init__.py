"""Doc 2 — `/api/v2/` API surface.

Pass 1 ships the foundation:

  * Auth: JWT validation dependency, role/permission guards, UserContext
  * Errors: RFC 7807 ProblemDetails envelope + handlers
  * Middleware: X-Request-ID + traceparent capture
  * Idempotency: ORM table + replay store (the per-endpoint wiring lands
    in subsequent passes)
  * Rate limiting: slowapi Limiter + per-class decorators
  * Router: `/api/v2/` root with `/system/health` + `/auth/whoami` stubs

Subsequent passes mount sub-routers (auth, investors, mandates, ...) on
the v2 router via `create_v2_router()`.

Top-level entry point: `setup_api_v2(app)`. It wires every cross-cutting
piece onto a FastAPI app in a single call:

```python
from artha.api_v2 import setup_api_v2

def create_app() -> FastAPI:
    app = FastAPI(...)
    setup_api_v2(app)
    return app
```
"""

from fastapi import FastAPI

from artha.api_v2.auth import (
    JWTSigner,
    Permission,
    Role,
    UserContext,
    default_permissions_for,
    get_current_user,
    get_default_signer,
    require_permission,
    require_role,
    set_default_signer,
)
from artha.api_v2.errors import (
    APIError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ProblemDetails,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    UnprocessableEntityError,
    setup_exception_handlers,
)
from artha.api_v2.idempotency import (
    IdempotencyKeyMismatchError,
    IdempotencyKeyRow,
    IdempotencyStore,
)
from artha.api_v2.observability import (
    RequestIDMiddleware,
    is_valid_request_id,
    setup_observability,
)
from artha.api_v2.rate_limit import (
    get_limiter,
    heavy_mutation_limit,
    mutation_limit,
    read_limit,
    service_to_service_limit,
    setup_rate_limiting,
)
from artha.api_v2.router import V2_PREFIX, create_v2_router


def setup_api_v2(app: FastAPI) -> None:
    """Wire all `/api/v2/` cross-cutting concerns onto a FastAPI app.

    Order matters:
      1. Exception handlers FIRST so they catch errors raised by deps
         (auth, rate limiting) downstream.
      2. Rate limiter SECOND so it registers its own 429 handler.
      3. Observability middleware THIRD so request_id is set before any
         endpoint runs (and exception handlers can read it).
      4. v2 router LAST.
    """
    setup_exception_handlers(app)
    setup_rate_limiting(app)
    setup_observability(app)
    app.include_router(create_v2_router())


__all__ = [
    "APIError",
    "BadRequestError",
    "ConflictError",
    "ForbiddenError",
    "IdempotencyKeyMismatchError",
    "IdempotencyKeyRow",
    "IdempotencyStore",
    "JWTSigner",
    "NotFoundError",
    "Permission",
    "ProblemDetails",
    "RateLimitError",
    "RequestIDMiddleware",
    "Role",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "UserContext",
    "V2_PREFIX",
    "create_v2_router",
    "default_permissions_for",
    "get_current_user",
    "get_default_signer",
    "get_limiter",
    "heavy_mutation_limit",
    "is_valid_request_id",
    "mutation_limit",
    "read_limit",
    "require_permission",
    "require_role",
    "service_to_service_limit",
    "set_default_signer",
    "setup_api_v2",
    "setup_exception_handlers",
    "setup_observability",
    "setup_rate_limiting",
]
