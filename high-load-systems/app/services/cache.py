import hashlib
import json
from enum import StrEnum
from typing import Any, Protocol

CACHE_NAMESPACE = "cdn:v1"
CACHE_HEADER = "X-Cache"


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


def cache_prefix(entity: str, identity: str = "*") -> str:
    """Prefix covering every cached variant of one entity instance.

    Invalidation works on this prefix so that a mutation drops all parameter
    combinations of an entity at once, rather than trying to enumerate them.
    """
    return f"{CACHE_NAMESPACE}:{entity}:{identity}"


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


def get_cache() -> CacheBackend:
    """FastAPI dependency returning the active cache backend.

    `NullCache` holds no data, so sharing one instance across requests introduces no
    cross-request state. Lab 4 replaces the returned object with a Redis-backed
    implementation here.
    """
    return _null_cache
