import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeHeartbeat(Base):
    """Append-only telemetry sample reported by an edge agent.

    This is the write-intensive table: fleet size x heartbeat frequency rows per
    second, and nothing ever updates a row once written.

    The primary key is a BIGINT identity rather than the UUID used everywhere else.
    Random UUIDs scatter inserts across the whole index, dirtying many pages per
    transaction; a monotonic key keeps every insert on the rightmost B-tree page.
    The trade-off (keys are guessable and not client-generatable) does not matter
    for telemetry that is never addressed individually by an external caller.
    """

    __tablename__ = "node_heartbeats"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_nodes.id", ondelete="CASCADE"),
    )
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    cpu_percent: Mapped[int] = mapped_column(SmallInteger)
    memory_percent: Mapped[int] = mapped_column(SmallInteger)
    bandwidth_out_mbps: Mapped[int] = mapped_column(Integer)
    active_connections: Mapped[int] = mapped_column(Integer)
    cache_hit_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    __table_args__ = (
        # Descending order matches the only read pattern: the newest samples for one node.
        Index("ix_node_heartbeats_node_id_received_at", "node_id", text("received_at DESC")),
        CheckConstraint("cpu_percent >= 0 AND cpu_percent <= 100", name="cpu_percent_range"),
        CheckConstraint(
            "memory_percent >= 0 AND memory_percent <= 100", name="memory_percent_range"
        ),
        CheckConstraint("bandwidth_out_mbps >= 0", name="bandwidth_out_mbps_non_negative"),
        CheckConstraint("active_connections >= 0", name="active_connections_non_negative"),
    )
