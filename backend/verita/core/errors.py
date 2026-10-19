"""RFC 9457 problem+json errors.

Every error response has the same shape. Unexpected exceptions are logged with their traceback
and returned as a generic 500 — exception text never reaches the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from verita.core.logging import get_logger, request_id_var

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_BASE = "https://verita.dev/problems/"

log = get_logger("verita.errors")


class AppError(Exception):
    """An expected failure with a stable, client-safe description."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.extra = extra or {}


def problem(
    status: int,
    slug: str,
    title: str,
    *,
    detail: str | None = None,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": _TYPE_BASE + slug, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    request_id = request_id_var.get()
    if request_id is not None:
        body["request_id"] = request_id
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_MEDIA_TYPE)


_STATUS_SLUGS = {
    400: ("bad-request", "Bad request"),
    401: ("unauthenticated", "Authentication required"),
    403: ("forbidden", "Not allowed"),
    404: ("not-found", "Not found"),
    405: ("method-not-allowed", "Method not allowed"),
    409: ("conflict", "Conflict"),
    429: ("rate-limited", "Too many requests"),
}


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - registration guarantees it
        raise TypeError(exc)
    return problem(
        exc.status,
        exc.slug,
        exc.title,
        detail=exc.detail,
        instance=request.url.path,
        extra=exc.extra,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - registration guarantees it
        raise TypeError(exc)
    slug, title = _STATUS_SLUGS.get(exc.status_code, ("http-error", "Request failed"))
    return problem(exc.status_code, slug, title, instance=request.url.path)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - registration guarantees it
        raise TypeError(exc)
    errors = [
        {"loc": [str(part) for part in err.get("loc", ())], "msg": str(err.get("msg", ""))}
        for err in exc.errors()
    ]
    return problem(
        422,
        "validation-error",
        "Request validation failed",
        instance=request.url.path,
        extra={"errors": errors},
    )


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, method=request.method)
    return problem(
        500,
        "internal-error",
        "Internal server error",
        detail="The error was logged. Quote the request_id when reporting it.",
        instance=request.url.path,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
