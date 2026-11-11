"""Lab4 — the Cache-Aside (lazy loading) read path, shared by every cached endpoint."""

import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.services.cache import CacheBackend, CacheStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CachedRead[M]:
    """A value and where it came from, so a route can set `X-Cache` without re-deriving it."""

    value: M
    status: CacheStatus


async def read_through[M: BaseModel](
    cache: CacheBackend,
    *,
    key: str,
    model: type[M],
    loader: Callable[[], Awaitable[M]],
    ttl_seconds: int | Callable[[M], int],
) -> CachedRead[M]:
    """Cache-aside over any Pydantic model.

    1. Backend disabled (not configured, or its breaker open) -> load and report BYPASS.
    2. Key present and parseable -> report HIT without touching the database.
    3. Key absent -> load, store with a TTL, report MISS.

    Three deliberate properties:

    * **Errors are never cached.** A 404 or 503 reaches this function as an exception from the
      loader, propagates, and the store is never written. Caching a 404 would keep an asset
      unresolvable for a whole TTL after it was published.
    * **A payload that no longer parses is treated as a miss and deleted**, so changing a
      response schema cannot make a fleet serve `ValidationError`s; the key simply refills.
    * **The status is decided after the fact.** If Redis dies during this very request the
      breaker opens mid-flight, and the honest answer is BYPASS rather than a MISS that was
      never stored.
    """
    if not cache.enabled:
        return CachedRead(await loader(), CacheStatus.BYPASS)

    # The fail-open guarantee lives here, not in the backend: whatever a `CacheBackend`
    # implementation does on failure, a cache fault must degrade this read to a database read
    # rather than surface as a 500. `usable` then carries that into the reported status, so
    # `BYPASS` keeps meaning "the cache did not serve this".
    usable = True

    cached: str | None = None
    try:
        cached = await cache.get(key)
    except Exception as exc:  # noqa: BLE001 - fail-open boundary, deliberately broad
        logger.warning("cache.get_failed key=%s error=%s", key, exc)
        usable = False

    if cached is not None:
        try:
            return CachedRead(model.model_validate_json(cached), CacheStatus.HIT)
        except ValidationError:
            logger.warning("cache.stale_payload key=%s model=%s", key, model.__name__)
            with suppress(Exception):
                await cache.delete(key)

    value = await loader()

    if usable:
        ttl = ttl_seconds(value) if callable(ttl_seconds) else ttl_seconds
        try:
            await cache.set(key, value.model_dump_json(), _with_jitter(ttl))
        except Exception as exc:  # noqa: BLE001 - fail-open boundary, deliberately broad
            logger.warning("cache.set_failed key=%s error=%s", key, exc)
            usable = False

    status = CacheStatus.MISS if usable and cache.enabled else CacheStatus.BYPASS
    return CachedRead(value, status)


def _with_jitter(ttl_seconds: int) -> int:
    """Shorten a TTL by up to `CACHE_TTL_JITTER_PERCENT`, never lengthen it.

    Keys written together - the burst of misses right after an invalidation - would otherwise
    expire together and send a synchronised wave of load at the database. Jitter spreads that
    wave. Downwards only, because the TTL ceiling is a freshness contract: for routes it is
    one heartbeat interval, and jitter must not be allowed to breach it.
    """
    percent = get_settings().cache_ttl_jitter_percent
    if percent <= 0:
        return max(1, ttl_seconds)
    return max(1, int(ttl_seconds * (1 - percent / 100 * random.random())))
