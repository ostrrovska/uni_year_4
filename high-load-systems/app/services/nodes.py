import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.db.integrity import translate_integrity_errors
from app.models.edge_node import EdgeNode
from app.models.enums import NodeStatus
from app.models.node_heartbeat import NodeHeartbeat
from app.models.region import Region
from app.schemas.node import HeartbeatReport, NodeRegister, NodeUpdate
from app.services import regions as regions_service

# Operators drain and decommission nodes; agents bring them back. Encoding the legal
# moves rejects nonsense like reviving a decommissioned node straight into `draining`,
# and makes the lifecycle reviewable in one place instead of scattered `if` branches.
_ALLOWED_TRANSITIONS: dict[NodeStatus, frozenset[NodeStatus]] = {
    NodeStatus.PROVISIONING: frozenset({NodeStatus.HEALTHY, NodeStatus.OFFLINE}),
    NodeStatus.HEALTHY: frozenset({NodeStatus.DEGRADED, NodeStatus.DRAINING, NodeStatus.OFFLINE}),
    NodeStatus.DEGRADED: frozenset({NodeStatus.HEALTHY, NodeStatus.DRAINING, NodeStatus.OFFLINE}),
    NodeStatus.DRAINING: frozenset({NodeStatus.HEALTHY, NodeStatus.OFFLINE}),
    NodeStatus.OFFLINE: frozenset({NodeStatus.PROVISIONING, NodeStatus.HEALTHY}),
}


def _apply_filters(
    statement: Select, *, region_code: str | None, status: NodeStatus | None
) -> Select:
    if region_code is not None:
        statement = statement.where(Region.code == region_code)
    if status is not None:
        statement = statement.where(EdgeNode.status == status)
    return statement


async def list_nodes(
    session: AsyncSession,
    *,
    page: PageParams,
    region_code: str | None = None,
    status: NodeStatus | None = None,
) -> tuple[list[tuple[EdgeNode, str]], int]:
    join_condition = Region.id == EdgeNode.region_id

    total = await session.scalar(
        _apply_filters(
            select(func.count()).select_from(EdgeNode).join(Region, join_condition),
            region_code=region_code,
            status=status,
        )
    )

    rows = await session.execute(
        _apply_filters(
            select(EdgeNode, Region.code).join(Region, join_condition),
            region_code=region_code,
            status=status,
        )
        .order_by(EdgeNode.hostname)
        .limit(page.limit)
        .offset(page.offset)
    )
    return [(node, code) for node, code in rows.all()], total or 0


