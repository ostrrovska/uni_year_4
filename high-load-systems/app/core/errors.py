from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
_PROBLEM_TYPE_BASE = "https://cdn-control-plane.local/problems"

# Spelled out rather than taken from starlette.status: the constant for 422 was renamed
# mid-release-line and merely reading the old name emits a deprecation warning.
_UNPROCESSABLE = 422


def _serialisable_errors(exc: RequestValidationError) -> Any:
    """Render Pydantic's error list as JSON.

    Pydantic puts the original exception object into `ctx`, which is not JSON
    encodable — without this the error handler would itself raise, turning a 422 into
    an opaque 500 exactly when the client needs to know what it got wrong.
    """
    cleaned = []
    for error in exc.errors():
        entry = {key: value for key, value in error.items() if key != "ctx"}
        context = error.get("ctx")
        if context:
            entry["ctx"] = {key: str(value) for key, value in context.items()}
        cleaned.append(entry)
    return jsonable_encoder(cleaned)


class DomainError(Exception):
    """Base class for failures that map onto a defined HTTP response.

    Services raise these instead of HTTPException so that business logic stays
    free of transport concerns and remains reusable from scripts and workers.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    problem_type: str = "internal-error"
    title: str = "Internal Server Error"

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    problem_type = "resource-not-found"
    title = "Resource Not Found"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    problem_type = "state-conflict"
    title = "Conflicting Resource State"


class UnprocessableError(DomainError):
    status_code = _UNPROCESSABLE
    problem_type = "business-rule-violation"
    title = "Business Rule Violation"


class ServiceUnavailableError(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    problem_type = "service-unavailable"
    title = "Service Unavailable"


def problem_response(
    request: Request,
    *,
    status_code: int,
    problem_type: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build an RFC 9457 `application/problem+json` response."""
    body: dict[str, Any] = {
        "type": f"{_PROBLEM_TYPE_BASE}/{problem_type}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
    }
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["request_id"] = request_id
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_MEDIA_TYPE)


_STARLETTE_PROBLEM_TITLES = {
    status.HTTP_404_NOT_FOUND: ("resource-not-found", "Resource Not Found"),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("method-not-allowed", "Method Not Allowed"),
}


def register_exception_handlers(app: FastAPI) -> None:
    """Route every failure mode through the same problem+json shape.

    Validation errors are included deliberately: a client should not have to parse
    two different error formats depending on whether the failure was structural
    (422 from Pydantic) or a business rule (422 from a service).
    """

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return problem_response(
            request,
            status_code=exc.status_code,
            problem_type=exc.problem_type,
            title=exc.title,
            detail=exc.detail,
            extra=exc.extra or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request,
            status_code=_UNPROCESSABLE,
            problem_type="request-validation-failed",
            title="Request Validation Failed",
            detail="One or more request parameters are invalid.",
            extra={"errors": _serialisable_errors(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        problem_type, title = _STARLETTE_PROBLEM_TITLES.get(
            exc.status_code, ("http-error", "HTTP Error")
        )
        return problem_response(
            request,
            status_code=exc.status_code,
            problem_type=problem_type,
            title=title,
            detail=str(exc.detail),
        )
