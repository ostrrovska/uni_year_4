import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DistributionRule(Base):
    """Declares that an asset is allowed to be cached in a given region.

    Absence of any enabled rule for an asset means "distribute everywhere". That
    default keeps the common case free of bookkeeping while still allowing the
    restricted case the domain calls for — e.g. an update bundle pinned to European
    nodes only.
    """

    __tablename__ = "distribution_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(SmallInteger, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("asset_id", "region_id", name="asset_id_region_id"),)
