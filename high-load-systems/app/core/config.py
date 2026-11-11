from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / config/.env.

    Everything that differs between a laptop run, a scaled Compose stack and a load
    test lives here rather than in code, so the same image serves every environment.
    """

    model_config = SettingsConfigDict(env_file="config/.env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    instance_id: str | None = None
    # Baked into the image by docker/Dockerfile; "dev" on a host run. Diagnostic
    # only, like instance_id - it names the build serving a request during a
    # rolling update, and no business logic may branch on it.
    app_version: str = "dev"

    database_url: str = "postgresql+asyncpg://cdn:cdn@localhost:5434/cdn_control_plane"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: float = 10.0
    db_echo: bool = False
    # Lab5 - return the connection to the pool as soon as a read path's last query is done,
    # instead of holding it until the session closes after the response has been serialised.
    # A switch rather than a constant because the effect has to be measurable: the two arms
    # must run on the same host minutes apart, not against a figure recorded hours earlier.
    # It costs one extra round trip (the COMMIT) per read and saves pool occupancy, so it is
    # not obviously a win at every load - see docs/lab5-results.md.
    # Default off. The fix is real and the switch works, but the 34 surviving runs of this
    # lab's matrix were measured without it, and a ladder whose rows come from two different
    # builds is not a baseline. Turn it on with DB_RELEASE_EARLY=true to measure the effect.
    db_release_early: bool = False

    heartbeat_stale_after_seconds: int = 30
    heartbeat_interval_seconds: int = 10
    node_overload_threshold_percent: int = 85

    routing_default_candidates: int = 3
    routing_max_candidates: int = 10

    # Lab3 — deliberate latency injection for the asymmetric-load experiment, both off
    # unless set on one instance. See app/core/fault.py.
    fault_delay_ms: int = 0
    fault_cpu_spin_ms: int = 0

    # Lab4 — distributed cache. Off by default: a cache is provisioned infrastructure, and an
    # instance with no Redis on its network must not pretend to have one. The Compose stack
    # turns it on; pytest and host runs stay on NullCache.
    cache_enabled: bool = False
    redis_url: str | None = "redis://localhost:6379/0"
    # Equal to heartbeat_interval_seconds on purpose: a cached route embeds heartbeat-derived
    # eligibility and load, so its staleness must not outlive one telemetry cycle.
    cache_route_ttl_seconds: int = 10
    cache_stats_ttl_seconds: int = 30
    # Spread expiries so a batch of keys written together does not expire together.
    cache_ttl_jitter_percent: int = 10
    # ~100x a local Redis GET, so a healthy cache never trips it while a dead one costs at
    # most this once before the breaker removes even that.
    cache_socket_timeout_seconds: float = 0.25
    cache_breaker_failure_threshold: int = 3
    cache_breaker_cooldown_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    """Cached accessor.

    Caching is safe here precisely because Settings is immutable configuration, not
    business state — see the statelessness rules in docs/architecture.md.
    """
    return Settings()
