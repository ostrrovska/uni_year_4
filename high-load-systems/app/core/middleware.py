import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.instance import get_instance_id

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
INSTANCE_ID_HEADER = "X-Instance-ID"
RESPONSE_TIME_HEADER = "X-Response-Time-ms"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach per-request correlation data and emit one structured access line.

    All state here lives on the request object and dies with it — nothing is stored
    on the middleware instance, which is what keeps the app horizontally scalable.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request.failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[INSTANCE_ID_HEADER] = get_instance_id()
        response.headers[RESPONSE_TIME_HEADER] = str(duration_ms)

        logger.info(
            "request.completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
