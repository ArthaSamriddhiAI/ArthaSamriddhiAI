"""Doc 2 §2.6 — RFC 7807 Problem Details envelope for `/api/v2/`.

Per Doc 2's locked answer:

  * `application/problem+json` content type for every error response.
  * Standard fields: `type`, `title`, `status`, `detail`, `instance`.
  * Custom extensions: `request_id`, `ex1_category`, `originating_component`,
    plus category-specific structured detail fields (e.g. `violations`,
    `missing_fields`).
  * HTTP status mapping: 400 / 401 / 403 / 404 / 409 / 422 / 429 / 500 / 503.

Endpoints raise `APIError` (or a subclass) on the failure path; the
`setup_exception_handlers(app)` registration converts these into
`application/problem+json` responses with the right status and shape.

EX1 categories per Doc 1 §13.9: `input_data_missing`, `schema_violation`,
`service_unavailable`, `component_conflict`, `timeout`,
`governance_rule_mismatch`, plus the API-layer additions
`rate_limit_exceeded` and `auth_failure`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


PROBLEM_CONTENT_TYPE = "application/problem+json"


# ---------------------------------------------------------------------------
# RFC 7807 envelope
# ---------------------------------------------------------------------------


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details + Doc 2 custom extensions.

    Pydantic shape used both for response serialisation and for typed
    construction inside endpoint code.
    """

    model_config = ConfigDict(extra="allow")  # allow category-specific keys

    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    instance: str | None = None

    # Doc 2 §2.6 custom extensions
    request_id: str | None = None
    ex1_category: str | None = None
    originating_component: str | None = None


# ---------------------------------------------------------------------------
# APIError exception family
# ---------------------------------------------------------------------------


class APIError(Exception):
    """Base for HTTP-mapped API errors. Render via `to_problem_details`."""

    default_status: int = 500
    default_type: str = "https://samriddhi.ai/errors/internal"
    default_title: str = "Internal server error"
    default_ex1_category: str | None = None

    def __init__(
        self,
        *,
        problem_type: str | None = None,
        title: str | None = None,
        status: int | None = None,
        detail: str = "",
        ex1_category: str | None = None,
        originating_component: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self.problem_type = problem_type or self.default_type
        self.title = title or self.default_title
        self.status = status or self.default_status
        self.detail = detail
        self.ex1_category = ex1_category or self.default_ex1_category
        self.originating_component = originating_component
        self.extensions: dict[str, Any] = dict(extensions or {})
        super().__init__(self.title)

    def to_problem_details(
        self,
        *,
        instance: str | None = None,
        request_id: str | None = None,
    ) -> ProblemDetails:
        return ProblemDetails(
            type=self.problem_type,
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=instance,
            request_id=request_id,
            ex1_category=self.ex1_category,
            originating_component=self.originating_component,
            **self.extensions,
        )


class BadRequestError(APIError):
    default_status = 400
    default_type = "https://samriddhi.ai/errors/bad-request"
    default_title = "Bad request"
    default_ex1_category = "input_data_missing"


class UnauthorizedError(APIError):
    default_status = 401
    default_type = "https://samriddhi.ai/errors/auth-required"
    default_title = "Authentication required"
    default_ex1_category = "auth_failure"


class ForbiddenError(APIError):
    default_status = 403
    default_type = "https://samriddhi.ai/errors/insufficient-permissions"
    default_title = "Insufficient permissions"
    default_ex1_category = "auth_failure"


class NotFoundError(APIError):
    default_status = 404
    default_type = "https://samriddhi.ai/errors/not-found"
    default_title = "Resource not found"


class ConflictError(APIError):
    default_status = 409
    default_type = "https://samriddhi.ai/errors/conflict"
    default_title = "Resource conflict"
    default_ex1_category = "component_conflict"


class UnprocessableEntityError(APIError):
    default_status = 422
    default_type = "https://samriddhi.ai/errors/unprocessable-entity"
    default_title = "Unprocessable entity"
    default_ex1_category = "schema_violation"


class RateLimitError(APIError):
    default_status = 429
    default_type = "https://samriddhi.ai/errors/rate-limit-exceeded"
    default_title = "Rate limit exceeded"
    default_ex1_category = "rate_limit_exceeded"


class ServiceUnavailableError(APIError):
    default_status = 503
    default_type = "https://samriddhi.ai/errors/service-unavailable"
    default_title = "Service unavailable"
    default_ex1_category = "service_unavailable"


# ---------------------------------------------------------------------------
# Response builder + handlers
# ---------------------------------------------------------------------------


def _problem_response(
    *,
    problem: ProblemDetails,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = problem.model_dump(mode="json", exclude_none=True)
    response = JSONResponse(
        content=payload,
        status_code=problem.status,
        media_type=PROBLEM_CONTENT_TYPE,
    )
    if headers:
        for k, v in headers.items():
            response.headers[k] = v
    if problem.request_id:
        response.headers["X-Request-ID"] = problem.request_id
    return response


def _request_id_from(request: Request) -> str | None:
    """Pull the X-Request-ID set by `RequestIDMiddleware` if present."""
    state_id = getattr(request.state, "request_id", None)
    if isinstance(state_id, str):
        return state_id
    header = request.headers.get("x-request-id")
    return header if isinstance(header, str) else None


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    problem = exc.to_problem_details(
        instance=request.url.path,
        request_id=_request_id_from(request),
    )
    return _problem_response(problem=problem)


async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI/Pydantic 422 → RFC 7807 envelope.

    Per Doc 2 §2.6 the 422 response body carries a `violations` array with
    the structured Pydantic validation errors so the frontend can render
    field-level error messages.
    """
    violations = []
    for err in exc.errors():
        violations.append(
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    problem = ProblemDetails(
        type="https://samriddhi.ai/errors/unprocessable-entity",
        title="Unprocessable entity",
        status=422,
        detail="Request payload failed validation.",
        instance=request.url.path,
        request_id=_request_id_from(request),
        ex1_category="schema_violation",
        violations=violations,
    )
    return _problem_response(problem=problem)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort 500 handler for any uncaught exception inside `/api/v2/`."""
    logger.exception("unhandled exception in api_v2: %s", exc)
    problem = ProblemDetails(
        type="https://samriddhi.ai/errors/internal",
        title="Internal server error",
        status=500,
        detail=(
            "An unexpected error occurred. The request_id is the foreign "
            "key into T1 for replay."
        ),
        instance=request.url.path,
        request_id=_request_id_from(request),
        ex1_category="service_unavailable",
    )
    return _problem_response(problem=problem)


def setup_exception_handlers(app: FastAPI) -> None:
    """Register the RFC 7807 handlers on a FastAPI app.

    Idempotent — re-registration replaces existing handlers.
    """
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


def with_extensions(error: APIError, **fields: Any) -> APIError:
    """Add category-specific structured fields to the error envelope."""
    error.extensions.update(fields)
    return error


__all__ = [
    "APIError",
    "BadRequestError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "PROBLEM_CONTENT_TYPE",
    "ProblemDetails",
    "RateLimitError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "api_error_handler",
    "request_validation_handler",
    "setup_exception_handlers",
    "unhandled_exception_handler",
    "with_extensions",
]
