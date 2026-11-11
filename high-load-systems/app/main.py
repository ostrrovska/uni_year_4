import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.responses import PROBLEM_SCHEMA
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.fault import FaultInjectionMiddleware
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from app.services.cache import close_cache

logger = logging.getLogger(__name__)

DESCRIPTION = """
Control plane for a content delivery network: the service that decides **where**
content lives and **which** edge node a client should talk to. It never serves the
content bytes itself.

* **Node management** — registration, lifecycle and continuous telemetry ingest.
* **Routing** — ranked edge-node selection by proximity, load and cache state.
* **Distribution** — asset metadata and the regional policy governing where it may be cached.
* **Invalidation** — tracked purge campaigns with per-node acknowledgement.

Errors follow RFC 9457 and are returned as `application/problem+json`.
Every response carries `X-Instance-ID`, `X-Request-ID` and `X-Response-Time-ms`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    try:
        yield
    finally:
        # Lab4: the cache holds a connection pool of its own, released before the database's.
        await close_cache()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CDN Control Plane API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )
    # Lab3: added before RequestContextMiddleware, so it ends up *inside* it and the injected
    # delay is counted in X-Response-Time-ms and in the access log. Starlette's add_middleware
    # inserts at the front of the list, so the last one added is the outermost.
    _install_fault_injection(app)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    _install_problem_schema(app)
    return app


def _install_fault_injection(app: FastAPI) -> None:
    """Lab3: make this instance deliberately slow. No-op unless a knob is set."""
    settings = get_settings()
    if not settings.fault_delay_ms and not settings.fault_cpu_spin_ms:
        return

    app.add_middleware(
        FaultInjectionMiddleware,
        delay_ms=settings.fault_delay_ms,
        cpu_spin_ms=settings.fault_cpu_spin_ms,
    )
    logger.warning(
        "fault_injection.enabled delay_ms=%s cpu_spin_ms=%s",
        settings.fault_delay_ms,
        settings.fault_cpu_spin_ms,
    )


def _install_problem_schema(app: FastAPI) -> None:
    """Publish the shared Problem schema that every error response references."""
    base_openapi = app.openapi

    def openapi() -> dict:
        schema = base_openapi()
        schema.setdefault("components", {}).setdefault("schemas", {})["Problem"] = PROBLEM_SCHEMA
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


app = create_app()
