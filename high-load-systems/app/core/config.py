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

    # DevOps Lab5 - baked into the image at build time (docker/Dockerfile ARGs) and
    # reported by /version. GitOps changes the deployed version by changing the image
    # tag in Git, so the running pods must be able to say which build they are.
    app_version: str = "0.0.0-dev"
    git_sha: str = "unknown"

    database_url: str = "postgresql+asyncpg://cdn:cdn@localhost:5434/cdn_control_plane"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: float = 10.0
    db_echo: bool = False

    heartbeat_stale_after_seconds: int = 30
    heartbeat_interval_seconds: int = 10
    node_overload_threshold_percent: int = 85

    routing_default_candidates: int = 3
    routing_max_candidates: int = 10


@lru_cache
def get_settings() -> Settings:
    """Cached accessor.

    Caching is safe here precisely because Settings is immutable configuration, not
    business state — see the statelessness rules in docs/architecture.md.
    """
    return Settings()
