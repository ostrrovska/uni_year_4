import hashlib
import json
import logging
from enum import StrEnum
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "cdn:v1"
CACHE_HEADER = "X-Cache"

# Entity segments of the key grammar `cdn:v1:<entity>:<identity>:<params_hash>`.
ROUTE_ENTITY = "route"
STATS_ENTITY = "stats"


class CacheStatus(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    BYPASS = "BYPASS"


class CacheBackend(Protocol):
    """Storage-agnostic contract for the read-path cache.

    Lab 1 deliberately ships only `NullCache`: a local in-process cache would be
    exactly the kind of instance-bound state the stateless refactor has to remove,
    and a shared cache has no home until Redis is introduced. Declaring the contract
    now means Lab 4 adds `RedisCache` and swaps one dependency provider without
    touching a single call site.
    """

    enabled: bool

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def delete_prefix(self, prefix: str) -> None: ...


class NullCache:
    """No-op backend: every lookup misses and every write is discarded."""

    enabled = False

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def delete_prefix(self, prefix: str) -> None:
        return None


def cache_prefix(entity: str, identity: str = "") -> str:
    """Literal prefix covering every cached variant of one entity instance.

    Invalidation works on this prefix so that a mutation drops all parameter
    combinations of an entity at once, rather than trying to enumerate them.

    The returned value is a **literal** string, never a pattern: globbing and escaping
    belong to `delete_prefix`. Lab 4 changed the default identity from `"*"` to `""` for
    that reason - a `*` here would be escaped by the backend and then match nothing,
    silently turning fleet-wide invalidation into a no-op.
    """
    return f"{CACHE_NAMESPACE}:{entity}:{identity}"


def glob_escape(value: str) -> str:
    """Neutralise the glob metacharacters Redis `SCAN MATCH` would otherwise interpret.

    Cache identities are real data - a route key carries the asset's `origin_path` - so an
    asset at `/static/[v2]/app.js` or `/media/*.m3u8` would otherwise under- or over-match
    and silently corrupt invalidation. Backslash first, or it would escape its own escapes.
    """
    for character in ("\\", "*", "?", "[", "]"):
        value = value.replace(character, f"\\{character}")
    return value


def route_scope(origin_path: str | None = None) -> str:
    """Invalidation scope for cached route resolutions.

    With a path, every cached variant of that one asset; without, the whole route keyspace.

    The trailing colon matters: without it the prefix for `/static/app.bundle.js` would also
    match `/static/app.bundle.js.map`, and publishing one asset would evict another.
    """
    if origin_path is None:
        return cache_prefix(ROUTE_ENTITY)
    return f"{cache_prefix(ROUTE_ENTITY, origin_path)}:"


def stats_scope() -> str:
    """Invalidation scope for the cached network statistics."""
    return cache_prefix(STATS_ENTITY)


async def invalidate(cache: "CacheBackend | None", *prefixes: str) -> None:
    """Drop every cached entry under each prefix, best-effort.

    A `None` cache means the caller opted out, which is how scripts and unit-level callers
    run without a backend at all.

    **A cache failure must never fail the mutation that triggered it.** Invalidation runs after
    the commit, so the write has already succeeded; raising here would turn a healthy write into
    a 500 because an optimisation was unreachable. `RedisCache` is fail-open by construction, but
    the guarantee belongs at this boundary rather than depending on every backend to implement
    it. The cost of a failed invalidation is bounded staleness, not permanent staleness: the
    entry still expires on its TTL, which is one heartbeat interval for routes. That is the
    second reason the TTL ceiling is short - it is the backstop for exactly this case.
    """
    if cache is None:
        return
    for prefix in prefixes:
        try:
            await cache.delete_prefix(prefix)
        except Exception as exc:  # noqa: BLE001 - fail-open boundary, deliberately broad
            logger.warning("cache.invalidate_failed prefix=%s error=%s", prefix, exc)


def cache_key(entity: str, identity: str = "all", /, **params: Any) -> str:
    """Build a collision-free key of the form `cdn:v1:<entity>:<identity>:<params_hash>`.

    Parameters are canonicalised (sorted, `None` dropped, compact JSON) before
    hashing, so logically identical requests that differ only in query-string order
    resolve to the same key instead of silently caching twice.
    """
    meaningful = {key: value for key, value in sorted(params.items()) if value is not None}
    if meaningful:
        canonical = json.dumps(meaningful, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    else:
        digest = "noargs"
    return f"{cache_prefix(entity, identity)}:{digest}"


_null_cache = NullCache()


@lru_cache
def get_cache() -> CacheBackend:
    """FastAPI dependency returning the active cache backend.

    Cached for the process lifetime because what it holds is a Redis connection pool, which
    belongs to the *Ephemeral / Local Safe* category of the Lab 2 state audit - the same
    category as the SQLAlchemy pool, and not business state. The cached data itself lives in
    Redis, shared by every instance, so no instance holds anything another instance cannot see.

    `CACHE_ENABLED` defaults to false and an unset `REDIS_URL` also yields `NullCache`: a
    cache is provisioned infrastructure, and an instance with no Redis on its network must not
    pretend to have one. That default is also what keeps the test suite and CI Redis-free.
    """
    settings = get_settings()
    if not settings.cache_enabled or not settings.redis_url:
        return _null_cache

    # Imported here rather than at module scope: cache_redis imports this module for the key
    # helpers, and a top-level import would close the cycle.
    from app.services.cache_redis import RedisCache

    logger.info("cache.backend_selected backend=redis url=%s", settings.redis_url)
    return RedisCache(
        settings.redis_url,
        socket_timeout_seconds=settings.cache_socket_timeout_seconds,
        breaker_failure_threshold=settings.cache_breaker_failure_threshold,
        breaker_cooldown_seconds=settings.cache_breaker_cooldown_seconds,
    )


async def close_cache() -> None:
    """Release the active backend's connections and forget it.

    Called from the application lifespan and from any script that built a cache of its own.
    """
    backend = get_cache()
    get_cache.cache_clear()
    closer = getattr(backend, "close", None)
    if closer is not None:
        await closer()