async def get_node(session: AsyncSession, node_id: uuid.UUID) -> tuple[EdgeNode, str]:
    row = (
        await session.execute(
            select(EdgeNode, Region.code)
            .join(Region, Region.id == EdgeNode.region_id)
            .where(EdgeNode.id == node_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(f"No edge node with id '{node_id}'.")
    return row[0], row[1]


async def register_node(session: AsyncSession, payload: NodeRegister) -> tuple[EdgeNode, str]:
    region = await regions_service.get_region_by_code(session, payload.region_code)

    duplicate = await session.scalar(
        select(EdgeNode.id).where(EdgeNode.hostname == payload.hostname)
    )
    if duplicate is not None:
        raise ConflictError(f"Edge node '{payload.hostname}' is already registered.")

    node = EdgeNode(
        hostname=payload.hostname,
        public_ipv4=str(payload.public_ipv4),
        region_id=region.id,
        capacity_mbps=payload.capacity_mbps,
        agent_version=payload.agent_version,
        status=NodeStatus.PROVISIONING,
    )
    session.add(node)
    async with translate_integrity_errors(
        session, message=f"Edge node '{payload.hostname}' is already registered."
    ):
        await session.commit()
    await session.refresh(node)
    return node, region.code


async def update_node(
    session: AsyncSession, node_id: uuid.UUID, payload: NodeUpdate
) -> tuple[EdgeNode, str]:
    node, region_code = await get_node(session, node_id)

    if payload.status is not None and payload.status is not node.status:
        allowed = _ALLOWED_TRANSITIONS[node.status]
        if payload.status not in allowed:
            raise ConflictError(
                f"Illegal status transition '{node.status}' -> '{payload.status}'.",
                allowed_transitions=sorted(allowed),
            )
        node.status = payload.status

    if payload.capacity_mbps is not None:
        node.capacity_mbps = payload.capacity_mbps
    if payload.agent_version is not None:
        node.agent_version = payload.agent_version

    await session.commit()
    await session.refresh(node)
    return node, region_code


async def delete_node(session: AsyncSession, node_id: uuid.UUID) -> None:
    result = await session.execute(delete(EdgeNode).where(EdgeNode.id == node_id))
    if result.rowcount == 0:
        raise NotFoundError(f"No edge node with id '{node_id}'.")
    await session.commit()


def _derive_load_percent(report: HeartbeatReport, capacity_mbps: int) -> int:
    """Collapse a telemetry sample into the single number routing sorts on.

    The worst of the three signals wins: a node saturating its uplink is just as
    unusable as one pinned at 100% CPU, and routing needs one comparable scalar
    rather than three thresholds evaluated on the hot path.
    """
    bandwidth_utilisation = round(report.bandwidth_out_mbps / capacity_mbps * 100)
    worst = max(report.cpu_percent, report.memory_percent, bandwidth_utilisation)
    return max(0, min(100, worst))


def _derive_status(current: NodeStatus, load_percent: int, overload_threshold: int) -> NodeStatus:
    """Decide the node's status from its own telemetry.

    A draining node keeps draining: that status is an explicit operator decision and
    must not be undone by a healthy-looking heartbeat. Everything else is driven by
    load, which is what automatically ejects overloaded nodes from routing and lets
    a recovered node rejoin without manual intervention.
    """
    if current is NodeStatus.DRAINING:
        return current
    if load_percent >= overload_threshold:
        return NodeStatus.DEGRADED
    return NodeStatus.HEALTHY


async def record_heartbeat(
    session: AsyncSession, node_id: uuid.UUID, report: HeartbeatReport
) -> tuple[EdgeNode, datetime]:
    """Ingest one telemetry sample — the write-intensive hot path.

    One transaction, two statements: an append to the telemetry table and an update
    of the node's denormalized liveness columns. No read-modify-write cycle spans
    requests, so any instance can serve any node's heartbeat.
    """
    settings = get_settings()

    node = await session.get(EdgeNode, node_id)
    if node is None:
        raise NotFoundError(f"No edge node with id '{node_id}'.")

    # Both timestamps come from the application clock so that the stored sample and
    # the value returned to the agent cannot disagree. All instances and the database
    # share the host clock, and the staleness threshold is measured in tens of
    # seconds, so sub-second skew is immaterial.
    received_at = datetime.now(UTC)
    cache_hit_ratio = (
        Decimal(str(report.cache_hit_ratio)) if report.cache_hit_ratio is not None else None
    )

    session.add(
        NodeHeartbeat(
            node_id=node.id,
            reported_at=report.reported_at or received_at,
            received_at=received_at,
            cpu_percent=report.cpu_percent,
            memory_percent=report.memory_percent,
            bandwidth_out_mbps=report.bandwidth_out_mbps,
            active_connections=report.active_connections,
            cache_hit_ratio=cache_hit_ratio,
        )
    )

    load_percent = _derive_load_percent(report, node.capacity_mbps)
    node.last_heartbeat_at = received_at
    node.current_load_percent = load_percent
    node.active_connections = report.active_connections
    node.cache_hit_ratio = cache_hit_ratio
    node.status = _derive_status(
        node.status, load_percent, settings.node_overload_threshold_percent
    )

    await session.commit()
    return node, received_at
