"""Doc 2 §2.9 — request-ID + W3C Trace Context middleware.

Every request through `/api/v2/*` carries an `X-Request-ID`:

  * If supplied by the client and matches a valid ULID/UUID format, it's
    honoured.
  * Otherwise the server generates a fresh ULID.

The request_id is then:

  * Stored on `request.state.request_id` so handlers + error envelopes can
    read it.
  * Echoed in the `X-Request-ID` response header.
  * Logged in every T1 event the request produces (downstream wiring).

The middleware also captures the W3C Trace Context `traceparent` header
when present and stores it on `request.state.traceparent`. v2.0 doesn't
actively use distributed tracing yet; this is forward-compat plumbing so
adding Jaeger/Honeycomb later is configuration, not code.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from artha.common.ulid import new_ulid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request-ID validators
# ---------------------------------------------------------------------------


# ULID: Crockford base32, 26 chars, [0-9A-HJKMNP-TV-Z]. Generous matcher.
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# W3C Trace Context: `version-trace_id-parent_id-flags`
# version: 2 hex; trace_id: 32 hex; parent_id: 16 hex; flags: 2 hex
_TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)


def is_valid_request_id(candidate: str) -> bool:
    """Accept ULID or UUID format; reject everything else."""
    if not candidate or len(candidate) > 64:
        return False
    return bool(_ULID_RE.match(candidate) or _UUID_RE.match(candidate))


def is_valid_traceparent(candidate: str) -> bool:
    return bool(candidate and _TRACEPARENT_RE.match(candidate))


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Read or generate `X-Request-ID`; capture `traceparent` if present.

    Sets `request.state.request_id` and `request.state.traceparent`. Adds
    `X-Request-ID` to every response (including ones produced by the
    `/api/v2/` exception handlers — see `errors.py`).
    """

    def __init__(self, app: ASGIApp, *, header_name: str = "x-request-id") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get(self._header_name)
        if supplied and is_valid_request_id(supplied):
            request_id = supplied
        else:
            if supplied:
                logger.debug("dropping malformed X-Request-ID header: %r", supplied)
            request_id = new_ulid()

        request.state.request_id = request_id

        traceparent = request.headers.get("traceparent")
        if traceparent and is_valid_traceparent(traceparent):
            request.state.traceparent = traceparent
        else:
            request.state.traceparent = None

        response = await call_next(request)

        # Always set the response header — even on error responses (the
        # exception handlers in errors.py also set this for their own
        # branches; this middleware path handles the success and the
        # exception-handler-fallback case where headers may not be set).
        response.headers[self._header_name] = request_id
        return response


def setup_observability(app: FastAPI) -> None:
    """Install request-id middleware on the app. Idempotent at call site."""
    app.add_middleware(RequestIDMiddleware)


__all__ = [
    "RequestIDMiddleware",
    "is_valid_request_id",
    "is_valid_traceparent",
    "setup_observability",
]
