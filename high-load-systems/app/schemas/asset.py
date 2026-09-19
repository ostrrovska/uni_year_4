import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssetStatus

ContentHash = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Lowercase hex SHA-256 of the artifact bytes.",
    ),
]

OriginPath = Annotated[
    str,
    Field(min_length=1, max_length=512, pattern=r"^/\S*$", examples=["/static/app.bundle.js"]),
]


class AssetCreate(BaseModel):
    origin_path: OriginPath
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=0)]
    content_type: Annotated[
        str, Field(min_length=1, max_length=127, examples=["application/javascript"])
    ]
    cache_ttl_seconds: Annotated[int, Field(ge=0, le=31_536_000)] = 3600
    publish: bool = True


class AssetVersionPublish(BaseModel):
    """Publish new bytes under an existing origin path."""

    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=0)]
    cache_ttl_seconds: Annotated[int | None, Field(ge=0, le=31_536_000)] = None
    requested_by: Annotated[str, Field(min_length=1, max_length=128, examples=["ci-pipeline"])]
    reason: Annotated[str | None, Field(max_length=255)] = None


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    origin_path: str
    content_hash: str
    size_bytes: int
    content_type: str
    version: int
    cache_ttl_seconds: int
    status: AssetStatus
    created_at: datetime
    updated_at: datetime


class AssetVersionPublished(BaseModel):
    """Result of a version bump: the new asset state plus the purge it triggered."""

    asset: AssetRead
    previous_version: int
    replicas_invalidated: int
    purge_event_id: uuid.UUID
