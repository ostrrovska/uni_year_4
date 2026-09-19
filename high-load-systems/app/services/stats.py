from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.edge_node import EdgeNode
from app.models.enums import AssetStatus, NodeStatus, PurgeStatus, ReplicaState
from app.models.purge_event import PurgeEvent
from app.models.region import Region
from app.schemas.stats import NetworkStats, RegionStats


async def network_stats(session: AsyncSession) -> NetworkStats:
    """Aggregate the whole control plane into one snapshot.

    Four grouped aggregates over the fleet, asset and replica tables. This is the most
    expensive read in the system and it is intentionally left uncached in Lab 1 — it
    is the reference workload for the caching layer introduced in Lab 4, and caching
    it now would hide the cost it is meant to demonstrate.
    """
    settings = get_settings()
    stale_cutoff = datetime.now(UTC) - timedelta(seconds=settings.heartbeat_stale_after_seconds)

    fleet = (
        await session.execute(
            select(
                func.count(EdgeNode.id),
                func.coalesce(func.sum(EdgeNode.capacity_mbps), 0),
                func.coalesce(func.avg(EdgeNode.current_load_percent), 0),
                func.count()
                .filter(
                    (EdgeNode.last_heartbeat_at.is_(None))
                    | (EdgeNode.last_heartbeat_at < stale_cutoff)
                )
                .label("stale"),
            )
        )
    ).one()

    status_rows = (
        await session.execute(select(EdgeNode.status, func.count()).group_by(EdgeNode.status))
    ).all()

    assets_row = (
        await session.execute(
            select(
                func.count(Asset.id),
                func.count().filter(Asset.status == AssetStatus.PUBLISHED),
            )
        )
    ).one()

    replicas_row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(AssetReplica.state == ReplicaState.CACHED),
            ).select_from(AssetReplica)
        )
    ).one()

    purges_in_flight = await session.scalar(
        select(func.count())
        .select_from(PurgeEvent)
        .where(PurgeEvent.status.in_([PurgeStatus.PENDING, PurgeStatus.IN_PROGRESS]))
    )

    region_rows = (
        await session.execute(
            select(
                Region.code,
                Region.continent,
                func.count(EdgeNode.id),
                func.coalesce(
                    func.sum(case((EdgeNode.status == NodeStatus.HEALTHY, 1), else_=0)), 0
                ),
                func.coalesce(func.sum(EdgeNode.capacity_mbps), 0),
                func.coalesce(func.avg(EdgeNode.current_load_percent), 0),
            )
            .outerjoin(EdgeNode, EdgeNode.region_id == Region.id)
            .group_by(Region.code, Region.continent)
            .order_by(Region.code)
        )
    ).all()

    replicas_total, replicas_cached = replicas_row
    coverage = (replicas_cached / replicas_total * 100) if replicas_total else 0.0

    return NetworkStats(
        nodes_total=fleet[0],
        nodes_by_status={status.value: count for status, count in status_rows},
        fleet_capacity_mbps=int(fleet[1]),
        fleet_average_load_percent=round(float(fleet[2]), 2),
        stale_node_count=fleet[3],
        assets_total=assets_row[0],
        assets_published=assets_row[1],
        replicas_total=replicas_total,
        replicas_cached=replicas_cached,
        replica_coverage_percent=round(coverage, 2),
        purges_in_flight=purges_in_flight or 0,
        regions=[
            RegionStats(
                region_code=code,
                continent=continent,
                node_count=node_count,
                healthy_node_count=int(healthy),
                total_capacity_mbps=int(capacity),
                average_load_percent=round(float(load), 2),
            )
            for code, continent, node_count, healthy, capacity, load in region_rows
        ],
    )
