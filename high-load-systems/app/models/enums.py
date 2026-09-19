import enum

from sqlalchemy import Enum as SAEnum


class NodeStatus(enum.StrEnum):
    PROVISIONING = "provisioning"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DRAINING = "draining"
    OFFLINE = "offline"


class AssetStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ReplicaState(enum.StrEnum):
    PENDING = "pending"
    CACHED = "cached"
    STALE = "stale"
    PURGED = "purged"


class PurgeScope(enum.StrEnum):
    ASSET = "asset"
    REGION = "region"
    GLOBAL = "global"


class PurgeStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"


class PurgeResult(enum.StrEnum):
    PURGED = "purged"
    NOT_FOUND = "not_found"
    FAILED = "failed"


def pg_enum(enum_cls: type[enum.StrEnum], name: str) -> SAEnum:
    """Map a StrEnum onto a native PostgreSQL enum type storing its *values*.

    SQLAlchemy stores member names by default, which would put `HEALTHY` in the
    column while the API speaks `healthy`. Persisting the values keeps ad-hoc SQL
    during a demo readable and identical to what the API returns.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda cls: [member.value for member in cls],
    )
