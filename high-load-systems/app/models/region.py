import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Region(Base):
    """A geographic zone that edge nodes belong to and clients are mapped into.

    Proximity is modelled as region equality first, continent equality second. That
    is deliberately coarser than real geo-distance: it is deterministic, needs no
    coordinate math on the hot path, and is explainable in a routing response.
    """

    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    continent: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
