import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PurgeResult, PurgeScope, PurgeStatus
from app.schemas.region import RegionCode


class PurgeCreate(BaseModel):
    scope: PurgeScope
    asset_id: uuid.UUID | None = None
    region_code: RegionCode | None = None
    path_pattern: Annotated[str | None, Field(max_length=512)] = None
    requested_by: Annotated[str, Field(min_length=1, max_length=128, examples=["ops@cdn.net"])]
    reason: Annotated[str | None, Field(max_length=255)] = None

    @model_validator(mode="after")
    def _require_target_for_scope(self) -> Self:
        if self.scope is PurgeScope.ASSET and self.asset_id is None:
            raise ValueError("asset_id is required when scope is 'asset'")
        if self.scope is PurgeScope.REGION and self.region_code is None:
            raise ValueError("region_code is required when scope is 'region'")
        return self


class PurgeAcknowledge(BaseModel):
    node_id: uuid.UUID
    result: PurgeResult = PurgeResult.PURGED
    detail: Annotated[str | None, Field(max_length=255)] = None


class PurgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: PurgeScope
    asset_id: uuid.UUID | None
    region_id: uuid.UUID | None
    path_pattern: str | None
    requested_by: str
    reason: str | None
    status: PurgeStatus
    target_node_count: int
    acknowledged_count: int
    created_at: datetime
    completed_at: datetime | None
