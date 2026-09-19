import uuid
from ipaddress import IPv4Address

from pydantic import BaseModel, Field


class RouteCandidate(BaseModel):
    node_id: uuid.UUID
    hostname: str
    public_ipv4: IPv4Address
    region_code: str
    capacity_mbps: int
    current_load_percent: int
    cache_state: str = Field(
        description="`warm` when the node already holds the current asset version, "
        "`cold` when it would have to pull from origin first.",
    )
    score: float = Field(
        description="Lower is better. Composed of proximity, load and cache state."
    )
    reason: str


class RouteResolution(BaseModel):
    asset_id: uuid.UUID
    origin_path: str
    version: int
    content_hash: str
    cache_ttl_seconds: int
    client_region: str | None
    candidates: list[RouteCandidate]
