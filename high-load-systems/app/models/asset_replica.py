import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ReplicaState, pg_enum


class AssetReplica(Base):
    """Tracks which edge node currently holds which version of an asset.

    This is the join table the routing decision hinges on: "nearest, least loaded
    node *that already has the content*". The composite primary key is the natural
    key — a node holds at most one copy of an asset — which also removes the extra
    unique index a surrogate key would have required.
    """

    __tablename__ = "asset_replicas"

    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[ReplicaState] = mapped_column(
        pg_enum(ReplicaState, "replica_state"), default=ReplicaState.PENDING
    )
    cached_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_cached: Mapped[int] = mapped_column(BigInteger, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # The composite PK is ordered (node_id, asset_id); routing and purge fan-out both
        # start from the asset, so they need the mirrored index to avoid a sequential scan.
        Index("ix_asset_replicas_asset_id_state", "asset_id", "state"),
    )
