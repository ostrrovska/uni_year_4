import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PurgeResult, pg_enum


class PurgeAcknowledgement(Base):
    """One edge node's confirmation that it acted on a purge event.

    The composite primary key makes the ack idempotent at the storage level: an edge
    agent that retries after a network timeout collides with its own row instead of
    inflating the acknowledgement tally.
    """

    __tablename__ = "purge_acknowledgements"

    purge_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purge_events.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    result: Mapped[PurgeResult] = mapped_column(pg_enum(PurgeResult, "purge_result"))
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
