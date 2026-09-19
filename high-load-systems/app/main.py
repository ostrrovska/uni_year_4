from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.responses import PROBLEM_SCHEMA
from app.api.router import api_router
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine

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
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CDN Control Plane API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    _install_problem_schema(app)
    return app


def _install_problem_schema(app: FastAPI) -> None:
    """Publish the shared Problem schema that every error response references."""
    base_openapi = app.openapi

    def openapi() -> dict:
        schema = base_openapi()
        schema.setdefault("components", {}).setdefault("schemas", {})["Problem"] = PROBLEM_SCHEMA
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


app = create_app()
