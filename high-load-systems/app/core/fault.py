"""Lab3 — deliberate latency injection. A lab instrument, not production code.

Lab 3 compares Round Robin against Least Connections on a pool where one peer is slow.
Slowing a peer from the outside needs either an extra proxy container, which holds the delay
outside the instance and so never occupies the instance's own concurrency — the quantity
Least Connections balances on — or tc/netem, which needs NET_ADMIN and an iproute2 package
`python:3.13-slim` does not ship. Delaying inside the instance holds the connection and the
worker slot for real, which is what the experiment is about.

Two knobs, because they model different failures:

* ``FAULT_DELAY_MS`` sleeps. The connection and worker slot are occupied, CPU is not, so this
  is a slow *dependency*.
* ``FAULT_CPU_SPIN_MS`` busy-loops. It blocks the single uvicorn worker's event loop, so the
  instance serialises and genuinely burns CPU — a *saturated* node.

Both default to 0 and the middleware is only installed when one is set, so a normal instance
does not carry it at all.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Health probes stay fast. Without the exemption the slow instance fails its readiness check,
# gets ejected from the pool, and the latency experiment silently becomes a failover one.
EXEMPT_PATH_PREFIX = "/health"


class FaultInjectionMiddleware(BaseHTTPMiddleware):
    """Hold each request for a configured time before handing it on."""

    def __init__(self, app: Callable, *, delay_ms: int = 0, cpu_spin_ms: int = 0) -> None:
        super().__init__(app)
        self._delay_seconds = max(0, delay_ms) / 1000
        self._spin_seconds = max(0, cpu_spin_ms) / 1000

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith(EXEMPT_PATH_PREFIX):
            return await call_next(request)

        if self._spin_seconds:
            deadline = perf_counter() + self._spin_seconds
            while perf_counter() < deadline:
                pass

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        return await call_next(request)
