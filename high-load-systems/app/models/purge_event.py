import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PurgeScope, PurgeStatus, pg_enum


class PurgeEvent(Base):
    """A cache-invalidation campaign broadcast to the edge fleet.

    A purge is not a fire-and-forget signal: it is a tracked campaign with a known
    target set (`target_node_count`) and a running tally of acknowledgements. That is
    what lets an operator answer "is the old bundle really gone everywhere?" rather
    than assuming it is.
    """

    __tablename__ = "purge_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[PurgeScope] = mapped_column(pg_enum(PurgeScope, "purge_scope"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=True
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), nullable=True
    )
    path_pattern: Mapped[str | None] = mapped_column(String(512), nullable=True)

    requested_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[PurgeStatus] = mapped_column(
        pg_enum(PurgeStatus, "purge_status"), default=PurgeStatus.PENDING
    )
    target_node_count: Mapped[int] = mapped_column(Integer, default=0)
    acknowledged_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_purge_events_status_created_at", "status", text("created_at DESC")),
        # The scope decides which target column is meaningful; enforcing it in the
        # schema means an inconsistent purge cannot exist even if a future caller
        # bypasses the service layer.
        CheckConstraint(
            "(scope = 'asset' AND asset_id IS NOT NULL)"
            " OR (scope = 'region' AND region_id IS NOT NULL)"
            " OR (scope = 'global')",
            name="scope_target_present",
        ),
        CheckConstraint("target_node_count >= 0", name="target_node_count_non_negative"),
        CheckConstraint(
            "acknowledged_count >= 0 AND acknowledged_count <= target_node_count",
            name="acknowledged_count_within_target",
        ),
    )
