import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AssetStatus, pg_enum


class Asset(Base):
    """Metadata for a piece of content distributed by the CDN.

    The control plane never stores the bytes — only the identity of the content and
    the invariants edge nodes need to validate their copy: `content_hash` and the
    monotonically increasing `version`. Bumping `version` is what makes every cached
    replica stale without having to compare hashes on the routing hot path.
    """

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(127))
    version: Mapped[int] = mapped_column(Integer, default=1)
    cache_ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    status: Mapped[AssetStatus] = mapped_column(
        pg_enum(AssetStatus, "asset_status"), default=AssetStatus.DRAFT, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("cache_ttl_seconds >= 0", name="cache_ttl_seconds_non_negative"),
    )
