"""Lab4 — the shared read cache on Redis."""

import asyncio
import logging
from contextlib import suppress
from time import monotonic

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.services.cache import glob_escape

logger = logging.getLogger(__name__)

# SCAN page size and UNLINK batch size. Bounded work per round trip, so invalidating a large
# prefix never becomes one huge blocking command.
_SCAN_COUNT = 512
_UNLINK_BATCH = 512

_FAILURES = (RedisError, OSError, asyncio.TimeoutError)


class RedisCache:
    """Cache-aside backend shared by every API instance.

    Three properties matter more here than speed:

    1. **Fail-open.** Every operation swallows connection and protocol errors and degrades to
       "nothing cached". The cache is an optimisation; losing it must cost throughput, never
       correctness or availability. A cache layer that can take the API down with it is a
       worse bottleneck than the query it was added to remove.
    2. **Bounded failure cost.** Short socket timeouts cap a dead Redis at one timeout per
       request, and the circuit breaker then removes even that by skipping Redis entirely for
       a cooldown. Without the breaker, `docker stop redis` would add a timeout to every
       request and "graceful degradation" would mean "100x slower".
    3. **Non-blocking invalidation.** Prefix deletes use SCAN plus UNLINK in batches, never
       KEYS. KEYS is O(keyspace) and blocks single-threaded Redis for its whole duration - on
       a cache shared by every instance that is a self-inflicted outage, triggered by the very
       mutation that was supposed to be cheap.
    """

    def __init__(
        self,
        url: str,
        *,
        socket_timeout_seconds: float = 0.25,
        breaker_failure_threshold: int = 3,
        breaker_cooldown_seconds: float = 10.0,
    ) -> None:
        self._client: redis.Redis = redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout_seconds,
            socket_connect_timeout=socket_timeout_seconds,
        )
        self._threshold = max(1, breaker_failure_threshold)
        self._cooldown = breaker_cooldown_seconds
        self._failures = 0
        self._open_until = 0.0
        # Counters behind the Hit / Miss / Invalidation metrics requirement. Per-process and
        # purely observational, so they stay in the Ephemeral / Local Safe category.
        self._invalidations = 0
        self._keys_dropped = 0

    @property
    def enabled(self) -> bool:
        """Whether the cache is worth consulting right now.

        False while the breaker is open, which is what makes `X-Cache: BYPASS` mean exactly
        what it says - the cache was not consulted - and what makes the Redis-down demo
        visible in the response headers rather than only in the latency.
        """
        return monotonic() >= self._open_until

    async def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        try:
            value = await self._client.get(key)
        except _FAILURES as exc:
            self._record_failure("get", exc)
            return None
        self._record_success()
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if not self.enabled:
            return
        try:
            await self._client.set(key, value, ex=max(1, ttl_seconds))
        except _FAILURES as exc:
            self._record_failure("set", exc)
            return
        self._record_success()

    async def delete(self, key: str) -> None:
        if not self.enabled:
            return
        try:
            await self._client.delete(key)
        except _FAILURES as exc:
            self._record_failure("delete", exc)
            return
        self._record_success()

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every key whose literal prefix is `prefix`.

        The prefix is data, so it is glob-escaped before the `*` is appended; see
        `cache.glob_escape`.
        """
        if not self.enabled:
            return
        pattern = f"{glob_escape(prefix)}*"
        batch: list[str] = []
        dropped = 0
        try:
            async for key in self._client.scan_iter(match=pattern, count=_SCAN_COUNT):
                batch.append(key)
                if len(batch) >= _UNLINK_BATCH:
                    await self._client.unlink(*batch)
                    dropped += len(batch)
                    batch.clear()
            if batch:
                await self._client.unlink(*batch)
                dropped += len(batch)
        except _FAILURES as exc:
            self._record_failure("delete_prefix", exc)
            return
        self._record_success()

        # The invalidation half of the Hit / Miss / Invalidation metrics. HIT and MISS are
        # observable per request in the X-Cache header; an invalidation belongs to a *write*,
        # has no response header of its own, and is the one of the three a reader cannot see -
        # so it is logged with the scope and the number of entries actually dropped.
        self._invalidations += 1
        self._keys_dropped += dropped
        logger.info(
            "cache.invalidated prefix=%s keys_dropped=%d invalidations_total=%d",
            prefix,
            dropped,
            self._invalidations,
        )

    @property
    def invalidation_stats(self) -> dict[str, int]:
        """What this instance has invalidated since it started."""
        return {"invalidations": self._invalidations, "keys_dropped": self._keys_dropped}

    async def close(self) -> None:
        # Nothing useful to do about a failure while shutting down.
        with suppress(*_FAILURES):
            await self._client.aclose()

    def _record_success(self) -> None:
        if self._failures:
            logger.info("cache.recovered")
        self._failures = 0

    def _record_failure(self, operation: str, exc: BaseException) -> None:
        self._failures += 1
        if self._failures < self._threshold:
            logger.debug("cache.operation_failed op=%s error=%s", operation, exc)
            return

        # One WARNING when the breaker opens, DEBUG for the rest: a dead Redis under load must
        # not emit a warning per request and bury the access log.
        was_closed = self.enabled
        self._open_until = monotonic() + self._cooldown
        if was_closed:
            logger.warning(
                "cache.breaker_open op=%s cooldown_s=%s error=%s",
                operation,
                self._cooldown,
                exc,
            )
