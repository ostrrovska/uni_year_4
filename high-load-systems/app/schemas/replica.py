import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReplicaState


class ReplicaReport(BaseModel):
    """An edge agent declaring what it currently holds for one asset."""

    state: ReplicaState
    cached_version: Annotated[int | None, Field(ge=1)] = None
    bytes_cached: Annotated[int, Field(ge=0)] = 0


class ReplicaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: uuid.UUID
    asset_id: uuid.UUID
    state: ReplicaState
    cached_version: int | None
    bytes_cached: int
    last_verified_at: datetime | None
