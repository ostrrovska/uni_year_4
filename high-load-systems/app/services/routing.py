from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, exists, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.distribution_rule import DistributionRule
from app.models.edge_node import EdgeNode
from app.models.enums import AssetStatus, NodeStatus, ReplicaState
from app.models.region import Region
from app.schemas.routing import RouteCandidate, RouteResolution

# Score weights. Lower total wins.
# Proximity dominates load so that a lightly loaded node on another continent never
# beats a moderately loaded one next door — for a CDN, distance is the whole point.
# The cold penalty sits between the two tiers: a warm node further away still beats a
# cold node nearby, because an origin pull costs far more than a few extra milliseconds
# of network distance.
_SAME_REGION_PENALTY = 0
_SAME_CONTINENT_PENALTY = 25
_CROSS_CONTINENT_PENALTY = 60
_COLD_REPLICA_PENALTY = 40
_LOAD_WEIGHT = 0.5


async def resolve_route(
    session: AsyncSession,
    *,
    path: str,
    client_region_code: str | None,
    limit: int,
) -> RouteResolution:
    """Pick the edge nodes a client should download an asset from.

    This is the read-intensive hot path. Three things keep it viable under load:

    1. The ranking is computed and ordered inside PostgreSQL and truncated with LIMIT,
       so the application never materialises the fleet in memory or sorts it in Python.
    2. The number of statements is constant (two, or three when a client region is
       given) regardless of how many nodes, replicas or rules exist — there is no
       per-candidate follow-up query.
    3. Node liveness is derived from a timestamp comparison in the WHERE clause rather
       than from a background reaper, so no instance holds fleet state in memory and
       every instance reaches the same verdict.
    """
    settings = get_settings()

    asset = await session.scalar(
        select(Asset).where(Asset.origin_path == path, Asset.status == AssetStatus.PUBLISHED)
    )
    if asset is None:
        raise NotFoundError(f"No published asset is registered at path '{path}'.")

    client_region: Region | None = None
    if client_region_code is not None:
        client_region = await session.scalar(
            select(Region).where(Region.code == client_region_code)
        )
        if client_region is None:
            raise NotFoundError(f"No region registered with code '{client_region_code}'.")

    replica = aliased(AssetReplica)
    is_warm = and_(
        replica.state == ReplicaState.CACHED,
        replica.cached_version == asset.version,
    )

    if client_region is not None:
        proximity = case(
            (EdgeNode.region_id == client_region.id, _SAME_REGION_PENALTY),
            (Region.continent == client_region.continent, _SAME_CONTINENT_PENALTY),
            else_=_CROSS_CONTINENT_PENALTY,
        )
    else:
        proximity = literal(_SAME_REGION_PENALTY)

    cold_penalty = case((is_warm, 0), else_=_COLD_REPLICA_PENALTY)
    score = (proximity + cold_penalty + EdgeNode.current_load_percent * _LOAD_WEIGHT).label("score")

    # No enabled rule for an asset means "cacheable everywhere"; as soon as one exists,
    # it becomes an allow-list. Expressed as a subquery so the whole decision stays in
    # one round trip.
    enabled_rules = select(DistributionRule.region_id).where(
        DistributionRule.asset_id == asset.id,
        DistributionRule.enabled.is_(True),
    )
    region_allowed = ~exists(enabled_rules) | EdgeNode.region_id.in_(enabled_rules)

    stale_cutoff = datetime.now(UTC) - timedelta(seconds=settings.heartbeat_stale_after_seconds)

    candidates_stmt = (
        select(
            EdgeNode.id,
            EdgeNode.hostname,
            EdgeNode.public_ipv4,
            EdgeNode.capacity_mbps,
            EdgeNode.current_load_percent,
            Region.code.label("region_code"),
            Region.continent.label("continent"),
            is_warm.label("is_warm"),
            score,
        )
        .join(Region, Region.id == EdgeNode.region_id)
        .outerjoin(
            replica,
            and_(replica.node_id == EdgeNode.id, replica.asset_id == asset.id),
        )
        .where(
            EdgeNode.status == NodeStatus.HEALTHY,
            EdgeNode.last_heartbeat_at.is_not(None),
            EdgeNode.last_heartbeat_at >= stale_cutoff,
            EdgeNode.current_load_percent < settings.node_overload_threshold_percent,
            region_allowed,
        )
        .order_by(score, EdgeNode.capacity_mbps.desc(), EdgeNode.id)
        .limit(limit)
    )

    rows = (await session.execute(candidates_stmt)).all()
    if not rows:
        raise ServiceUnavailableError(
            "No edge node is currently eligible to serve this asset.",
            origin_path=path,
            client_region=client_region_code,
        )

    return RouteResolution(
        asset_id=asset.id,
        origin_path=asset.origin_path,
        version=asset.version,
        content_hash=asset.content_hash,
        cache_ttl_seconds=asset.cache_ttl_seconds,
        client_region=client_region_code,
        candidates=[
            RouteCandidate(
                node_id=row.id,
                hostname=row.hostname,
                public_ipv4=row.public_ipv4,
                region_code=row.region_code,
                capacity_mbps=row.capacity_mbps,
                current_load_percent=row.current_load_percent,
                cache_state="warm" if row.is_warm else "cold",
                score=round(float(row.score), 2),
                reason=_explain(
                    is_warm=row.is_warm,
                    node_region=row.region_code,
                    node_continent=row.continent,
                    load_percent=row.current_load_percent,
                    client_region=client_region,
                ),
            )
            for row in rows
        ],
    )


def _explain(
    *,
    is_warm: bool,
    node_region: str,
    node_continent: str,
    load_percent: int,
    client_region: Region | None,
) -> str:
    """Render the score back into words.

    A routing decision that cannot be explained cannot be debugged when a client
    complains about being sent to the wrong continent.
    """
    if client_region is None:
        locality = "no client region supplied, ranked by load only"
    elif node_region == client_region.code:
        locality = "same region as client"
    elif node_continent == client_region.continent:
        locality = f"same continent, serving {client_region.code} from {node_region}"
    else:
        locality = f"cross-continent fallback, serving {client_region.code} from {node_region}"

    freshness = (
        "holds the current version"
        if is_warm
        else "cold cache, will pull from origin on first request"
    )
    return f"{locality}; {freshness}; {load_percent}% loaded"
