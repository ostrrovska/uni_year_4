import uuid
from datetime import datetime
from ipaddress import IPv4Address
from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator

from app.models.edge_node import EdgeNode
from app.models.enums import NodeStatus
from app.schemas.region import RegionCode

Percent = Annotated[int, Field(ge=0, le=100)]


class NodeRegister(BaseModel):
    hostname: Annotated[str, Field(min_length=1, max_length=255, examples=["edge-eu-01.cdn.net"])]
    public_ipv4: IPv4Address
    region_code: RegionCode
    capacity_mbps: Annotated[int, Field(gt=0, le=1_000_000, examples=[10_000])]
    agent_version: Annotated[str, Field(min_length=1, max_length=32, examples=["1.4.2"])]


class NodeUpdate(BaseModel):
    status: NodeStatus | None = None
    capacity_mbps: Annotated[int | None, Field(gt=0, le=1_000_000)] = None
    agent_version: Annotated[str | None, Field(min_length=1, max_length=32)] = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> Self:
        if self.status is None and self.capacity_mbps is None and self.agent_version is None:
            raise ValueError("at least one of status, capacity_mbps, agent_version is required")
        return self


class NodeRead(BaseModel):
    id: uuid.UUID
    hostname: str
    public_ipv4: IPv4Address
    region_code: str
    status: NodeStatus
    capacity_mbps: int
    agent_version: str
    last_heartbeat_at: datetime | None
    current_load_percent: int
    active_connections: int
    cache_hit_ratio: float | None
    created_at: datetime

    @classmethod
    def from_model(cls, node: EdgeNode, region_code: str) -> "NodeRead":
        return cls(
            id=node.id,
            hostname=node.hostname,
            public_ipv4=IPv4Address(node.public_ipv4),
            region_code=region_code,
            status=node.status,
            capacity_mbps=node.capacity_mbps,
            agent_version=node.agent_version,
            last_heartbeat_at=node.last_heartbeat_at,
            current_load_percent=node.current_load_percent,
            active_connections=node.active_connections,
            cache_hit_ratio=float(node.cache_hit_ratio)
            if node.cache_hit_ratio is not None
            else None,
            created_at=node.created_at,
        )


class HeartbeatReport(BaseModel):
    """Telemetry sample sent by an edge agent.

    `reported_at` is optional and defaults to server receipt time; an agent with a
    skewed clock should not be able to poison the freshness calculation, so routing
    eligibility is evaluated against `received_at`, never this field.
    """

    reported_at: datetime | None = None
    cpu_percent: Percent
    memory_percent: Percent
    bandwidth_out_mbps: Annotated[int, Field(ge=0)]
    active_connections: Annotated[int, Field(ge=0)]
    cache_hit_ratio: Annotated[float | None, Field(ge=0, le=1)] = None


class HeartbeatAccepted(BaseModel):
    node_id: uuid.UUID
    status: NodeStatus
    current_load_percent: int
    received_at: datetime
    next_heartbeat_in_seconds: int
