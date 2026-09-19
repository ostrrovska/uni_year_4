import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import NodeStatus, pg_enum


class EdgeNode(Base):
    """A managed edge server in the CDN fleet.

    The `last_heartbeat_at` / `current_load_percent` / `active_connections` columns are
    a denormalized projection of the newest `node_heartbeats` row. They exist so the
    routing query never has to reach into the telemetry table, which is by far the
    largest and fastest-growing one. The trade-off is that every heartbeat updates the
    same row — see docs/bottlenecks.md, bottleneck #2.
    """

    __tablename__ = "edge_nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    public_ipv4: Mapped[str] = mapped_column(INET)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id", ondelete="RESTRICT"))
    capacity_mbps: Mapped[int] = mapped_column(Integer)
    status: Mapped[NodeStatus] = mapped_column(
        pg_enum(NodeStatus, "node_status"), default=NodeStatus.PROVISIONING
    )
    agent_version: Mapped[str] = mapped_column(String(32))

    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_load_percent: Mapped[int] = mapped_column(SmallInteger, default=0)
    active_connections: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Serves the routing eligibility filter and the per-region fleet listing.
        Index("ix_edge_nodes_region_id_status", "region_id", "status"),
        # Serves staleness sweeps: "which healthy nodes have gone quiet?".
        Index("ix_edge_nodes_status_last_heartbeat_at", "status", "last_heartbeat_at"),
        CheckConstraint("capacity_mbps > 0", name="capacity_mbps_positive"),
        CheckConstraint(
            "current_load_percent >= 0 AND current_load_percent <= 100",
            name="current_load_percent_range",
        ),
        CheckConstraint("active_connections >= 0", name="active_connections_non_negative"),
    )
